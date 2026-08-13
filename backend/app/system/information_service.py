import platform
import psutil
import subprocess
import json
import dataclasses
from typing import List, Optional
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

@dataclasses.dataclass
class OSInfo:
    operating_system: str
    edition: Optional[str]
    version: str
    build: Optional[str]
    architecture: str

@dataclasses.dataclass
class DeviceInfo:
    manufacturer: Optional[str]
    model: Optional[str]
    product_name: Optional[str]
    system_sku: Optional[str]
    bios_vendor: Optional[str]
    bios_version: Optional[str]

@dataclasses.dataclass
class CPUInfo:
    manufacturer: Optional[str]
    model: str
    architecture: str
    physical_cores: int
    logical_processors: int
    base_frequency_mhz: Optional[int]
    current_frequency_mhz: Optional[int]

@dataclasses.dataclass
class MemoryInfo:
    total_gb: float
    available_gb: float
    used_gb: float
    utilization_percentage: float

@dataclasses.dataclass
class GPUInfo:
    name: str
    vendor: Optional[str]
    vram_mb: Optional[int]
    driver_version: Optional[str]

@dataclasses.dataclass
class StorageInfo:
    device: str
    mountpoint: str
    filesystem: str
    total_gb: float
    used_gb: float
    free_gb: float

@dataclasses.dataclass
class NetworkInfo:
    interface: str
    ip_address: Optional[str]
    mac_address: Optional[str]
    is_up: bool

@dataclasses.dataclass
class BatteryInfo:
    present: bool
    charging: Optional[bool]
    percentage: Optional[float]

@dataclasses.dataclass
class MachineProfile:
    os: OSInfo
    device: DeviceInfo
    cpu: CPUInfo
    memory: MemoryInfo
    gpu: List[GPUInfo]
    storage: List[StorageInfo]
    network: List[NetworkInfo]
    battery: BatteryInfo

    def to_dict(self):
        return dataclasses.asdict(self)

