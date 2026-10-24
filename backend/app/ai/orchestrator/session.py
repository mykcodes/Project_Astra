"""
ASTRA AI Orchestrator - Session Management

Maintains in-memory conversation context for the current session.
"""

from collections.abc import AsyncIterator
from typing import Any, Optional
import json
import uuid

from app.ai.providers.types import AIMessage, MessageRole, AIRequest, ToolDefinition
from app.ai.providers.base import AIProvider
from app.core.config import get_settings
from app.core.logging.logger import get_logger
from app.tools.registry import registry
from app.tools.executor import executor
from app.domain.goals import Goal, Task, GoalState, TaskState, Intent, SemanticAction
from app.domain.events import ExecutionEvent, ExecutionEventType
from app.domain.execution_context import ExecutionContext
from app.domain.clarification import (
    ClarificationType, ClarificationOption, ClarificationRequest, ClarificationResponse
)

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are ASTRA, a personal AI assistant and a robust Capability-Aware Windows Intelligence Layer.
You have direct, deep integration with the user's Windows operating system through deterministic environmental intelligence.

CORE RULES:
1. ASTRA HAS ACCESS TO LOCAL TOOLS. You MUST NEVER say "I don't have access to your computer" or "I cannot do that" if a registered capability exists.
2. The operating system is the ultimate source of truth. You must NEVER fabricate OS state, application status, hardware details, or file contents.
3. You MUST ALWAYS use your tools to perform actions and verify state.
4. Trust the tools' results over any assumptions. The tool results are strict, verified JSON contracts. NEVER claim success unless the tool verified it.
5. If the user asks about installed applications, running applications, system info, files, or desktop state, you MUST use the appropriate tool.
6. To know what you can do, use get_capabilities. If a user asks "What CPU do I have?", call get_system_info. If a user asks "Open Spotify", call execute_application_intent.
7. Distinguish between state properly: "not installed", "installed but not running", "running in background", "running in foreground", "unknown", "access denied", "operation failed".
8. Do not invent natural-language responses as a fallback when a tool is required. Do not fake capabilities. If a tool fails, report the structured diagnostic error directly to the user.
9. NEVER claim an application is installed, running, or opened without querying the environment and receiving verified action success.
10. If the environment engine returns ambiguity, ask the user for clarification.
11. NEVER hallucinate or guess URLs for videos, music, or web pages. When asked to play a video (e.g. on YouTube), ALWAYS use the browser SEARCH intent, then use interact_browser to CLICK the correct result. NEVER use NAVIGATE with a fabricated video URL.
12. ABSOLUTELY PROHIBITED: Do NOT ask for procedural confirmation (e.g., "Would you like me to...", "Should I proceed?", "Shall I search?"). The user's request is an instruction. Formulate a multi-step goal plan and execute it autonomously.
13. A multi-step request (e.g., "Open Brave, go to YouTube, and search for a video") is ONE autonomous goal. DO NOT generate single tool calls and pause to ask the user. Submit a complete goal plan with all required tasks.
14. Maintain context. "Search there" means the currently active browser session.

Keep spoken responses reasonably concise, as they will be read aloud. Provide more detail when explicitly requested.
Avoid conversational filler like "umm" or "Here's the answer". Do not use markdown formatting like asterisks or code blocks unless requested.

