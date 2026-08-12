from collections.abc import AsyncIterator

from app.ai.providers.base import AIProvider
from app.ai.providers.errors import ProviderConfigurationError, ProviderUnavailableError
from app.ai.providers.types import (
    AIRequest,
    AIResponse,
    AIResponseChunk,
    ModelCapabilities,
    ModelInfo,
)
from app.core.config import get_settings
from app.core.logging.logger import get_logger
from app.ai.runtimes.openai import OpenAICompatibleRuntime

logger = get_logger(__name__)


class LocalProvider(AIProvider):
    """
    Local AI Provider. Proxies requests to a local OpenAI-compatible inference server.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        
        if not self.settings.astra_local_enabled:
            raise ProviderConfigurationError(
                "Local AI Provider is disabled. Set ASTRA_LOCAL_ENABLED=true to enable.",
                provider=self.provider_name
            )

        # Do NOT require any API keys.
        
        self.base_url = self.settings.astra_local_base_url
        if self.settings.astra_local_runtime.lower() == "openai":
            self.runtime = OpenAICompatibleRuntime(self.base_url)
        else:
            raise ProviderConfigurationError(
                f"Unsupported local runtime: {self.settings.astra_local_runtime}",
                provider=self.provider_name
            )
            
        self.default_model = self.settings.astra_local_model
        self.max_tokens = self.settings.astra_local_max_tokens
        self.context_length = self.settings.astra_local_context_length
        self.temperature = self.settings.astra_local_temperature

        # We will discover the actual model running if the configured one is not found
        self._actual_model: str | None = None

    @property
    def provider_name(self) -> str:
        return "local"

    async def close(self):
        await self.runtime.close()

    async def _resolve_model(self) -> str:
        """Resolve the active model on the local runtime."""
        if self._actual_model:
            return self._actual_model
            
        if self.default_model:
            # Trust the configured model and skip discovery to avoid latency
            self._actual_model = self.default_model
            return self._actual_model
            
        models = await self.runtime.get_models()
        if not models:
            logger.warning("Local runtime did not return any models, but it is available. Using 'default'.")
            return "default"
            
        self._actual_model = models[0]
        return self._actual_model

    async def generate(self, request: AIRequest) -> AIResponse:
        try:
            model_to_use = await self._resolve_model()
            return await self.runtime.generate(
                request=request,
                configured_model=model_to_use,
                default_max_tokens=self.max_tokens,
                default_temperature=self.temperature,
                fallback_provider_name=self.provider_name
            )
        except Exception as exc:
            self._actual_model = None
            raise exc

    async def generate_stream(self, request: AIRequest) -> AsyncIterator[AIResponseChunk]:
        try:
            model_to_use = await self._resolve_model()
            async for chunk in self.runtime.generate_stream(
                request=request,
                configured_model=model_to_use,
                default_max_tokens=self.max_tokens,
                default_temperature=self.temperature,
                fallback_provider_name=self.provider_name
            ):
                yield chunk
        except Exception as exc:
            self._actual_model = None
            raise exc

    async def count_tokens(self, text: str) -> int:
        return len(text) // 4

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            max_context_tokens=self.context_length,
            supports_streaming=True,
            supports_function_calling=True,
            supports_vision=False
        )

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            provider_name=self.provider_name,
            model_name=self._actual_model or self.default_model or "unknown",
            capabilities=self.get_capabilities(),
        )

    async def check_health(self) -> bool:
        """Verify the local runtime is reachable and a model is available."""
        try:
            models = await self.runtime.get_models()
            if not models:
                logger.warning("Local runtime is reachable, but no models are loaded.")
                return False
            return True
        except ProviderUnavailableError:
            return False
        except Exception as exc:
            logger.warning(f"Local provider health check failed: {exc}")
            return False