class SystemInformationEngine:
    def _run_powershell(self, script: str) -> dict:
        try:
            process = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False
            )
            stdout, _ = process.communicate(timeout=5)
            if stdout.strip():
                try:
                    return json.loads(stdout)
                except json.JSONDecodeError:
                    return {}
            return {}
        except Exception as e:
            logger.warning(f"PowerShell execution failed: {e}")
            return {}

    def get_os_info(self) -> OSInfo:
        script = "Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, OSArchitecture | ConvertTo-Json"
        data = self._run_powershell(script)
        
        return OSInfo(
            operating_system=platform.system(),
            edition=data.get("Caption", platform.release()).strip(),
            version=platform.version(),
            build=data.get("BuildNumber"),
            architecture=platform.machine()
        )

    def get_device_info(self) -> DeviceInfo:
        script = """
        $cs = Get-CimInstance Win32_ComputerSystem
        $bios = Get-CimInstance Win32_BIOS
        @{
            Manufacturer = $cs.Manufacturer
            Model = $cs.Model
            SystemSKU = $cs.SystemSKUNumber
            BIOSVendor = $bios.Manufacturer
            BIOSVersion = $bios.SMBIOSBIOSVersion
        } | ConvertTo-Json
        """
        data = self._run_powershell(script)
        
        return DeviceInfo(
            manufacturer=data.get("Manufacturer"),
            model=data.get("Model"),
            product_name=data.get("Model"),
            system_sku=data.get("SystemSKU"),
            bios_vendor=data.get("BIOSVendor"),
            bios_version=data.get("BIOSVersion")
        )

    def get_cpu_info(self) -> CPUInfo:
        script = "Get-CimInstance Win32_Processor | Select-Object Name, Manufacturer, MaxClockSpeed | ConvertTo-Json"
        data = self._run_powershell(script)
        if isinstance(data, list) and len(data) > 0:
            data = data[0]

        freq = psutil.cpu_freq()
        
        return CPUInfo(
            manufacturer=data.get("Manufacturer"),
            model=data.get("Name", platform.processor()),
            architecture=platform.machine(),
            physical_cores=psutil.cpu_count(logical=False) or 0,
            logical_processors=psutil.cpu_count(logical=True) or 0,
            base_frequency_mhz=int(data.get("MaxClockSpeed")) if data.get("MaxClockSpeed") else (int(freq.max) if freq else None),
            current_frequency_mhz=int(freq.current) if freq else None
        )

    def get_memory_info(self) -> MemoryInfo:
        mem = psutil.virtual_memory()
        return MemoryInfo(
            total_gb=round(mem.total / (1024**3), 2),
            available_gb=round(mem.available / (1024**3), 2),
            used_gb=round(mem.used / (1024**3), 2),
            utilization_percentage=mem.percent
        )

    def get_gpu_info(self) -> List[GPUInfo]:
        script = "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterCompatibility, AdapterRAM, DriverVersion | ConvertTo-Json"
        data = self._run_powershell(script)
        if isinstance(data, dict):
            data = [data]
            
        gpus = []
        for item in (data or []):
            if item.get("Name"):
                ram = item.get("AdapterRAM")
                vram_mb = int(ram) // (1024**2) if ram else None
                gpus.append(GPUInfo(
                    name=item.get("Name"),
                    vendor=item.get("AdapterCompatibility"),
                    vram_mb=vram_mb,
                    driver_version=item.get("DriverVersion")
                ))
        return gpus

    def get_storage_info(self) -> List[StorageInfo]:
        storage = []
        for part in psutil.disk_partitions(all=False):
            if part.fstype:
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    storage.append(StorageInfo(
                        device=part.device,
                        mountpoint=part.mountpoint,
                        filesystem=part.fstype,
                        total_gb=round(usage.total / (1024**3), 2),
                        used_gb=round(usage.used / (1024**3), 2),
                        free_gb=round(usage.free / (1024**3), 2)
                    ))
                except PermissionError:
                    continue
        return storage

    def get_network_info(self) -> List[NetworkInfo]:
        network = []
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        
        for interface_name, stat in stats.items():
            if not stat.isup:
                continue
            
            ip = None
            mac = None
            if interface_name in addrs:
                for addr in addrs[interface_name]:
                    if addr.family == 2:  # AF_INET
                        ip = addr.address
                    elif addr.family == -1 or addr.family == 23:  # MAC address
                        mac = addr.address
                        
            if ip and not ip.startswith("127."):
                network.append(NetworkInfo(
                    interface=interface_name,
                    ip_address=ip,
                    mac_address=mac,
                    is_up=stat.isup
                ))
        return network

    def get_battery_info(self) -> BatteryInfo:
        battery = psutil.sensors_battery()
        if battery:
            return BatteryInfo(
                present=True,
                charging=battery.power_plugged,
                percentage=round(battery.percent, 2)
            )
        return BatteryInfo(present=False, charging=None, percentage=None)

    def get_machine_profile(self) -> MachineProfile:
        return MachineProfile(
            os=self.get_os_info(),
            device=self.get_device_info(),
            cpu=self.get_cpu_info(),
            memory=self.get_memory_info(),
            gpu=self.get_gpu_info(),
            storage=self.get_storage_info(),
            network=self.get_network_info(),
            battery=self.get_battery_info()
        )
        
    def get_selected_fields(self, sections: List[str]) -> dict:
        result = {}
        if not sections or "os" in sections:
            result["os"] = dataclasses.asdict(self.get_os_info())
        if not sections or "device" in sections or "identity" in sections:
            result["device"] = dataclasses.asdict(self.get_device_info())
        if not sections or "cpu" in sections:
            result["cpu"] = dataclasses.asdict(self.get_cpu_info())
        if not sections or "memory" in sections:
            result["memory"] = dataclasses.asdict(self.get_memory_info())
        if not sections or "gpu" in sections:
            result["gpu"] = [dataclasses.asdict(g) for g in self.get_gpu_info()]
        if not sections or "storage" in sections:
            result["storage"] = [dataclasses.asdict(s) for s in self.get_storage_info()]
        if not sections or "network" in sections:
            result["network"] = [dataclasses.asdict(n) for n in self.get_network_info()]
        if not sections or "battery" in sections:
            result["battery"] = dataclasses.asdict(self.get_battery_info())
            
        return result

system_engine = SystemInformationEngine()