CURRENT CONTEXT SUMMARY:
{context_summary}
"""

from app.database.goal_store import get_goal_store, GoalStore

class ConversationSession:
    def __init__(
        self,
        provider: AIProvider,
        goal_store: GoalStore | None = None,
        memory_engine: Any | None = None,
    ):
        self.provider = provider
        self.goal_store = goal_store or get_goal_store()
        self.memory_engine = memory_engine or self._get_default_memory_engine()
        self.execution_context = ExecutionContext(execution_id=str(uuid.uuid4()))
        self.history: list[AIMessage] = []
        self.active_runtime = None
        self.pending_goal_id: Optional[str] = None
        self._update_system_prompt()

    @staticmethod
    def _get_default_memory_engine() -> Any | None:
        try:
            from app.memory.engine import get_memory_engine
            return get_memory_engine()
        except Exception as e:
            logger.debug(f"ConversationSession: Could not initialize MemoryEngine: {e}")
            return None

    def cancel(self) -> bool:
        """Cancels the currently running GoalRuntime, if any."""
        if self.active_runtime is not None:
            self.active_runtime.cancel()
            return True
        return False

    async def list_resumable_goals(self) -> list[dict]:
        """Returns all persisted goals currently eligible for resumption."""
        checkpoints = self.goal_store.list_resumable_goals()
        return [cp.to_dict() for cp in checkpoints]

    async def resume_goal_stream(self, goal_id: str) -> AsyncIterator[str]:
        """
        Resumes an existing suspended or interrupted goal from its checkpoint.
        Streams SSE events truthfully without duplicate execution.
        """
        if self.active_runtime is not None:
            raise RuntimeError(f"Cannot resume goal '{goal_id}': another execution is currently active ({self.active_runtime.goal.id})")
        
        checkpoint = self.goal_store.get_checkpoint(goal_id)
        if not checkpoint:
            raise ValueError(f"Goal '{goal_id}' not found in goal store.")
            
        is_resumable, reason = checkpoint.validate_resumable()
        if not is_resumable:
            raise ValueError(f"Goal '{goal_id}' is not eligible for resumption: {reason}")
            
        from app.ai.orchestrator.runtime import GoalRuntime
        from app.domain.checkpoints import ResumptionClassification
        
        # Instantiate runtime via resume
        runtime, classification, reason = GoalRuntime.resume(
            checkpoint=checkpoint,
            goal_store=self.goal_store,
            context=self.execution_context
        )
        
        if classification == ResumptionClassification.UNSAFE_TO_RESUME:
            raise ValueError(f"Resumption rejected: {reason}")
            
        self.active_runtime = runtime
        
        try:
            async for event in runtime.run():
                yield event.to_sse_json() + "\n"
        finally:
            self.active_runtime = None
            
        # Build terminal response summary
        completed_tasks = [t.description for t in runtime.goal.tasks if getattr(t.state, "value", str(t.state)) == "COMPLETED"]
        failed_tasks = [t.description for t in runtime.goal.tasks if getattr(t.state, "value", str(t.state)) == "FAILED"]
        goal_state_str = getattr(runtime.goal.state, "value", "UNKNOWN") if hasattr(runtime.goal, "state") else ("COMPLETED" if runtime.goal.is_complete else "FAILED")

        # Phase B.10: Record episodic memory ONLY after goal reaches GoalState.COMPLETED
        if goal_state_str == "COMPLETED" and self.memory_engine is not None:
            try:
                self.memory_engine.record_completed_goal(runtime.goal, runtime.context)
            except Exception as ex:
                logger.warning(f"Failed to record resumed completed goal in episodic memory: {ex}")
        
        if goal_state_str == "COMPLETED":
            final_text = "✅ Resumed execution completed successfully."
            self.pending_goal_id = None
        elif goal_state_str == "FAILED":
            failed_tasks_str = ", ".join(failed_tasks) if failed_tasks else "unknown"
            final_text = f"⚠️ Resumed execution failed: {failed_tasks_str}."
            self.pending_goal_id = None
        elif goal_state_str == "WAITING_FOR_USER":
            clarif = runtime.context.pending_clarification or getattr(runtime.goal, "pending_clarification", None)
            if clarif and getattr(clarif, "prompt", None):
                final_text = clarif.prompt
            else:
                final_text = "⏸️ Resumed execution waiting for user: Please complete the required steps in the application."
            self.pending_goal_id = runtime.goal.id
        else:
            final_text = "⛔ Resumed execution cancelled."
            self.pending_goal_id = None
            
        yield ExecutionEvent(
            event_type=ExecutionEventType.ASSISTANT_RESPONSE,
            execution_id=runtime.execution_id,
            state="RESPONDING",
            progress_label="Resumed execution terminal response",
            payload={"text": final_text}
        ).to_sse_json() + "\n"
        
        self.history.append(AIMessage(role=MessageRole.ASSISTANT, content=final_text))
        
    def _update_system_prompt(self, user_message: Optional[str] = None):
        summary = f"Browser: {self.execution_context.active_browser_identity or 'None'}\n"
        summary += f"Page: {self.execution_context.current_title or 'None'}\n"
        summary += f"URL: {self.execution_context.current_url or 'None'}\n"
        summary += f"Last Action: {self.execution_context.last_action or 'None'}\n"

        # Phase B.12: Multimodal Desktop Observation Context
        try:
            from app.environment.visual.observer import desktop_observer
            mmo = None
            if self.execution_context.aligned_observation_id:
                mmo = desktop_observer.get_observation_by_id(self.execution_context.aligned_observation_id)
            if mmo is None:
                mmo = desktop_observer.get_latest_observation()
            if mmo:
                if mmo.active_window and mmo.active_window.title:
                    summary += f"Active Window: {mmo.active_window.title}\n"
                if mmo.text_detections:
                    top_texts = [f"'{t.label}'" for t in mmo.text_detections[:8] if len(t.label.strip()) > 2]
                    if top_texts:
                        summary += f"Visible Elements: {', '.join(top_texts)}\n"
        except Exception as ex:
            logger.debug(f"Could not retrieve multimodal observation context: {ex}")

        # Phase B.10: Bounded memory injection (strictly bounded context budget)
        if self.memory_engine is not None and user_message:
            try:
                mem_block = self.memory_engine.get_relevant_context(user_message, max_items=5, max_chars=1200)
                if mem_block:
                    summary += f"\n{mem_block}\n"
            except Exception as ex:
                logger.debug(f"Failed to retrieve memory context: {ex}")
        
        if self.history and self.history[0].role == MessageRole.SYSTEM:
            self.history[0] = AIMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT.format(context_summary=summary))
        else:
            self.history.insert(0, AIMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT.format(context_summary=summary)))

    async def chat(self, user_message: str, aligned_observation_id: Optional[str] = None) -> str:
        """
        Sends a user message, maintains history, and returns the response.
        Accumulates textual content from ASSISTANT_RESPONSE execution events and raw chunks.
        """
        response_text = ""
        async for chunk in self.chat_stream(user_message, aligned_observation_id=aligned_observation_id):
            try:
                event_data = json.loads(chunk)
                if isinstance(event_data, dict):
                    if event_data.get("event_type") == "ASSISTANT_RESPONSE":
                        payload = event_data.get("payload", {})
                        if isinstance(payload, dict):
                            response_text += payload.get("text", "")
            except json.JSONDecodeError:
                # Fallback for plain text chunks
                response_text += chunk
        return response_text

    def _match_pending_clarification(
        self, user_message: str, clarif: ClarificationRequest
    ) -> Optional[ClarificationResponse]:
        """
        Deterministically evaluates whether user_message is an answer to clarif,
        or an unrelated command. Returns ClarificationResponse if matched, else None.
        """
        text = user_message.strip()
        lower = text.lower()
        
        # 1. Consequential Action Confirmation
        if clarif.clarification_type == ClarificationType.CONSEQUENTIAL_ACTION:
            positive_exact = {
                "yes", "y", "yes please", "confirm", "confirmed", "approve", "approved",
                "proceed", "go ahead", "do it", "allow", "yes proceed", "yes do it"
            }
            negative_exact = {
                "no", "n", "cancel", "stop", "abort", "reject", "rejected",
                "deny", "denied", "nevermind", "don't", "do not", "don't do that"
            }
            if lower in positive_exact or lower.startswith("confirm ") or lower.startswith("approve "):
                return ClarificationResponse(request_id=clarif.request_id, confirmed=True)
            if lower in negative_exact or lower.startswith("cancel ") or lower.startswith("abort "):
                return ClarificationResponse(request_id=clarif.request_id, confirmed=False)
            return None

        # 2. Ambiguous Target, Missing Parameter, Human Intervention
        # Check against available options
        if clarif.options:
            for idx, opt in enumerate(clarif.options):
                if lower in (str(idx + 1), f"option {idx + 1}", f"#{idx + 1}"):
                    remember = any(w in lower for w in ("always", "default", "remember", "prefer"))
                    return ClarificationResponse(
                        request_id=clarif.request_id,
                        selected_option_id=opt.option_id,
                        remember_as_preference=remember,
                    )
            for opt in clarif.options:
                opt_label_lower = opt.label.lower()
                opt_val_lower = opt.value.lower()
                if lower == opt_label_lower or lower == opt_val_lower or (
                    opt_label_lower in lower and len(opt_label_lower) > 2
                ) or (
                    opt_val_lower in lower and len(opt_val_lower) > 2
                ):
                    remember = any(w in lower for w in ("always", "default", "remember", "prefer"))
                    return ClarificationResponse(
                        request_id=clarif.request_id,
                        selected_option_id=opt.option_id,
                        remember_as_preference=remember,
                    )

        if not clarif.options and len(text.split()) <= 4:
            return ClarificationResponse(
                request_id=clarif.request_id,
                custom_input=text,
            )

        return None

    async def resolve_clarification_stream(self, response: ClarificationResponse) -> AsyncIterator[str]:
        """
        Resolves a pending clarification or consequential action confirmation.
        Resumes goal execution, updates targets, or safely cancels as appropriate.
        """
        checkpoint = None
        if self.pending_goal_id:
            cp = self.goal_store.get_checkpoint(self.pending_goal_id)
            if cp and cp.pending_clarification and cp.pending_clarification.request_id == response.request_id:
                checkpoint = cp
        if not checkpoint:
            for candidate in self.goal_store.list_resumable_goals():
                if candidate.pending_clarification and candidate.pending_clarification.request_id == response.request_id:
                    checkpoint = candidate
                    break

        if not checkpoint or not checkpoint.pending_clarification:
            raise ValueError(f"Clarification request '{response.request_id}' not found, expired, or already resolved.")

        clarif = checkpoint.pending_clarification
        if clarif.is_expired():
            raise ValueError(f"Clarification request '{response.request_id}' has expired.")

        is_valid, err_msg = response.validate_against(clarif)
        if not is_valid:
            raise ValueError(f"Invalid clarification response: {err_msg}")

        # Case 1: Consequential Action Confirmation
        if clarif.clarification_type == ClarificationType.CONSEQUENTIAL_ACTION:
            if not response.confirmed:
                checkpoint.goal_state = GoalState.CANCELLED
                checkpoint.is_resumable = False
                checkpoint.pending_clarification = None
                checkpoint.suspension_reason = "User rejected consequential action confirmation."
                self.goal_store.save_checkpoint(checkpoint)
                self.pending_goal_id = None

                yield ExecutionEvent(
                    event_type=ExecutionEventType.GOAL_CANCELLED,
                    execution_id=checkpoint.execution_id,
                    state="CANCELLED",
                    progress_label="Action cancelled by user",
                    payload={"goal_id": checkpoint.goal_id, "reason": "User rejected confirmation"}
                ).to_sse_json() + "\n"

                final_text = "⛔ Consequential action rejected. Goal cancelled safely."
                yield ExecutionEvent(
                    event_type=ExecutionEventType.ASSISTANT_RESPONSE,
                    execution_id=checkpoint.execution_id,
                    state="RESPONDING",
                    progress_label="Action cancelled",
                    payload={"text": final_text}
                ).to_sse_json() + "\n"
                self.history.append(AIMessage(role=MessageRole.ASSISTANT, content=final_text))
                return

            from app.core.security.evaluator import permission_evaluator
            from app.domain.permissions import PermissionRequest, CapabilityScope, ResourceScope

            scope_name = clarif.metadata.get("capability") or "SYSTEM_MODIFICATION"
            scope = getattr(CapabilityScope, scope_name, CapabilityScope.SYSTEM_MODIFICATION)
            perm_req = PermissionRequest(
                request_id=str(uuid.uuid4()),
                requester_task_id=None,
                capability=scope,
                resource_scope=ResourceScope(capability=scope, resource=clarif.target_name),
                reason=f"User approved confirmation {clarif.request_id}",
            )
            permission_evaluator.grant(
                perm_req,
                reason=f"Explicit user confirmation {clarif.request_id}",
                duration_seconds=300,
                constraints={"request_id": clarif.request_id, "target": clarif.target_name}
            )

            checkpoint.pending_clarification = None
            checkpoint.goal_state = GoalState.EXECUTING
            self.goal_store.save_checkpoint(checkpoint)

            yield ExecutionEvent(
                event_type=ExecutionEventType.CLARIFICATION_RESOLVED,
                execution_id=checkpoint.execution_id,
                state="EXECUTING",
                progress_label="Confirmation approved",
                payload={"request_id": clarif.request_id, "confirmed": True}
            ).to_sse_json() + "\n"

            async for chunk in self.resume_goal_stream(checkpoint.goal_id):
                yield chunk
            return

        # Case 2: Ambiguous Target / Missing Parameter
        chosen_val = None
        if response.selected_option_id:
            opt = clarif.get_option(response.selected_option_id)
            chosen_val = opt.value if opt else response.selected_option_id
        elif response.custom_input:
            chosen_val = response.custom_input.strip()

        if not chosen_val:
            raise ValueError("No option selected or custom input provided.")

        if response.remember_as_preference and self.memory_engine:
            try:
                from app.domain.memory import MemoryType, ProvenanceType
                target_key = f"pref_{clarif.target_name or 'target'}"
                self.memory_engine.remember(
                    key=target_key,
                    content=f"Preferred application/target for '{clarif.target_name}': {chosen_val}",
                    memory_type=MemoryType.PREFERENCE,
                    provenance=ProvenanceType.USER_EXPLICIT,
                    tags=["user_preference", "application_selection"]
                )
            except Exception as ex:
                logger.warning(f"Failed to record user preference: {ex}")

        yield ExecutionEvent(
            event_type=ExecutionEventType.CLARIFICATION_RESOLVED,
            execution_id=checkpoint.execution_id,
            state="EXECUTING",
            progress_label=f"Selected target: {chosen_val}",
            payload={"request_id": clarif.request_id, "chosen_value": chosen_val}
        ).to_sse_json() + "\n"

        tasks = []
        for tcp in checkpoint.task_checkpoints:
            desc = tcp.description
            if clarif.target_name and clarif.target_name in desc:
                desc = desc.replace(clarif.target_name, chosen_val)
            action_enum = getattr(SemanticAction, clarif.action_type, SemanticAction.OPEN) if clarif.action_type else SemanticAction.OPEN
            intents = [
                Intent(
                    intent_id=str(uuid.uuid4()),
                    action=action_enum,
                    target=chosen_val,
                )
            ]
            t = Task(
                task_id=tcp.task_id,
                description=desc,
                state=TaskState.PLANNING if tcp.task_state == TaskState.WAITING_FOR_USER else tcp.task_state,
                intents=intents,
            )
            tasks.append(t)

        obj = checkpoint.objective
        if clarif.target_name and clarif.target_name in obj:
            obj = obj.replace(clarif.target_name, chosen_val)

        goal = Goal(
            goal_id=checkpoint.goal_id,
            objective=obj,
            tasks=tasks,
            state=GoalState.PLAN_CREATED,
        )

        checkpoint.pending_clarification = None
        checkpoint.goal_state = GoalState.PLAN_CREATED
        self.goal_store.save_checkpoint(checkpoint)

        from app.ai.orchestrator.compiler import ActionCompiler
        compiler = ActionCompiler(memory_engine=self.memory_engine)
        self.execution_context.pending_clarification = None
        compiled_goal = await compiler.compile(goal, self.execution_context)

        from app.ai.orchestrator.runtime import GoalRuntime
        runtime = GoalRuntime(compiled_goal, context=self.execution_context, goal_store=self.goal_store)
        self.active_runtime = runtime

        try:
            async for event in runtime.run():
                yield event.to_sse_json() + "\n"
        finally:
            self.active_runtime = None
            self.pending_goal_id = None

        goal_state_str = getattr(runtime.goal.state, "value", "UNKNOWN") if hasattr(runtime.goal, "state") else ("COMPLETED" if runtime.goal.is_complete else "FAILED")
        completed_tasks = [t.description for t in runtime.goal.tasks if getattr(t.state, "value", str(t.state)) == "COMPLETED"]
        failed_tasks = [t.description for t in runtime.goal.tasks if getattr(t.state, "value", str(t.state)) == "FAILED"]

        if goal_state_str == "COMPLETED":
            if self.memory_engine:
                try:
                    self.memory_engine.record_completed_goal(runtime.goal, runtime.context)
                except Exception as ex:
                    logger.warning(f"Failed to record completed goal in memory: {ex}")
            final_text = f"✅ Goal completed using '{chosen_val}'."
        elif goal_state_str == "FAILED":
            failed_str = ", ".join(failed_tasks) if failed_tasks else "unknown"
            final_text = f"⚠️ Goal execution failed: {failed_str}."
        elif goal_state_str == "WAITING_FOR_USER":
            clarif_next = runtime.context.pending_clarification or getattr(runtime.goal, "pending_clarification", None)
            final_text = clarif_next.prompt if clarif_next and getattr(clarif_next, "prompt", None) else "⏸️ Waiting for user action."
            self.pending_goal_id = runtime.goal.id
        else:
            final_text = "⛔ Execution cancelled."

        yield ExecutionEvent(
            event_type=ExecutionEventType.ASSISTANT_RESPONSE,
            execution_id=runtime.execution_id,
            state="RESPONDING",
            progress_label="Terminal response",
            payload={"text": final_text}
        ).to_sse_json() + "\n"
        self.history.append(AIMessage(role=MessageRole.ASSISTANT, content=final_text))

    async def chat_stream(self, user_message: str, aligned_observation_id: Optional[str] = None) -> AsyncIterator[str]:
        """
        Sends a user message, maintains history, and yields the response as a stream.
        """
        # Track aligned observation for current utterance; clear when None to prevent cross-utterance leakage
        self.execution_context.aligned_observation_id = aligned_observation_id

        # Phase B.11: Multi-turn Clarification & Confirmation Interception
        pending_cp = None
        if self.pending_goal_id:
            pending_cp = self.goal_store.get_checkpoint(self.pending_goal_id)
            if pending_cp and (not pending_cp.pending_clarification or pending_cp.pending_clarification.is_expired()):
                pending_cp = None
        if not pending_cp:
            for cp in self.goal_store.list_resumable_goals():
                if cp.pending_clarification and not cp.pending_clarification.is_expired():
                    pending_cp = cp
                    self.pending_goal_id = cp.goal_id
                    break

        if pending_cp and pending_cp.pending_clarification and not pending_cp.pending_clarification.is_expired():
            matched_resp = self._match_pending_clarification(user_message, pending_cp.pending_clarification)
            if matched_resp:
                self.history.append(AIMessage(role=MessageRole.USER, content=user_message))
                async for chunk in self.resolve_clarification_stream(matched_resp):
                    yield chunk
                return
            else:
                logger.info(f"User input did not match pending clarification for goal '{pending_cp.goal_id}'. Superseding suspended goal.")
                pending_cp.suspension_reason = "Superseded by user starting new goal."
                self.goal_store.save_checkpoint(pending_cp)
                self.pending_goal_id = None

        self._update_system_prompt(user_message=user_message)
        self.history.append(AIMessage(role=MessageRole.USER, content=user_message))
        
        settings = get_settings()
        
        try:
            # Phase 9B: Request LLM to formulate a Goal Plan
            # We inject a specific tool for the LLM to use
            from pydantic import BaseModel
            
            class GoalPlanRequest(BaseModel):
                goal: Goal
                
            # Wrap in a tool
            submit_goal_tool = ToolDefinition(
                name="submit_goal_plan",
                description="Submit a multi-step semantic goal plan to achieve the user's objective. Use this tool for ALL tasks.",
                parameters=GoalPlanRequest.model_json_schema()
            )
            
            # Remove raw tool fallbacks to force semantic decomposition
            tools = [submit_goal_tool]
                
            request = AIRequest(
                messages=self.history,
                temperature=0.7,
                tools=tools
            )
            
            # ASTRA doesn't stream intermediate thoughts during planning.
            # We await the first response.
            response = await self.provider.generate(request)
            
            goal_plan = None
            if response.tool_calls:
                for call in response.tool_calls:
                    if call.name == "submit_goal_plan":
                        goal_data = call.arguments.get("goal")
                        if goal_data:
                            if isinstance(goal_data, str):
                                goal_data = json.loads(goal_data)
                            goal_plan = Goal(**goal_data)
                        break
                        
                if not goal_plan:
                    logger.warning("LLM did not submit a goal plan.")
                        
            # Phase 9B.3.1: Strict Execution Authority in GoalRuntime with Persistent Context
            if goal_plan:
                from app.ai.orchestrator.runtime import GoalRuntime
                
                # We append the LLM's thought process (the tool call) so history is consistent
                # but we do NOT yield any conversational text during planning/execution.
                self.history.append(AIMessage(
                    role=MessageRole.ASSISTANT,
                    content="", # Suppress intermediate text
                    tool_calls=response.tool_calls
                ))
                
                self.execution_context.goal = goal_plan
                
                from app.ai.orchestrator.compiler import ActionCompiler
                compiler = ActionCompiler(memory_engine=self.memory_engine)
                compiled_goal = await compiler.compile(goal_plan, self.execution_context)
                
                runtime = GoalRuntime(compiled_goal, context=self.execution_context, goal_store=self.goal_store)
                self.active_runtime = runtime
                
                try:
                    async for event in runtime.run():
                        # Stream structured events immediately
                        yield event.to_sse_json() + "\n"
                finally:
                    self.active_runtime = None
                    
                # Build verified execution summary for the final response
                completed_tasks = [t.description for t in runtime.goal.tasks if getattr(t.state, "value", str(t.state)) == "COMPLETED"]
                failed_tasks = [t.description for t in runtime.goal.tasks if getattr(t.state, "value", str(t.state)) == "FAILED"]
                
                goal_state_str = getattr(runtime.goal.state, "value", "UNKNOWN") if hasattr(runtime.goal, "state") else ("COMPLETED" if runtime.goal.is_complete else "FAILED")

                # Phase B.10: Record episodic memory ONLY after goal reaches GoalState.COMPLETED
                if goal_state_str == "COMPLETED" and self.memory_engine is not None:
                    try:
                        self.memory_engine.record_completed_goal(runtime.goal, runtime.context)
                    except Exception as ex:
                        logger.warning(f"Failed to record completed goal in episodic memory: {ex}")
                
                execution_summary = {
                    "goal_state": goal_state_str,
                    "completed_tasks": completed_tasks,
                    "failed_tasks": failed_tasks,
                    "verified_environment_state": runtime.context.environment_snapshot
                }
                
                strict_invariant = ""
                if goal_state_str == "COMPLETED":
                    strict_invariant = "INVARIANT: The goal succeeded. You may claim success."
                elif goal_state_str == "FAILED":
                    strict_invariant = "INVARIANT: The goal FAILED. You MUST NOT claim success under any circumstances. Report the failure and mention which tasks failed."
                elif goal_state_str == "CANCELLED":
                    strict_invariant = "INVARIANT: The goal was CANCELLED by the user. State clearly that the action was cancelled."
                else:
                    strict_invariant = "INVARIANT: The goal requires user action (WAITING). You MUST ask the user to intervene (e.g. solve a CAPTCHA or confirm an action)."

                self.history.append(AIMessage(
                    role=MessageRole.TOOL,
                    content=f"Goal Execution Finished.\nExecution Summary: {json.dumps(execution_summary)}\n\n{strict_invariant}\nYou MUST summarize the final state truthfully based ONLY on these verified facts.",
                    tool_call_id=response.tool_calls[0].id if response.tool_calls else str(uuid.uuid4()),
                    name=response.tool_calls[0].name if response.tool_calls else "submit_goal_plan"
                ))
                
                if goal_state_str in ("FAILED", "CANCELLED", "WAITING_FOR_USER"):
                    # Deterministic terminal response bypass
                    if goal_state_str == "FAILED":
                        failed_tasks_str = ", ".join(failed_tasks) if failed_tasks else "unknown"
                        final_text = f"⚠️ Execution failed: {failed_tasks_str}."
                        self.pending_goal_id = None
                    elif goal_state_str == "WAITING_FOR_USER":
                        clarif = runtime.context.pending_clarification or getattr(runtime.goal, "pending_clarification", None)
                        if clarif and getattr(clarif, "prompt", None):
                            final_text = clarif.prompt
                        else:
                            final_text = "⏸️ Waiting for your action: Please complete the required steps in the browser or application."
                        self.pending_goal_id = runtime.goal.id
                    else:
                        final_text = "⛔ Execution cancelled."
                        self.pending_goal_id = None
                        
                    yield ExecutionEvent(
                        event_type=ExecutionEventType.ASSISTANT_RESPONSE,
                        execution_id=runtime.execution_id,
                        state="RESPONDING",
                        progress_label="Generating deterministic response",
                        payload={"text": final_text}
                    ).to_sse_json() + "\n"
                    
                    self.history.append(AIMessage(role=MessageRole.ASSISTANT, content=final_text))
                    return
                
                # Final token-streamed response after Goal terminal state (SUCCESS path)
                final_request = AIRequest(messages=self.history, temperature=0.7)
                final_response = []
                response_execution_id = runtime.execution_id
                
                async for chunk in self.provider.generate_stream(final_request):
                    if chunk.content:
                        final_response.append(chunk.content)
                        yield ExecutionEvent(
                            event_type=ExecutionEventType.ASSISTANT_RESPONSE,
                            execution_id=response_execution_id,
                            state="RESPONDING",
                            progress_label="Generating response",
                            payload={"text": chunk.content}
                        ).to_sse_json() + "\n"
                        
                self.history.append(AIMessage(role=MessageRole.ASSISTANT, content="".join(final_response)))
                return
                
            else:
                # Ordinary conversational text with no execution (No GoalRuntime needed)
                self.history.append(AIMessage(
                    role=MessageRole.ASSISTANT,
                    content=response.content or ""
                ))
                if response.content:
                    yield ExecutionEvent(
                        event_type=ExecutionEventType.ASSISTANT_RESPONSE,
                        execution_id=str(uuid.uuid4()),
                        state="RESPONDING",
                        progress_label="Generating response",
                        payload={"text": response.content}
                    ).to_sse_json() + "\n"
                    
        except Exception as e:
            logger.error(f"Error during AI streaming orchestration: {e}")
            self.history.pop()
            raise
