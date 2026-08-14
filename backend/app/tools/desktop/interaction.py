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
        
        attempt = 1
        max_attempts = recovery_engine.max_attempts + 1
        diagnostics = {"recovery_attempts": [], "latencies": {}}
        
        while attempt <= max_attempts:
            # 1. Resolve Window
            window_res = target_resolver.resolve_window_target(app_name) # Assuming this was updated or is compatible
            if window_res.get("status") != "RESOLVED":
                return self._fail("WINDOW_NOT_FOUND", window_res.get("reason"), diagnostics)
                
            hwnd = window_res["window"].hwnd
            
            # 2. Pre-Action Observation
            pre_obs = ui_engine.observe_window(hwnd, force=(attempt > 1))
            if pre_obs.window.is_modal and not (target_query and "modal" in target_query.lower()):
                return self._fail("MODAL_BLOCKED", "An unexpected modal is blocking interaction", diagnostics)
                
            # 3. Target Resolution
            ui_element = None
            if target_query:
                res_result = target_resolver.resolve_ui_target(hwnd, target_query, force_refresh=False)
                if res_result.status != "RESOLVED":
                    strategies = recovery_engine.attempt_recovery(attempt, res_result.status, hwnd, app_name)
                    if strategies:
                        diagnostics["recovery_attempts"].append(strategies)
                        attempt += 1
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
            exec_result = None
            used_strategy = None
            for strategy in applicable_strategies:
                exec_result = strategy_engine.execute_strategy(strategy, interaction_action, pre_obs, ui_element, value)
                if exec_result.get("success"):
                    used_strategy = strategy
                    break
                    
            if not exec_result or not exec_result.get("success"):
                return self._fail("INPUT_FAILED", "All applicable interaction strategies failed.", diagnostics)
                
            # 6. Post-Action Observation & Verification
            exec_result["method"] = used_strategy
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
                strategies = recovery_engine.attempt_recovery(attempt, "VERIFICATION_FAILED", hwnd, app_name)
                if strategies:
                    diagnostics["recovery_attempts"].append(strategies)
                    attempt += 1
                    continue
                    
            # 7. Update Context
            context_engine.update_interaction_context(target_query or app_name, interaction_action.value, final_result.success, pre_obs)
            return final_result.to_dict()
            
        return self._fail("RECOVERY_EXHAUSTED", "Max recovery attempts exceeded", diagnostics)

    def _fail(self, category: str, reason: str, diagnostics: dict) -> dict:
        return {"success": False, "error_category": category, "reason": reason, "diagnostics": diagnostics}
