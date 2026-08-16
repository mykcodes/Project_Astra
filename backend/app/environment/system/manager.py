import platform
import psutil
import subprocess
import json
import dataclasses
from typing import List, Optional
from app.core.logging.logger import get_logger
from app.environment.models import (
    SystemEntity, CPUEntity, GPUEntity, RAMEntity, 
    StorageDriveEntity, DisplayEntity, BatteryEntity, NetworkEntity
)

logger = get_logger(__name__)

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

    def get_os_info(self) -> dict:
        script = "Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, OSArchitecture | ConvertTo-Json"
        data = self._run_powershell(script)
        
        return {
            "os": platform.system(),
            "os_version": platform.version(),
            "os_build": data.get("BuildNumber", "unknown"),
            "machine_architecture": platform.machine(),
            "edition": data.get("Caption", platform.release()).strip() if data.get("Caption") else "unknown"
        }

    def get_device_info(self) -> dict:
        script = """
        $cs = Get-CimInstance Win32_ComputerSystem
        @{
            Manufacturer = $cs.Manufacturer
            Model = $cs.Model
            DeviceName = $cs.Name
        } | ConvertTo-Json
        """
        data = self._run_powershell(script)
        
        return {
            "manufacturer": data.get("Manufacturer", "unknown"),
            "model": data.get("Model", "unknown"),
            "device_name": data.get("DeviceName", "unknown"),
            "serial_availability": False  # Usually requires admin rights
        }

    def get_cpu_info(self) -> CPUEntity:
        script = "Get-CimInstance Win32_Processor | Select-Object Name, Manufacturer, MaxClockSpeed | ConvertTo-Json"
        data = self._run_powershell(script)
        if isinstance(data, list) and len(data) > 0:
            data = data[0]

        freq = psutil.cpu_freq()
        
        return CPUEntity(
            brand=data.get("Manufacturer", "unknown"),
            model=data.get("Name", platform.processor() or "unknown"),
            cores=psutil.cpu_count(logical=False) or 0,
            logical_processors=psutil.cpu_count(logical=True) or 0,
            frequency=int(data.get("MaxClockSpeed")) if data.get("MaxClockSpeed") else (int(freq.max) if freq else None),
            usage=psutil.cpu_percent(interval=0.1)
        )

    def get_ram_info(self) -> RAMEntity:
        mem = psutil.virtual_memory()
        return RAMEntity(
            total=round(mem.total / (1024**3), 2),
            available=round(mem.available / (1024**3), 2),
            used=round(mem.used / (1024**3), 2),
            percentage=mem.percent
        )

    def get_gpu_info(self) -> List[GPUEntity]:
        script = "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterCompatibility, AdapterRAM, DriverVersion | ConvertTo-Json"
        data = self._run_powershell(script)
        if isinstance(data, dict):
            data = [data]
            
        gpus = []
        for item in (data or []):
            if item.get("Name"):
                ram = item.get("AdapterRAM")
                vram_mb = int(ram) // (1024**2) if ram else None
                gpus.append(GPUEntity(
                    name=item.get("Name"),
                    vram=vram_mb,
                    driver_information=item.get("DriverVersion", "unknown"),
                    usage=None  # Hard to get reliably without admin/external tools
                ))
        return gpus

    def get_storage_info(self) -> List[StorageDriveEntity]:
        storage = []
        for part in psutil.disk_partitions(all=False):
            if part.fstype:
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    storage.append(StorageDriveEntity(
                        device=part.device,
                        capacity=round(usage.total / (1024**3), 2),
                        used=round(usage.used / (1024**3), 2),
                        free=round(usage.free / (1024**3), 2)
                    ))
                except PermissionError:
                    continue
        return storage

    def get_network_info(self) -> List[NetworkEntity]:
        network = []
        stats = psutil.net_if_stats()
        
        for interface_name, stat in stats.items():
            if stat.isup:
                network.append(NetworkEntity(
                    interface=interface_name,
                    is_up=True
                ))
        return network

    def get_battery_info(self) -> BatteryEntity:
        battery = psutil.sensors_battery()
        if battery:
            return BatteryEntity(
                percentage=round(battery.percent, 2),
                charging=battery.power_plugged
            )
        return BatteryEntity(percentage=None, charging=None)
        
    def get_display_info(self) -> DisplayEntity:
        script = "Get-CimInstance Win32_VideoController | Select-Object CurrentHorizontalResolution, CurrentVerticalResolution | ConvertTo-Json"
        data = self._run_powershell(script)
        if isinstance(data, dict):
            data = [data]
        
        monitor_count = 0
        primary_res = "unknown"
        if data and len(data) > 0 and data[0].get("CurrentHorizontalResolution"):
            monitor_count = len(data)
            primary_res = f"{data[0].get('CurrentHorizontalResolution')}x{data[0].get('CurrentVerticalResolution')}"
            
        return DisplayEntity(
            monitor_count=monitor_count or 1,
            primary_resolution=primary_res,
            primary_monitor=True
        )

    def get_system_entity(self) -> SystemEntity:
        os_info = self.get_os_info()
        device_info = self.get_device_info()
        
        return SystemEntity(
            os=os_info.get("os"),
            os_version=os_info.get("os_version"),
            os_build=os_info.get("os_build"),
            machine_architecture=os_info.get("machine_architecture"),
            manufacturer=device_info.get("manufacturer"),
            model=device_info.get("model"),
            device_name=device_info.get("device_name"),
            serial_availability=device_info.get("serial_availability"),
            cpu=self.get_cpu_info(),
            gpu=self.get_gpu_info(),
            ram=self.get_ram_info(),
            storage=self.get_storage_info(),
            battery=self.get_battery_info(),
            display=self.get_display_info(),
            network=self.get_network_info()
        )

    def get_selected_fields(self, sections: Optional[List[str]] = None) -> dict:
        entity = self.get_system_entity()
        data = dataclasses.asdict(entity)
        if not sections:
            return data
        return {k: v for k, v in data.items() if k in sections}

system_engine = SystemInformationEngine()
