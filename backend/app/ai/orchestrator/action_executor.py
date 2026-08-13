import json
import uuid
from typing import Any, Dict
from app.ai.orchestrator.intent import NormalizedIntent, IntentDomain
from app.ai.orchestrator.action_planner import ActionPlanner, ActionPlan
from app.ai.orchestrator.verification import VerificationEngine
from app.tools.executor import executor
from app.ai.providers.types import ToolCall
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class ActionExecutor:
    """Executes ActionPlans, manages bounded retries, and enforces Action Result Contracts."""
    
    def __init__(self):
        self.planner = ActionPlanner()
        self.verifier = VerificationEngine()
        
    async def execute_tool_call(self, tool_call: ToolCall, max_attempts: int = 2) -> Dict[str, Any]:
        """Intercepts a tool call, translates it to an intent, executes via ToolExecutor, and enforces Action Result Contracts."""
        
        # 1. Normalize the intent from the raw LLM tool call
        try:
            intent = self._normalize_tool_call(tool_call)
        except Exception as e:
            logger.warning(f"Failed to normalize tool call: {e}")
            # Fallback to direct execution without retry/verification if we don't understand it
            raw_result = await executor.execute(tool_call)
            return self._build_raw_result(raw_result)

        attempts = 0
        last_error = None
        last_diagnostics = {}
        
        while attempts < max_attempts:
            attempts += 1
            logger.info(f"ACTION_EXECUTION_ATTEMPT", extra={"intent": intent.action, "attempt": attempts})
            
            # Execute the underlying tool
            tool_result = await executor.execute(tool_call)
            
            if not tool_result.success:
                last_error = tool_result.error
                continue
                
            try:
                result_data = json.loads(tool_result.result)
            except json.JSONDecodeError:
                result_data = {"raw": tool_result.result}
                
            last_diagnostics = result_data
            
            verified = False
            state_after = "UNKNOWN"
            state_before = "UNKNOWN"
            
            # Verify based on domain
            if intent.domain == IntentDomain.DESKTOP:
                state_after = result_data.get("state", "UNKNOWN")
                verified = self.verifier.verify_desktop_action(intent.action, intent.target, state_after, result_data.get("pids", []))
                
                if not verified and not result_data.get("success", False):
                    last_error = result_data.get("reason", "Action verification failed")
                    continue
                    
                verified = result_data.get("success", False)
                if not verified:
                    last_error = result_data.get("reason", "Desktop controller reported failure")
                    continue
                
            elif intent.domain == IntentDomain.SYSTEM:
                verified = self.verifier.verify_system_action(intent.parameters.get("requested_fields", []), result_data)
                if not verified:
                    last_error = "System information missing requested fields."
                    continue
            else:
                verified = result_data.get("success", True)
                if not verified:
                    last_error = result_data.get("error", "Operation failed")
                    continue
            
            if verified:
                return {
                    "success": True,
                    "action": intent.action,
                    "target": intent.target or "system",
                    "state_before": state_before,
                    "state_after": state_after,
                    "verified": True,
                    "attempts": attempts,
                    "error": None,
                    "diagnostics": result_data
                }
                
        # If we exhausted attempts
        return self._build_failure_result(last_error or "Max attempts reached without verification", attempts, last_diagnostics)

    def _normalize_tool_call(self, tool_call: ToolCall) -> NormalizedIntent:
        name = tool_call.name
        args = tool_call.arguments
        
        if name == "execute_application_intent":
            return NormalizedIntent.desktop(action=args.get("intent"), target=args.get("application"))
        elif name == "get_system_info":
            return NormalizedIntent.system(action="get_info", requested_fields=args.get("sections", []))
        elif name == "open_url":
            return NormalizedIntent.browser(action="open_url", target=args.get("url"))
        elif name == "list_directory":
            return NormalizedIntent.filesystem(action="list", target=args.get("path"))
        elif name == "search_files":
            return NormalizedIntent.filesystem(action="search", target=args.get("path"), query=args.get("query"))
        elif name == "create_folder":
            return NormalizedIntent.filesystem(action="create_folder", target=args.get("path"))
        
        raise ValueError(f"Cannot normalize unknown tool: {name}")

    def _build_raw_result(self, tool_result) -> Dict[str, Any]:
        if tool_result.success:
            try:
                return json.loads(tool_result.result)
            except:
                return {"success": True, "result": tool_result.result}
        return {"success": False, "error": tool_result.error}

    def _build_failure_result(self, error_msg: str, attempts: int = 0, diagnostics: Dict = None) -> Dict[str, Any]:
        return {
            "success": False,
            "verified": False,
            "error": {
                "code": "EXECUTION_FAILED",
                "message": error_msg
            },
            "attempts": attempts,
            "diagnostics": diagnostics or {}
        }

action_executor = ActionExecutor()
