"""
ASTRA AI Provider Registry and Factory
"""

from app.ai.providers.base import AIProvider
from app.ai.providers.gemini import GeminiProvider

_providers: dict[str, type[AIProvider]] = {
    "gemini": GeminiProvider,
    # "openai": OpenAIProvider,
    # "anthropic": AnthropicProvider,
}


def get_provider(name: str) -> AIProvider:
    """
    Factory function to get an AIProvider instance by name.
    
    Args:
        name: The name of the provider (e.g., 'gemini')
        
    Returns:
        An instance of the requested AIProvider
        
    Raises:
        ValueError: If the provider name is not registered
    """
    provider_class = _providers.get(name.lower())
    if not provider_class:
        raise ValueError(f"Unknown AI provider: {name}. Available providers: {list(_providers.keys())}")
        
    return provider_class()
