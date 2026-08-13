from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional

class CapabilityCategory(str, Enum):
    DESKTOP = "desktop"
    SYSTEM = "system"
    BROWSER = "browser"
    FILESYSTEM = "filesystem"

@dataclass
class CapabilityDef:
    name: str
    description: str
    category: CapabilityCategory
    required_tools: List[str]
    input_requirements: List[str]
    expected_result: str
    verification_method: str
    failure_modes: List[str] = field(default_factory=list)

class CapabilityRegistry:
    def __init__(self):
        self._capabilities = {}
        self._register_defaults()
        
    def _register_defaults(self):
        self.register(CapabilityDef(
            name="desktop.execute_intent",
            description="Executes application intents like open, close, focus, minimize, restore, status.",
            category=CapabilityCategory.DESKTOP,
            required_tools=["execute_application_intent"],
            input_requirements=["intent", "application_name"],
            expected_result="Action applied to the application, returning new state.",
            verification_method="Verify application process and window state transition.",
            failure_modes=["Application not installed", "Process failed to launch", "Window not found"]
        ))
        
        self.register(CapabilityDef(
            name="system.get_info",
            description="Retrieves structured system information.",
            category=CapabilityCategory.SYSTEM,
            required_tools=["get_system_info"],
            input_requirements=["fields (optional)"],
            expected_result="Structured JSON with requested fields.",
            verification_method="Check output dictionary against requested fields.",
            failure_modes=["Access denied", "WMI failure"]
        ))
        
        self.register(CapabilityDef(
            name="browser.open_url",
            description="Opens a URL in the default browser.",
            category=CapabilityCategory.BROWSER,
            required_tools=["open_url"],
            input_requirements=["url"],
            expected_result="Browser spawned with URL.",
            verification_method="Assume success if webbrowser.open returns True.",
            failure_modes=["Invalid URL scheme", "Browser launch failed"]
        ))
        
        self.register(CapabilityDef(
            name="filesystem.list",
            description="Lists contents of a directory.",
            category=CapabilityCategory.FILESYSTEM,
            required_tools=["list_directory"],
            input_requirements=["path"],
            expected_result="List of files and directories.",
            verification_method="Validate returned dictionary.",
            failure_modes=["Path not found", "Path outside allowed root"]
        ))

        self.register(CapabilityDef(
            name="filesystem.search",
            description="Searches for files by name.",
            category=CapabilityCategory.FILESYSTEM,
            required_tools=["search_files"],
            input_requirements=["query", "path (optional)"],
            expected_result="List of matching file paths.",
            verification_method="Validate list of strings.",
            failure_modes=["Path not found", "Path outside allowed root"]
        ))

        self.register(CapabilityDef(
            name="filesystem.create_folder",
            description="Creates a new folder.",
            category=CapabilityCategory.FILESYSTEM,
            required_tools=["create_folder"],
            input_requirements=["path"],
            expected_result="Folder created.",
            verification_method="Verify directory exists after creation.",
            failure_modes=["Path already exists", "Path outside allowed root", "Permission denied"]
        ))

    def register(self, capability: CapabilityDef):
        self._capabilities[capability.name] = capability
        
    def get(self, name: str) -> Optional[CapabilityDef]:
        return self._capabilities.get(name)
        
    def list_all(self) -> List[CapabilityDef]:
        return list(self._capabilities.values())

capability_registry = CapabilityRegistry()
