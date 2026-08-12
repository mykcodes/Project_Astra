from typing import Dict, List

from app.tools.base import Tool
from app.tools.errors import ToolNotFoundError

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        if name in self._tools:
            del self._tools[name]

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolNotFoundError(name)
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

# Global registry instance
registry = ToolRegistry()
