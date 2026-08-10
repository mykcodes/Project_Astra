"""ASTRA API Router Aggregation."""

from fastapi import APIRouter

from .health import router as health_router
from .voice import router as voice_router
from .conversation import router as conversation_router

api_router = APIRouter()

api_router.include_router(health_router, tags=["system"])
api_router.include_router(voice_router, tags=["voice"])
api_router.include_router(conversation_router, tags=["conversation"])
