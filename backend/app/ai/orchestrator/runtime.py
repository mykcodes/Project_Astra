import uuid
from typing import AsyncGenerator, Dict, Any
import asyncio

from app.domain.goals import Goal, Task, TaskState, GoalState, Action, VerificationResult, FailureClass
from app.domain.events import ExecutionEvent, ExecutionEventType
from app.domain.execution_context import ExecutionContext
from app.domain.memory import RecoveryStrategy
from app.ai.orchestrator.action_executor import action_executor
from app.ai.providers.types import ToolCall
from app.core.logging.logger import get_logger
from app.core.config import get_settings
from app.ai.orchestrator.recovery import recovery_engine

logger = get_logger(__name__)

class GoalRuntime:
    """
    Phase 9C: Stateful Goal Execution Runtime
    Owns execution of a Goal until terminal state, tracking environment context.
    """
    
    def __init__(self, goal: Goal, context: ExecutionContext = None):
        self.goal = goal
        self.context = context or ExecutionContext(
            execution_id=str(uuid.uuid4()),
            goal=goal
        )
        self.cancel_event = asyncio.Event()

    @property
    def execution_id(self) -> str:
        return self.context.execution_id
        
    def cancel(self):
        """Signals the runtime to cancel execution."""
        self.cancel_event.set()
        
    async def run(self) -> AsyncGenerator[ExecutionEvent, None]:
        """Executes the goal tasks sequentially in a stateful manner."""
        
        settings = get_settings()
        goal_timeout = getattr(settings, "astra_goal_execution_timeout_seconds", 600)
        
        self.goal.state = GoalState.EXECUTING
        yield self._create_event(ExecutionEventType.GOAL_ACCEPTED, state="STARTED", progress_label=f"Executing Goal: {self.goal.objective}")
        
        try:
            async with asyncio.timeout(goal_timeout):
                # Execute Tasks
                for index, task in enumerate(self.goal.tasks):
                    if self.cancel_event.is_set():
                        self.goal.state = GoalState.CANCELLED
                        yield self._create_event(ExecutionEventType.GOAL_CANCELLED, state="CANCELLED", progress_label="Goal cancelled by user")
                        return

                    self.context.current_task_index = index
                    task.state = TaskState.EXECUTING
                    
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
                                    self.context.waiting_reason = "CAPTCHA or User Intervention Required"
                                    yield self._create_event(
                                        ExecutionEventType.WAITING_FOR_USER,
                                        task_id=task.task_id,
                                        state="WAITING",
                                        progress_label=f"Action requires human verification: {task.description}"
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
                    yield self._create_event(
                        ExecutionEventType.TASK_COMPLETED, 
                        task_id=task.task_id, 
                        state=task.state.value, 
                        progress_label=f"Completed: {task.description}"
                    )
                    
                # Final Goal Verification
                self.goal.state = GoalState.VERIFYING
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
                    yield self._create_event(ExecutionEventType.GOAL_COMPLETED, state="COMPLETED", progress_label="Goal achieved and verified")
                else:
                    self.goal.state = GoalState.FAILED
                    yield self._create_event(ExecutionEventType.GOAL_FAILED, state="VERIFICATION_FAILED", progress_label="Goal execution completed but final verification failed")
                
        except TimeoutError:
            logger.error("Goal execution timed out.")
            self.goal.state = GoalState.FAILED
            yield self._create_event(ExecutionEventType.GOAL_FAILED, state="TIMEOUT", progress_label="Goal execution timed out")
            return

    async def _execute_task(self, task: Task) -> tuple[bool, bool, Any]:
        """
        Executes a single Task. Returns (success, requires_human_verification, failure_class)
        """
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
                
                if intent.target:
                    # Strip stale 'ast-' identifiers if the LLM provided them, forcing semantic re-resolution
                    target_val = ""
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
                            
                    tool_args["target"] = target_val
                    
                    if intent.capability_id in ("desktop.open_application", "desktop.focus_application", "desktop.close_application"):
                        tool_args["application"] = tool_args.pop("target", None)
                        if intent.capability_id == "desktop.open_application":
                            tool_args["intent"] = "OPEN"
                        elif intent.capability_id == "desktop.focus_application":
                            tool_args["intent"] = "FOCUS"
                        elif intent.capability_id == "desktop.close_application":
                            tool_args["intent"] = "CLOSE"
                        # Ensure 'action' is removed so it doesn't fail schema validation (additionalProperties: False)
                        # Also strip all other semantic compiler parameters (like 'ordinal', 'query', etc.) 
                        # because execute_application_intent has additionalProperties: False.
                        tool_args = {
                            "intent": tool_args["intent"],
                            "application": tool_args["application"]
                        }
                    elif tool_name == "execute_browser_intent" or tool_name == "open_url":
                        tool_args["target"] = tool_args.pop("target", None)
                        tool_name = "execute_browser_intent"
                        new_args = {
                            "intent": "NAVIGATE",
                            "target": tool_args.get("target")
                        }
                        if "browser_name" in tool_args:
                            new_args["browser_name"] = tool_args["browser_name"]
                        if "_current_url" in tool_args:
                            new_args["_current_url"] = tool_args["_current_url"]
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
