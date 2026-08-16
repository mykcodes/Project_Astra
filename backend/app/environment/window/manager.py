import ctypes
from typing import List, Dict, Optional
from app.core.logging.logger import get_logger
from app.environment.models import WindowEntity

logger = get_logger(__name__)

# Constants
SW_RESTORE = 9
SW_MINIMIZE = 6
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

    def get_windows_for_pids(self, pids: List[int]) -> List[WindowEntity]:
        """
        Returns a list of structured WindowEntity objects for matching PIDs.
        Prioritizes top-level visible windows but relaxes constraints to capture 
        Electron/UWP apps correctly.
        """
        if not self.user32 or not pids:
            return []

        windows = []
        pid_set = set(pids)
        foreground_hwnd = self.user32.GetForegroundWindow()

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long),
                        ("top", ctypes.c_long),
                        ("right", ctypes.c_long),
                        ("bottom", ctypes.c_long)]

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
                if title or is_visible or is_foreground:
                    rect = RECT()
                    self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    width = rect.right - rect.left
                    height = rect.bottom - rect.top
                    
                    # Owner/Parent
                    owner = self.user32.GetWindow(hwnd, GW_OWNER)
                    
                    # Determine Monitor (simplified via default)
                    MONITOR_DEFAULTTONEAREST = 2
                    hmonitor = ctypes.windll.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
                    
                    # Give preference points to help select the "best" window later
                    score = 0
                    if is_visible: score += 10
                    if is_foreground: score += 20
                    if not self.user32.GetWindow(hwnd, GW_OWNER): score += 5
                    if title: score += 5
                    if is_minimized: score += 5
                    
                    if score > 0:
                        entity = WindowEntity(
                            hwnd=hwnd,
                            title=title,
                            pid=window_pid.value,
                            process_name=None, # Filled later if needed
                            visible=is_visible,
                            minimized=is_minimized,
                            foreground=is_foreground,
                            fullscreen=(width > 0 and height > 0 and width >= 1920 and height >= 1080), # Simplification
                            monitor=hmonitor,
                            x=rect.left,
                            y=rect.top,
                            width=width,
                            height=height
                        )
                        # We attach score temporarily for sorting
                        windows.append((score, entity))
                        
            return True

        try:
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
            self.user32.EnumWindows(WNDENUMPROC(callback), 0)
        except Exception as e:
            logger.warning(f"Error enumerating windows: {e}")
            
        # Sort windows by score descending so the "main" window is likely first
        windows.sort(key=lambda x: x[0], reverse=True)
        return [w[1] for w in windows]

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
            else:
                self.user32.ShowWindow(hwnd, 5) # SW_SHOW
                
            # Trick to force foreground: Simulate Alt key press/release
            # This temporarily disables Windows' foreground lock mechanism
            VK_MENU = 0x12
            KEYEVENTF_EXTENDEDKEY = 0x0001
            KEYEVENTF_KEYUP = 0x0002
            
            # Press ALT
            self.user32.keybd_event(VK_MENU, 0, KEYEVENTF_EXTENDEDKEY, 0)
            
            # Bring window to the top and activate
            self.user32.SetForegroundWindow(hwnd)
            
            # Release ALT
            self.user32.keybd_event(VK_MENU, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
            
            # Just to be absolutely sure it's on top visually
            HWND_TOP = 0
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            self.user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
                
            # Verify Focus
            return self.user32.GetForegroundWindow() == hwnd
            
        except Exception as e:
            logger.warning(f"Failed to focus window: {e}")
            return False

    def move_to_main_screen(self, hwnd: int) -> bool:
        if not self.user32:
            return False
        try:
            # Get primary monitor bounds (0, 0 is top left of primary monitor)
            screen_width = self.user32.GetSystemMetrics(0)
            screen_height = self.user32.GetSystemMetrics(1)
            
            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long),
                            ("top", ctypes.c_long),
                            ("right", ctypes.c_long),
                            ("bottom", ctypes.c_long)]
            rect = RECT()
            self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            
            # Center it on the main screen
            x = (screen_width - width) // 2
            y = (screen_height - height) // 2
            
            # Ensure it's not off-screen if it's larger than the screen
            x = max(0, x)
            y = max(0, y)
            
            SWP_NOZORDER = 0x0004
            SWP_NOSIZE = 0x0001
            
            self.user32.SetWindowPos(hwnd, 0, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER)
            return True
        except Exception as e:
            logger.warning(f"Failed to move window to main screen: {e}")
            return False

    def minimize_window(self, hwnd: int) -> bool:
        if not self.user32:
            return False
        try:
            self.user32.ShowWindow(hwnd, SW_MINIMIZE)
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
            
    def get_foreground_window(self) -> Optional[WindowEntity]:
        if not self.user32:
            return None
            
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return None
            
        window_pid = ctypes.c_ulong(0)
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        
        length = self.user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long),
                        ("top", ctypes.c_long),
                        ("right", ctypes.c_long),
                        ("bottom", ctypes.c_long)]
        rect = RECT()
        self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        
        MONITOR_DEFAULTTONEAREST = 2
        hmonitor = ctypes.windll.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        
        return WindowEntity(
            hwnd=hwnd,
            title=title,
            pid=window_pid.value,
            process_name=None,
            visible=True,
            minimized=False,
            foreground=True,
            fullscreen=(width > 0 and height > 0 and width >= 1920 and height >= 1080),
            monitor=hmonitor,
            x=rect.left,
            y=rect.top,
            width=width,
            height=height
        )

window_manager = WindowManager()
