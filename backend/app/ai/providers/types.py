"""
ASTRA AI Provider Provider Types

Provider-level types that have no knowledge of domain concepts like
Memory, Tools, or Conversations. These represent the pure contract
with the LLM API.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class AIMessage:
    role: MessageRole
    content: str


@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class ModelCapabilities:
    max_context_tokens: int
    supports_streaming: bool
    supports_function_calling: bool
    supports_vision: bool


@dataclass
class AIRequest:
    messages: list[AIMessage]
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    stop_sequences: list[str] | None = None


@dataclass
class AIResponse:
    content: str
    model: str
    usage: TokenUsage
    finish_reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class AIResponseChunk:
    content: str
    is_done: bool = False
    usage: TokenUsage | None = None
