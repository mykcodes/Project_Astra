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
)
from app.core.config import get_settings


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
        for msg in request.messages:
            if msg.role == "system":
                # For Gemini, system instructions are best handled via system_instruction config,
                # but for simplicity in this proxy loop we can prepend as a user/model interaction
                # or just use types.Content(role="user", ...)
                messages.append(types.Content(
                    role="user", 
                    parts=[types.Part.from_text(text=msg.content)]
                ))
                messages.append(types.Content(
                    role="model", 
                    parts=[types.Part.from_text(text="I understand the system instructions.")]
                ))
            else:
                role = "user" if msg.role == "user" else "model"
                messages.append(types.Content(
                    role=role, 
                    parts=[types.Part.from_text(text=msg.content)]
                ))

        response = await self.client.aio.models.generate_content(
            model=request.model or self.default_model,
            contents=messages,
            config=types.GenerateContentConfig(
                temperature=request.temperature or 0.7,
                max_output_tokens=request.max_tokens,
            )
        )

        return AIResponse(
            content=response.text,
            role="assistant",
            finish_reason="stop",
            metadata={"model": request.model or self.default_model}
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
