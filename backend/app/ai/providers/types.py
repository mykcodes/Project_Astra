"""
ASTRA AI Provider Types

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
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    success: bool
    result: str | None = None
    error: str | None = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of parameters
    risk: str = "SAFE" # Storing the risk level string


@dataclass
class AIMessage:
    role: MessageRole
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


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
class ModelInfo:
    """Information about the provider and model currently in use."""
    provider_name: str
    model_name: str
    capabilities: ModelCapabilities


@dataclass
class AIRequest:
    messages: list[AIMessage]
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    stop_sequences: list[str] | None = None
    tools: list[ToolDefinition] | None = None


@dataclass
class AIResponse:
    content: str
    model: str
    provider: str
    usage: TokenUsage
    finish_reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[ToolCall] | None = None


@dataclass
class AIResponseChunk:
    content: str
    is_done: bool = False
    usage: TokenUsage | None = None
    tool_calls: list[ToolCall] | None = None
