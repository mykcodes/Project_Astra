from typing import Dict, Any, Optional
import json
from app.tools.base import Tool
from app.tools.schemas import ToolRisk
from app.interaction.models import InteractionAction
from app.interaction.target_resolver import target_resolver
from app.interaction.input.engine import input_engine
from app.interaction.verification import verification_engine
from app.interaction.ui.engine import ui_engine
from app.ai.context.engine import context_engine
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class ExecuteInteractionIntentTool(Tool):
    name = "execute_interaction_intent"
    description = "Executes semantic interactions (click, type, focus, etc) on UI elements within an application."
    risk = ToolRisk.CONTROLLED
    capabilities = ["INTERACTION"]
    
    # We define parameters manually here for simplicity, in a full pydantic model it would be strict
    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "The action to perform (e.g. CLICK, TYPE_TEXT, PRESS_KEY, FOCUS)"
                },
                "target_ui_element": {
                    "type": "string",
                    "description": "The semantic name of the UI element (e.g. 'search button', 'address bar')"
                },
                "application_name": {
                    "type": "string",
                    "description": "The application to interact with."
                },
                "value": {
                    "type": "string",
                    "description": "The text to type or key to press, if applicable."
                }
            },
            "required": ["action", "application_name"]
        }

    async def execute(self, action: str, application_name: str, target_ui_element: Optional[str] = None, value: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        try:
            interaction_action = InteractionAction(action.upper())
        except ValueError:
            return {"success": False, "reason": f"Invalid interaction action: {action}"}
            
        app_name = context_engine.resolve_reference(application_name) or application_name
        
        # Genuine 2-attempt loop for target resolution + interaction
        attempt = 1
        max_attempts = 2
        last_result = None
        
        while attempt <= max_attempts:
            # 1. Resolve Window
            window_res = target_resolver.resolve_window_target(app_name)
            if window_res["status"] != "RESOLVED":
                return {"success": False, "reason": window_res["reason"]}
                
            window_target = window_res["window"]
            hwnd = window_target.hwnd
            
            # Capture Pre-State
            pre_state = verification_engine.get_pre_action_state(hwnd)
            
            # 2. Check UI Capability
            if window_target.automation_support == "UI_AUTOMATION_UNAVAILABLE":
                return {"success": False, "reason": "UI_AUTOMATION_UNAVAILABLE: Application does not expose accessibility information."}
                
            # 3. Resolve Element if needed
            ui_element = None
            if target_ui_element:
                target_query = context_engine.resolve_reference(target_ui_element) or target_ui_element
                element_res = target_resolver.resolve_ui_target(hwnd, target_query, force_refresh=(attempt > 1))
                
                if element_res["status"] != "RESOLVED":
                    if attempt < max_attempts:
                        ui_engine.invalidate_cache(hwnd)
                        attempt += 1
                        continue
                    return {"success": False, "reason": element_res["reason"], "status": element_res["status"], "diagnostics": element_res.get("diagnostics", {})}
                    
                ui_element = element_res["element"]
                
            # 4. Execute Action
            result_payload = {"success": False, "reason": "Action not implemented"}
            if interaction_action == InteractionAction.CLICK:
                if not ui_element:
                    return {"success": False, "reason": "Target UI element required for CLICK"}
                result_payload = input_engine.click(ui_element)
                
            elif interaction_action == InteractionAction.TYPE_TEXT:
                if not ui_element:
                    return {"success": False, "reason": "Target UI element required for TYPE_TEXT"}
                if not value:
                    return {"success": False, "reason": "Value required for TYPE_TEXT"}
                result_payload = input_engine.type_text(ui_element, value)
                
            elif interaction_action == InteractionAction.PRESS_KEY:
                if not value:
                    return {"success": False, "reason": "Value (key) required for PRESS_KEY"}
                result_payload = input_engine.press_key(value)
                
            elif interaction_action == InteractionAction.FOCUS:
                from app.environment.window.manager import window_manager
                success = window_manager.restore_and_focus(hwnd)
                result_payload = {"success": success, "method": "WIN32"}
                
            # 5. Verify
            final_result = verification_engine.verify_action(
                action=interaction_action,
                target_name=target_ui_element or app_name,
                app_name=app_name,
                hwnd=hwnd,
                element=ui_element,
                result_payload=result_payload,
                pre_state=pre_state
            )
            final_result.attempts = attempt
            
            # Recovery logic: if we verified it failed and we haven't maxed out attempts
            if not final_result.success and attempt < max_attempts:
                ui_engine.invalidate_cache(hwnd)
                context_engine.invalidate_ui_context()
                attempt += 1
                continue
                
            # 6. Update Context
            context_engine.update_interaction_context(target_ui_element or app_name, interaction_action.value, final_result.success)
            
            return final_result.to_dict()
            
        return {"success": False, "reason": "Max attempts exceeded."}

# We need to register this tool in the registry later
