import httpx
import json
import time
from typing import Any, AsyncIterator

from app.ai.providers.types import (
    AIRequest,
    AIResponse,
    AIResponseChunk,
    TokenUsage,
)
from app.ai.providers.errors import ProviderUnavailableError
from app.core.logging.logger import get_logger

logger = get_logger(__name__)


class OpenAICompatibleRuntime:
    """
    A runtime wrapper for an OpenAI-compatible API endpoint (e.g. LM Studio, Ollama).
    It manages the HTTP client and raw payload formatting.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        # Persistent client with pooling and timeouts
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
        self.client = httpx.AsyncClient(timeout=180.0, limits=limits)

    async def close(self):
        await self.client.aclose()

    async def get_models(self) -> list[str]:
        """Fetch the available models from the local server."""
        try:
            response = await self.client.get(f"{self.base_url}/models", timeout=5.0)
            response.raise_for_status()
            data = response.json()
            if "data" in data and isinstance(data["data"], list):
                return [model.get("id") for model in data["data"] if "id" in model]
            return []
        except httpx.RequestError as exc:
            logger.warning(f"Failed to fetch models from local runtime at {self.base_url}: {exc}")
            raise ProviderUnavailableError(f"Local runtime unavailable at {self.base_url}", original_error=exc)
        except Exception as exc:
            logger.warning(f"Error parsing models from local runtime: {exc}")
            raise ProviderUnavailableError(f"Error interacting with local runtime: {exc}", original_error=exc)

    def _build_payload(self, request: AIRequest, configured_model: str, default_max_tokens: int, default_temperature: float, stream: bool = False) -> dict[str, Any]:
        model_name = request.model or configured_model
        payload = {
            "model": model_name,
            "messages": [{"role": msg.role.value, "content": msg.content} for msg in request.messages],
            "temperature": request.temperature if request.temperature is not None else default_temperature,
            "max_tokens": request.max_tokens if request.max_tokens is not None else default_max_tokens,
            "stream": stream,
            "reasoning": False,
            "reasoning_effort": "none"
        }
        if request.stop_sequences:
            payload["stop"] = request.stop_sequences
        return payload, model_name

    async def generate(self, request: AIRequest, configured_model: str, default_max_tokens: int, default_temperature: float, fallback_provider_name: str) -> AIResponse:
        """Execute a generation request."""
        payload, model_name = self._build_payload(request, configured_model, default_max_tokens, default_temperature)

        try:
            start_time = time.time()
            response = await self.client.post(f"{self.base_url}/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            
            # Parse OpenAI compatible response
            choices = data.get("choices", [])
            if not choices:
                raise ProviderUnavailableError("Local runtime returned empty choices.")
            
            message = choices[0].get("message", {})
            content = message.get("content", "")
            finish_reason = choices[0].get("finish_reason", "stop")
            
            usage_data = data.get("usage", {})
            usage = TokenUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            )
            
            generation_time = time.time() - start_time
            tps = usage.completion_tokens / generation_time if generation_time > 0 and usage.completion_tokens > 0 else 0.0
            
            logger.info(
                "LOCAL_REQUEST_COMPLETED",
                extra={
                    "model": model_name,
                    "generation_time": round(generation_time, 3),
                    "tokens": usage.completion_tokens,
                    "tps": round(tps, 2)
                }
            )
            
            return AIResponse(
                content=content,
                model=model_name,
                provider=fallback_provider_name,
                usage=usage,
                finish_reason=finish_reason,
                metadata={"provider_runtime": "openai_compatible"}
            )
            
        except httpx.RequestError as exc:
            logger.error(f"Local runtime request failed: {exc}", exc_info=True)
            raise ProviderUnavailableError(f"Local runtime request failed: {exc}", original_error=exc)
        except Exception as exc:
            logger.error(f"Error processing local runtime response: {exc}", exc_info=True)
            raise ProviderUnavailableError(f"Error processing local runtime response: {exc}", original_error=exc)

    async def generate_stream(self, request: AIRequest, configured_model: str, default_max_tokens: int, default_temperature: float, fallback_provider_name: str) -> AsyncIterator[AIResponseChunk]:
        """Execute a streaming generation request."""
        payload, model_name = self._build_payload(request, configured_model, default_max_tokens, default_temperature, stream=True)
        
        start_time = time.time()
        first_token_time = None
        
        try:
            async with self.client.stream("POST", f"{self.base_url}/chat/completions", json=payload) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if not line:
                        continue
                        
                    line = line.strip()
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                            
                        try:
                            data = json.loads(data_str)
                            choices = data.get("choices", [])
                            if not choices:
                                continue
                                
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            reasoning_content = delta.get("reasoning_content", "")
                            
                            chunk_text = content or reasoning_content
                            
                            if chunk_text:
                                if first_token_time is None:
                                    first_token_time = time.time()
                                    ttft = first_token_time - start_time
                                    logger.info(
                                        "LOCAL_FIRST_TOKEN",
                                        extra={"model": model_name, "ttft": round(ttft, 3)}
                                    )
                                
                                yield AIResponseChunk(content=chunk_text, is_done=False)
                                
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse SSE line: {data_str}")
                            continue
                            
            generation_time = time.time() - start_time
            logger.info(
                "LOCAL_REQUEST_COMPLETED",
                extra={
                    "model": model_name,
                    "generation_time": round(generation_time, 3),
                    "stream": True
                }
            )
            
            yield AIResponseChunk(content="", is_done=True)
            
        except httpx.RequestError as exc:
            logger.error(f"Local runtime stream request failed: {exc}")
            raise ProviderUnavailableError(f"Local runtime stream request failed: {exc}", original_error=exc)
        except Exception as exc:
            logger.error(f"Error processing local runtime stream: {exc}")
            raise ProviderUnavailableError(f"Error processing local runtime stream: {exc}", original_error=exc)
