from typing import Dict, Any, Optional
import json
from app.tools.base import Tool
from app.tools.schemas import ToolRisk
from app.interaction.models import InteractionAction, InteractionErrorCategory
from app.interaction.target_resolver import target_resolver
from app.interaction.strategy import strategy_engine
from app.interaction.verification import verification_engine
from app.interaction.ui.engine import ui_engine
from app.interaction.recovery import recovery_engine
from app.interaction.capability_manager import capability_manager
from app.environment.application.state_engine import state_engine
from app.ai.context.engine import context_engine
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class ExecuteInteractionIntentTool(Tool):
    name = "execute_interaction_intent"
    description = "Executes semantic interactions on UI elements utilizing an Observe -> Act -> Observe -> Verify loop."
    risk = ToolRisk.CONTROLLED
    capabilities = ["INTERACTION"]
    
    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "target_ui_element": {"type": "string"},
                "application_name": {"type": "string"},
                "value": {"type": "string"}
            },
            "required": ["action", "application_name"]
        }

    async def execute(self, action: str, application_name: str, target_ui_element: Optional[str] = None, value: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        try:
            interaction_action = InteractionAction(action.upper())
        except ValueError:
            return {"success": False, "error_category": "INTERACTION_UNSUPPORTED", "reason": f"Invalid action: {action}"}
            
        app_name = context_engine.resolve_reference(application_name) or application_name
        target_query = context_engine.resolve_reference(target_ui_element) if target_ui_element else None
        
        max_attempts = 2
        attempt = 1
        diagnostics = {}
        
        while attempt <= max_attempts:
            # 1. Resolve Window
            state = state_engine.get_state(app_name)
            if state["state"] in ("NOT_INSTALLED", "UNKNOWN"):
                return self._fail("WINDOW_NOT_FOUND", f"Application {app_name} not found or ambiguous", diagnostics)
            if not state["windows"]:
                return self._fail("WINDOW_NOT_FOUND", f"Application {app_name} has no active windows", diagnostics)
                
            # Select best window (foreground or first visible)
            target_window = next((w for w in state["windows"] if w.get("foreground")), state["windows"][0])
            hwnd = target_window["hwnd"]
            
            # 2. Pre-Action Observation
            pre_obs = ui_engine.observe_window(hwnd, force=(attempt > 1))
            if pre_obs.window.is_modal and not (target_query and "modal" in target_query.lower()):
                return self._fail("MODAL_BLOCKED", "An unexpected modal is blocking interaction", diagnostics)
                
            # 3. Target Resolution
            ui_element = None
            if target_query:
                res_result = target_resolver.resolve_ui_target(hwnd, target_query, force_refresh=(attempt > 1))
                if res_result.status != "RESOLVED":
                    if attempt < max_attempts:
                        attempt += 1
                        ui_engine.invalidate_observation()
                        continue
                    return self._fail(res_result.status, f"Failed to resolve target: {target_query}", diagnostics)
                ui_element = res_result.selected_candidate
                
            # 4. Strategy Selection
            caps = capability_manager.inspect_window(hwnd)
            adapter = capability_manager.adapters[-1] # Simplification, need actual routing
            for a in capability_manager.adapters:
                if a.can_handle(pre_obs.window):
                    adapter = a
                    break
                    
            applicable_strategies = strategy_engine.select_interaction_strategy(interaction_action, adapter, pre_obs, ui_element)
            
            # 5. Execute
            if not applicable_strategies:
                if attempt < max_attempts:
                    attempt += 1
                    ui_engine.invalidate_observation()
                    continue
                return self._fail("INPUT_UNAVAILABLE", "No applicable interaction strategies found", diagnostics)
                
            strategy = applicable_strategies[0]
            diagnostics["strategy"] = strategy
            exec_result = strategy_engine.execute_strategy(strategy, interaction_action, pre_obs, ui_element, value)
                    
            # 6. Post-Action Observation & Verification
            exec_result["method"] = strategy
            final_result = verification_engine.verify_action(
                action=interaction_action,
                target_name=target_query or app_name,
                app_name=app_name,
                element=ui_element,
                result_payload=exec_result,
                pre_state_obs=pre_obs
            )
            final_result.attempts = attempt
            final_result.diagnostics.update(diagnostics)
            
            if not final_result.success:
                if attempt < max_attempts:
                    attempt += 1
                    ui_engine.invalidate_observation()
                    continue
                
                # Map verification failures to structured taxonomy
                err_category = "VERIFICATION_FAILED"
                err_reason = final_result.error or "Verification failed without specific error"
                if "Target window did not become foreground" in err_reason:
                    err_category = "FOCUS_DENIED"
                    
                return self._fail(err_category, err_reason, diagnostics)
                    
            # 7. Update Context
            context_engine.update_interaction_context(target_query or app_name, interaction_action.value, final_result.success, pre_obs)
            return final_result.to_dict()
            
        return self._fail("RECOVERY_EXHAUSTED", "Max recovery attempts exceeded", diagnostics)

    def _fail(self, category: str, reason: str, diagnostics: dict) -> dict:
        return {"success": False, "error_category": category, "reason": reason, "diagnostics": diagnostics}
