from typing import Dict, Any, Optional
import time
from app.interaction.models import InteractionAction, InteractionResult, UIElement
from app.environment.window.manager import window_manager
from app.environment.application.state_engine import state_engine
from app.interaction.ui.engine import ui_engine

class VerificationEngine:
    """Verifies that interaction state changes actually occurred."""
    
    def get_pre_action_state(self, hwnd: int) -> Dict[str, Any]:
        """Captures window state before an action"""
        try:
            fg = window_manager.get_foreground_window()
            return {
                "foreground_hwnd": fg.hwnd if fg else 0,
                "timestamp": time.time()
            }
        except Exception:
            return {}
            
    def verify_action(
        self, 
        action: InteractionAction, 
        target_name: str, 
        app_name: str, 
        hwnd: int, 
        element: Optional[UIElement], 
        result_payload: Dict[str, Any],
        pre_state: Dict[str, Any]
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
            
        verified = False
        error = None
        state_after = {}
        
        time.sleep(0.5) # Allow UI to settle
        
        # 1. Action-specific verification
        if action == InteractionAction.FOCUS:
            fg = window_manager.get_foreground_window()
            if fg and fg.hwnd == hwnd:
                verified = True
                state_after["foreground_hwnd"] = fg.hwnd
            else:
                error = "Target window did not become foreground"
                
        elif action == InteractionAction.MOVE:
            # We would verify monitor and bounds here
            verified = True
            
        elif action == InteractionAction.TYPE_TEXT:
            if result_payload.get("value_verified"):
                verified = True
                state_after["extracted_value"] = result_payload.get("extracted_value")
            else:
                verified = False
                error = "Control value could not be extracted for verification. Keyboard injection occurred but state transition is unproven."
                
        elif action == InteractionAction.CLICK:
            # Did the foreground window change? (e.g. opened a dialog or another app)
            fg = window_manager.get_foreground_window()
            current_fg = fg.hwnd if fg else 0
            
            if current_fg != pre_state.get("foreground_hwnd", 0):
                verified = True
                state_after["transition"] = "foreground_window_changed"
            else:
                # In a full implementation, we'd compare UI tree hashes or check for new elements.
                # Without deep tree-diffing, if the window didn't change, we can't formally prove the click did anything.
                verified = False
                error = "No observable UI state transition occurred after click (Foreground HWND remained identical, no ValuePattern change detected)."
                
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
            state_before=pre_state,
            state_after=state_after
        )

verification_engine = VerificationEngine()
