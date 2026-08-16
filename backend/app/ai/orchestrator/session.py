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

Keep spoken responses reasonably concise, as they will be read aloud. Provide more detail when explicitly requested.
Avoid conversational filler like "umm" or "Here's the answer". Do not use markdown formatting like asterisks or code blocks unless requested.
"""

class ConversationSession:
    def __init__(self, provider: AIProvider):
        self.provider = provider
        self.history: list[AIMessage] = [
            AIMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT)
        ]

    async def chat(self, user_message: str) -> str:
        """
        Sends a user message, maintains history, and returns the response.
        """
        self.history.append(AIMessage(role=MessageRole.USER, content=user_message))
        
        settings = get_settings()
        max_calls = getattr(settings, "astra_tool_max_calls_per_turn", 10)
        
        try:
            turn_executed_calls = set()
            
            for _ in range(max_calls):
                tools = [t.get_definition() for t in registry.list_tools()] if getattr(settings, "astra_tools_enabled", True) else None
                request = AIRequest(
                    messages=self.history,
                    temperature=0.7,
                    tools=tools
                )
                
                response = await self.provider.generate(request)
                self.history.append(AIMessage(
                    role=MessageRole.ASSISTANT, 
                    content=response.content,
                    tool_calls=response.tool_calls
                ))
                
                if not response.tool_calls:
                    return response.content or ""
                    
                # Execute tool calls
                for tool_call in response.tool_calls:
                    # Duplicate check
                    args_str = json.dumps(tool_call.arguments, sort_keys=True) if isinstance(tool_call.arguments, dict) else str(tool_call.arguments)
                    call_signature = (tool_call.name, args_str)
                    
                    if call_signature in turn_executed_calls:
                        logger.warning("TOOL_CALL_DUPLICATE_BLOCKED", extra={"tool_name": tool_call.name})
                        error_payload = json.dumps({
                            "error_type": "DUPLICATE_CALL_BLOCKED",
                            "message": "This action was blocked because you already performed the exact same action with the same arguments in this turn."
                        })
                        self.history.append(AIMessage(
                            role=MessageRole.TOOL,
                            content=error_payload,
                            tool_call_id=tool_call.id,
                            name=tool_call.name
                        ))
                        continue
                        
                    turn_executed_calls.add(call_signature)
                    
                    from app.ai.orchestrator.action_executor import action_executor
                    
                    raw_result = await action_executor.execute_tool_call(tool_call)
                    
                    self.history.append(AIMessage(
                        role=MessageRole.TOOL,
                        content=json.dumps(raw_result),
                        tool_call_id=tool_call.id,
                        name=tool_call.name
                    ))
                    
            logger.warning("TOOL_LOOP_LIMIT_REACHED")
            return "I needed to perform too many actions and had to stop."
            
        except Exception as e:
            logger.error(f"Error during AI orchestration: {e}")
            self.history.pop() 
            raise

    async def chat_stream(self, user_message: str) -> AsyncIterator[str]:
        """
        Sends a user message, maintains history, and yields the response as a stream.
        """
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
                description="Submit a multi-step semantic goal plan to achieve the user's objective.",
                parameters=GoalPlanRequest.model_json_schema()
            )
            
            # Allow fallback to regular tools for single actions, but prioritize goal
            tools = [submit_goal_tool]
            if getattr(settings, "astra_tools_enabled", True):
                tools.extend([t.get_definition() for t in registry.list_tools()])
                
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
                    # Raw tool calls exist, build a dynamic Goal
                    from app.domain.goals import Task, TaskState, Intent, Action
                    from app.ai.orchestrator.action_executor import action_executor
                    
                    tasks = []
                    for call in response.tool_calls:
                        try:
                            intent = action_executor._normalize_tool_call(call)
                            
                            goal_intent = Intent(
                                intent_id=str(uuid.uuid4()),
                                capability_id=call.name,
                                parameters=call.arguments
                            )
                            
                            tasks.append(Task(
                                task_id=str(uuid.uuid4()),
                                description=f"Execute {intent.action} on {intent.target or 'system'}",
                                intents=[goal_intent],
                                state=TaskState.PLANNING,
                                actions_taken=[]
                            ))
                        except Exception as e:
                            logger.warning(f"Could not normalize tool call {call.name} to Intent: {e}")
                            
                    if tasks:
                        goal_plan = Goal(
                            goal_id=str(uuid.uuid4()),
                            objective="Execute requested actions",
                            tasks=tasks,
                            is_complete=False
                        )
                        
            # Phase 9B.1: Single Execution Authority
            if goal_plan:
                from app.ai.orchestrator.runtime import GoalRuntime
                
                # We append the LLM's thought process (the tool call) so history is consistent
                self.history.append(AIMessage(
                    role=MessageRole.ASSISTANT,
                    content=response.content or "",
                    tool_calls=response.tool_calls
                ))
                
                runtime = GoalRuntime(goal_plan)
                
                async for event in runtime.run():
                    # Stream structured events immediately
                    yield event.to_sse_json() + "\n"
                    
                # Append tool result pseudo-message to satisfy the LLM that the tool finished
                self.history.append(AIMessage(
                    role=MessageRole.TOOL,
                    content=f"Goal Execution Finished. State: {'COMPLETED' if goal_plan.is_complete else 'FAILED'}.",
                    tool_call_id=response.tool_calls[0].id if response.tool_calls else str(uuid.uuid4()),
                    name="submit_goal_plan"
                ))
                
                # Final token-streamed response after Goal terminal state
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
