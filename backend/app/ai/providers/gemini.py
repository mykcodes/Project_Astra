"""
ASTRA Gemini Provider Skeleton

Implementation of the AIProvider interface for Google's Gemini models.
"""

from collections.abc import AsyncIterator
from google import genai
from google.genai import types

from app.ai.providers.base import AIProvider
from app.ai.providers.types import (
    AIRequest,
    AIResponse,
    AIResponseChunk,
    ModelCapabilities,
    TokenUsage,
)
from app.core.config import get_settings
from app.core.logging.logger import get_logger

logger = get_logger(__name__)


class GeminiProvider(AIProvider):
    """Gemini implementation of the AIProvider interface."""

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.gemini_api_key
        self.default_model = settings.astra_ai_model
        
        if not self.api_key:
            from app.core.logging.logger import get_logger
            get_logger(__name__).warning("Gemini API Key missing. Generation will fail.")
            self.client = None
        else:
            self.client = genai.Client(api_key=self.api_key)

    async def generate(self, request: AIRequest) -> AIResponse:
        if not self.client:
            raise ValueError("Gemini API Key missing. Cannot generate.")
            
        messages = []
        system_instruction = None

        for msg in request.messages:
            if msg.role == "system":
                system_instruction = msg.content
            else:
                role = "user" if msg.role == "user" else "model"
                messages.append(types.Content(
                    role=role, 
                    parts=[types.Part.from_text(text=msg.content)]
                ))

        logger.info(f"AI_REQUEST_STARTED: model={request.model or self.default_model}")

        response = await self.client.aio.models.generate_content(
            model=request.model or self.default_model,
            contents=messages,
            config=types.GenerateContentConfig(
                temperature=request.temperature or 0.7,
                max_output_tokens=request.max_tokens,
                system_instruction=system_instruction,
            )
        )

        logger.info("AI_RESPONSE_RECEIVED")

        usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        if response.usage_metadata:
            usage = TokenUsage(
                prompt_tokens=response.usage_metadata.prompt_token_count or 0,
                completion_tokens=response.usage_metadata.candidates_token_count or 0,
                total_tokens=response.usage_metadata.total_token_count or 0,
            )

        return AIResponse(
            content=response.text or "",
            model=request.model or self.default_model,
            usage=usage,
            finish_reason="stop",
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
