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
    INTERACTION = "INTERACTION"
    PHYSICAL_INPUT = "PHYSICAL_INPUT"

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
        
    def resolve_capability(self, capability_id: str) -> str:
        """
        Maps a semantic capability ID to an executable tool name.
        Provides a single authoritative boundary between semantic planning and execution.
        """
        mapping = {
            "browser.navigate": "execute_browser_intent",
            "browser.search": "execute_browser_intent",
            "browser.interact": "execute_browser_intent",
            "browser.click": "interact_browser",
            "browser.play": "interact_browser",
            "browser.pause": "interact_browser",
            "browser.input": "interact_browser",
            "browser.status": "execute_browser_intent",
            "desktop.open_application": "execute_application_intent",
            "desktop.focus_application": "execute_application_intent",
            "desktop.close_application": "execute_application_intent",
            "desktop.physical_input": "execute_physical_input",
            "system.generic": "generic_tool",
            "system.status": "get_system_info"
        }
        resolved = mapping.get(capability_id)
        if not resolved:
            raise ToolNotFoundError(f"Capability resolution failed: Unknown capability ID '{capability_id}'")
        return resolved

# Global registry instance
registry = ToolRegistry()
