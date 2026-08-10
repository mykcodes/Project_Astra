"""
ASTRA AI Orchestrator - Session Management

Maintains in-memory conversation context for the current session.
"""

from app.ai.providers.types import AIMessage, MessageRole, AIRequest
from app.ai.providers.base import AIProvider
from app.core.logging.logger import get_logger

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
        
        request = AIRequest(
            messages=self.history,
            temperature=0.7
        )
        
        try:
            response = await self.provider.generate(request)
            self.history.append(AIMessage(role=MessageRole.ASSISTANT, content=response.content))
            return response.content
        except Exception as e:
            logger.error(f"Error during AI orchestration: {e}")
            # Ensure we don't leave the user message dangling without a response if error
            self.history.pop() 
            raise
