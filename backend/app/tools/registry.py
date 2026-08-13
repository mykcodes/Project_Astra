from enum import Enum
from typing import Dict, List, Set

from app.tools.base import Tool
from app.tools.errors import ToolNotFoundError

class Capability(str, Enum):
    SYSTEM_INFORMATION = "SYSTEM_INFORMATION"
    APPLICATION_DISCOVERY = "APPLICATION_DISCOVERY"
    APPLICATION_LAUNCH = "APPLICATION_LAUNCH"
    APPLICATION_CLOSE = "APPLICATION_CLOSE"
    APPLICATION_FOCUS = "APPLICATION_FOCUS"
    APPLICATION_STATUS = "APPLICATION_STATUS"
    PROCESS_INSPECTION = "PROCESS_INSPECTION"
    WINDOW_INSPECTION = "WINDOW_INSPECTION"
    FILESYSTEM_DISCOVERY = "FILESYSTEM_DISCOVERY"
    FILESYSTEM_SEARCH = "FILESYSTEM_SEARCH"
    URL_OPEN = "URL_OPEN"
    BROWSER_CONTROL = "BROWSER_CONTROL"
    FILE_CREATION = "FILE_CREATION"
    FILE_MODIFICATION = "FILE_MODIFICATION"
    SYSTEM_TIME = "SYSTEM_TIME"

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._capabilities: Set[Capability] = set()

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool
        if hasattr(tool, "capabilities"):
            for cap in tool.capabilities:
                self._capabilities.add(cap)

    def unregister(self, name: str) -> None:
        if name in self._tools:
            tool = self._tools[name]
            del self._tools[name]
            # We would technically need to rebuild capabilities, but unregistering is rare at runtime
            self._rebuild_capabilities()

    def _rebuild_capabilities(self):
        self._capabilities.clear()
        for tool in self._tools.values():
            if hasattr(tool, "capabilities"):
                for cap in tool.capabilities:
                    self._capabilities.add(cap)

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolNotFoundError(name)
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())
        
    def get_capabilities(self) -> List[str]:
        return sorted([c.value for c in self._capabilities])

# Global registry instance
registry = ToolRegistry()
