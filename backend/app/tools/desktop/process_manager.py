import os
import psutil
from typing import List, Set
from app.core.logging.logger import get_logger
from app.tools.desktop.application_state import ApplicationDescriptor

logger = get_logger(__name__)

class ProcessManager:
    @staticmethod
    def get_pids_for_descriptor(descriptor: ApplicationDescriptor) -> List[int]:
        if not descriptor:
            return []
            
        pids = []
        target_path = None
        if descriptor.executable_path:
            target_path = os.path.normpath(descriptor.executable_path).lower()
            
        expected_names = {name.lower() for name in descriptor.expected_process_names} if descriptor.expected_process_names else set()
        
        # If it's a UWP app, we often match by process name because the executable is inside WindowsApps
        # If it has expected_process_names, we match against those.
        # Otherwise we match against the executable_path or executable_name
        
        fallback_name = None
        if descriptor.executable_name:
            fallback_name = descriptor.executable_name.lower()
        elif target_path:
            fallback_name = os.path.basename(target_path)
            
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                proc_name = proc.info.get('name')
                proc_exe = proc.info.get('exe')
                
                if not proc_name:
                    continue
                    
                proc_name_lower = proc_name.lower()
                
                # 1. Match by expected process names (most reliable for complex apps)
                if expected_names and proc_name_lower in expected_names:
                    pids.append(proc.info['pid'])
                    continue
                    
                # 2. Match by exact executable path
                if target_path and proc_exe:
                    proc_exe_norm = os.path.normpath(proc_exe).lower()
                    if proc_exe_norm == target_path:
                        pids.append(proc.info['pid'])
                        continue
                        
                if fallback_name and not expected_names:
                    if proc_name_lower == fallback_name:
                        # For safety, avoid false positives on common names like "update.exe"
                        if proc_name_lower not in ("update.exe", "launcher.exe", "setup.exe", "cmd.exe", "powershell.exe"):
                            pids.append(proc.info['pid'])
                            continue

                # 4. Match UWP by package family name in the executable path
                if descriptor.package_family_name and proc_exe:
                    if descriptor.package_family_name.lower() in proc_exe.lower():
                        pids.append(proc.info['pid'])
                        continue
                        
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
                
        # Find child processes of any identified PIDs to capture renderer/worker processes
        final_pids = set(pids)
        for pid in pids:
            try:
                parent = psutil.Process(pid)
                children = parent.children(recursive=True)
                for child in children:
                    final_pids.add(child.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
                
        return list(final_pids)
        
    @staticmethod
    def is_process_running(pid: int) -> bool:
        return psutil.pid_exists(pid)
        
    @staticmethod
    def get_process_details(pid: int) -> dict:
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                return {
                    "pid": p.pid,
                    "name": p.name(),
                    "exe": p.exe(),
                    "status": p.status(),
                    "create_time": p.create_time(),
                    "cpu_percent": p.cpu_percent(),
                    "memory_mb": round(p.memory_info().rss / (1024 * 1024), 2),
                    "cmdline": p.cmdline() if p.pid != 0 else []
                }
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return {}

process_manager = ProcessManager()
