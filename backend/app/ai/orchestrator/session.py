"""
ASTRA AI Orchestrator - Session Management

Maintains in-memory conversation context for the current session.
"""

from collections.abc import AsyncIterator

from app.ai.providers.types import AIMessage, MessageRole, AIRequest
from app.ai.providers.base import AIProvider
from app.core.config import get_settings
from app.core.logging.logger import get_logger
from app.tools.registry import registry
from app.tools.executor import executor

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are ASTRA, a personal AI assistant.
Answer clearly and prioritize factual accuracy.
Never knowingly fabricate information.
Acknowledge uncertainty and never invent sources or claims.
Distinguish known information from uncertainty.
Follow user instructions exactly.
Keep spoken responses reasonably concise, as they will be read aloud.
Provide more detail when explicitly requested.
Avoid unnecessary conversational filler like "umm", "I see", or "Here's the answer".
Do not use markdown formatting like asterisks or code blocks unless requested.
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
        max_calls = settings.astra_tool_max_calls_per_turn
        
        try:
            for _ in range(max_calls):
                tools = [t.get_definition() for t in registry.list_tools()] if settings.astra_tools_enabled else None
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
                    return response.content
                    
                # Execute tool calls
                for tool_call in response.tool_calls:
                    result = await executor.execute(tool_call)
                    self.history.append(AIMessage(
                        role=MessageRole.TOOL,
                        content=result.result if result.success else result.error or "Failed",
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
        max_calls = settings.astra_tool_max_calls_per_turn
        
        try:
            for _ in range(max_calls):
                tools = [t.get_definition() for t in registry.list_tools()] if settings.astra_tools_enabled else None
                request = AIRequest(
                    messages=self.history,
                    temperature=0.7,
                    tools=tools
                )
                
                full_response = []
                tool_calls_buffered = None
                
                async for chunk in self.provider.generate_stream(request):
                    if chunk.tool_calls:
                        tool_calls_buffered = chunk.tool_calls
                    if chunk.content:
                        full_response.append(chunk.content)
                        yield chunk.content
                        
                # Once stream is complete, append full response to history
                self.history.append(AIMessage(
                    role=MessageRole.ASSISTANT, 
                    content="".join(full_response),
                    tool_calls=tool_calls_buffered
                ))
                
                if not tool_calls_buffered:
                    return
                    
                # Execute tool calls and continue loop
                for tool_call in tool_calls_buffered:
                    result = await executor.execute(tool_call)
                    self.history.append(AIMessage(
                        role=MessageRole.TOOL,
                        content=result.result if result.success else result.error or "Failed",
                        tool_call_id=tool_call.id,
                        name=tool_call.name
                    ))
                    
            logger.warning("TOOL_LOOP_LIMIT_REACHED")
            yield "\n[System: I needed to perform too many actions and had to stop.]"
            
        except Exception as e:
            logger.error(f"Error during AI streaming orchestration: {e}")
            self.history.pop()
            raise
