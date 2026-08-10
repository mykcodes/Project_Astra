"""
ASTRA AI Provider Abstract Base Class

The strict interface that all LLM providers (Gemini, OpenAI, Anthropic)
must implement. The rest of the application ONLY interacts with this interface.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.ai.providers.types import (
    AIRequest,
    AIResponse,
    AIResponseChunk,
    ModelCapabilities,
)


class AIProvider(ABC):
    """Abstract base class for all AI providers."""

    @abstractmethod
    async def generate(self, request: AIRequest) -> AIResponse:
        """Generate a complete response."""
        pass

    @abstractmethod
    async def generate_stream(
        self, request: AIRequest
    ) -> AsyncIterator[AIResponseChunk]:
        """Generate a streaming response."""
        pass

    @abstractmethod
    async def count_tokens(self, text: str) -> int:
        """Count the number of tokens in the given text."""
        pass

    @abstractmethod
    def get_capabilities(self) -> ModelCapabilities:
        """Get the capabilities of the current model."""
        pass
