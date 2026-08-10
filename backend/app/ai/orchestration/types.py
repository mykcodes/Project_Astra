"""
ASTRA AI Orchestration Types

Orchestrator-level types that know about domain concepts (Tools, Knowledge, Memory).
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Source:
    """A source document or memory used to ground a response."""
    id: str
    type: str  # 'document', 'memory', 'web'
    content: str
    metadata: dict[str, Any]


@dataclass
class ToolCallResult:
    """The execution result of a tool call."""
    tool_name: str
    arguments: dict[str, Any]
    result: Any
    is_error: bool = False


@dataclass
class OrchestratorRequest:
    """Request payload to the AI orchestrator."""
    user_input: str
    conversation_id: str | None = None
    include_memory: bool = True
    include_knowledge: bool = True
    available_tools: list[str] | None = None


@dataclass
class OrchestratorResponse:
    """Final response from the AI orchestrator to the client."""
    content: str
    sources: list[Source] | None = None
    tool_calls: list[ToolCallResult] | None = None
    confidence: float | None = None  # Future: verification system output
    metadata: dict[str, Any] = field(default_factory=dict)
