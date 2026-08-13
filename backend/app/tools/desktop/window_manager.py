import ctypes
from typing import List, Tuple, Dict
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

# Constants
SW_RESTORE = 9
WM_CLOSE = 0x0010
GW_OWNER = 4

class WindowManager:
    def __init__(self):
        try:
            if hasattr(ctypes, "windll"):
                self.user32 = ctypes.windll.user32
            else:
                self.user32 = None
        except Exception:
            self.user32 = None

    def get_windows_for_pids(self, pids: List[int]) -> List[Dict]:
        """
        Returns a list of structured window dictionaries for matching PIDs.
        Prioritizes top-level visible windows but relaxes constraints to capture 
        Electron/UWP apps correctly.
        """
        if not self.user32 or not pids:
            return []

        windows = []
        pid_set = set(pids)
        foreground_hwnd = self.user32.GetForegroundWindow()

        def callback(hwnd, extra):
            window_pid = ctypes.c_ulong(0)
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            
            if window_pid.value in pid_set:
                is_visible = bool(self.user32.IsWindowVisible(hwnd))
                is_minimized = bool(self.user32.IsIconic(hwnd))
                is_foreground = (hwnd == foreground_hwnd)
                
                # Retrieve Title
                length = self.user32.GetWindowTextLengthW(hwnd)
                title = ""
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    self.user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    
                # We want windows that have titles, OR are visible, OR are foreground.
                # UWP apps often have a visible wrapper window.
                # We loosen the strict GW_OWNER == 0 constraint.
                
                if title or is_visible or is_foreground:
                    # Give preference points to help select the "best" window later
                    score = 0
                    if is_visible: score += 10
                    if is_foreground: score += 20
                    if not self.user32.GetWindow(hwnd, GW_OWNER): score += 5
                    if title: score += 5
                    if is_minimized: score += 5
                    
                    if score > 0:
                        windows.append({
                            "hwnd": hwnd,
                            "title": title,
                            "is_visible": is_visible,
                            "is_minimized": is_minimized,
                            "is_foreground": is_foreground,
                            "score": score
                        })
                        
            return True

        try:
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
            self.user32.EnumWindows(WNDENUMPROC(callback), 0)
        except Exception as e:
            logger.warning(f"Error enumerating windows: {e}")
            
        # Sort windows by score descending so the "main" window is likely first
        windows.sort(key=lambda x: x["score"], reverse=True)
        return windows

    def is_minimized(self, hwnd: int) -> bool:
        if not self.user32:
            return False
        return bool(self.user32.IsIconic(hwnd))

    def restore_and_focus(self, hwnd: int) -> bool:
        if not self.user32:
            return False
            
        try:
            if self.is_minimized(hwnd):
                self.user32.ShowWindow(hwnd, SW_RESTORE)
            self.user32.SetForegroundWindow(hwnd)
            return True
        except Exception as e:
            logger.warning(f"Failed to focus window: {e}")
            return False

    def minimize_window(self, hwnd: int) -> bool:
        if not self.user32:
            return False
        try:
            # SW_MINIMIZE = 6
            self.user32.ShowWindow(hwnd, 6)
            return True
        except Exception:
            return False

    def restore_window(self, hwnd: int) -> bool:
        if not self.user32:
            return False
        try:
            self.user32.ShowWindow(hwnd, SW_RESTORE)
            return True
        except Exception:
            return False

    def close_window(self, hwnd: int) -> bool:
        if not self.user32:
            return False
        try:
            # For modern UWP or complex apps, WM_CLOSE is standard, 
            # though some apps minimize to tray instead.
            self.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return True
        except Exception as e:
            logger.warning(f"Failed to close window: {e}")
            return False

window_manager = WindowManager()
