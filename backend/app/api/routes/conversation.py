from typing import Optional
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
    utterance_id: Optional[str] = None
    aligned_observation_id: Optional[str] = None
    session_id: Optional[str] = None

from fastapi.responses import StreamingResponse

@router.post("/message")
async def send_message(request: MessageRequest):
    """Sends a message to the AI and gets a response."""
    try:
        response_text = await session.chat(
            request.text,
            aligned_observation_id=request.aligned_observation_id,
        )
        return {"text": response_text}
    except Exception as e:
        logger.error(f"Conversation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to get AI response")

@router.post("/message/stream")
async def stream_message(request: MessageRequest):
    """Sends a message to the AI and streams back the response."""
    try:
        return StreamingResponse(
            session.chat_stream(
                request.text,
                aligned_observation_id=request.aligned_observation_id,
            ),
            media_type="application/x-ndjson",
        )
    except Exception as e:
        logger.error(f"Conversation stream failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to stream AI response")

@router.post("/cancel")
async def cancel_execution():
    """Cancels the currently running goal or action execution in the active session."""
    try:
        cancelled = session.cancel()
        return {"cancelled": cancelled}
    except Exception as e:
        logger.error(f"Conversation cancel failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel execution")

@router.get("/goals/resumable")
async def list_resumable_goals():
    """Lists all persisted goals currently eligible for safe resumption."""
    try:
        resumable = await session.list_resumable_goals()
        return {"goals": resumable}
    except Exception as e:
        logger.error(f"Failed to list resumable goals: {e}")
        raise HTTPException(status_code=500, detail="Failed to list resumable goals")

@router.post("/goals/{goal_id}/resume")
async def resume_goal(goal_id: str):
    """Resumes an interrupted or suspended goal from its checkpoint and streams execution events."""
    try:
        return StreamingResponse(session.resume_goal_stream(goal_id), media_type="application/x-ndjson")
    except ValueError as e:
        logger.warning(f"Resume validation failed for goal {goal_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.warning(f"Resume conflict for goal {goal_id}: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to resume goal {goal_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to resume goal")

# ---------------------------------------------------------
# Phase B.10: Long-Term Memory & Application Profile Routes
# ---------------------------------------------------------

class RememberRequest(BaseModel):
    key: str
    content: str
    memory_type: str = "FACT"
    tags: list[str] = []

class ProfileRequest(BaseModel):
    canonical_name: str
    display_name: str
    category: str = "general"
    aliases: list[str] = []
    is_default_for_category: bool = False
    notes: str = ""

@router.post("/memory/remember")
async def remember_memory(request: RememberRequest):
    """Stores an explicit fact or preference into long-term durable memory."""
    try:
        from app.domain.memory import MemoryType, ProvenanceType
        mem_type = MemoryType[request.memory_type.upper()] if request.memory_type.upper() in MemoryType.__members__ else MemoryType.FACT
        record = session.memory_engine.remember(
            key=request.key,
            content=request.content,
            memory_type=mem_type,
            provenance=ProvenanceType.USER_EXPLICIT,
            tags=request.tags,
        )
        return {"record": record.to_dict()}
    except Exception as e:
        logger.error(f"Failed to store memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/memory/recall")
async def recall_memory(query: str, limit: int = 5):
    """Searches long-term memory for relevant user preferences, facts, and history."""
    try:
        results = session.memory_engine.recall(query=query, limit=limit)
        return {"results": [r.to_dict() for r in results]}
    except Exception as e:
        logger.error(f"Failed to recall memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/memory/{key}")
async def forget_memory(key: str):
    """Deletes a long-term memory record by key."""
    try:
        success = session.memory_engine.forget(key)
        if not success:
            raise HTTPException(status_code=404, detail=f"Memory record '{key}' not found.")
        return {"deleted": True, "key": key}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete memory '{key}': {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/memory/profiles")
async def list_profiles(category: str | None = None):
    """Lists registered application profiles and aliases."""
    try:
        profiles = session.memory_engine.list_application_profiles(category=category)
        return {"profiles": [p.to_dict() for p in profiles]}
    except Exception as e:
        logger.error(f"Failed to list application profiles: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/memory/profiles")
async def save_profile(request: ProfileRequest):
    """Saves or updates an application profile with user aliases and preferences."""
    try:
        from app.domain.memory import ApplicationProfile
        profile = ApplicationProfile(
            canonical_name=request.canonical_name,
            display_name=request.display_name,
            category=request.category,
            aliases=request.aliases,
            is_default_for_category=request.is_default_for_category,
            notes=request.notes,
        )
        saved = session.memory_engine.save_application_profile(profile)
        return {"profile": saved.to_dict()}
    except Exception as e:
        logger.error(f"Failed to save application profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------
# Phase B.11: Clarification & Consequential Confirmation Routes
# ---------------------------------------------------------

class ClarifyRequest(BaseModel):
    request_id: str
    selected_option_id: str | None = None
    custom_input: str | None = None
    remember_as_preference: bool = False

class ConfirmRequest(BaseModel):
    request_id: str
    confirmed: bool

@router.post("/clarify")
async def clarify_target(request: ClarifyRequest):
    """Submits a clarification response for an ambiguous target or missing parameter."""
    try:
        from app.domain.clarification import ClarificationResponse
        resp = ClarificationResponse(
            request_id=request.request_id,
            selected_option_id=request.selected_option_id,
            custom_input=request.custom_input,
            remember_as_preference=request.remember_as_preference,
        )
        return StreamingResponse(session.resolve_clarification_stream(resp), media_type="application/x-ndjson")
    except ValueError as e:
        logger.warning(f"Clarification validation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.warning(f"Clarification conflict: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to resolve clarification: {e}")
        raise HTTPException(status_code=500, detail="Failed to resolve clarification")

@router.post("/confirm")
async def confirm_action(request: ConfirmRequest):
    """Submits explicit authorization or rejection for a consequential desktop action."""
    try:
        from app.domain.clarification import ClarificationResponse
        resp = ClarificationResponse(
            request_id=request.request_id,
            confirmed=request.confirmed,
        )
        return StreamingResponse(session.resolve_clarification_stream(resp), media_type="application/x-ndjson")
    except ValueError as e:
        logger.warning(f"Confirmation validation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.warning(f"Confirmation conflict: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to confirm consequential action: {e}")
        raise HTTPException(status_code=500, detail="Failed to process confirmation")



