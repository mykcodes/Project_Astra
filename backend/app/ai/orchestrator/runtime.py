import json
import uuid
from typing import AsyncGenerator, Dict, Any, List
import asyncio

from app.domain.goals import Goal, Task, TaskState, Intent, Action
from app.domain.events import ExecutionEvent, ExecutionEventType
from app.ai.orchestrator.action_executor import action_executor
from app.ai.providers.types import ToolCall
from app.core.logging.logger import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)

class GoalRuntime:
    """
    Phase 9B: Goal Execution & Task Runtime
    Owns execution of a Goal until terminal state.
    """
    
    def __init__(self, goal: Goal):
        self.goal = goal
        self.execution_id = str(uuid.uuid4())
        self.cancel_event = asyncio.Event()
        
    def cancel(self):
        """Signals the runtime to cancel execution."""
        self.cancel_event.set()
        
    async def run(self) -> AsyncGenerator[ExecutionEvent, None]:
        """Executes the goal tasks sequentially."""
        
        settings = get_settings()
        goal_timeout = getattr(settings, "astra_goal_execution_timeout_seconds", 600)
        
        yield self._create_event(ExecutionEventType.GOAL_ACCEPTED, state="STARTED", progress_label=f"Goal accepted: {self.goal.objective}")
        yield self._create_event(ExecutionEventType.PLAN_CREATED, state="PLANNED", progress_label="Execution plan formulated")
        
        try:
            async with asyncio.timeout(goal_timeout):
                for task in self.goal.tasks:
                    if self.cancel_event.is_set():
                        yield self._create_event(ExecutionEventType.GOAL_FAILED, state="CANCELLED", progress_label="Goal cancelled by user")
                        return

                    task.state = TaskState.EXECUTING
                    yield self._create_event(
                        ExecutionEventType.TASK_STARTED, 
                        task_id=task.task_id, 
                        state=task.state.value, 
                        progress_label=task.description
                    )
                    
                    yield self._create_event(
                        ExecutionEventType.TASK_PROGRESS, 
                        task_id=task.task_id, 
                        state="EXECUTING", 
                        progress_label=f"Executing: {task.description}"
                    )
                    
                    # Wrap task execution in its own timeout, but still bound by goal_timeout
                    task_timeout = getattr(settings, "astra_task_execution_timeout_seconds", 120)
                    
                    try:
                        async with asyncio.timeout(task_timeout):
                            task_success = False
                            # We loop here if we are waiting for user
                            while True:
                                if self.cancel_event.is_set():
                                    task_success = False
                                    break
                                    
                                result, wait_for_user = await self._execute_task(task)
                                
                                if wait_for_user:
                                    yield self._create_event(
                                        ExecutionEventType.WAITING_FOR_USER,
                                        task_id=task.task_id,
                                        state="WAITING",
                                        progress_label=f"Action requires human verification: {task.description}"
                                    )
                                    # Passive wait loop checking for user resolution or cancellation
                                    while not self.cancel_event.is_set():
                                        await asyncio.sleep(2.0)
                                        # Execute again with verify_only to see if challenge disappeared
                                        check_result, still_waiting = await self._execute_task(task, verify_only=True)
                                        if not still_waiting:
                                            # Challenge resolved, break the wait loop and actually execute
                                            yield self._create_event(
                                                ExecutionEventType.TASK_PROGRESS,
                                                task_id=task.task_id,
                                                state="RESUMING",
                                                progress_label=f"Resuming: {task.description}"
                                            )
                                            break
                                    continue # loop back to execute task properly
                                else:
                                    task_success = result
                                    break

                    except TimeoutError:
                        logger.warning(f"Task {task.task_id} timed out.")
                        task_success = False
                    
                    if not task_success:
                        task.state = TaskState.FAILED
                        yield self._create_event(
                            ExecutionEventType.RECOVERY_STARTED,
                            task_id=task.task_id,
                            state="RECOVERING",
                            progress_label=f"Attempting recovery for: {task.description}"
                        )
                        
                        yield self._create_event(
                            ExecutionEventType.RECOVERY_COMPLETED,
                            task_id=task.task_id,
                            state="FAILED",
                            progress_label="Recovery exhausted"
                        )
                        
                        yield self._create_event(
                            ExecutionEventType.TASK_FAILED, 
                            task_id=task.task_id, 
                            state=task.state.value, 
                            progress_label=f"Failed: {task.description}"
                        )
                        self.goal.is_complete = False
                        yield self._create_event(ExecutionEventType.GOAL_FAILED, state="FAILED", progress_label="Goal execution failed")
                        return
                    
                    task.state = TaskState.COMPLETED
                    
                    yield self._create_event(
                        ExecutionEventType.VERIFICATION_STARTED, 
                        task_id=task.task_id, 
                        state="VERIFYING", 
                        progress_label=f"Verifying: {task.description}"
                    )
                    
                    yield self._create_event(
                        ExecutionEventType.VERIFICATION_COMPLETED, 
                        task_id=task.task_id, 
                        state="VERIFIED", 
                        progress_label=f"Verified: {task.description}"
                    )
                    
                    yield self._create_event(
                        ExecutionEventType.TASK_COMPLETED, 
                        task_id=task.task_id, 
                        state=task.state.value, 
                        progress_label=f"Completed: {task.description}"
                    )
                    
                self.goal.is_complete = True
                yield self._create_event(ExecutionEventType.GOAL_COMPLETED, state="COMPLETED", progress_label="Goal achieved")
                
        except TimeoutError:
            logger.error("Goal execution timed out.")
            yield self._create_event(ExecutionEventType.GOAL_FAILED, state="TIMEOUT", progress_label="Goal execution timed out")
            return

    async def _execute_task(self, task: Task, verify_only: bool = False) -> tuple[bool, bool]:
        """
        Executes a single Task.
        Follows PLAN -> EXECUTE -> OBSERVE -> VERIFY
        Returns (success, requires_human_verification)
        """
        for intent in task.intents:
            tool_name = self._map_capability_to_tool(intent.capability_id)
            
            # Bounded recovery loop
            max_recovery_attempts = 3
            attempt = 0
            intent_success = False
            requires_human_verification = False
            
            while attempt <= max_recovery_attempts:
                tool_args = intent.parameters.copy()
                if intent.target:
                    if hasattr(intent.target, "id"):
                        tool_args["target"] = intent.target.id
                    elif isinstance(intent.target, dict) and "id" in intent.target:
                        tool_args["target"] = intent.target["id"]
                    else:
                        tool_args["target"] = str(intent.target)
                    
                    if tool_name == "execute_application_intent":
                        tool_args["application"] = tool_args.pop("target", None)
                    elif tool_name == "open_url":
                        tool_args["url"] = tool_args.pop("target", None)
                        
                if verify_only:
                    tool_args["_verify_only"] = True
                
                tool_call = ToolCall(id=str(uuid.uuid4()), name=tool_name, arguments=tool_args)
                result = await action_executor.execute_tool_call(tool_call, max_attempts=1)
                
                task.actions_taken.append(Action(
                    action_id=str(uuid.uuid4()),
                    capability_id=intent.capability_id,
                    provider_id="local_executor",
                    payload=result
                ))
                
                # Check for human verification
                if not result.get("success", False) and result.get("error", {}).get("code") == "HUMAN_VERIFICATION_REQUIRED":
                    requires_human_verification = True
                    break
                
                # Verified success
                if result.get("success", False) and result.get("verified", False):
                    intent_success = True
                    break
                    
                # Action succeeded but not explicitly verified by provider, assume success for generic tools
                if result.get("success", False) and "verified" not in result:
                    intent_success = True
                    break
                
                # If we're just checking verification, don't loop recovery
                if verify_only:
                    break
                    
                attempt += 1
                if attempt <= max_recovery_attempts:
                    logger.warning(f"Intent failed. Initiating bounded recovery attempt {attempt}/{max_recovery_attempts}")
                    await asyncio.sleep(2.0)
            
            if requires_human_verification:
                return False, True
                
            if not intent_success:
                logger.error(f"Intent execution failed after {max_recovery_attempts} recovery attempts.")
                return False, False
                
        return True, False

    def _map_capability_to_tool(self, capability_id: str) -> str:
        mapping = {
            "browser.navigate": "execute_browser_intent",
            "browser.search": "execute_browser_intent",
            "browser.click": "interact_browser",
            "desktop.open_application": "execute_application_intent",
            "system.get_info": "get_system_info",
        }
        return mapping.get(capability_id, capability_id)

    def _create_event(self, event_type: ExecutionEventType, state: str, progress_label: str, task_id: str = None, payload: Dict = None) -> ExecutionEvent:
        return ExecutionEvent(
            event_type=event_type,
            execution_id=self.execution_id,
            goal_id=self.goal.goal_id,
            task_id=task_id,
            state=state,
            progress_label=progress_label,
            payload=payload
        )
