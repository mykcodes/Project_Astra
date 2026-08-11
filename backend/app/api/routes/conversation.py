from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.ai.providers import get_default_provider
from app.ai.orchestrator.session import ConversationSession
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/conversation", tags=["Conversation"])

# Singleton session — provider is resolved from ASTRA_AI_PROVIDER setting
provider = get_default_provider()
session = ConversationSession(provider=provider)

class MessageRequest(BaseModel):
    text: str

from fastapi.responses import StreamingResponse

@router.post("/message")
async def send_message(request: MessageRequest):
    """Sends a message to the AI and gets a response."""
    try:
        response_text = await session.chat(request.text)
        return {"text": response_text}
    except Exception as e:
        logger.error(f"Conversation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to get AI response")

@router.post("/message/stream")
async def stream_message(request: MessageRequest):
    """Sends a message to the AI and streams back the response."""
    try:
        # Wrap the generator to match standard SSE format (optional but standard)
        # or just stream the raw text chunks. We will stream raw text chunks.
        return StreamingResponse(session.chat_stream(request.text), media_type="text/plain")
    except Exception as e:
        logger.error(f"Conversation stream failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to stream AI response")
