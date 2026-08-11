"""
ASTRA Gemini Provider

Implementation of the AIProvider interface for Google's Gemini models.
"""

import time
from collections.abc import AsyncIterator

from google import genai
from google.genai import types

from app.ai.providers.base import AIProvider
from app.ai.providers.errors import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderUnavailableError,
)
from app.ai.providers.types import (
    AIRequest,
    AIResponse,
    AIResponseChunk,
    ModelCapabilities,
    ModelInfo,
    TokenUsage,
)
from app.core.config import get_settings
from app.core.logging.logger import get_logger

logger = get_logger(__name__)


class GeminiProvider(AIProvider):
    """Gemini implementation of the AIProvider interface."""

    @property
    def provider_name(self) -> str:
        return "gemini"

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.gemini_api_key
        self.default_model = settings.astra_ai_model

        if not self.api_key:
            logger.warning("Gemini API key missing — generation will fail.")
            self.client = None
        else:
            self.client = genai.Client(api_key=self.api_key)
            logger.info(
                "PROVIDER_INITIALIZED",
                extra={"provider": "gemini", "model": self.default_model},
            )

    async def generate(self, request: AIRequest) -> AIResponse:
        if not self.client:
            raise ProviderConfigurationError(
                "Gemini API key is not configured.",
                provider="gemini",
            )

        messages = []
        system_instruction = None

        for msg in request.messages:
            if msg.role == "system":
                system_instruction = msg.content
            else:
                role = "user" if msg.role == "user" else "model"
                messages.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg.content)],
                ))

        model_name = request.model or self.default_model
        logger.info(f"AI_REQUEST_STARTED: provider=gemini model={model_name}")

        start = time.perf_counter()

        try:
            response = await self.client.aio.models.generate_content(
                model=model_name,
                contents=messages,
                config=types.GenerateContentConfig(
                    temperature=request.temperature or 0.7,
                    max_output_tokens=request.max_tokens,
                    system_instruction=system_instruction,
                ),
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._handle_api_error(exc, latency_ms)

        latency_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "AI_RESPONSE_RECEIVED",
            extra={"provider": "gemini", "model": model_name, "latency_ms": round(latency_ms, 1)},
        )

        usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        if response.usage_metadata:
            usage = TokenUsage(
                prompt_tokens=response.usage_metadata.prompt_token_count or 0,
                completion_tokens=response.usage_metadata.candidates_token_count or 0,
                total_tokens=response.usage_metadata.total_token_count or 0,
            )

        return AIResponse(
            content=response.text or "",
            model=model_name,
            provider="gemini",
            usage=usage,
            finish_reason="stop",
            metadata={"latency_ms": round(latency_ms, 1)},
        )

    async def generate_stream(
        self, request: AIRequest
    ) -> AsyncIterator[AIResponseChunk]:
        raise NotImplementedError("GeminiProvider.generate_stream is not yet implemented")

    async def count_tokens(self, text: str) -> int:
        raise NotImplementedError("GeminiProvider.count_tokens is not yet implemented")

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            max_context_tokens=1_000_000,  # Gemini 1.5/2.0 context window
            supports_streaming=True,
            supports_function_calling=True,
            supports_vision=True,
        )

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            provider_name="gemini",
            model_name=self.default_model,
            capabilities=self.get_capabilities(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_api_error(self, exc: Exception, latency_ms: float) -> None:
        """Translate Gemini SDK exceptions into provider-neutral errors."""
        error_msg = str(exc)

        logger.error(
            "AI_REQUEST_FAILED",
            extra={"provider": "gemini", "latency_ms": round(latency_ms, 1), "error": error_msg},
        )

        # Map common Google API error patterns to provider-neutral errors.
        # The google-genai SDK surfaces google.api_core errors.
        error_lower = error_msg.lower()

        if "401" in error_msg or "invalid api key" in error_lower or "permission denied" in error_lower:
            raise ProviderAuthenticationError(
                "Authentication failed — check your Gemini API key.",
                provider="gemini",
                original_error=exc,
            ) from exc

        if "429" in error_msg or "resource exhausted" in error_lower or "quota" in error_lower:
            raise ProviderRateLimitError(
                "Rate limit or quota exceeded.",
                provider="gemini",
                original_error=exc,
            ) from exc

        if "400" in error_msg or "invalid argument" in error_lower:
            raise ProviderRequestError(
                f"Invalid request: {error_msg}",
                provider="gemini",
                original_error=exc,
            ) from exc

        if "503" in error_msg or "unavailable" in error_lower or "connection" in error_lower:
            raise ProviderUnavailableError(
                "Gemini API is currently unavailable.",
                provider="gemini",
                original_error=exc,
            ) from exc

        # Fallback: wrap as a generic ProviderRequestError
        raise ProviderRequestError(
            f"Gemini request failed: {error_msg}",
            provider="gemini",
            original_error=exc,
        ) from exc
