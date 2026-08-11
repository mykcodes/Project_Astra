"""
ASTRA AI Provider Registry

Config-driven factory for LLM providers. Only providers that are actually
implemented are registered here.  The rest of the application obtains its
provider through ``get_default_provider()`` which reads ``astra_ai_provider``
from Settings.
"""

from __future__ import annotations

from app.ai.providers.base import AIProvider
from app.ai.providers.errors import ProviderConfigurationError
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.groq import GroqProvider

from app.ai.providers.local.provider import LocalProvider

# ---------------------------------------------------------------------------
# Provider registry — add new providers here as they are implemented.
# ---------------------------------------------------------------------------
_providers: dict[str, type[AIProvider]] = {
    "gemini": GeminiProvider,
    "groq": GroqProvider,
    "local": LocalProvider,
    # Future:
    # "mistral": MistralProvider,
    # "openrouter": OpenRouterProvider,
}


def list_providers() -> list[str]:
    """Return the names of all registered (implemented) providers."""
    return list(_providers.keys())


def get_provider(name: str) -> AIProvider:
    """
    Instantiate a provider by name.

    Args:
        name: Canonical provider name (e.g. ``"gemini"``).

    Returns:
        A ready-to-use ``AIProvider`` instance.

    Raises:
        ProviderConfigurationError: If the name is not registered.
    """
    provider_class = _providers.get(name.lower())
    if not provider_class:
        raise ProviderConfigurationError(
            f"Unknown provider '{name}'. Available: {list_providers()}",
            provider=name,
        )
    return provider_class()


def get_default_provider() -> AIProvider:
    """
    Return the ProviderManager which proxies to the provider specified by
    ``ASTRA_AI_PROVIDER`` and handles automatic fallback.
    """
    from app.ai.providers.manager import ProviderManager
    return ProviderManager()

