"""ASTRA Health Check API."""

import time
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Any

from app.core.config import get_settings
from app.schemas.common import HealthResponse
from app.database.session import get_db_session
from app.core.lifecycle.state import get_uptime

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def check_health(db: AsyncSession = Depends(get_db_session)) -> Any:
    """
    Check system health and database connectivity.
    """
    settings = get_settings()
    
    # Check database connectivity
    db_connected = False
    try:
        await db.execute(text("SELECT 1"))
        db_connected = True
    except Exception:
        db_connected = False

    return HealthResponse(
        status="ok" if db_connected else "degraded",
        version=settings.version,
        environment=settings.environment,
        uptime=get_uptime(),
        database_connected=db_connected,
    )
