"""ASTRA Tool System Types."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = True


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: list[ToolParameter]
    # The actual python function to call
    handler: Callable[..., Any]
    # Required permissions to execute
    required_permissions: list[str]


@dataclass
class ToolResult:
    success: bool
    data: Any
    error_message: str | None = None
