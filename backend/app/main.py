"""
ASTRA — Application Entry Point

FastAPI application factory with:
- CORS middleware
- Lifespan management (startup/shutdown)
- Router inclusion
- Health and version endpoints
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging.logger import get_logger
from app.api.routes import api_router

logger = get_logger(__name__)

# Track application start time for uptime calculation
_start_time: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — startup and shutdown hooks."""
    global _start_time
    _start_time = time.time()

    settings = get_settings()
    logger.info(
        "ASTRA starting",
        extra={
            "version": settings.version,
            "environment": settings.environment,
            "debug": settings.debug,
        },
    )

    # Future: initialize database pool, AI providers, event bus, etc.

    yield

    # Future: cleanup database pool, close connections, etc.
    logger.info("ASTRA shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="ASTRA — Personal AI Operating System",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(api_router, prefix="/api")

    return app


def get_uptime() -> float:
    """Get application uptime in seconds."""
    if _start_time == 0.0:
        return 0.0
    return time.time() - _start_time


# Application instance
app = create_app()
