import json
import uuid
from typing import Any, Dict
from app.domain.goals import VerificationResult, FailureClass, Intent
from app.domain.entities import TriState
from app.ai.orchestrator.verification import VerificationEngine
from app.tools.executor import executor
from app.ai.providers.types import ToolCall
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class ActionExecutor:
    """Executes ActionPlans, manages bounded retries, and enforces Action Result Contracts."""
    
    def __init__(self):
        self.verifier = VerificationEngine()
        
    async def execute_intent(self, intent: Intent, tool_args: Dict[str, Any], max_attempts: int = 1) -> Dict[str, Any]:
        """Executes a semantic intent via ToolExecutor and enforces Action Result Contracts."""
        
        from app.tools.registry import registry
        
        # 1. Resolve semantic capability to executable tool name
        executable_tool_name = registry.resolve_capability(intent.capability_id)
        
        # 1.5 Sanitize arguments dynamically based on tool schema (to avoid validation failures)
        tool = registry.get(executable_tool_name)
        if tool and hasattr(tool, "schema") and isinstance(tool.schema, dict):
            if "properties" in tool.schema:
                allowed_keys = set(tool.schema["properties"].keys())
                tool_args = {k: v for k, v in tool_args.items() if k in allowed_keys}
        
        tool_call = ToolCall(id=str(uuid.uuid4()), name=executable_tool_name, arguments=tool_args)

        attempts = 0
        last_error = None
        last_diagnostics = {}
        
        while attempts < max_attempts:
            attempts += 1
            logger.info(f"ACTION_EXECUTION_ATTEMPT", extra={"intent": intent.action, "attempt": attempts, "tool": executable_tool_name})
            
            from app.environment.awareness import get_awareness_provider
            
            is_interaction = intent.capability_id.startswith("interaction.") or intent.capability_id.startswith("desktop.")
            
            world_before = None
            if is_interaction:
                provider = get_awareness_provider()
                world_before = provider.observe_world_state()
            
            tool_result = await executor.execute(tool_call)
            
            world_after = None
            if is_interaction:
                world_after = provider.observe_world_state()
            
            if not tool_result.success:
                last_error = tool_result.error
                continue
                
            try:
                result_data = json.loads(tool_result.result)
            except json.JSONDecodeError:
                result_data = {"raw": tool_result.result, "action_executed": True, "error": {"code": "RESULT_PUBLICATION_ERROR", "message": "Result serialization failed"}}
                
            last_diagnostics = result_data
            action_executed = result_data.get("action_executed", True) # Assume executed if tool_result.success=True unless specified
            
            # Check for HUMAN_VERIFICATION_REQUIRED block from tools
            if not result_data.get("success", False):
                err = result_data.get("error", {})
                if isinstance(err, dict) and err.get("code") == "HUMAN_VERIFICATION_REQUIRED":
                    last_error = err
                    break
                    
            verification_result = None
            
            # Verify based on domain (semantic capability domain)
            if intent.capability_id.startswith("browser."):
                provider_verified = result_data.get("verified", False)
                provider_success = result_data.get("success", False)
                # Reconstruct a formal VerificationResult
                if provider_verified:
                    verification_result = VerificationResult(
                        verified=TriState.TRUE,
                        verification_type=intent.action,
                        expected_state=intent.target,
                        actual_state="Verified by provider",
                        observation_id=result_data.get("observation_id")
                    )
                else:
                    failure_code = None
                    err_code = result_data.get("error", {}).get("code", "") if isinstance(result_data.get("error"), dict) else ""
                    if err_code == "PLAYBACK_NOT_CONFIRMED":
                        failure_code = FailureClass.VERIFICATION_FAILED
                    elif err_code == "TARGET_RESOLUTION_FAILED":
                        failure_code = FailureClass.TARGET_NOT_FOUND
                    elif err_code == "BROWSER_NOT_RUNNING":
                        failure_code = FailureClass.BROWSER_CLOSED
                    elif err_code == "VERIFICATION_FAILED":
                        failure_code = FailureClass.VERIFICATION_FAILED
                    elif err_code == "RESULT_PUBLICATION_ERROR":
                        failure_code = FailureClass.UNKNOWN
                    elif not provider_success:
                        failure_code = FailureClass.EXECUTION_FAILED
                    else:
                        failure_code = FailureClass.VERIFICATION_FAILED
                        
                    verification_result = VerificationResult(
                        verified=TriState.FALSE,
                        verification_type=intent.action,
                        expected_state=intent.target,
                        actual_state="Unverified or Failed",
                        failure_code=failure_code,
                        observation_id=result_data.get("observation_id"),
                        evidence=result_data.get("error", {}).get("message", "Provider could not verify.") if isinstance(result_data.get("error"), dict) else str(result_data.get("error", ""))
                    )
                    
            elif is_interaction:
                if intent.capability_id.startswith("desktop.physical_input"):
                    provider_verified = result_data.get("verified", TriState.UNKNOWN)
                    verification_result = VerificationResult(
                        verified=provider_verified if hasattr(TriState, str(provider_verified)) else TriState.UNKNOWN,
                        verification_type=intent.action,
                        expected_state="Physical Actuation",
                        actual_state=str(provider_verified),
                        failure_code=None if result_data.get("success") else FailureClass.EXECUTION_FAILED
                    )
                elif intent.capability_id.startswith("desktop.visual_"):
                    verification_val = result_data.get("verification", TriState.UNKNOWN)
                    if isinstance(verification_val, str):
                        try:
                            verification_val = TriState(verification_val)
                        except ValueError:
                            verification_val = TriState.UNKNOWN
                    verification_result = VerificationResult(
                        verified=verification_val,
                        verification_type="VISUAL_INTERACTION",
                        expected_state="Visual Click",
                        actual_state=str(verification_val.value if isinstance(verification_val, TriState) else verification_val),
                        failure_code=None if result_data.get("success") else FailureClass.EXECUTION_FAILED
                    )
                else:
                    canonical_identity = result_data.get("canonical_name", intent.target)
                    verification_result = self.verifier.verify_interaction(intent.action, canonical_identity, world_before, world_after)
                
            elif intent.capability_id.startswith("system."):
                is_verified = self.verifier.verify_system_action(intent.parameters.get("requested_fields", []), result_data)
                verification_result = VerificationResult(
                    verified=TriState.TRUE if is_verified else TriState.FALSE,
                    verification_type="SYSTEM",
                    expected_state="Data Returned",
                    actual_state="Data Returned" if is_verified else "Missing Data",
                    failure_code=None if is_verified else FailureClass.VERIFICATION_FAILED
                )
            else:
                # Default domain
                is_verified = result_data.get("success", False)
                verification_result = VerificationResult(
                    verified=TriState.TRUE if is_verified else TriState.FALSE,
                    verification_type="GENERIC",
                    expected_state="Success",
                    actual_state="Success" if is_verified else "Failed",
                    failure_code=None if is_verified else FailureClass.VERIFICATION_FAILED
                )
            is_successful_actuation = result_data.get("success", False)
            if verification_result and (
                verification_result.verified in (TriState.TRUE, True) or
                (verification_result.verified == TriState.UNKNOWN and is_successful_actuation)
            ):
                result_payload = {
                    "success": True,
                    "action": intent.action,
                    "target": intent.target or "system",
                    "verified": verification_result.verified,
                    "attempts": attempts,
                    "error": None,
                    "diagnostics": result_data,
                    "verification_result": verification_result,
                    "session_id": result_data.get("session_id"),
                    "observation_id": result_data.get("observation_id"),
                    "action_executed": action_executed
                }
                return result_payload
            else:
                last_error = result_data.get("error") or result_data.get("message") or "Action failed or could not be verified."
                break
                
        failure_code = "EXECUTION_FAILED"
        if isinstance(last_error, dict) and last_error.get("code"):
            failure_code = last_error.get("code")
        elif 'verification_result' in locals() and verification_result and verification_result.failure_code:
            failure_code = getattr(verification_result.failure_code, "name", str(verification_result.failure_code))
            
        if failure_code == "HUMAN_VERIFICATION_REQUIRED":
            error_details = last_error.get("message", "Human verification required") if isinstance(last_error, dict) else "Human verification required"
        else:
            error_details = last_error or "Max attempts reached without verification"
            
        failure_payload = self._build_failure_result(error_details, attempts, last_diagnostics, failure_code)
        failure_payload["action"] = intent.action
        failure_payload["target"] = intent.target or "system"
        failure_payload["action_executed"] = locals().get("action_executed", False)
        if 'verification_result' in locals() and verification_result:
            failure_payload["verification_result"] = verification_result
            
        return failure_payload

    def _build_raw_result(self, tool_result) -> Dict[str, Any]:
        if tool_result.success:
            try:
                return json.loads(tool_result.result)
            except:
                return {"success": True, "result": tool_result.result}
        return {"success": False, "error": tool_result.error}

    def _build_failure_result(self, error_msg: str, attempts: int = 0, diagnostics: Dict = None, failure_code: str = "EXECUTION_FAILED") -> Dict[str, Any]:
        return {
            "success": False,
            "verified": TriState.FALSE,
            "error": {
                "code": failure_code,
                "message": error_msg
            },
            "attempts": attempts,
            "diagnostics": diagnostics or {}
        }

action_executor = ActionExecutor()
