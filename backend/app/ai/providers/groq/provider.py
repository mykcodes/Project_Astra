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
    ToolCall,
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
            if msg.role == "tool":
                messages.append({
                    "role": "tool",
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id
                })
            elif msg.role == "assistant" and msg.tool_calls:
                groq_tool_calls = []
                for call in msg.tool_calls:
                    import json
                    groq_tool_calls.append({
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments)
                        }
                    })
                msg_dict = {
                    "role": "assistant",
                    "tool_calls": groq_tool_calls
                }
                if msg.content:
                    msg_dict["content"] = msg.content
                messages.append(msg_dict)
            else:
                messages.append({
                    "role": msg.role.value,
                    "content": msg.content
                })

        groq_tools = None
        if request.tools:
            groq_tools = []
            for tool in request.tools:
                groq_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters
                    }
                })

        # Do NOT reuse ASTRA_AI_MODEL from request if we don't have to,
        # but if the user explicitly configures a model we should honor it,
        # IF we want to strictly follow the prompt we should only use self.default_model.
        # "The provider should use settings.groq_model." -> ok, we'll ignore request.model.
        model_name = self.default_model
        
        logger.info(f"AI_REQUEST_STARTED: provider=groq model={model_name}")

        start = time.perf_counter()

        kwargs = {
            "model": model_name,
            "messages": messages,
            "temperature": request.temperature or 0.7,
            "max_tokens": request.max_tokens,
            "stop": request.stop_sequences,
        }
        if groq_tools:
            kwargs["tools"] = groq_tools
            kwargs["tool_choice"] = "auto"

        try:
            response = await self.client.chat.completions.create(**kwargs)
        except groq.BadRequestError as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            err_dict = getattr(exc, "body", {})
            if isinstance(err_dict, dict) and err_dict.get("error", {}).get("code") == "tool_use_failed":
                failed_gen = err_dict.get("error", {}).get("failed_generation", "")
                logger.warning(
                    "Groq tool validation failed. Returning failed generation as text.",
                    extra={"failed_generation": failed_gen}
                )
                return AIResponse(
                    content=failed_gen,
                    model=model_name,
                    provider="groq",
                    usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                    finish_reason="stop",
                    metadata={"latency_ms": round(latency_ms, 1)},
                    tool_calls=None
                )
            self._handle_api_error(exc, latency_ms)
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
        
        tool_calls = None
        if response.choices[0].message.tool_calls:
            import json
            tool_calls = []
            for tc in response.choices[0].message.tool_calls:
                args = {}
                try:
                    args = json.loads(tc.function.arguments)
                except:
                    pass
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args
                ))
        
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
            tool_calls=tool_calls
        )

    async def generate_stream(
        self, request: AIRequest
    ) -> AsyncIterator[AIResponseChunk]:
        if not self.client:
            raise ProviderConfigurationError(
                "Groq API key is not configured.",
                provider="groq",
            )

        messages = []
        for msg in request.messages:
            if msg.role == "tool":
                messages.append({
                    "role": "tool",
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id
                })
            elif msg.role == "assistant" and msg.tool_calls:
                groq_tool_calls = []
                for call in msg.tool_calls:
                    import json
                    groq_tool_calls.append({
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments)
                        }
                    })
                msg_dict = {
                    "role": "assistant",
                    "tool_calls": groq_tool_calls
                }
                if msg.content:
                    msg_dict["content"] = msg.content
                messages.append(msg_dict)
            else:
                messages.append({
                    "role": msg.role.value,
                    "content": msg.content
                })

        groq_tools = None
        if request.tools:
            groq_tools = []
            for tool in request.tools:
                groq_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters
                    }
                })

        model_name = self.default_model
        
        logger.info(f"AI_STREAM_REQUEST_STARTED: provider=groq model={model_name}")
        start = time.perf_counter()

        kwargs = {
            "model": model_name,
            "messages": messages,
            "temperature": request.temperature or 0.7,
            "max_tokens": request.max_tokens,
            "stop": request.stop_sequences,
            "stream": True,
        }
        if groq_tools:
            kwargs["tools"] = groq_tools
            kwargs["tool_choice"] = "auto"

        try:
            stream = await self.client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    content = delta.content or ""
                    yield AIResponseChunk(content=content)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._handle_api_error(exc, latency_ms)

        logger.info(
            "AI_STREAM_RESPONSE_FINISHED",
            extra={"provider": "groq", "model": model_name},
        )

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
