from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.ai.providers.gemini import GeminiProvider
from app.ai.orchestrator.session import ConversationSession
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/conversation", tags=["Conversation"])

# Singleton session for Phase 2 prototype
provider = GeminiProvider()
session = ConversationSession(provider=provider)

class MessageRequest(BaseModel):
    text: str

@router.post("/message")
async def send_message(request: MessageRequest):
    """Sends a message to the AI and gets a response."""
    try:
        response_text = await session.chat(request.text)
        return {"text": response_text}
    except Exception as e:
        logger.error(f"Conversation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to get AI response")
