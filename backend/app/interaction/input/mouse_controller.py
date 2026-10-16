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

    def get_cursor_pos_safe(self) -> Tuple[bool, ScreenPoint]:
        """Safely queries cursor position, returning (success, point)."""
        if not self.user32:
            return False, ScreenPoint(x=0, y=0)
            
        def _get():
            pt = POINT()
            if self.user32.GetCursorPos(ctypes.byref(pt)):
                return True, ScreenPoint(x=pt.x, y=pt.y)
            return False, ScreenPoint(x=0, y=0)
            
        return self._with_dpi_awareness(_get)

    def get_cursor_pos(self) -> ScreenPoint:
        ok, pt = self.get_cursor_pos_safe()
        return pt

    def _normalize_coordinates(self, point: ScreenPoint) -> Tuple[int, int]:
        """
        Maps physical screen coordinates to Windows normalized absolute coordinates [0, 65535].
        
        Windows win32k maps normalized coordinates back to pixels via integer bit-shift:
            pixel = (norm * dimension) >> 16
        To prevent downward truncation errors and ensure exact pixel accuracy,
        coordinates are mapped to pixel centers (point + 0.5) in 16-bit fixed-point
        space (scale 65536) and clamped to the valid Win32 range [0, 65535].
        """
        vx, vy, vcx, vcy = self._get_virtual_screen_bounds()
        if vcx <= 0 or vcy <= 0:
            return 0, 0

        norm_x = int(((point.x - vx + 0.5) * 65536) / vcx)
        norm_y = int(((point.y - vy + 0.5) * 65536) / vcy)

        clamped_x = max(0, min(65535, norm_x))
        clamped_y = max(0, min(65535, norm_y))
        return clamped_x, clamped_y

    def actuate_move(self, point: ScreenPoint, verify: bool = False) -> Dict[str, Any]:
        if not self._is_valid_coordinate(point):
            return {
                "success": False,
                "error": {
                    "code": "OUT_OF_BOUNDS",
                    "message": f"Coordinate ({point.x}, {point.y}) falls outside known display topology."
                },
                "verified": TriState.FALSE
            }

        norm_x, norm_y = self._normalize_coordinates(point)
        flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        inp = self._create_mouse_input(norm_x, norm_y, flags)
        
        def _move():
            return self._send_input([inp])
            
        success = self._with_dpi_awareness(_move)
        if not success:
            return {
                "success": False,
                "error": {
                    "code": "ACTUATION_FAILURE",
                    "message": "OS rejected SendInput for MOVE_MOUSE."
                },
                "verified": TriState.UNKNOWN
            }

        # Actuation was accepted by the OS
        if verify:
            ok, observed = self.get_cursor_pos_safe()
            if not ok:
                return {
                    "success": True,
                    "action": "MOVE_MOUSE",
                    "actuation_status": "ACTUATION_ACCEPTED",
                    "verified": TriState.UNKNOWN,
                    "error": {
                        "code": "OBSERVATION_UNAVAILABLE",
                        "message": "Failed to read cursor position for verification."
                    }
                }
            elif observed.x == point.x and observed.y == point.y:
                return {
                    "success": True,
                    "action": "MOVE_MOUSE",
                    "actuation_status": "ACTUATION_ACCEPTED",
                    "verified": TriState.TRUE,
                    "observed_point": {"x": observed.x, "y": observed.y}
                }
            else:
                return {
                    "success": True,
                    "action": "MOVE_MOUSE",
                    "actuation_status": "ACTUATION_ACCEPTED",
                    "verified": TriState.FALSE,
                    "error": {
                        "code": "VERIFIED_MISMATCH",
                        "message": f"Cursor at ({observed.x}, {observed.y}) does not match target ({point.x}, {point.y}).",
                        "discrepancy": {"x": observed.x - point.x, "y": observed.y - point.y}
                    },
                    "observed_point": {"x": observed.x, "y": observed.y}
                }

        # Default (unverified): OS accepted actuation, verification awaiting observation
        return {
            "success": True,
            "action": "MOVE_MOUSE",
            "actuation_status": "ACTUATION_ACCEPTED",
            "verified": TriState.UNKNOWN
        }

    def actuate_click(self, point: ScreenPoint) -> Dict[str, Any]:
        move_result = self.actuate_move(point)
        if not move_result.get("success"):
            return move_result
            
        # Click
        flags_down = MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        flags_up = MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        
        # Consistent normalization for click events
        norm_x, norm_y = self._normalize_coordinates(point)
        
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
