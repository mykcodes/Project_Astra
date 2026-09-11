import ctypes
import math
from typing import Dict, Any, Tuple
from app.core.logging.logger import get_logger
from app.domain.entities import ScreenPoint, TriState

logger = get_logger(__name__)

# Constants for Windows API
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

class MOUSEINPUT(ctypes.Structure):
    _fields_ = (("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)))

class INPUT_union(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT),)

class INPUT(ctypes.Structure):
    _fields_ = (("type", ctypes.c_ulong),
                ("union", INPUT_union))

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class MouseController:
    def __init__(self):
        try:
            if hasattr(ctypes, "windll"):
                self.user32 = ctypes.windll.user32
                self.user32.SendInput.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_int]
            else:
                self.user32 = None
        except Exception:
            self.user32 = None

    def _with_dpi_awareness(self, func):
        if not self.user32:
            return func()
        
        # Save original context
        try:
            original_context = self.user32.GetThreadDpiAwarenessContext()
        except AttributeError:
            original_context = None

        # Set Per-Monitor V2
        try:
            if hasattr(self.user32, "SetThreadDpiAwarenessContext"):
                self.user32.SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        except Exception as e:
            logger.warning(f"Failed to set DPI awareness context: {e}")

        try:
            result = func()
        finally:
            if original_context and hasattr(self.user32, "SetThreadDpiAwarenessContext"):
                self.user32.SetThreadDpiAwarenessContext(original_context)
                
        return result

    def _get_virtual_screen_bounds(self) -> Tuple[int, int, int, int]:
        """Returns (x, y, width, height) of the virtual screen."""
        if not self.user32:
            return 0, 0, 1920, 1080 # Fallback
            
        def get_bounds():
            x = self.user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            y = self.user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            cx = self.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            cy = self.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
            
            # If metrics return 0 for size, fallback to primary screen
            if cx == 0 or cy == 0:
                cx = self.user32.GetSystemMetrics(0) # SM_CXSCREEN
                cy = self.user32.GetSystemMetrics(1) # SM_CYSCREEN
            return x, y, cx, cy

        return self._with_dpi_awareness(get_bounds)

    def _is_valid_coordinate(self, point: ScreenPoint) -> bool:
        if math.isnan(point.x) or math.isnan(point.y) or math.isinf(point.x) or math.isinf(point.y):
            return False
            
        x, y, cx, cy = self._get_virtual_screen_bounds()
        if point.x < x or point.x >= x + cx:
            return False
        if point.y < y or point.y >= y + cy:
            return False
        return True

    def _send_input(self, inputs: list) -> bool:
        if not self.user32:
            return False
            
        nInputs = len(inputs)
        LPINPUT = INPUT * nInputs
        pInputs = LPINPUT(*inputs)
        
        result = self.user32.SendInput(nInputs, ctypes.byref(pInputs), ctypes.sizeof(INPUT))
        if result == 0:
            logger.error(f"SendInput failed. GetLastError: {ctypes.windll.kernel32.GetLastError()}")
        return result == nInputs

    def _create_mouse_input(self, dx: int, dy: int, flags: int) -> INPUT:
        mi = MOUSEINPUT(dx, dy, 0, flags, 0, None)
        union = INPUT_union(mi=mi)
        return INPUT(0, union)

    def get_cursor_pos(self) -> ScreenPoint:
        if not self.user32:
            return ScreenPoint(x=0, y=0)
            
        def _get():
            pt = POINT()
            if self.user32.GetCursorPos(ctypes.byref(pt)):
                return ScreenPoint(x=pt.x, y=pt.y)
            return ScreenPoint(x=0, y=0)
            
        return self._with_dpi_awareness(_get)

    def actuate_move(self, point: ScreenPoint) -> Dict[str, Any]:
        if not self._is_valid_coordinate(point):
            return {"success": False, "error": {"code": "OUT_OF_BOUNDS", "message": f"Coordinate ({point.x}, {point.y}) falls outside known display topology."}}

        vx, vy, vcx, vcy = self._get_virtual_screen_bounds()
        
        # Normalize to 0-65535
        # The virtual desktop coords: (x - left) * 65535 / width
        norm_x = int(((point.x - vx) * 65535) / vcx) if vcx > 0 else 0
        norm_y = int(((point.y - vy) * 65535) / vcy) if vcy > 0 else 0

        flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        inp = self._create_mouse_input(norm_x, norm_y, flags)
        
        def _move():
            return self._send_input([inp])
            
        success = self._with_dpi_awareness(_move)
        if success:
            return {"success": True, "action": "MOVE_MOUSE", "verified": TriState.TRUE}
        else:
            return {"success": False, "error": {"code": "ACTUATION_FAILURE", "message": "OS rejected SendInput for MOVE_MOUSE."}}

    def actuate_click(self, point: ScreenPoint) -> Dict[str, Any]:
        move_result = self.actuate_move(point)
        if not move_result.get("success"):
            return move_result
            
        # Click
        flags_down = MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        flags_up = MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        
        # We must include coordinates in down/up as well when using ABSOLUTE | VIRTUALDESK
        vx, vy, vcx, vcy = self._get_virtual_screen_bounds()
        norm_x = int(((point.x - vx) * 65535) / vcx) if vcx > 0 else 0
        norm_y = int(((point.y - vy) * 65535) / vcy) if vcy > 0 else 0
        
        inp_down = self._create_mouse_input(norm_x, norm_y, flags_down)
        inp_up = self._create_mouse_input(norm_x, norm_y, flags_up)
        
        def _click():
            return self._send_input([inp_down, inp_up])
            
        success = self._with_dpi_awareness(_click)
        if success:
            return {"success": True, "action": "CLICK", "verified": TriState.UNKNOWN}
        else:
            return {"success": False, "error": {"code": "ACTUATION_FAILURE", "message": "OS rejected SendInput for CLICK."}}

    def actuate_double_click(self, point: ScreenPoint) -> Dict[str, Any]:
        click1 = self.actuate_click(point)
        if not click1.get("success"):
            return click1
            
        click2 = self.actuate_click(point)
        if not click2.get("success"):
            return click2
            
        return {"success": True, "action": "DOUBLE_CLICK", "verified": TriState.UNKNOWN}

mouse_controller = MouseController()
