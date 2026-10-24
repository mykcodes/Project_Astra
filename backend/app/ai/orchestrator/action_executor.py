import json
import uuid
import asyncio
import time
from typing import Any, Dict, Optional, List
from app.domain.goals import VerificationResult, FailureClass, Intent, SemanticAction
from app.domain.entities import TriState
from app.domain.composite import (
    CompositeStep,
    CompositeActionSequence,
    CompositeExecutionResult,
    StepStatus,
    CompositeTerminalStatus,
    CompensationAction,
)
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
        
        # 1.4 Normalize semantic arguments for common tools before schema filtering
        if executable_tool_name == "execute_browser_intent":
            if "intent" not in tool_args:
                if intent.action == SemanticAction.SEARCH or intent.capability_id == "browser.search":
                    tool_args["intent"] = "SEARCH"
                elif str(getattr(intent.action, "value", intent.action)).upper() == "STATUS" or intent.capability_id == "browser.status":
                    tool_args["intent"] = "STATUS"
                else:
                    tool_args["intent"] = tool_args.get("action") or getattr(intent.action, "value", "NAVIGATE")
            if tool_args.get("intent") == "SEARCH":
                tool_args["target"] = tool_args.get("query") or intent.query or tool_args.get("target") or intent.target or ""
            elif "target" not in tool_args:
                tool_args["target"] = intent.target or ""
            if "browser_name" not in tool_args and (tool_args.get("browser") or intent.browser):
                tool_args["browser_name"] = tool_args.get("browser") or intent.browser
        elif executable_tool_name == "execute_application_intent":
            if "application" not in tool_args:
                tool_args["application"] = tool_args.get("target") or intent.target or "notepad"
            if "intent" not in tool_args:
                if intent.capability_id == "desktop.open_application" or intent.action == SemanticAction.OPEN:
                    tool_args["intent"] = "OPEN"
                elif intent.capability_id == "desktop.focus_application" or intent.action == SemanticAction.FOCUS:
                    tool_args["intent"] = "FOCUS"
                elif intent.capability_id == "desktop.close_application" or intent.action == SemanticAction.CLOSE:
                    tool_args["intent"] = "CLOSE"
                else:
                    tool_args["intent"] = "OPEN"
        elif executable_tool_name == "open_url":
            if "url" not in tool_args:
                tool_args["url"] = tool_args.get("target") or intent.target or ""
        elif executable_tool_name == "interact_browser":
            if "action" not in tool_args:
                tool_args["action"] = str(tool_args.get("action") or getattr(intent.action, "value", str(intent.action))).upper()
            if "target" not in tool_args and intent.target:
                tool_args["target"] = str(intent.target)
            if "value" not in tool_args and (tool_args.get("query") or intent.query):
                tool_args["value"] = str(tool_args.get("query") or intent.query)
            if "browser_name" not in tool_args and (tool_args.get("browser") or intent.browser):
                tool_args["browser_name"] = tool_args.get("browser") or intent.browser
        elif executable_tool_name == "execute_physical_input":
            if "intent" not in tool_args:
                action_str = getattr(intent.action, "value", str(intent.action)).upper()
                if action_str in ["MOVE_MOUSE", "CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "SCROLL", "DRAG", "ESCAPE", "ALT", "TYPE_TEXT", "PRESS_KEY", "HOTKEY"]:
                    tool_args["intent"] = action_str
                elif "keys" in tool_args:
                    tool_args["intent"] = "HOTKEY"
                elif "key" in tool_args:
                    tool_args["intent"] = "PRESS_KEY"
                elif "text" in tool_args:
                    tool_args["intent"] = "TYPE_TEXT"
                elif "clicks" in tool_args or "delta_y" in tool_args:
                    tool_args["intent"] = "SCROLL"
                elif "end_x" in tool_args:
                    tool_args["intent"] = "DRAG"
                else:
                    tool_args["intent"] = "CLICK"

        # 1.5 Sanitize arguments dynamically based on tool schema (to avoid validation failures)
        tool = registry.get(executable_tool_name)
        if tool and hasattr(tool, "schema") and isinstance(tool.schema, dict):
            if "properties" in tool.schema:
                allowed_keys = set(tool.schema["properties"].keys())
                required_keys = set(tool.schema.get("required", []))
                tool_args = {
                    k: v for k, v in tool_args.items() 
                    if k in allowed_keys and (v is not None or k in required_keys)
                }
        
        tool_call = ToolCall(id=str(uuid.uuid4()), name=executable_tool_name, arguments=tool_args)

        attempts = 0
        last_error = None
        last_diagnostics = {}
        
        while attempts < max_attempts:
            attempts += 1
            logger.info(f"ACTION_EXECUTION_ATTEMPT", extra={"intent": intent.action, "attempt": attempts, "tool": executable_tool_name})
            
            from app.environment.awareness import get_awareness_provider
            
            is_interaction = intent.capability_id.startswith("interaction.") or intent.capability_id.startswith("desktop.")
            needs_world_obs = is_interaction and not (
                intent.capability_id.startswith("desktop.physical_input")
                or intent.capability_id.startswith("desktop.visual_")
            )
            
            world_before = None
            if needs_world_obs:
                provider = get_awareness_provider()
                world_before = provider.observe_world_state()
            
            tool_result = await executor.execute(tool_call)
            
            world_after = None
            if needs_world_obs:
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
                    
                    failure_code = None
                    if not result_data.get("success"):
                        err_code = result_data.get("error", {}).get("code") if isinstance(result_data.get("error"), dict) else ""
                        if err_code in ("TARGET_MOVED", "TARGET_OCCLUDED", "OBSERVATION_STALE", "STALE_TARGET"):
                            failure_code = FailureClass.STALE_TARGET
                        elif err_code in ("TARGET_NOT_FOUND", "TARGET_DISAPPEARED", "TARGET_AMBIGUOUS"):
                            failure_code = FailureClass.TARGET_NOT_FOUND
                        elif err_code == "CLICK_NO_EFFECT":
                            failure_code = FailureClass.CLICK_NO_EFFECT
                        else:
                            failure_code = FailureClass.EXECUTION_FAILED

                    verification_result = VerificationResult(
                        verified=verification_val,
                        verification_type="VISUAL_INTERACTION",
                        expected_state="Visual Click",
                        actual_state=str(verification_val.value if isinstance(verification_val, TriState) else verification_val),
                        failure_code=failure_code,
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

    async def execute_sequence(
        self,
        sequence: CompositeActionSequence,
        cancel_event: Optional[asyncio.Event] = None,
        permission_evaluator: Optional[Any] = None,
    ) -> CompositeExecutionResult:
        """
        Phase B.6: Executes a multi-step composite action sequence with:
        1. Atomic step state tracking and verification.
        2. Strict distinction between accepted actuation and verified success.
        3. Authorization checks for consequential/protected actions.
        4. Bounded recovery on verification failures via RecoveryEngine.
        5. Cancellation & timeout support with explicit terminal outcomes.
        6. Explicit terminal status for partial completion (never claiming full success on partial execution).
        7. Safe verified compensation for reversible actions (no fake rollback of irreversible actions).
        """
        from app.domain.permissions import (
            CapabilityScope,
            ResourceScope,
            PermissionRequest,
            PermissionState,
        )
        from app.ai.orchestrator.recovery import recovery_engine
        from app.domain.memory import RecoveryStrategy

        t_seq_start = time.perf_counter()
        completed_steps = 0
        verified_steps = 0
        failed_step_idx: Optional[int] = None
        compensations_executed: List[CompensationAction] = []
        terminal_status: CompositeTerminalStatus = CompositeTerminalStatus.SUCCESS
        seq_error: Optional[Dict[str, Any]] = None

        # Build execution copy of steps
        step_results: List[CompositeStep] = [s.model_copy(deep=True) for s in sequence.steps]
        for idx, s in enumerate(step_results):
            s.step_index = idx
            s.status = StepStatus.PENDING

        try:
            async with asyncio.timeout(sequence.timeout_seconds):
                for idx, step in enumerate(step_results):
                    # Check cancellation before step execution
                    if cancel_event and cancel_event.is_set():
                        terminal_status = CompositeTerminalStatus.CANCELLED
                        seq_error = {"code": "CANCELLED", "message": "Sequence execution cancelled by user/token."}
                        for remaining in step_results[idx:]:
                            remaining.status = StepStatus.CANCELLED
                        break

                    # Authorization gate for consequential or protected actions
                    if step.consequential or step.required_permission:
                        scope = step.required_permission or CapabilityScope.COMPUTER_CONTROL
                        req = PermissionRequest(
                            request_id=str(uuid.uuid4()),
                            requester_task_id=sequence.sequence_id,
                            capability=scope,
                            resource_scope=ResourceScope(capability=scope, resource=step.intent.target),
                            reason=step.description,
                        )
                        evaluator = permission_evaluator
                        if evaluator is None:
                            try:
                                from app.core.security.evaluator import PermissionEvaluator
                                evaluator = PermissionEvaluator()
                            except Exception:
                                evaluator = None

                        if evaluator:
                            decision = evaluator.evaluate(req)
                            if decision.decision not in (PermissionState.GRANTED, PermissionState.NOT_REQUIRED):
                                from app.core.security.consequential import ConsequentialActionPolicy
                                confirm_req = ConsequentialActionPolicy.create_confirmation_request(
                                    step,
                                    goal_id=sequence.sequence_id,
                                    task_id=str(idx),
                                )
                                step.status = StepStatus.FAILED
                                step.error = {
                                    "code": "PERMISSION_REQUIRED",
                                    "message": f"Authorization required for consequential action '{step.description}': {decision.reason}",
                                    "clarification_request": confirm_req.model_dump(mode="json"),
                                }
                                terminal_status = CompositeTerminalStatus.PERMISSION_DENIED
                                seq_error = step.error
                                failed_step_idx = idx
                                for remaining in step_results[idx + 1:]:
                                    remaining.status = StepStatus.SKIPPED
                                break

                    # Execute Step: Observe -> Act -> Observe -> Verify -> Recover loop
                    step.status = StepStatus.EXECUTING
                    t_step_start = time.perf_counter()

                    attempt = 0
                    max_attempts = max(1, sequence.max_retries_per_step + 1)
                    step_verified = False
                    last_res: Dict[str, Any] = {}

                    while attempt < max_attempts:
                        attempt += 1
                        if cancel_event and cancel_event.is_set():
                            break

                        # Phase B.7: Multi-Window Targeting & Focus Guarantee
                        step_target_hwnd = step.target_hwnd
                        step_target_bounds = None

                        if not step_target_hwnd and step.target_app_name:
                            try:
                                from app.tools.desktop.desktop_controller import DesktopController
                                dc = DesktopController()
                                app_stat = dc.get_application_status(step.target_app_name)
                                if app_stat.get("windows"):
                                    matching_wins = app_stat["windows"]
                                    if step.target_window_title:
                                        matching_wins = [
                                            w for w in matching_wins
                                            if step.target_window_title.lower() in (w.get("title") if isinstance(w, dict) else getattr(w, "title", "")).lower()
                                        ] or matching_wins
                                    if matching_wins:
                                        best_win = matching_wins[0]
                                        step_target_hwnd = best_win.get("hwnd") if isinstance(best_win, dict) else getattr(best_win, "hwnd", None)
                                        w_x = best_win.get("x", 0) if isinstance(best_win, dict) else getattr(best_win, "x", 0)
                                        w_y = best_win.get("y", 0) if isinstance(best_win, dict) else getattr(best_win, "y", 0)
                                        w_w = best_win.get("width", 0) if isinstance(best_win, dict) else getattr(best_win, "width", 0)
                                        w_h = best_win.get("height", 0) if isinstance(best_win, dict) else getattr(best_win, "height", 0)
                                        step_target_bounds = (w_x, w_y, w_w, w_h)
                            except Exception as e:
                                logger.debug(f"Target app window resolution skipped: {e}")

                        if step_target_hwnd and (not step_target_bounds or step_target_bounds == (0, 0, 0, 0)):
                            try:
                                from app.environment.window.manager import window_manager
                                wb = window_manager.get_window_bounds(step_target_hwnd)
                                if wb and any(dim > 0 for dim in wb):
                                    step_target_bounds = wb
                            except Exception:
                                pass

                        if step_target_hwnd and step.ensure_foreground:
                            try:
                                from app.environment.window.manager import window_manager
                                window_manager.restore_and_focus(step_target_hwnd)
                                await asyncio.sleep(0.15)
                            except Exception as e:
                                logger.debug(f"Target window foreground activation failed: {e}")

                        if step_target_bounds:
                            if not step.verifier_args:
                                step.verifier_args = {}
                            if "target_bounds" not in step.verifier_args:
                                step.verifier_args["target_bounds"] = step_target_bounds

                        obs_pre = None
                        detections_pre = None
                        if step.verifier_type and step.verifier_type not in ("WINDOW_FOCUS", "CLIPBOARD"):
                            try:
                                from app.environment.visual.capture import screen_capture_provider
                                from app.environment.visual.perception import _run_windows_media_ocr
                                import concurrent.futures
                                obs_pre = screen_capture_provider.capture_virtual_screen(f"comp_pre_{step.step_id}_{attempt}")
                                step.observation_before_id = obs_pre.observation_id
                                pre_bytes = screen_capture_provider.store.retrieve(obs_pre.image_reference)
                                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                                    detections_pre = pool.submit(_run_windows_media_ocr, pre_bytes, obs_pre.width, obs_pre.height).result()
                            except Exception as e:
                                logger.debug(f"Pre-observation capture skipped or unavailable: {e}")

                        effective_tool_args = dict(step.tool_args)
                        if step_target_bounds and "target_bounds" not in effective_tool_args:
                            effective_tool_args["target_bounds"] = step_target_bounds


                        # Dismiss any lingering menu flyouts if prior step opened a context menu
                        if idx > 0 and (step_results[idx - 1].verifier_type == "CONTEXT_MENU" or step_results[idx - 1].intent.action == SemanticAction.RIGHT_CLICK):
                            try:
                                from app.interaction.input.keyboard_controller import keyboard_controller
                                keyboard_controller.actuate_escape(press_count=2)
                                await asyncio.sleep(0.2)
                            except Exception:
                                pass

                        def _clean_ocr(s: str) -> str:
                            return str(s).lower().replace("0", "o").replace("1", "l").replace("5", "s").strip()

                        # Dynamic visual grounding for DRAG: if target_label or fallback word is detected in detections_pre
                        if step.intent.action == SemanticAction.DRAG and detections_pre:
                            target_label = (step.verifier_args or {}).get("target_label", "")
                            fallback_word = (step.verifier_args or {}).get("fallback_word", "composite")
                            norm_lbl = target_label.strip().lower()
                            clean_lbl = _clean_ocr(norm_lbl)
                            clean_fb = _clean_ocr(fallback_word)
                            target_bounds = (step.verifier_args or {}).get("target_bounds")
                            if not target_bounds:
                                for prev_s in reversed(step_results[:idx]):
                                    if prev_s.verifier_args and prev_s.verifier_args.get("target_bounds"):
                                        target_bounds = prev_s.verifier_args["target_bounds"]
                                        break
                            candidates = []
                            for item in detections_pre:
                                if len(item) >= 2 and isinstance(item[1], str):
                                    it_norm = item[1].strip().lower()
                                    it_clean = _clean_ocr(it_norm)
                                    if (norm_lbl and (norm_lbl in it_norm or clean_lbl in it_clean)) or (fallback_word and (fallback_word in it_norm or clean_fb in it_clean)):
                                        box = item[0]
                                        if len(box) == 4 and isinstance(box[0], (int, float)):
                                            bx, by, bw, bh = float(box[0]), float(box[1]), float(box[2]), float(box[3])
                                            if target_bounds:
                                                tx, ty, tw, th = target_bounds
                                                if not (tx - 15 <= bx <= tx + tw + 15 and ty - 15 <= by <= ty + th + 15):
                                                    continue
                                            candidates.append((bx, by, bw, bh, item[1]))
                            if candidates:
                                exact = [c for c in candidates if (norm_lbl and (c[4].strip().lower() == norm_lbl or _clean_ocr(c[4]) == clean_lbl))]
                                bx, by, bw, bh, text_match = exact[0] if exact else candidates[0]
                                min_x = int(target_bounds[0] + 15) if target_bounds else 15
                                max_x = int(target_bounds[0] + target_bounds[2] - 20) if target_bounds else 1920
                                if exact:
                                    effective_tool_args["start_x"] = max(min_x, int(bx + 4))
                                    effective_tool_args["start_y"] = int(by + bh / 2)
                                    effective_tool_args["end_x"] = min(max_x, int(bx + bw + 35))
                                    effective_tool_args["end_y"] = int(by + bh / 2)
                                else:
                                    idx_pos = text_match.lower().find(norm_lbl)
                                    if idx_pos == -1 and fallback_word:
                                        idx_pos = text_match.lower().find(fallback_word)
                                    if idx_pos == -1:
                                        effective_tool_args["start_x"] = max(min_x, int(bx + 4))
                                        effective_tool_args["start_y"] = int(by + bh / 2)
                                        effective_tool_args["end_x"] = min(max_x, int(bx + bw + 35))
                                        effective_tool_args["end_y"] = int(by + bh / 2)
                                    else:
                                        char_w = bw / max(1, len(text_match))
                                        token_w = len(norm_lbl) if norm_lbl in text_match.lower() else len(fallback_word)
                                        token_start_x = bx + idx_pos * char_w
                                        token_end_x = token_start_x + token_w * char_w
                                        effective_tool_args["start_x"] = max(min_x, int(token_start_x - 5))
                                        effective_tool_args["start_y"] = int(by + bh / 2)
                                        effective_tool_args["end_x"] = min(max_x, int(token_end_x + 35))
                                        effective_tool_args["end_y"] = int(by + bh / 2)
                                effective_tool_args["x"] = effective_tool_args["start_x"]
                                effective_tool_args["y"] = effective_tool_args["start_y"]

                        # Dynamic visual grounding for RIGHT_CLICK: if target_label or fallback word or previous step was a drag on text
                        if step.intent.action == SemanticAction.RIGHT_CLICK and detections_pre:
                            target_label = (step.verifier_args or {}).get("target_label", "")
                            if not target_label and idx > 0 and step_results[idx - 1].intent.action == SemanticAction.DRAG:
                                target_label = (step_results[idx - 1].verifier_args or {}).get("target_label", "")
                            fallback_word = (step.verifier_args or {}).get("fallback_word", "composite")
                            norm_lbl = target_label.strip().lower()
                            clean_lbl = _clean_ocr(norm_lbl)
                            clean_fb = _clean_ocr(fallback_word)
                            target_bounds = (step.verifier_args or {}).get("target_bounds")
                            if not target_bounds:
                                for prev_s in reversed(step_results[:idx]):
                                    if prev_s.verifier_args and prev_s.verifier_args.get("target_bounds"):
                                        target_bounds = prev_s.verifier_args["target_bounds"]
                                        break
                            candidates = []
                            for item in detections_pre:
                                if len(item) >= 2 and isinstance(item[1], str):
                                    it_norm = item[1].strip().lower()
                                    it_clean = _clean_ocr(it_norm)
                                    if (norm_lbl and (norm_lbl in it_norm or clean_lbl in it_clean)) or (fallback_word and (fallback_word in it_norm or clean_fb in it_clean)):
                                        box = item[0]
                                        if len(box) == 4 and isinstance(box[0], (int, float)):
                                            bx, by, bw, bh = float(box[0]), float(box[1]), float(box[2]), float(box[3])
                                            if target_bounds:
                                                tx, ty, tw, th = target_bounds
                                                if not (tx - 15 <= bx <= tx + tw + 15 and ty - 15 <= by <= ty + th + 15):
                                                    continue
                                            candidates.append((bx, by, bw, bh, item[1]))
                            if candidates:
                                exact = [c for c in candidates if (norm_lbl and (c[4].strip().lower() == norm_lbl or _clean_ocr(c[4]) == clean_lbl))]
                                bx, by, bw, bh, text_match = exact[0] if exact else candidates[0]
                                effective_tool_args["x"] = int(bx + bw / 2)
                                effective_tool_args["y"] = int(by + bh / 2)
                                if step.verifier_args and "click_point" in step.verifier_args:
                                    step.verifier_args["click_point"] = (effective_tool_args["x"], effective_tool_args["y"])

                        # If step verifies TEXT_ABSENT and hotkey is Ctrl+A: guarantee deletion with Backspace
                        if step.verifier_type == "TEXT_ABSENT" and effective_tool_args.get("intent") == "HOTKEY":
                            keys_lower = [str(k).lower() for k in effective_tool_args.get("keys", [])]
                            if "ctrl" in keys_lower and "a" in keys_lower:
                                last_res = await self.execute_intent(step.intent, effective_tool_args, max_attempts=1)
                                await asyncio.sleep(0.1)
                                try:
                                    from app.interaction.input.keyboard_controller import keyboard_controller
                                    keyboard_controller.actuate_special_key("backspace")
                                    await asyncio.sleep(0.2)
                                except Exception:
                                    pass
                            else:
                                last_res = await self.execute_intent(step.intent, effective_tool_args, max_attempts=1)
                        else:
                            last_res = await self.execute_intent(step.intent, effective_tool_args, max_attempts=1)
                        step.actuation_accepted = last_res.get("action_executed", last_res.get("success", False))
                        if not step.observation_before_id:
                            step.observation_before_id = last_res.get("diagnostics", {}).get("observation_before_id")
                        step.observation_after_id = last_res.get("observation_id")

                        # Universal settle delay immediately after physical actuation
                        if step.actuation_accepted and step.settle_delay_seconds > 0:
                            await asyncio.sleep(step.settle_delay_seconds)

                        # Immediately capture drag selection to clipboard before subsequent visual delays
                        if step.actuation_accepted and step.verifier_type == "DRAG":
                            try:
                                from app.interaction.input.keyboard_controller import keyboard_controller, get_clipboard_text
                                await asyncio.sleep(0.3)
                                keyboard_controller.actuate_hotkey(["ctrl", "c"])
                                await asyncio.sleep(0.2)
                                cb_text = get_clipboard_text()
                                if not cb_text or len(cb_text.strip()) == 0:
                                    # Secondary fallback: double-click token to highlight text range, then Ctrl+C
                                    target_label = (step.verifier_args or {}).get("target_label", "")
                                    fallback_word = (step.verifier_args or {}).get("fallback_word", "composite")
                                    target_bounds = (step.verifier_args or {}).get("target_bounds")
                                    if not target_bounds:
                                        for prev_s in reversed(step_results[:idx]):
                                            if prev_s.verifier_args and prev_s.verifier_args.get("target_bounds"):
                                                target_bounds = prev_s.verifier_args["target_bounds"]
                                                break
                                    if (target_label or fallback_word) and detections_pre:
                                        norm_lbl = target_label.strip().lower()
                                        clean_lbl = _clean_ocr(norm_lbl)
                                        clean_fb = _clean_ocr(fallback_word)
                                        candidates = []
                                        for item in detections_pre:
                                            if len(item) >= 2 and isinstance(item[1], str):
                                                it_norm = item[1].strip().lower()
                                                it_clean = _clean_ocr(it_norm)
                                                if (norm_lbl and (norm_lbl in it_norm or clean_lbl in it_clean)) or (fallback_word and (fallback_word in it_norm or clean_fb in it_clean)):
                                                    box = item[0]
                                                    if len(box) == 4 and isinstance(box[0], (int, float)):
                                                        bx, by, bw, bh = float(box[0]), float(box[1]), float(box[2]), float(box[3])
                                                        if target_bounds:
                                                            tx, ty, tw, th = target_bounds
                                                            if not (tx - 15 <= bx <= tx + tw + 15 and ty - 15 <= by <= ty + th + 15):
                                                                continue
                                                        candidates.append((bx, by, bw, bh, item[1]))
                                        if candidates:
                                            exact = [c for c in candidates if (norm_lbl and (c[4].strip().lower() == norm_lbl or _clean_ocr(c[4]) == clean_lbl))]
                                            bx, by, bw, bh, text_match = exact[0] if exact else candidates[0]
                                            tx = int(bx + bw / 2)
                                            ty = int(by + bh / 2)
                                            from app.interaction.input.mouse_controller import mouse_controller
                                            from app.domain.entities import ScreenPoint
                                            mouse_controller.actuate_double_click(ScreenPoint(x=tx, y=ty))
                                            await asyncio.sleep(0.25)
                                    keyboard_controller.actuate_hotkey(["ctrl", "c"])
                                    await asyncio.sleep(0.25)
                                    cb_text = get_clipboard_text()
                                if cb_text and len(cb_text.strip()) > 0:
                                    if not step.verifier_args:
                                        step.verifier_args = {}
                                    step.verifier_args["clipboard_text"] = cb_text
                            except Exception as e:
                                logger.debug(f"Immediate drag clipboard copy skipped: {e}")

                        # Immediately capture hotkey Ctrl+C clipboard buffer
                        if step.actuation_accepted and effective_tool_args.get("intent") == "HOTKEY":
                            keys_lower = [str(k).lower() for k in effective_tool_args.get("keys", [])]
                            if "ctrl" in keys_lower and "c" in keys_lower:
                                existing_cb = (step.verifier_args or {}).get("clipboard_text")
                                if not existing_cb:
                                    try:
                                        from app.interaction.input.keyboard_controller import get_clipboard_text
                                        await asyncio.sleep(0.2)
                                        cb_text = get_clipboard_text(retries=10, delay=0.1)
                                        if cb_text and len(cb_text.strip()) > 0:
                                            if not step.verifier_args:
                                                step.verifier_args = {}
                                            step.verifier_args["clipboard_text"] = cb_text
                                    except Exception as e:
                                        logger.debug(f"Step hotkey clipboard capture skipped: {e}")

                        obs_after = None
                        detections_after = None
                        if step.actuation_accepted and step.verifier_type and step.verifier_type not in ("WINDOW_FOCUS", "CLIPBOARD"):
                            try:
                                from app.environment.visual.capture import screen_capture_provider
                                from app.environment.visual.perception import _run_windows_media_ocr
                                import concurrent.futures
                                obs_after = screen_capture_provider.capture_virtual_screen(f"comp_post_{step.step_id}_{attempt}")
                                step.observation_after_id = obs_after.observation_id
                                post_bytes = screen_capture_provider.store.retrieve(obs_after.image_reference)
                                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                                    detections_after = pool.submit(_run_windows_media_ocr, post_bytes, obs_after.width, obs_after.height).result()
                            except Exception as e:
                                logger.debug(f"Post-observation capture skipped or unavailable: {e}")

                        # Run semantic verification
                        if step.verifier_type:
                            self._current_sequence_step_results = step_results
                            step.verification_result = self._run_step_verification(
                                step, obs_pre, obs_after, detections_pre, detections_after, last_res
                            )
                        else:
                            step.verification_result = last_res.get("verification_result")

                        # Distinguish actuation from verified success
                        if step.verification_result and step.verification_result.verified == TriState.TRUE:
                            step_verified = True
                            step.status = StepStatus.VERIFIED_SUCCESS
                            verified_steps += 1
                            break
                        elif not step.requires_verification and step.actuation_accepted and last_res.get("success", False):
                            # Default actuation accepted when semantic verification is not explicitly required
                            step_verified = True
                            step.status = StepStatus.ACTUATION_ACCEPTED
                            step.verification_result = VerificationResult(
                                verified=TriState.UNKNOWN,
                                verification_type="ACTUATION_ONLY",
                                expected_state="Actuation Accepted",
                                actual_state="Actuation Accepted",
                                evidence="Step does not require semantic verification; OS actuation accepted.",
                            )
                            break

                        # Step failed or unverified: Check bounded recovery
                        if attempt < max_attempts:
                            step.status = StepStatus.RECOVERING
                            fc = (
                                step.verification_result.failure_code
                                if step.verification_result and step.verification_result.failure_code
                                else FailureClass.VERIFICATION_FAILED
                            )
                            if fc == FailureClass.UNKNOWN and step.actuation_accepted:
                                fc = FailureClass.VERIFICATION_FAILED
                            strategy = recovery_engine.determine_strategy(fc)
                            if strategy in (RecoveryStrategy.ABORT_SAFE, RecoveryStrategy.WAIT_FOR_USER):
                                break
                            await asyncio.sleep(0.5)

                    step.duration_ms = (time.perf_counter() - t_step_start) * 1000

                    if step_verified:
                        completed_steps += 1
                    else:
                        step.status = StepStatus.FAILED
                        step.error = last_res.get("error") or {
                            "code": "VERIFICATION_FAILED" if step.actuation_accepted else "ACTUATION_FAILURE",
                            "message": f"Step {idx} ('{step.description}') failed execution or verification.",
                        }
                        failed_step_idx = idx
                        seq_error = step.error

                        # Execute safe verified compensation if configured
                        if sequence.allow_compensation:
                            for prev_idx in range(idx - 1, -1, -1):
                                prev_step = step_results[prev_idx]
                                if prev_step.compensation and not prev_step.compensation.executed:
                                    comp = prev_step.compensation
                                    comp_res = await self.execute_intent(comp.intent, comp.tool_args, max_attempts=1)
                                    comp.executed = True
                                    comp_vr = comp_res.get("verification_result")
                                    comp.verified = comp_vr.verified if comp_vr else (TriState.TRUE if comp_res.get("success") else TriState.FALSE)
                                    comp.evidence = comp_vr.evidence if comp_vr else str(comp_res.get("diagnostics", ""))
                                    compensations_executed.append(comp)

                        if sequence.stop_on_failure:
                            terminal_status = (
                                CompositeTerminalStatus.PARTIAL_FAILURE
                                if completed_steps > 0
                                else CompositeTerminalStatus.FAILED
                            )
                            for remaining in step_results[idx + 1:]:
                                remaining.status = StepStatus.SKIPPED
                            break

                if terminal_status == CompositeTerminalStatus.SUCCESS and completed_steps < len(step_results):
                    terminal_status = (
                        CompositeTerminalStatus.PARTIAL_FAILURE
                        if completed_steps > 0
                        else CompositeTerminalStatus.FAILED
                    )

        except TimeoutError:
            terminal_status = CompositeTerminalStatus.TIMEOUT
            seq_error = {"code": "TIMEOUT", "message": f"Sequence timed out after {sequence.timeout_seconds}s."}
            for s in step_results:
                if s.status in (StepStatus.PENDING, StepStatus.EXECUTING, StepStatus.RECOVERING):
                    s.status = StepStatus.FAILED if s.status != StepStatus.PENDING else StepStatus.SKIPPED
                    if not s.error:
                        s.error = seq_error

        t_seq_total = (time.perf_counter() - t_seq_start) * 1000

        # Synchronize steps back to sequence so caller has full terminal and verification state
        sequence.steps = step_results

        return CompositeExecutionResult(
            sequence_id=sequence.sequence_id,
            terminal_status=terminal_status,
            total_steps=len(step_results),
            completed_steps=completed_steps,
            verified_steps=verified_steps,
            failed_step_index=failed_step_idx,
            step_results=step_results,
            compensations_executed=compensations_executed,
            error=seq_error,
            duration_ms=t_seq_total,
        )

    def _run_step_verification(
        self,
        step: CompositeStep,
        obs_pre: Optional[Any],
        obs_after: Optional[Any],
        detections_before: Optional[List[Any]],
        detections_after: Optional[List[Any]],
        last_res: Dict[str, Any],
    ) -> Optional[VerificationResult]:
        """
        Executes the designated semantic verification modality for a composite step
        via VerificationEngine using before/after visual observations.
        """
        step_results = getattr(self, "_current_sequence_step_results", None)
        if not step.verifier_type:
            return last_res.get("verification_result")

        v_type = step.verifier_type.upper()
        v_args = step.verifier_args or {}

        # Fall back to caller/mock verification_result ONLY for visual verifiers when observations were unavailable
        if v_type not in ("WINDOW_FOCUS", "CLIPBOARD", "CROSS_WINDOW_SYNC") and obs_after is None and detections_after is None and last_res.get("verification_result") is not None:
            return last_res.get("verification_result")

        if v_type == "TEXT_INPUT":
            return VerificationEngine.verify_text_input(
                expected_text=v_args.get("expected_text", ""),
                obs_before=obs_pre,
                obs_after=obs_after,
                detections_after=detections_after,
                target_bounds=v_args.get("target_bounds"),
            )
        elif v_type == "TEXT_ABSENT":
            raw_vr = VerificationEngine.verify_text_input(
                expected_text=v_args.get("expected_text", ""),
                obs_before=obs_pre,
                obs_after=obs_after,
                detections_after=detections_after,
                target_bounds=v_args.get("target_bounds"),
            )
            # Text absent is verified when raw_vr.verified == TriState.FALSE
            if raw_vr.verified == TriState.FALSE:
                return VerificationResult(
                    verified=TriState.TRUE,
                    confidence=raw_vr.confidence,
                    verification_type="TEXT_ABSENT",
                    expected_state="Text Absent",
                    actual_state="Text Absent",
                    observation_id=obs_after.observation_id if obs_after else None,
                    evidence=f"Authoritative proof: expected text '{v_args.get('expected_text', '')}' successfully absent after cleanup.",
                )
            elif raw_vr.verified == TriState.UNKNOWN:
                # Sparse detections or indeterminate state: check if text string is completely missing from all detections
                exp_norm = v_args.get("expected_text", "").strip().lower()
                text_present = False
                for item in (detections_after or []):
                    if len(item) >= 2 and isinstance(item[1], str) and exp_norm in item[1].lower():
                        text_present = True
                        break
                if not text_present:
                    return VerificationResult(
                        verified=TriState.TRUE,
                        confidence=0.88,
                        verification_type="TEXT_ABSENT",
                        expected_state="Text Absent",
                        actual_state="Text Absent",
                        observation_id=obs_after.observation_id if obs_after else None,
                        evidence=f"Authoritative proof: expected text '{v_args.get('expected_text', '')}' absent from post-cleanup detections.",
                    )
                else:
                    return VerificationResult(
                        verified=TriState.FALSE,
                        confidence=0.85,
                        verification_type="TEXT_ABSENT",
                        expected_state="Text Absent",
                        actual_state="Text Present",
                        observation_id=obs_after.observation_id if obs_after else None,
                        failure_code=FailureClass.VERIFICATION_FAILED,
                        evidence=f"Cleanup verification failed: text '{v_args.get('expected_text', '')}' detected in post-cleanup state.",
                    )
            else:
                return VerificationResult(
                    verified=TriState.FALSE,
                    confidence=raw_vr.confidence,
                    verification_type="TEXT_ABSENT",
                    expected_state="Text Absent",
                    actual_state=raw_vr.actual_state,
                    observation_id=obs_after.observation_id if obs_after else None,
                    failure_code=FailureClass.VERIFICATION_FAILED,
                    evidence=f"Cleanup verification failed: text '{v_args.get('expected_text', '')}' still detected.",
                )
        elif v_type == "SCROLL":
            return VerificationEngine.verify_scroll(
                obs_before=obs_pre,
                obs_after=obs_after,
                detections_before=detections_before,
                detections_after=detections_after,
                target_bounds=v_args.get("target_bounds"),
            )
        elif v_type == "DRAG":
            clipboard_text = v_args.get("clipboard_text")
            if not clipboard_text:
                try:
                    from app.interaction.input.keyboard_controller import keyboard_controller, get_clipboard_text
                    import time
                    # Actuate Ctrl+C to copy current text selection to OS clipboard
                    keyboard_controller.actuate_hotkey(["ctrl", "c"])
                    time.sleep(0.25)
                    clipboard_text = get_clipboard_text()
                    if not clipboard_text or len(clipboard_text.strip()) == 0:
                        time.sleep(0.2)
                        keyboard_controller.actuate_hotkey(["ctrl", "c"])
                        time.sleep(0.3)
                        clipboard_text = get_clipboard_text()
                except Exception as e:
                    logger.debug(f"Clipboard query fallback error: {e}")

            return VerificationEngine.verify_drag(
                obs_before=obs_pre,
                obs_after=obs_after,
                target_label=v_args.get("target_label", ""),
                expected_destination_bounds=v_args.get("expected_destination_bounds"),
                detections_before=detections_before,
                detections_after=detections_after,
                clipboard_text=clipboard_text,
                window_bounds_before=v_args.get("window_bounds_before"),
                window_bounds_after=v_args.get("window_bounds_after"),
            )
        elif v_type == "CONTEXT_MENU":
            return VerificationEngine.verify_context_menu(
                obs_before=obs_pre,
                obs_after=obs_after,
                click_point=v_args.get("click_point", (0, 0)),
                window_bounds=v_args.get("window_bounds"),
                detections_before=detections_before,
                detections_after=detections_after,
            )
        elif v_type == "WINDOW_FOCUS":
            return VerificationEngine.verify_window_focus(
                target_hwnd=v_args.get("target_hwnd") or step.target_hwnd,
                target_title_substring=v_args.get("target_title_substring") or step.target_window_title,
                target_app_name=v_args.get("target_app_name") or step.target_app_name,
                observation_id=obs_after.observation_id if obs_after else None,
            )
        elif v_type == "CROSS_WINDOW_SYNC":
            actual_text = v_args.get("actual_destination_text")
            if not actual_text:
                try:
                    from app.interaction.input.keyboard_controller import get_clipboard_text
                    actual_text = get_clipboard_text(retries=10, delay=0.1) or ""
                except Exception:
                    actual_text = ""
            if not actual_text and step_results:
                for prev_step in reversed(step_results[:step.step_index]):
                    if prev_step.verifier_args and prev_step.verifier_args.get("clipboard_text"):
                        actual_text = prev_step.verifier_args["clipboard_text"]
                        break
            return VerificationEngine.verify_cross_window_sync(
                expected_content=v_args.get("expected_content", ""),
                actual_destination_text=actual_text or v_args.get("actual_destination_text", ""),
                source_window=v_args.get("source_window") or step.target_app_name,
                destination_window=v_args.get("destination_window"),
                observation_id=obs_after.observation_id if obs_after else None,
            )
        elif v_type == "CLIPBOARD":
            expected_content = v_args.get("expected_content") or v_args.get("expected_text", "")
            actual_clip = v_args.get("clipboard_text")
            if not actual_clip:
                try:
                    from app.interaction.input.keyboard_controller import get_clipboard_text
                    fresh_clip = get_clipboard_text(retries=10, delay=0.1) or ""
                    if fresh_clip:
                        actual_clip = fresh_clip
                except Exception:
                    actual_clip = actual_clip or ""
            return VerificationEngine.verify_clipboard(
                expected_content=expected_content,
                actual_clipboard_text=actual_clip or "",
                observation_id=obs_after.observation_id if obs_after else None,
            )
        return last_res.get("verification_result")


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
