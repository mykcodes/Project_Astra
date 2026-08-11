"""
ASTRA Provider Manager

Implements the AIProvider interface as a proxy that handles automatic fallback,
health tracking, and cooldowns for underlying LLM providers.
"""

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.ai.providers.base import AIProvider
from app.ai.providers.errors import (
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from app.ai.providers.types import (
    AIRequest,
    AIResponse,
    AIResponseChunk,
    ModelCapabilities,
    ModelInfo,
)
from app.core.config import get_settings
from app.core.logging.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ProviderHealth:
    available: bool = True
    last_failure_time: float = 0.0
    failure_count: int = 0
    cooldown_until: float = 0.0
    last_error_category: str | None = None


class ProviderManager(AIProvider):
    """
    Acts as an AIProvider proxy, routing requests to the configured primary
    provider or falling back to healthy alternatives if retryable errors occur.
    """

    def __init__(self) -> None:
        # Avoid circular import by importing registry functions locally
        from app.ai.providers import get_provider

        settings = get_settings()
        
        self.cooldown_seconds = settings.astra_provider_cooldown_seconds
        self.primary_provider_name = settings.astra_ai_provider.strip().lower()
        
        fallback_str = settings.astra_ai_fallback_providers
        self.fallback_provider_names = [
            p.strip().lower() for p in fallback_str.split(",") if p.strip()
        ]

        # Combine primary and fallbacks, removing duplicates while preserving order
        candidate_names = [self.primary_provider_name] + self.fallback_provider_names
        self.configured_order = []
        for name in candidate_names:
            if name not in self.configured_order:
                self.configured_order.append(name)

        # Lazy load providers and initialize health state
        self.providers: dict[str, AIProvider] = {}
        self.health_state: dict[str, ProviderHealth] = {}

        for name in self.configured_order:
            try:
                self.providers[name] = get_provider(name)
                self.health_state[name] = ProviderHealth()
            except Exception as exc:
                logger.warning(
                    f"Failed to initialize provider '{name}': {exc}. "
                    f"It will be unavailable for fallback."
                )

        if not self.providers:
            # Re-raise configuration error if literally nothing loaded
            raise ProviderConfigurationError(
                "No providers successfully initialized. Check your ASTRA_AI_PROVIDER configuration."
            )

    @property
    def provider_name(self) -> str:
        # We represent ourselves as a "manager", though actual responses will carry the real provider's name
        return "manager"

    def _get_eligible_providers(self) -> list[str]:
        """Returns a list of provider names that are not currently in cooldown."""
        eligible = []
        now = time.time()
        for name in self.configured_order:
            if name not in self.health_state or name not in self.providers:
                continue
            
            health = self.health_state[name]
            if not health.available:
                if now >= health.cooldown_until:
                    # Cooldown expired, mark available again
                    health.available = True
                    logger.info(f"Provider '{name}' cooldown expired. Marking available.")
                else:
                    # Still in cooldown
                    continue
                    
            eligible.append(name)
        return eligible

    def _mark_unhealthy(self, name: str, exc: Exception) -> None:
        """Mark a provider as temporarily unavailable due to a retryable error."""
        health = self.health_state[name]
        health.available = False
        health.last_failure_time = time.time()
        health.failure_count += 1
        health.cooldown_until = time.time() + self.cooldown_seconds
        health.last_error_category = exc.__class__.__name__

        logger.warning(
            "AI_PROVIDER_MARKED_UNAVAILABLE",
            extra={
                "provider": name,
                "error_category": health.last_error_category,
                "cooldown_seconds": self.cooldown_seconds,
            },
        )

    async def generate(self, request: AIRequest) -> AIResponse:
        eligible_providers = self._get_eligible_providers()

        if not eligible_providers:
            logger.error("AI_ALL_PROVIDERS_FAILED", extra={"reason": "All configured providers are in cooldown."})
            raise ProviderUnavailableError("All AI providers are currently unavailable or in cooldown.")

        last_exception = None

        for name in eligible_providers:
            provider = self.providers[name]
            
            if name != self.configured_order[0]:
                logger.info("AI_PROVIDER_FALLBACK", extra={"target_provider": name})
                
            logger.info("AI_PROVIDER_SELECTED", extra={"provider": name})

            try:
                # The underlying provider will emit AI_REQUEST_STARTED and AI_RESPONSE_RECEIVED
                response = await provider.generate(request)
                
                # Ensure the response accurately reflects the provider that succeeded
                response.provider = name
                return response

            except (ProviderRateLimitError, ProviderUnavailableError) as exc:
                # Retryable errors
                if isinstance(exc, ProviderRateLimitError):
                    logger.warning("AI_PROVIDER_RATE_LIMITED", extra={"provider": name})
                
                self._mark_unhealthy(name, exc)
                last_exception = exc
                continue # Try the next eligible provider

            except Exception as exc:
                # Non-retryable errors (Configuration, Authentication, Request)
                logger.error(f"Non-retryable error from provider '{name}': {exc}")
                raise exc

        # If we exhausted the loop and only got retryable errors
        logger.error("AI_ALL_PROVIDERS_FAILED", extra={"reason": "All eligible providers exhausted due to retryable errors."})
        raise ProviderUnavailableError("All available AI providers failed.", original_error=last_exception)

    async def close(self):
        for provider in self.providers.values():
            if hasattr(provider, "close"):
                import inspect
                if inspect.iscoroutinefunction(provider.close):
                    await provider.close()
                else:
                    provider.close()

    async def generate_stream(self, request: AIRequest) -> AsyncIterator[AIResponseChunk]:
        eligible_providers = self._get_eligible_providers()

        if not eligible_providers:
            logger.error("AI_ALL_PROVIDERS_FAILED", extra={"reason": "All configured providers are in cooldown."})
            raise ProviderUnavailableError("All AI providers are currently unavailable or in cooldown.")

        last_exception = None

        for name in eligible_providers:
            provider = self.providers[name]
            
            if name != self.configured_order[0]:
                logger.info("AI_PROVIDER_FALLBACK", extra={"target_provider": name})
                
            logger.info("AI_PROVIDER_SELECTED", extra={"provider": name})

            try:
                # Get the iterator
                stream_iter = provider.generate_stream(request)
                # Try fetching the first chunk to catch connection errors before yielding
                first_chunk = await anext(stream_iter)
                
            except (ProviderRateLimitError, ProviderUnavailableError) as exc:
                if isinstance(exc, ProviderRateLimitError):
                    logger.warning("AI_PROVIDER_RATE_LIMITED", extra={"provider": name})
                self._mark_unhealthy(name, exc)
                last_exception = exc
                continue
            except StopAsyncIteration:
                # Stream instantly empty
                return
            except Exception as exc:
                logger.error(f"Non-retryable error from provider '{name}': {exc}")
                raise exc

            # We successfully connected and got the first chunk. No more fallback from here.
            try:
                yield first_chunk
                async for chunk in stream_iter:
                    yield chunk
            except Exception as exc:
                logger.error(f"Stream interrupted from provider '{name}': {exc}")
                raise ProviderUnavailableError(f"Stream interrupted mid-response: {exc}", original_error=exc)
                
            return

        logger.error("AI_ALL_PROVIDERS_FAILED", extra={"reason": "All eligible providers exhausted due to retryable errors."})
        raise ProviderUnavailableError("All available AI providers failed.", original_error=last_exception)

    async def count_tokens(self, text: str) -> int:
        # Just route to the primary provider for token counting
        primary = self.providers.get(self.primary_provider_name)
        if primary:
            return await primary.count_tokens(text)
        raise NotImplementedError("count_tokens not available on configured primary provider")

    def get_capabilities(self) -> ModelCapabilities:
        # Route to primary
        primary = self.providers.get(self.primary_provider_name)
        if primary:
            return primary.get_capabilities()
        return ModelCapabilities(max_context_tokens=0)

    def get_model_info(self) -> ModelInfo:
        # Route to primary
        primary = self.providers.get(self.primary_provider_name)
        if primary:
            return primary.get_model_info()
        return ModelInfo(provider_name="manager", model_name="unknown")
