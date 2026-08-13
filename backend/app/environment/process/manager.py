import os
import psutil
from typing import List, Set, Dict, Optional
from app.core.logging.logger import get_logger
from app.environment.models import ProcessEntity

logger = get_logger(__name__)

class ProcessManager:
    @staticmethod
    def _create_process_entity(proc: psutil.Process) -> Optional[ProcessEntity]:
        try:
            with proc.oneshot():
                return ProcessEntity(
                    pid=proc.pid,
                    parent_pid=proc.ppid(),
                    name=proc.name(),
                    executable_path=proc.exe() if proc.pid != 0 else None,
                    command_line=proc.cmdline() if proc.pid != 0 else None,
                    status=proc.status(),
                    create_time=proc.create_time(),
                    children=[]
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None

    @staticmethod
    def get_process_tree(root_pid: int) -> Optional[ProcessEntity]:
        """Returns a process and all its children as a tree."""
        try:
            root_proc = psutil.Process(root_pid)
            root_entity = ProcessManager._create_process_entity(root_proc)
            if not root_entity:
                return None
                
            children = root_proc.children(recursive=True)
            child_entities = {}
            
            for child in children:
                ce = ProcessManager._create_process_entity(child)
                if ce:
                    child_entities[ce.pid] = ce
                    
            # Build tree structure for children
            for pid, ce in child_entities.items():
                if ce.parent_pid == root_entity.pid:
                    root_entity.children.append(ce)
                elif ce.parent_pid in child_entities:
                    child_entities[ce.parent_pid].children.append(ce)
                    
            return root_entity
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    @staticmethod
    def get_pids_for_names_and_paths(expected_names: Set[str], target_path: Optional[str] = None, package_family_name: Optional[str] = None) -> List[int]:
        pids = []
        expected_names_lower = {name.lower() for name in expected_names} if expected_names else set()
        target_path_lower = os.path.normpath(target_path).lower() if target_path else None
        
        fallback_name = None
        if target_path_lower:
            fallback_name = os.path.basename(target_path_lower)
            
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                proc_name = proc.info.get('name')
                proc_exe = proc.info.get('exe')
                
                if not proc_name:
                    continue
                    
                proc_name_lower = proc_name.lower()
                
                # Match by expected names
                if expected_names_lower and proc_name_lower in expected_names_lower:
                    pids.append(proc.info['pid'])
                    continue
                    
                # Match by exact executable path
                if target_path_lower and proc_exe:
                    proc_exe_norm = os.path.normpath(proc_exe).lower()
                    if proc_exe_norm == target_path_lower:
                        pids.append(proc.info['pid'])
                        continue
                        
                # Match by fallback name
                if fallback_name and not expected_names_lower:
                    if proc_name_lower == fallback_name:
                        # Avoid matching generic names accidentally
                        if proc_name_lower not in ("update.exe", "launcher.exe", "setup.exe", "cmd.exe", "powershell.exe"):
                            pids.append(proc.info['pid'])
                            continue

                # Match by package family name (UWP)
                if package_family_name and proc_exe:
                    if package_family_name.lower() in proc_exe.lower():
                        pids.append(proc.info['pid'])
                        continue
                        
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
                
        # Resolve children
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
    def get_process_details(pid: int) -> Optional[ProcessEntity]:
        try:
            p = psutil.Process(pid)
            return ProcessManager._create_process_entity(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None

    @staticmethod
    def terminate_process_tree(pid: int) -> bool:
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            parent.terminate()
            
            # Wait for processes to exit
            psutil.wait_procs(children + [parent], timeout=3)
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            return False

process_manager = ProcessManager()
