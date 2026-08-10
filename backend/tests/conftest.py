"""
ASTRA Pytest Configuration and Fixtures
"""

import pytest
from httpx import AsyncClient, ASGITransport
from typing import AsyncGenerator

from app.main import app
from app.core.config import get_settings


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for testing endpoints."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
