"""
ASTRA Groq Provider

Implementation of the AIProvider interface for Groq's fast LLM APIs.
"""

import time
from collections.abc import AsyncIterator

import groq

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


class GroqProvider(AIProvider):
    """Groq implementation of the AIProvider interface."""

    @property
    def provider_name(self) -> str:
        return "groq"

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.groq_api_key
        
        # We explicitly isolate Groq's model default so it doesn't accidentally
        # use the Gemini model identifier if the user forgot to configure it.
        self.default_model = settings.groq_model

        if not self.api_key:
            logger.warning("Groq API key missing — generation will fail.")
            self.client = None
        else:
            self.client = groq.AsyncGroq(api_key=self.api_key)
            logger.info(
                "PROVIDER_INITIALIZED",
                extra={"provider": "groq", "model": self.default_model},
            )

    async def generate(self, request: AIRequest) -> AIResponse:
        if not self.client:
            raise ProviderConfigurationError(
                "Groq API key is not configured.",
                provider="groq",
            )

        # Map ASTRA messages to Groq/OpenAI compatible format
        messages = []
        for msg in request.messages:
            # Groq uses standard roles: "system", "user", "assistant"
            messages.append({
                "role": msg.role.value,
                "content": msg.content
            })

        # Do NOT reuse ASTRA_AI_MODEL from request if we don't have to,
        # but if the user explicitly configures a model we should honor it,
        # IF we want to strictly follow the prompt we should only use self.default_model.
        # "The provider should use settings.groq_model." -> ok, we'll ignore request.model.
        model_name = self.default_model
        
        logger.info(f"AI_REQUEST_STARTED: provider=groq model={model_name}")

        start = time.perf_counter()

        try:
            response = await self.client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=request.temperature or 0.7,
                max_tokens=request.max_tokens,
                stop=request.stop_sequences,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._handle_api_error(exc, latency_ms)

        latency_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "AI_RESPONSE_RECEIVED",
            extra={"provider": "groq", "model": model_name, "latency_ms": round(latency_ms, 1)},
        )

        content = response.choices[0].message.content or ""
        finish_reason = response.choices[0].finish_reason or "stop"
        
        usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                total_tokens=response.usage.total_tokens or 0,
            )

        return AIResponse(
            content=content,
            model=model_name,
            provider="groq",
            usage=usage,
            finish_reason=finish_reason,
            metadata={"latency_ms": round(latency_ms, 1)},
        )

    async def generate_stream(
        self, request: AIRequest
    ) -> AsyncIterator[AIResponseChunk]:
        raise NotImplementedError("GroqProvider.generate_stream is not yet implemented")

    async def count_tokens(self, text: str) -> int:
        raise NotImplementedError("GroqProvider.count_tokens is not yet implemented")

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            max_context_tokens=131072,  # Typical for llama-3 on Groq
            supports_streaming=True,
            supports_function_calling=True,
            supports_vision=False,
        )

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            provider_name="groq",
            model_name=self.default_model,
            capabilities=self.get_capabilities(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_api_error(self, exc: Exception, latency_ms: float) -> None:
        """Translate Groq SDK exceptions into provider-neutral errors."""
        error_msg = str(exc)

        logger.error(
            "AI_REQUEST_FAILED",
            extra={"provider": "groq", "latency_ms": round(latency_ms, 1), "error": error_msg},
        )

        if isinstance(exc, groq.AuthenticationError):
            raise ProviderAuthenticationError(
                "Authentication failed — check your Groq API key.",
                provider="groq",
                original_error=exc,
            ) from exc

        if isinstance(exc, groq.RateLimitError):
            raise ProviderRateLimitError(
                "Rate limit or quota exceeded.",
                provider="groq",
                original_error=exc,
            ) from exc

        if isinstance(exc, groq.BadRequestError):
            raise ProviderRequestError(
                f"Invalid request: {error_msg}",
                provider="groq",
                original_error=exc,
            ) from exc

        if isinstance(exc, (groq.APIConnectionError, groq.APITimeoutError, groq.InternalServerError)):
            raise ProviderUnavailableError(
                "Groq API is currently unavailable.",
                provider="groq",
                original_error=exc,
            ) from exc

        # Fallback: wrap as a generic ProviderRequestError
        raise ProviderRequestError(
            f"Groq request failed: {error_msg}",
            provider="groq",
            original_error=exc,
        ) from exc
