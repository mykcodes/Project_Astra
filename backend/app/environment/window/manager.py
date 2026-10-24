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

    def _ensure_active_desktop(self) -> None:
        """Ensures the calling thread is attached to the active input desktop."""
        if not self.user32:
            return
        try:
            h_input = self.user32.OpenInputDesktop(0, False, 0x01FF)
            if h_input:
                self.user32.SetThreadDesktop(h_input)
                if getattr(self, "_h_desktop", None) and self._h_desktop != h_input:
                    try:
                        self.user32.CloseDesktop(self._h_desktop)
                    except Exception:
                        pass
                self._h_desktop = h_input
        except Exception:
            pass

    def get_windows_for_pids(self, pids: List[int]) -> List[WindowEntity]:
        """
        Returns a list of structured WindowEntity objects for matching PIDs.
        Prioritizes top-level visible windows but relaxes constraints to capture 
        Electron/UWP apps correctly.
        """
        if not self.user32 or not pids:
            return []

        self._ensure_active_desktop()
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
            
            effective_pid = window_pid.value
            matched = effective_pid in pid_set

            # UWP App Support: Top-level window is owned by ApplicationFrameHost.exe,
            # while the core app logic runs under a child CoreWindow matching pid_set
            if not matched:
                class_buf = ctypes.create_unicode_buffer(64)
                self.user32.GetClassNameW(hwnd, class_buf, 64)
                if class_buf.value == "ApplicationFrameWindow":
                    def child_cb(child_hwnd, _):
                        nonlocal matched, effective_pid
                        c_pid = ctypes.c_ulong(0)
                        self.user32.GetWindowThreadProcessId(child_hwnd, ctypes.byref(c_pid))
                        if c_pid.value in pid_set:
                            matched = True
                            effective_pid = c_pid.value
                            return False
                        return True
                    CHILDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
                    self.user32.EnumChildWindows(hwnd, CHILDENUMPROC(child_cb), 0)

            if matched:
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
                    if width > 0 and height > 0: score += 15  # Prefer real application windows over 0x0 IME helpers
                    
                    if score > 0:
                        entity = WindowEntity(
                            hwnd=hwnd,
                            title=title,
                            pid=effective_pid,
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
            
        self._ensure_active_desktop()
        try:
            fg_hwnd = self.user32.GetForegroundWindow()
            if fg_hwnd == hwnd:
                return True

            if self.is_minimized(hwnd):
                self.user32.ShowWindow(hwnd, SW_RESTORE)
            else:
                self.user32.ShowWindow(hwnd, 5) # SW_SHOW
                
            my_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            target_thread = self.user32.GetWindowThreadProcessId(hwnd, None) if hwnd else 0
            fg_thread = self.user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
            
            attached_fg = False
            attached_target = False
            
            try:
                if fg_thread and fg_thread != my_thread:
                    attached_fg = bool(self.user32.AttachThreadInput(my_thread, fg_thread, True))
                if target_thread and target_thread != my_thread:
                    attached_target = bool(self.user32.AttachThreadInput(my_thread, target_thread, True))

                self.user32.SetForegroundWindow(hwnd)
                self.user32.BringWindowToTop(hwnd)
                self.user32.SetFocus(hwnd)

                # If still not foreground, pulse Alt to bypass foreground lock timeout, but immediately cancel menu mode
                if self.user32.GetForegroundWindow() != hwnd:
                    VK_MENU = 0x12
                    VK_ESCAPE = 0x1B
                    KEYEVENTF_KEYUP = 0x0002
                    self.user32.keybd_event(VK_MENU, 0, 0, 0)
                    self.user32.SetForegroundWindow(hwnd)
                    self.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
                    self.user32.BringWindowToTop(hwnd)
                    # Cancel menu bar activation caused by Alt pulse
                    self.user32.keybd_event(VK_ESCAPE, 0, 0, 0)
                    self.user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)
            finally:
                if attached_fg:
                    self.user32.AttachThreadInput(my_thread, fg_thread, False)
                if attached_target:
                    self.user32.AttachThreadInput(my_thread, target_thread, False)
            
            # Just to be absolutely sure it's on top visually
            HWND_TOP = 0
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            self.user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
                
            # If still not foreground, execute authoritative title-bar physical click
            if self.user32.GetForegroundWindow() != hwnd:
                try:
                    from app.interaction.input.mouse_controller import mouse_controller
                    from app.domain.entities import ScreenPoint
                    class RECT(ctypes.Structure):
                        _fields_ = [('l', ctypes.c_long), ('t', ctypes.c_long), ('r', ctypes.c_long), ('b', ctypes.c_long)]
                    rect = RECT()
                    if self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                        w = rect.r - rect.l
                        if w > 100:
                            mouse_controller.actuate_click(ScreenPoint(x=int(rect.l + min(150, w // 2)), y=int(rect.t + 15)))
                except Exception:
                    pass

            # Verify Focus
            return self.user32.GetForegroundWindow() == hwnd
            
        except Exception as e:
            logger.warning(f"Failed to focus window: {e}")
            return False

    def move_to_main_screen(self, hwnd: int) -> bool:
        if not self.user32:
            return False
        self._ensure_active_desktop()
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

    def get_window_geometry(self, hwnd: int) -> Optional[tuple[int, int, int, int]]:
        """Returns (x, y, width, height) of the given window handle."""
        if not self.user32:
            return None
        try:
            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long),
                            ("top", ctypes.c_long),
                            ("right", ctypes.c_long),
                            ("bottom", ctypes.c_long)]
            rect = RECT()
            if self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
            return None
        except Exception as e:
            logger.warning(f"Failed to get window geometry: {e}")
            return None

    def set_window_geometry(self, hwnd: int, x: int, y: int, width: Optional[int] = None, height: Optional[int] = None) -> bool:
        """Sets window position and optionally dimensions."""
        if not self.user32:
            return False
        self._ensure_active_desktop()
        try:
            if width is not None and height is not None:
                if self.user32.MoveWindow(hwnd, int(x), int(y), int(width), int(height), True):
                    return True
            SWP_NOZORDER = 0x0004
            flags = SWP_NOZORDER
            if width is None or height is None:
                SWP_NOSIZE = 0x0001
                flags |= SWP_NOSIZE
                w, h = 0, 0
            else:
                w, h = width, height
            return bool(self.user32.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h), flags))
        except Exception as e:
            logger.warning(f"Failed to set window geometry: {e}")
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
            
        self._ensure_active_desktop()
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
