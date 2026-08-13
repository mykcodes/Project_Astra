from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Set

class ApplicationType(str, Enum):
    WIN32 = "WIN32"
    UWP = "UWP"
    STORE = "STORE"
    PWA = "PWA"
    ELECTRON = "ELECTRON"
    GAME = "GAME"
    WEB = "WEB"
    UNKNOWN = "UNKNOWN"

class ApplicationState(str, Enum):
    UNKNOWN = "UNKNOWN"
    NOT_INSTALLED = "NOT_INSTALLED"
    INSTALLED_NOT_RUNNING = "INSTALLED_NOT_RUNNING"
    RUNNING_BACKGROUND = "RUNNING_BACKGROUND"
    RUNNING_NO_WINDOW = "RUNNING_NO_WINDOW"
    RUNNING_MINIMIZED = "RUNNING_MINIMIZED"
    RUNNING_FOREGROUND = "RUNNING_FOREGROUND"

@dataclass
class ApplicationEntity:
    canonical_name: str
    display_name: str
    normalized_name: str
    application_type: ApplicationType = ApplicationType.UNKNOWN
    installed: bool = False
    launch_target: Optional[str] = None
    executable_path: Optional[str] = None
    process_names: Set[str] = field(default_factory=set)
    package_family_name: Optional[str] = None
    app_user_model_id: Optional[str] = None
    discovery_source: str = "UNKNOWN"
    aliases: Set[str] = field(default_factory=set)
    confidence: float = 0.0

@dataclass
class ProcessEntity:
    pid: int
    parent_pid: Optional[int]
    name: str
    executable_path: Optional[str]
    command_line: Optional[List[str]]
    status: str
    create_time: float
    children: List['ProcessEntity'] = field(default_factory=list)

@dataclass
class WindowEntity:
    hwnd: int
    title: str
    pid: int
    process_name: Optional[str]
    visible: bool
    minimized: bool
    foreground: bool
    fullscreen: bool
    monitor: Optional[int]
    x: int
    y: int
    width: int
    height: int

@dataclass
class FileEntity:
    path: str
    name: str
    extension: str
    size: int
    modified_time: float
    is_directory: bool
    is_executable: bool

@dataclass
class CPUEntity:
    brand: Optional[str] = None
    model: Optional[str] = None
    cores: Optional[int] = None
    logical_processors: Optional[int] = None
    frequency: Optional[int] = None
    usage: Optional[float] = None

@dataclass
class GPUEntity:
    name: Optional[str] = None
    vram: Optional[int] = None
    driver_information: Optional[str] = None
    usage: Optional[float] = None

@dataclass
class RAMEntity:
    total: Optional[float] = None
    available: Optional[float] = None
    used: Optional[float] = None
    percentage: Optional[float] = None

@dataclass
class StorageDriveEntity:
    device: str
    capacity: float
    free: float
    used: float

@dataclass
class DisplayEntity:
    monitor_count: int
    primary_resolution: Optional[str] = None
    primary_monitor: bool = True

@dataclass
class BatteryEntity:
    percentage: Optional[float] = None
    charging: Optional[bool] = None

@dataclass
class NetworkEntity:
    interface: str
    is_up: bool

@dataclass
class SystemEntity:
    os: Optional[str] = None
    os_version: Optional[str] = None
    os_build: Optional[str] = None
    machine_architecture: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    device_name: Optional[str] = None
    serial_availability: Optional[bool] = None
    cpu: CPUEntity = field(default_factory=CPUEntity)
    gpu: List[GPUEntity] = field(default_factory=list)
    ram: RAMEntity = field(default_factory=RAMEntity)
    storage: List[StorageDriveEntity] = field(default_factory=list)
    battery: BatteryEntity = field(default_factory=BatteryEntity)
    display: DisplayEntity = field(default_factory=lambda: DisplayEntity(monitor_count=1))
    network: List[NetworkEntity] = field(default_factory=list)
