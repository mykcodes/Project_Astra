from typing import Dict, Any, List
from app.environment.window.manager import window_manager
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

try:
    import win32api
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

class WindowController:
    def get_monitors(self) -> List[Dict[str, Any]]:
        """Retrieves structured monitor information."""
        if not HAS_WIN32:
            return []
            
        monitors = []
        try:
            enum = win32api.EnumDisplayMonitors()
            for index, (hmonitor, hdc, rect) in enumerate(enum):
                info = win32api.GetMonitorInfo(hmonitor)
                is_primary = info.get("Flags", 0) == win32con.MONITORINFOF_PRIMARY
                work_area = info.get("Work", (0,0,0,0))
                monitor_area = info.get("Monitor", (0,0,0,0))
                
                monitors.append({
                    "id": index,
                    "hmonitor": hmonitor,
                    "is_primary": is_primary,
                    "bounds": {
                        "left": monitor_area[0],
                        "top": monitor_area[1],
                        "right": monitor_area[2],
                        "bottom": monitor_area[3]
                    },
                    "work_area": {
                        "left": work_area[0],
                        "top": work_area[1],
                        "right": work_area[2],
                        "bottom": work_area[3]
                    }
                })
        except Exception as e:
            logger.error(f"Failed to enumerate monitors: {e}")
            
        return monitors

    def move_to_monitor(self, hwnd: int, target_monitor_index: int) -> bool:
        if not HAS_WIN32:
            return False
            
        monitors = self.get_monitors()
        if target_monitor_index < 0 or target_monitor_index >= len(monitors):
            return False
            
        target = monitors[target_monitor_index]
        work_area = target["work_area"]
        
        # We use window_manager to move it
        return window_manager.move_window(
            hwnd, 
            x=work_area["left"] + 50, 
            y=work_area["top"] + 50, 
            width=800, 
            height=600
        )

window_controller = WindowController()
