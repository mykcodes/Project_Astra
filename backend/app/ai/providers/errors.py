"""
ASTRA Provider Errors

Provider-neutral error hierarchy. These errors allow the Conversation Core
and future Provider Health Manager to understand failure categories without
parsing provider-specific exceptions.

Every error preserves the original exception for debugging.
No error ever logs or exposes API keys.
"""


class ProviderError(Exception):
    """Base class for all provider errors."""

    def __init__(self, message: str, *, provider: str = "unknown", original_error: Exception | None = None):
        self.provider = provider
        self.original_error = original_error
        super().__init__(f"[{provider}] {message}")


class ProviderUnavailableError(ProviderError):
    """Provider is unreachable — network failure or outage."""
    pass


class ProviderAuthenticationError(ProviderError):
    """Invalid or expired API key / credentials."""
    pass


class ProviderRateLimitError(ProviderError):
    """Quota or rate limit exceeded."""
    pass


class ProviderRequestError(ProviderError):
    """Invalid request — bad parameters, unsupported model, etc."""
    pass


class ProviderConfigurationError(ProviderError):
    """Missing or invalid provider configuration (e.g. no API key set)."""
    pass
