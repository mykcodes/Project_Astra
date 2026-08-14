from typing import Dict, Any, Optional
import time
from app.interaction.models import InteractionAction, InteractionResult, UIElement, UIObservation, UIChange
from app.environment.window.manager import window_manager
from app.interaction.ui.engine import ui_engine

class VerificationEngine:
    """Verifies that interaction state changes actually occurred using UIChange semantics."""
    
    def verify_action(
        self, 
        action: InteractionAction, 
        target_name: str, 
        app_name: str, 
        element: Optional[UIElement], 
        result_payload: Dict[str, Any],
        pre_state_obs: UIObservation
    ) -> InteractionResult:
        
        success = result_payload.get("success", False)
        if not success:
            return InteractionResult(
                success=False,
                action=action.value,
                target_name=target_name,
                target_resolved=element is not None,
                verified=True, 
                error=result_payload.get("reason", "Unknown failure")
            )
            
        time.sleep(0.5) # Wait for OS UI loop
        post_state_obs = ui_engine.observe_window(pre_state_obs.window.hwnd, force=True)
        
        changes = ui_engine.compare_state(pre_state_obs, post_state_obs)
        verified = False
        error = None
        state_after = {}
        
        if action == InteractionAction.FOCUS:
            if any(c.change_type == "FOREGROUND_CHANGED" for c in changes) or (post_state_obs.foreground_hwnd == post_state_obs.window.hwnd):
                verified = True
            else:
                error = "Target window did not become foreground"
                
        elif action == InteractionAction.TYPE_TEXT:
            val_change = next((c for c in changes if c.change_type == "VALUE_CHANGED" and (not element or c.element_id == element.runtime_id)), None)
            if val_change:
                verified = True
                state_after["extracted_value"] = "***" # Masked
            else:
                verified = False
                error = "Control value change not observed."
                
        elif action == InteractionAction.CLICK:
            if changes:
                verified = True
                state_after["transition"] = changes[0].change_type
            else:
                verified = False
                error = "No observable UI state transition occurred after click."
                
        else:
            verified = True 
            
        return InteractionResult(
            success=verified,
            action=action.value,
            target_name=target_name,
            target_resolved=element is not None,
            interaction_method=result_payload.get("method"),
            verified=verified,
            error=error,
            state_before={"hash": pre_state_obs.state_hash},
            state_after=state_after,
            diagnostics={"changes": [c.change_type for c in changes]}
        )

verification_engine = VerificationEngine()
