"""
ASTRA AI Provider Abstract Base Class

The strict interface that all LLM providers (Gemini, Groq, Mistral, etc.)
must implement. The rest of the application ONLY interacts with this interface.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.ai.providers.types import (
    AIRequest,
    AIResponse,
    AIResponseChunk,
    ModelCapabilities,
    ModelInfo,
)


class AIProvider(ABC):
    """Abstract base class for all AI providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the canonical name of this provider (e.g. 'gemini', 'groq')."""
        ...

    @abstractmethod
    async def generate(self, request: AIRequest) -> AIResponse:
        """Generate a complete response."""
        ...

    @abstractmethod
    async def generate_stream(
        self, request: AIRequest
    ) -> AsyncIterator[AIResponseChunk]:
        """Generate a streaming response."""
        ...

    @abstractmethod
    async def count_tokens(self, text: str) -> int:
        """Count the number of tokens in the given text."""
        ...

    @abstractmethod
    def get_capabilities(self) -> ModelCapabilities:
        """Get the capabilities of the current model."""
        ...

    def get_model_info(self) -> ModelInfo:
        """Get information about the provider and current model."""
        return ModelInfo(
            provider_name=self.provider_name,
            model_name="unknown",
            capabilities=self.get_capabilities(),
        )

    async def check_health(self) -> bool:
        """Check whether this provider is operational. Override for real checks."""
        return True

