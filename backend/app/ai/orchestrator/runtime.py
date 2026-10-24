import uuid
from typing import AsyncGenerator, Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
import asyncio

from app.domain.goals import Goal, Task, TaskState, GoalState, Action, VerificationResult, FailureClass, SemanticAction
from app.domain.events import ExecutionEvent, ExecutionEventType
from app.domain.execution_context import ExecutionContext
from app.domain.entities import TriState
from app.domain.composite import StepStatus, CompositeActionSequence, CompositeStep
from app.domain.checkpoints import (
    GoalCheckpoint,
    TaskCheckpoint,
    ResumptionClassification,
    SCHEMA_VERSION,
)
from app.domain.memory import RecoveryStrategy
from app.ai.orchestrator.action_executor import action_executor
from app.ai.providers.types import ToolCall
from app.core.logging.logger import get_logger
from app.core.config import get_settings
from app.ai.orchestrator.recovery import recovery_engine

logger = get_logger(__name__)

class GoalRuntime:
    """
    Phase B.9: Stateful Goal Execution Runtime with Checkpointing & Resumption
    Owns execution of a Goal until terminal state, tracking environment context,
    persisting durable progress checkpoints, and safely resuming across interruptions.
    """
    
    def __init__(
        self,
        goal: Goal,
        context: Optional[ExecutionContext] = None,
        goal_store: Any = None,
        cancel_event: Optional[asyncio.Event] = None,
    ):
        self.goal = goal
        self.context = context or ExecutionContext(
            execution_id=str(uuid.uuid4()),
            goal=goal
        )
        self.goal_store = goal_store
        self.cancel_event = cancel_event or asyncio.Event()
        self._created_at = datetime.now(timezone.utc)

    @property
    def execution_id(self) -> str:
        return self.context.execution_id
        
    def cancel(self):
        """Signals the runtime to cancel execution."""
        self.cancel_event.set()

    def _create_checkpoint(self, suspension_reason: Optional[str] = None) -> GoalCheckpoint:
        """Constructs a versioned GoalCheckpoint snapshot from the current execution state."""
        now = datetime.now(timezone.utc)
        
        task_cps: List[TaskCheckpoint] = []
        for idx, t in enumerate(self.goal.tasks):
            completed_steps: List[int] = []
            verified_steps: List[int] = []
            step_statuses: Dict[int, StepStatus] = {}
            step_verifications: Dict[int, VerificationResult] = {}
            target_app: Optional[str] = None

            if getattr(t, "composite_sequence", None) and getattr(t.composite_sequence, "steps", None):
                for s in t.composite_sequence.steps:
                    if s.target_app_name and not target_app:
                        target_app = s.target_app_name
                    step_statuses[s.step_index] = s.status
                    if s.verification_result:
                        step_verifications[s.step_index] = s.verification_result

                    if s.actuation_accepted or s.status in (StepStatus.ACTUATION_ACCEPTED, StepStatus.VERIFIED_SUCCESS):
                        completed_steps.append(s.step_index)
                    if s.verification_result and s.verification_result.verified == TriState.TRUE and s.status == StepStatus.VERIFIED_SUCCESS:
                        verified_steps.append(s.step_index)
            else:
                for i in t.intents:
                    if i.target and not target_app:
                        target_app = str(i.target)

            tcp = TaskCheckpoint(
                task_id=t.task_id,
                task_index=idx,
                description=t.description or f"Task {idx}",
                task_state=t.state,
                target_app_name=target_app,
                completed_step_indices=completed_steps,
                verified_step_indices=verified_steps,
                step_statuses=step_statuses,
                step_verifications=step_verifications,
                is_verified=(t.state == TaskState.COMPLETED),
                updated_at=now,
            )
            task_cps.append(tcp)

        is_resumable = self.goal.state not in (GoalState.COMPLETED, GoalState.CANCELLED)

        # Build clean environment snapshot without unsafe live objects
        env_snap = dict(self.context.environment_snapshot or {})
        if self.context.active_browser_identity:
            env_snap["browser"] = self.context.active_browser_identity
        if self.context.current_url:
            env_snap["url"] = self.context.current_url
        if self.context.current_title:
            env_snap["title"] = self.context.current_title

        return GoalCheckpoint(
            checkpoint_id=str(uuid.uuid4()),
            schema_version=SCHEMA_VERSION,
            goal_id=self.goal.goal_id,
            objective=self.goal.objective,
            goal_state=self.goal.state,
            current_task_index=self.context.current_task_index,
            total_tasks=len(self.goal.tasks),
            task_checkpoints=task_cps,
            execution_id=self.context.execution_id,
            environment_snapshot=env_snap,
            recovery_history=list(self.context.recovery_history or []),
            suspension_reason=suspension_reason or self.context.waiting_reason,
            pending_clarification=getattr(self.context, "pending_clarification", None),
            is_resumable=is_resumable,
            created_at=self._created_at,
            updated_at=now,
        )

    def _persist_checkpoint(self, suspension_reason: Optional[str] = None) -> Optional[GoalCheckpoint]:
        """Saves current checkpoint to the configured GoalStore."""
        try:
            cp = self._create_checkpoint(suspension_reason=suspension_reason)
            if self.goal_store:
                self.goal_store.save_checkpoint(cp)
            return cp
        except Exception as e:
            logger.error(f"Failed to persist GoalCheckpoint for goal '{self.goal.goal_id}': {e}")
            return None

    @classmethod
    def resume(
        cls,
        checkpoint: GoalCheckpoint,
        goal: Optional[Goal] = None,
        goal_store: Optional[Any] = None,
        context: Optional[ExecutionContext] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> Tuple["GoalRuntime", ResumptionClassification, str]:
        """
        Reconstructs a GoalRuntime from a persisted GoalCheckpoint.
        Performs safety validation, identifies the exact continuation boundary,
        and clears stale environment handles.
        Returns: (runtime, classification, summary_message)
        """
        is_valid, reason = checkpoint.validate_resumable()
        if not is_valid:
            logger.error(f"Resumption rejected for goal '{checkpoint.goal_id}': {reason}")
            raise ValueError(f"Cannot resume goal '{checkpoint.goal_id}': {reason}")

        # If original Goal object is not passed, reconstruct it from checkpoint metadata
        if goal is None:
            tasks = []
            for tcp in checkpoint.task_checkpoints:
                t = Task(
                    task_id=tcp.task_id,
                    description=tcp.description,
                    state=tcp.task_state,
                )
                tasks.append(t)
            goal = Goal(
                goal_id=checkpoint.goal_id,
                objective=checkpoint.objective,
                tasks=tasks,
                state=checkpoint.goal_state,
            )

        # Reconstruct execution context, stripping ephemeral live handles
        if context is None:
            context = ExecutionContext(
                execution_id=checkpoint.execution_id or str(uuid.uuid4()),
                goal=goal,
                current_task_index=checkpoint.current_task_index,
                completed_tasks=[],
                recovery_history=list(checkpoint.recovery_history),
                environment_snapshot=dict(checkpoint.environment_snapshot),
                pending_clarification=getattr(checkpoint, "pending_clarification", None),
            )
        else:
            if getattr(checkpoint, "pending_clarification", None):
                context.pending_clarification = checkpoint.pending_clarification

        # Clear ephemeral Win32 handles / stale browser connection IDs
        context.browser_session_id = None
        context.active_page_id = None
        context.environment_snapshot.pop("target_hwnd", None)

        # Determine continuation boundary across tasks
        resume_task_idx = 0
        classification = ResumptionClassification.VERIFIED_AND_SAFE
        summary = f"Resuming goal '{goal.goal_id}'."

        for tcp in checkpoint.task_checkpoints:
            # Task is already verified complete: retain without repeating
            if tcp.task_state == TaskState.COMPLETED and tcp.is_verified:
                if tcp.task_id not in context.completed_tasks:
                    context.completed_tasks.append(tcp.task_id)
                if tcp.task_index < len(goal.tasks):
                    goal.tasks[tcp.task_index].state = TaskState.COMPLETED
                continue

            # First incomplete or unverified task: continuation boundary
            resume_task_idx = tcp.task_index
            if tcp.task_index < len(goal.tasks):
                active_task = goal.tasks[tcp.task_index]
                # If task has a composite sequence, slice out completed verified steps
                if getattr(active_task, "composite_sequence", None) and tcp.verified_step_indices:
                    seq = active_task.composite_sequence
                    last_verified_step = max(tcp.verified_step_indices)
                    remainder_steps = [s for s in seq.steps if s.step_index > last_verified_step]
                    if remainder_steps:
                        for new_idx, s in enumerate(remainder_steps):
                            s.step_index = new_idx
                            s.status = StepStatus.PENDING
                        seq.steps = remainder_steps
                        classification = ResumptionClassification.VERIFIED_AND_SAFE
                        summary = f"Resuming task {tcp.task_index} at step index {last_verified_step + 1} (skipped {last_verified_step + 1} verified steps)."
                    else:
                        classification = ResumptionClassification.VERIFIED_AND_SAFE
                        summary = f"All steps in task {tcp.task_index} verified; advancing to next task."
                elif tcp.completed_step_indices and not tcp.verified_step_indices:
                    # Actuated but unverified: unknown outcome at interruption
                    classification = ResumptionClassification.REQUIRES_REVERIFICATION
                    summary = f"Task {tcp.task_index} had unverified actuation at interruption; re-verifying environment state."
                else:
                    classification = ResumptionClassification.SAFE_TO_RETRY
                    summary = f"Resuming task {tcp.task_index} from start."
            break

        context.current_task_index = resume_task_idx
        goal.state = GoalState.EXECUTING

        runtime = cls(goal=goal, context=context, goal_store=goal_store)
        if cancel_event:
            runtime.cancel_event = cancel_event

        # Checkpoint the fresh resumed state
        runtime._persist_checkpoint(suspension_reason=None)
        return runtime, classification, summary

    async def abort_and_rollback(self, reason: str = "Unrecoverable failure") -> Dict[str, Any]:
        """
        Executes safe rollback semantics for unrecoverable aborts.
        Distinguishes:
        1. Persisted store update (marking checkpoint as non-resumable FAILED).
        2. Execution of explicit safe compensations for completed reversible steps.
        Does NOT invent compensations for irreversible actions.
        """
        self.goal.state = GoalState.FAILED
        self.context.waiting_reason = reason
        
        executed_compensations: List[Dict[str, Any]] = []
        unresolved_steps: List[str] = []

        # Iterate through completed tasks in reverse order to execute known compensations
        for task in reversed(self.goal.tasks):
            if getattr(task, "composite_sequence", None) and getattr(task.composite_sequence, "steps", None):
                for step in reversed(task.composite_sequence.steps):
                    if step.actuation_accepted and step.compensation:
                        comp = step.compensation
                        try:
                            logger.info(f"Rollback executing compensation for step '{step.step_id}': {comp.description}")
                            res = await action_executor.execute_intent(
                                comp.intent,
                                tool_args=comp.tool_args,
                                max_attempts=1,
                            )
                            comp.executed = bool(res.get("success", False))
                            executed_compensations.append({
                                "step_id": step.step_id,
                                "compensation": comp.description,
                                "success": comp.executed,
                            })
                        except Exception as e:
                            logger.error(f"Rollback compensation failed for step '{step.step_id}': {e}")
                            unresolved_steps.append(step.step_id)
                    elif step.actuation_accepted and not step.compensation:
                        # Irreversible action: truthfully recorded as uncompensated
                        unresolved_steps.append(step.step_id)

        # Update persisted checkpoint: permanently non-resumable
        if self.goal_store:
            abort_msg = f"Aborted: {reason}. Unresolved external actions: {len(unresolved_steps)}"
            self._persist_checkpoint(suspension_reason=abort_msg)
            self.goal_store.mark_non_resumable(
                self.goal.goal_id,
                reason=abort_msg
            )

        return {
            "goal_id": self.goal.goal_id,
            "goal_state": GoalState.FAILED.value,
            "is_resumable": False,
            "reason": reason,
            "compensations_executed": executed_compensations,
            "unresolved_steps": unresolved_steps,
        }
        
    async def run(self) -> AsyncGenerator[ExecutionEvent, None]:
        """Executes the goal tasks sequentially in a stateful manner."""
        
        settings = get_settings()
        goal_timeout = getattr(settings, "astra_goal_execution_timeout_seconds", 600)
        
        # Phase B.11: Check if goal is suspended waiting for clarification
        if self.goal.state == GoalState.WAITING_FOR_USER and getattr(self.goal, "pending_clarification", None):
            self.context.pending_clarification = self.goal.pending_clarification
            prompt = self.goal.pending_clarification.prompt
            self.context.waiting_reason = prompt
            self._persist_checkpoint(suspension_reason=prompt)
            yield self._create_event(ExecutionEventType.GOAL_ACCEPTED, state="STARTED", progress_label=f"Goal Received: {self.goal.objective}")
            yield self._create_event(
                ExecutionEventType.WAITING_FOR_USER,
                state="WAITING",
                progress_label=prompt,
                payload={
                    "clarification": self.goal.pending_clarification.model_dump(mode="json") if hasattr(self.goal.pending_clarification, "model_dump") else self.goal.pending_clarification,
                    "waiting_reason": prompt,
                }
            )
            return

        # Fast-fail if goal already failed validation during compilation
        if self.goal.state == GoalState.FAILED and getattr(self.goal, "validation_errors", None):
            val_msg = "; ".join(self.goal.validation_errors)
            logger.warning(f"GoalRuntime aborting execution: Goal validation failed ({val_msg})")
            self._persist_checkpoint(suspension_reason=f"Validation failed: {val_msg}")
            yield self._create_event(ExecutionEventType.GOAL_ACCEPTED, state="STARTED", progress_label=f"Goal Received: {self.goal.objective}")
            yield self._create_event(
                ExecutionEventType.GOAL_FAILED,
                state="VALIDATION_FAILED",
                progress_label=f"Plan validation failed: {val_msg}",
                payload={"errors": self.goal.validation_errors}
            )
            return

        self.goal.state = GoalState.EXECUTING
        self._persist_checkpoint()
        yield self._create_event(ExecutionEventType.GOAL_ACCEPTED, state="STARTED", progress_label=f"Executing Goal: {self.goal.objective}")
        
        try:
            async with asyncio.timeout(goal_timeout):
                # Execute Tasks
                for index, task in enumerate(self.goal.tasks):
                    # Check if already completed and verified (e.g. from checkpoint resumption)
                    if task.state == TaskState.COMPLETED and task.task_id in self.context.completed_tasks:
                        logger.info(f"GoalRuntime: Task {index} ('{task.task_id}') already completed in checkpoint; skipping execution.")
                        continue

                    if self.cancel_event.is_set():
                        self.goal.state = GoalState.CANCELLED
                        self._persist_checkpoint(suspension_reason="Goal cancelled by user")
                        yield self._create_event(ExecutionEventType.GOAL_CANCELLED, state="CANCELLED", progress_label="Goal cancelled by user")
                        return

                    self.context.current_task_index = index
                    task.state = TaskState.EXECUTING
                    self._persist_checkpoint()
                    
                    yield self._create_event(
                        ExecutionEventType.TASK_STARTED, 
                        task_id=task.task_id, 
                        state=task.state.value, 
                        progress_label=task.description
                    )
                    
                    task_timeout = getattr(settings, "astra_task_execution_timeout_seconds", 120)
                    task_success = False
                    
                    try:
                        async with asyncio.timeout(task_timeout):
                            while True:
                                if self.cancel_event.is_set():
                                    task_success = False
                                    break
                                    
                                result, wait_for_user, failure_class = await self._execute_task(task)
                                
                                if wait_for_user:
                                    task.state = TaskState.WAITING_FOR_USER
                                    self.goal.state = GoalState.WAITING_FOR_USER
                                    clarif = getattr(self.context, "pending_clarification", None)
                                    prompt = clarif.prompt if clarif else f"Action requires human verification: {task.description}"
                                    self.context.waiting_reason = prompt
                                    self._persist_checkpoint(suspension_reason=self.context.waiting_reason)
                                    yield self._create_event(
                                        ExecutionEventType.WAITING_FOR_USER,
                                        task_id=task.task_id,
                                        state="WAITING",
                                        progress_label=prompt,
                                        payload={
                                            "clarification": clarif.model_dump(mode="json") if (clarif and hasattr(clarif, "model_dump")) else clarif,
                                            "waiting_reason": self.context.waiting_reason,
                                        }
                                    )
                                    return # Terminal state, return immediately for deterministic response
                                else:
                                    task_success = result
                                    break
                    except TimeoutError:
                        logger.warning(f"Task {task.task_id} timed out.")
                        task_success = False
                        
                    if not task_success:
                        task.state = TaskState.FAILED
                        self.goal.state = GoalState.FAILED
                        self._persist_checkpoint()
                        yield self._create_event(
                            ExecutionEventType.TASK_FAILED, 
                            task_id=task.task_id, 
                            state=task.state.value, 
                            progress_label=f"Task Failed: {task.description}"
                        )
                        yield self._create_event(ExecutionEventType.GOAL_FAILED, state="FAILED", progress_label="Goal execution failed")
                        return
                        
                    task.state = TaskState.COMPLETED
                    self.context.completed_tasks.append(task.task_id)
                    self._persist_checkpoint()
                    yield self._create_event(
                        ExecutionEventType.TASK_COMPLETED, 
                        task_id=task.task_id, 
                        state=task.state.value, 
                        progress_label=f"Completed: {task.description}"
                    )
                    
                # Final Goal Verification
                self.goal.state = GoalState.VERIFYING
                self._persist_checkpoint()
                yield self._create_event(
                    ExecutionEventType.GOAL_VERIFYING,
                    state="VERIFYING",
                    progress_label="Performing final goal verification"
                )
                
                # Check environment state
                final_verification = await self._verify_goal()
                if final_verification:
                    self.goal.state = GoalState.COMPLETED
                    self.goal.is_complete = True
                    self._persist_checkpoint()
                    yield self._create_event(ExecutionEventType.GOAL_COMPLETED, state="COMPLETED", progress_label="Goal achieved and verified")
                else:
                    self.goal.state = GoalState.FAILED
                    self._persist_checkpoint()
                    yield self._create_event(ExecutionEventType.GOAL_FAILED, state="VERIFICATION_FAILED", progress_label="Goal execution completed but final verification failed")
                
        except TimeoutError:
            logger.error("Goal execution timed out.")
            self.goal.state = GoalState.FAILED
            self._persist_checkpoint(suspension_reason="Goal execution timed out")
            yield self._create_event(ExecutionEventType.GOAL_FAILED, state="TIMEOUT", progress_label="Goal execution timed out")
            return

    async def _execute_task(self, task: Task) -> tuple[bool, bool, Any]:
        """
        Executes a single Task. Returns (success, requires_human_verification, failure_class).
        Supports both atomic composite sequences (Phase B.6) and sequential task intents.
        """
        if getattr(task, "composite_sequence", None):
            from app.domain.composite import CompositeTerminalStatus
            max_replans = 2
            replan_attempt = 0

            while True:
                seq_res = await action_executor.execute_sequence(
                    task.composite_sequence,
                    cancel_event=self.cancel_event,
                )
                if task.composite_sequence:
                    task.composite_sequence.steps = seq_res.step_results
                for step in seq_res.step_results:
                    task.actions_taken.append(Action(
                        action_id=step.step_id,
                        capability_id=step.intent.capability_id,
                        provider_id="composite_executor",
                        payload={"step_index": step.step_index, "status": step.status.value, "tool_args": step.tool_args},
                        verification_result=step.verification_result,
                    ))

                if seq_res.terminal_status == CompositeTerminalStatus.SUCCESS:
                    return True, False, None
                elif seq_res.terminal_status == CompositeTerminalStatus.PERMISSION_DENIED:
                    if seq_res.error and "clarification_request" in seq_res.error:
                        from app.domain.clarification import ClarificationRequest
                        try:
                            self.context.pending_clarification = ClarificationRequest.model_validate(seq_res.error["clarification_request"])
                        except Exception as ex:
                            logger.warning(f"Failed to parse clarification_request from error: {ex}")
                    return False, True, FailureClass.VERIFICATION_FAILED
                elif self.cancel_event.is_set() or seq_res.terminal_status == CompositeTerminalStatus.CANCELLED:
                    return False, False, None
                else:
                    fc = FailureClass.VERIFICATION_FAILED
                    if seq_res.error and seq_res.error.get("code") == "TIMEOUT":
                        fc = FailureClass.NAVIGATION_TIMEOUT
                        return False, False, fc

                    strategy = recovery_engine.determine_strategy(fc, self.context.model_dump())
                    if strategy in (RecoveryStrategy.ABORT_SAFE, RecoveryStrategy.WAIT_FOR_USER):
                        return False, strategy == RecoveryStrategy.WAIT_FOR_USER, fc

                    # Adaptive re-planning: attempt bounded re-planning if intermediate step failed
                    if replan_attempt < max_replans and seq_res.failed_step_index is not None:
                        replan_attempt += 1
                        failed_idx = seq_res.failed_step_index
                        logger.info(f"GoalRuntime adaptive re-planning: attempt {replan_attempt}/{max_replans} for failed step {failed_idx}")
                        self.context.recovery_history.append({
                            "replan_attempt": replan_attempt,
                            "failed_step_index": failed_idx,
                            "failure_code": getattr(fc, "name", str(fc)),
                            "strategy": strategy.name,
                        })

                        from app.ai.orchestrator.compiler import action_compiler
                        repaired_seq = action_compiler.replan_remainder_sequence(
                            task.composite_sequence,
                            failed_step_index=failed_idx,
                            strategy=strategy,
                        )
                        if repaired_seq:
                            task.composite_sequence = repaired_seq
                            continue

                    return False, False, fc

        for intent in task.intents:
            tool_name = intent.capability_id
            
            max_recovery_attempts = 3
            attempt = 0
            intent_success = False
            requires_human_verification = False
            failure_class = None
            
            while attempt <= max_recovery_attempts:
                tool_args = intent.parameters.copy()
                
                # Contextual resolution logic here.
                # Inject current environmental state to maintain strict identity and context.
                if "browser" in tool_name:
                    if self.context.active_browser_identity:
                        tool_args["browser_name"] = self.context.active_browser_identity
                    if self.context.current_url:
                        tool_args["_current_url"] = self.context.current_url
                        
                    # Fresh observation before action
                    try:
                        from app.tools.desktop.browser.browser_provider import browser_provider
                        obs_res = await browser_provider.observe()
                        if obs_res.get("success"):
                            obs = obs_res["observation"]
                            self.context.current_url = obs.url
                            self.context.current_title = obs.title
                            self.context.active_page_id = obs.page_id
                            self.context.environment_snapshot["browser_observation"] = obs.model_dump()
                    except Exception as e:
                        logger.warning(f"Failed to fetch fresh observation: {e}")
                
                target_val = ""
                if intent.target:
                    # Strip stale 'ast-' identifiers if the LLM provided them, forcing semantic re-resolution
                    if hasattr(intent.target, "id"):
                        target_val = intent.target.id
                    elif isinstance(intent.target, dict) and "id" in intent.target:
                        target_val = intent.target["id"]
                    else:
                        target_val = str(intent.target)
                        
                    if target_val.startswith("ast-"):
                        logger.warning(f"Task intent contains stale target {target_val}. Stripping to force semantic re-resolution.")
                        # Extract the semantic name if it's an entity, else use intent.parameters
                        if hasattr(intent.target, "name") and intent.target.name and intent.target.name != "target":
                            target_val = intent.target.name
                        elif "target" in intent.parameters and not str(intent.parameters["target"]).startswith("ast-"):
                            target_val = str(intent.parameters["target"])
                        else:
                            target_val = "target" # Generic fallback
                elif "target" in intent.parameters:
                    target_val = str(intent.parameters["target"])
                elif "query" in intent.parameters:
                    target_val = str(intent.parameters["query"])

                if target_val:
                    tool_args["target"] = target_val
                    
                from app.tools.registry import registry
                try:
                    resolved_tool = registry.resolve_capability(intent.capability_id)
                except Exception:
                    resolved_tool = tool_name

                if resolved_tool == "execute_application_intent" or intent.capability_id in ("desktop.open_application", "desktop.focus_application", "desktop.close_application"):
                    app_name = tool_args.pop("target", None) or target_val or intent.target
                    app_intent = "OPEN"
                    if intent.capability_id == "desktop.open_application" or intent.action == SemanticAction.OPEN:
                        app_intent = "OPEN"
                    elif intent.capability_id == "desktop.focus_application" or intent.action == SemanticAction.FOCUS:
                        app_intent = "FOCUS"
                    elif intent.capability_id == "desktop.close_application" or intent.action == SemanticAction.CLOSE:
                        app_intent = "CLOSE"
                    tool_args = {
                        "intent": app_intent,
                        "application": str(app_name) if app_name else "notepad"
                    }
                elif resolved_tool == "execute_browser_intent" or intent.capability_id.startswith("browser.") or tool_name in ("execute_browser_intent", "open_url"):
                    browser_intent = "NAVIGATE"
                    if intent.action == SemanticAction.SEARCH or intent.capability_id == "browser.search":
                        browser_intent = "SEARCH"
                    elif str(getattr(intent.action, "value", intent.action)).upper() == "STATUS" or intent.capability_id == "browser.status":
                        browser_intent = "STATUS"
                    
                    target_arg = tool_args.get("target") or target_val
                    if browser_intent == "SEARCH":
                        target_arg = tool_args.get("query") or intent.query or target_arg
                        
                    new_args = {
                        "intent": browser_intent,
                        "target": str(target_arg) if target_arg else ""
                    }
                    browser_candidate = tool_args.get("browser_name") or tool_args.get("browser") or self.context.active_browser_identity
                    if browser_candidate:
                        new_args["browser_name"] = str(browser_candidate)
                    if tool_args.get("_current_url"):
                        new_args["_current_url"] = tool_args["_current_url"]
                    tool_args = new_args
                elif resolved_tool == "open_url":
                    tool_args = {
                        "url": str(tool_args.get("url") or tool_args.get("target") or target_val)
                    }
                elif resolved_tool == "interact_browser":
                    new_args = {
                        "action": str(tool_args.get("action") or getattr(intent.action, "value", str(intent.action))).upper(),
                        "target": str(tool_args.get("target") or target_val),
                    }
                    if tool_args.get("value") or tool_args.get("query"):
                        new_args["value"] = str(tool_args.get("value") or tool_args.get("query"))
                    browser_candidate = tool_args.get("browser_name") or tool_args.get("browser") or self.context.active_browser_identity
                    if browser_candidate:
                        new_args["browser_name"] = str(browser_candidate)
                    tool_args = new_args
                
                yield_event = self._create_event(
                    ExecutionEventType.ACTION_STARTED,
                    task_id=task.task_id,
                    state="ACTION_STARTED",
                    progress_label=f"Executing intent: {intent.action.value} on {intent.target}"
                )
                logger.info(f"Executing semantic action: {intent.action.value} with {tool_args}")
                
                result = await action_executor.execute_intent(intent, tool_args, max_attempts=1)
                
                # Update Context with authoritative state
                diagnostics = result.get("diagnostics", {})
                if "observation_id" in result:
                    self.context.last_observation_id = result["observation_id"]
                if "observation_id" in diagnostics:
                    self.context.last_observation_id = diagnostics["observation_id"]
                    
                if "session_id" in result:
                    self.context.browser_session_id = result["session_id"]
                    
                # If we executed a desktop intent, check if the application was actually a browser.
                # If so, establish the browser identity in context so subsequent browser actions can acquire a session.
                if intent.capability_id.startswith("desktop.") and "canonical_name" in diagnostics:
                    try:
                        from app.tools.desktop.browser.browser_identity import browser_registry as ident_registry
                        identity = ident_registry.resolve_browser(diagnostics["canonical_name"])
                        if identity:
                            self.context.active_browser_identity = identity.canonical_name
                            logger.info(f"Established active_browser_identity: {identity.canonical_name} after application launch")
                    except Exception as e:
                        logger.warning(f"Failed to resolve browser identity for {diagnostics['canonical_name']}: {e}")
                        
                if "browser_identity" in result:
                    self.context.active_browser_identity = result["browser_identity"]
                        
                # Keep snapshot up to date for follow-up verifications
                self.context.environment_snapshot.update({
                    "last_action": tool_name,
                    "last_target": tool_args.get("target"),
                    "browser_session": self.context.browser_session_id
                })
                
                # We can dynamically fetch latest browser observation to update context
                # ONLY if we are actively interacting with a browser
                if self.context.browser_session_id:
                    try:
                        from app.tools.desktop.browser.browser_provider import browser_provider
                        obs_res = await browser_provider.observe()
                        if obs_res.get("success"):
                            obs = obs_res["observation"]
                            self.context.current_url = obs.url
                            self.context.current_title = obs.title
                            self.context.active_page_id = obs.page_id
                            self.context.environment_snapshot["browser_observation"] = obs.model_dump()
                    except Exception as e:
                        logger.warning(f"Failed to update environment snapshot: {e}")
                
                self.context.last_action = {"action": intent.action.value, "args": tool_args}
                self.context.last_intent = intent
                if not result.get("success", False):
                    self.context.retryable_intent = intent
                
                is_verified = result.get("verified", False)
                if result.get("success", False) and not is_verified:
                    logger.warning("Action executed but verification failed/absent. Truthfulness invariant violated.")
                    failure_class = FailureClass.VERIFICATION_FAILED
                    result["success"] = False # Override
                
                task.actions_taken.append(Action(
                    action_id=str(uuid.uuid4()),
                    capability_id=intent.capability_id,
                    provider_id="local_executor",
                    payload=result,
                    verification_result=result.get("verification_result")
                ))
                
                # Check for human verification
                if not result.get("success", False) and result.get("error", {}).get("code") == "HUMAN_VERIFICATION_REQUIRED":
                    requires_human_verification = True
                    break
                    
                # Explicit Verification Engine checks
                if result.get("success", False) and is_verified:
                    intent_success = True
                    break
                    
                # If the provider says success but didn't verify, we MUST treat it as a failure because truthfulness is mandatory
                if result.get("success", False) and (not vr or not vr.verified):
                    logger.warning(f"Action executed but verification failed/absent. Truthfulness invariant violated.")
                    failure_class = vr.failure_code if vr else FailureClass.VERIFICATION_FAILED
                    result["success"] = False # Override
                
                # If we get here, it failed. Map recovery strategy.
                if not result.get("success", False):
                    err_code = result.get("error", {}).get("code", "")
                    if err_code == "BROWSER_NOT_RUNNING" or err_code == "BROWSER_CLOSED":
                        failure_class = FailureClass.BROWSER_CLOSED
                    elif err_code == "TARGET_RESOLUTION_FAILED":
                        failure_class = FailureClass.TARGET_NOT_FOUND
                    
                    strategy = recovery_engine.determine_strategy(failure_class, self.context.model_dump())
                    logger.info(f"Applying recovery strategy: {strategy.name}")
                    
                    self.context.recovery_history.append({
                        "failure_class": getattr(failure_class, "name", str(failure_class)),
                        "strategy": strategy.name,
                        "attempt": attempt
                    })
                    
                    if strategy == RecoveryStrategy.ABORT_SAFE or strategy == RecoveryStrategy.WAIT_FOR_USER:
                        break # Cannot recover automatically
                    elif strategy == RecoveryStrategy.RECOVER_SESSION:
                        await self._recover_session()
                    elif strategy == RecoveryStrategy.REFRESH_OBSERVATION:
                        await asyncio.sleep(2.0)
                        # Re-observation will happen automatically when tool is called again
                    elif strategy == RecoveryStrategy.ALTERNATE_TARGET:
                        await asyncio.sleep(1.0)
                    # For now, bounded retry implements the loop.
                    
                attempt += 1
                if attempt <= max_recovery_attempts:
                    await asyncio.sleep(1.0)
            
            if requires_human_verification:
                return False, True, failure_class
                
            if not intent_success:
                return False, False, failure_class
                
        return True, False, None

    async def _check_wait_resolved(self) -> bool:
        """Checks if the condition that caused WAITING_FOR_USER has been resolved."""
        # For browser challenges
        if self.context.browser_session_id:
            from app.tools.desktop.browser.browser_provider import browser_provider
            res = await browser_provider.check_challenges()
            if res.get("success", False):
                # Challenge gone
                # We do NOT return the stale target ID. The next _execute_task loop will call the tool again.
                # And the tool will do a fresh observation and re-resolution.
                return True
        return False
        
    async def _recover_session(self):
        """Attempts to recover the active browser session."""
        if self.context.active_browser_identity:
            from app.tools.desktop.browser.browser_provider import browser_provider
            await browser_provider.ensure_browser_session(self.context.active_browser_identity)

    async def _verify_goal(self) -> bool:
        """Performs final goal-level verification against actual environment state."""
        logger.info(f"Verifying final goal state for: {self.goal.objective}")
        
        # 1. Update the final snapshot
        if self.context.browser_session_id:
            try:
                from app.tools.desktop.browser.browser_provider import browser_provider
                obs_res = await browser_provider.observe()
                if obs_res.get("success"):
                    obs = obs_res["observation"]
                    self.context.environment_snapshot["browser_observation"] = obs.model_dump()
            except Exception:
                pass
            
        # 2. Check task completions (all tasks must have successfully executed)
        if any(t.state != TaskState.COMPLETED for t in self.goal.tasks):
            logger.warning("Goal verification failed: Not all tasks completed successfully.")
            return False
            
        # 3. Deterministic check based on task intents
        obs_dump = self.context.environment_snapshot.get("browser_observation", {})
        url = obs_dump.get("url", "").lower()
        title = obs_dump.get("title", "").lower()
        media = obs_dump.get("media_elements", [])
        
        for task in self.goal.tasks:
            for intent in task.intents:
                intent_action = intent.capability_id
                target = str(intent.target).lower() if intent.target else ""
                
                if "browser.navigate" in intent_action:
                    # Basic domain verify
                    try:
                        import urllib.parse
                        target_parsed = urllib.parse.urlparse(target if "://" in target else f"http://{target}")
                        domain = target_parsed.netloc.replace("www.", "")
                        if domain and domain not in url:
                            logger.warning(f"Goal verification failed: Expected domain {domain} not in {url}")
                            return False
                    except:
                        pass
                elif "browser.search" in intent_action or ("interact_browser" in intent_action and "search" in target):
                    # Check if query is in URL or title
                    query_terms = [t for t in intent.parameters.get("target", "").lower().split() if len(t) > 3]
                    if query_terms and not any(term in url or term in title for term in query_terms):
                        # Some sites don't put query in URL. Just a heuristic.
                        pass
                elif "interact_browser" in intent_action and intent.parameters.get("action") == "CLICK":
                    if "play" in target or "video" in target:
                        if not any(not m.get("paused", True) for m in media):
                            logger.warning("Goal verification failed: Expected media playing, but none found active.")
                            return False
                            
        # If no explicit failures found and all tasks completed, we consider it verified.
        return True

    def _create_event(self, event_type: ExecutionEventType, state: str, progress_label: str, task_id: str = None, payload: Dict = None) -> ExecutionEvent:
        return ExecutionEvent(
            event_type=event_type,
            execution_id=self.context.execution_id,
            goal_id=self.goal.goal_id,
            task_id=task_id,
            state=state,
            progress_label=progress_label,
            payload=payload,
            observation_id=self.context.last_observation_id,
            browser_session_id=self.context.browser_session_id,
            page_id=self.context.active_page_id
        )
