"""
ASTRA AI Orchestrator - Session Management

Maintains in-memory conversation context for the current session.
"""

from collections.abc import AsyncIterator
import json
import uuid

from app.ai.providers.types import AIMessage, MessageRole, AIRequest, ToolDefinition
from app.ai.providers.base import AIProvider
from app.core.config import get_settings
from app.core.logging.logger import get_logger
from app.tools.registry import registry
from app.tools.executor import executor
from app.domain.goals import Goal
from app.domain.events import ExecutionEvent, ExecutionEventType
from app.domain.execution_context import ExecutionContext

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

class ConversationSession:
    def __init__(self, provider: AIProvider):
        self.provider = provider
        self.execution_context = ExecutionContext(execution_id=str(uuid.uuid4()))
        self.history: list[AIMessage] = []
        self._update_system_prompt()
        
    def _update_system_prompt(self):
        summary = f"Browser: {self.execution_context.active_browser_identity or 'None'}\n"
        summary += f"Page: {self.execution_context.current_title or 'None'}\n"
        summary += f"URL: {self.execution_context.current_url or 'None'}\n"
        summary += f"Last Action: {self.execution_context.last_action or 'None'}\n"
        
        if self.history and self.history[0].role == MessageRole.SYSTEM:
            self.history[0] = AIMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT.format(context_summary=summary))
        else:
            self.history.insert(0, AIMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT.format(context_summary=summary)))

    async def chat(self, user_message: str) -> str:
        """
        Sends a user message, maintains history, and returns the response.
        """
        response_text = ""
        async for chunk in self.chat_stream(user_message):
            try:
                # If it's a JSON event, ignore it for the plain text response
                json.loads(chunk)
            except json.JSONDecodeError:
                # It's a text chunk
                response_text += chunk
        return response_text

    async def chat_stream(self, user_message: str) -> AsyncIterator[str]:
        """
        Sends a user message, maintains history, and yields the response as a stream.
        """
        self._update_system_prompt()
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
                compiler = ActionCompiler()
                compiled_goal = await compiler.compile(goal_plan, self.execution_context)
                
                runtime = GoalRuntime(compiled_goal, context=self.execution_context)
                
                async for event in runtime.run():
                    # Stream structured events immediately
                    yield event.to_sse_json() + "\n"
                    
                # Build verified execution summary for the final response
                completed_tasks = [t.description for t in runtime.goal.tasks if getattr(t.state, "value", str(t.state)) == "COMPLETED"]
                failed_tasks = [t.description for t in runtime.goal.tasks if getattr(t.state, "value", str(t.state)) == "FAILED"]
                
                goal_state_str = getattr(runtime.goal.state, "value", "UNKNOWN") if hasattr(runtime.goal, "state") else ("COMPLETED" if runtime.goal.is_complete else "FAILED")
                
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
                    elif goal_state_str == "WAITING_FOR_USER":
                        final_text = "⏸️ Waiting for your action: Please complete the required steps in the browser or application."
                    else:
                        final_text = "⛔ Execution cancelled."
                        
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
