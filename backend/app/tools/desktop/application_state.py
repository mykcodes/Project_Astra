import dataclasses
from enum import Enum
from typing import List, Optional, Set

class ApplicationState(str, Enum):
    UNKNOWN = "UNKNOWN"
    NOT_INSTALLED = "NOT_INSTALLED"
    INSTALLED_NOT_RUNNING = "INSTALLED_NOT_RUNNING"
    RUNNING_NO_WINDOW = "RUNNING_NO_WINDOW"
    RUNNING_MINIMIZED = "RUNNING_MINIMIZED"
    RUNNING_BACKGROUND = "RUNNING_BACKGROUND"
    RUNNING_FOREGROUND = "RUNNING_FOREGROUND"

class LaunchType(str, Enum):
    WIN32 = "WIN32"
    UWP = "UWP"
    URL = "URL"

class ApplicationIntent(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    FOCUS = "FOCUS"
    MINIMIZE = "MINIMIZE"
    RESTORE = "RESTORE"
    STATUS = "STATUS"
    RESTART = "RESTART"

@dataclasses.dataclass
class ApplicationDescriptor:
    canonical_name: str
    normalized_name: str
    display_name: str
    installed: bool = False
    aliases: List[str] = dataclasses.field(default_factory=list)
    launch_target: Optional[str] = None
    launch_type: Optional[LaunchType] = None
    executable_path: Optional[str] = None
    executable_name: Optional[str] = None
    expected_process_names: Set[str] = dataclasses.field(default_factory=set)
    package_family_name: Optional[str] = None
    app_user_model_id: Optional[str] = None
    publisher: Optional[str] = None
    install_location: Optional[str] = None
    discovery_source: Optional[str] = None
    confidence: float = 0.0
    verified: bool = False
    ambiguous: bool = False

    def to_dict(self):
        return {
            "canonical_name": self.canonical_name,
            "normalized_name": self.normalized_name,
            "display_name": self.display_name,
            "installed": self.installed,
            "aliases": self.aliases,
            "launch_target": self.launch_target,
            "launch_type": self.launch_type.value if self.launch_type else None,
            "executable_path": self.executable_path,
            "executable_name": self.executable_name,
            "expected_process_names": list(self.expected_process_names),
            "package_family_name": self.package_family_name,
            "app_user_model_id": self.app_user_model_id,
            "publisher": self.publisher,
            "install_location": self.install_location,
            "discovery_source": self.discovery_source,
            "confidence": self.confidence,
            "verified": self.verified,
            "ambiguous": self.ambiguous
        }

@dataclasses.dataclass
class ApplicationStatus:
    descriptor: ApplicationDescriptor
    state: ApplicationState = ApplicationState.UNKNOWN
    pids: List[int] = dataclasses.field(default_factory=list)
    windows: List[dict] = dataclasses.field(default_factory=list)
    
    def to_dict(self):
        return {
            "application": self.descriptor.canonical_name,
            "state": self.state.value,
            "installed": self.descriptor.installed,
            "running": self.state not in (ApplicationState.UNKNOWN, ApplicationState.NOT_INSTALLED, ApplicationState.INSTALLED_NOT_RUNNING),
            "window_found": self.state in (ApplicationState.RUNNING_MINIMIZED, ApplicationState.RUNNING_BACKGROUND, ApplicationState.RUNNING_FOREGROUND),
            "foreground": self.state == ApplicationState.RUNNING_FOREGROUND,
            "pids": self.pids,
            "launch_type": self.descriptor.launch_type.value if self.descriptor.launch_type else None,
            "discovery_source": self.descriptor.discovery_source
        }
