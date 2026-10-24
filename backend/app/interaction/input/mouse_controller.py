import ctypes
import math
import time
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
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
WHEEL_DELTA = 120

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

    def _send_input(self, inputs: list) -> bool:
        if not self.user32:
            return False
            
        self._ensure_active_desktop()
        nInputs = len(inputs)
        LPINPUT = INPUT * nInputs
        pInputs = LPINPUT(*inputs)
        
        result = self.user32.SendInput(nInputs, ctypes.byref(pInputs), ctypes.sizeof(INPUT))
        if result == 0:
            err = ctypes.windll.kernel32.GetLastError() if hasattr(ctypes, "windll") else 0
            if err == 5:  # ERROR_ACCESS_DENIED (desktop isolation retry)
                self._ensure_active_desktop()
                result = self.user32.SendInput(nInputs, ctypes.byref(pInputs), ctypes.sizeof(INPUT))
            if result == 0:
                logger.error(f"SendInput failed. GetLastError: {ctypes.windll.kernel32.GetLastError() if hasattr(ctypes, 'windll') else 0}")
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

    def _ensure_window_activated(self, point: ScreenPoint) -> Tuple[int, int, bool]:
        """
        Ensures the window at point has foreground focus if it belongs to a different process.
        Uses AttachThreadInput to overcome Win32 SetForegroundWindow restrictions.
        Returns (target_hwnd, fg_before, window_activated).
        """
        target_hwnd = 0
        fg_before = 0
        window_activated = False

        if not self.user32:
            return target_hwnd, fg_before, window_activated

        pt = POINT(int(point.x), int(point.y))
        hwnd_at_pt = self.user32.WindowFromPoint(pt)
        if hwnd_at_pt:
            root_hwnd = self.user32.GetAncestor(hwnd_at_pt, 2)  # GA_ROOT = 2
            target_hwnd = root_hwnd if root_hwnd else hwnd_at_pt
            fg_before = self.user32.GetForegroundWindow()
            if not fg_before:
                return target_hwnd, fg_before, window_activated
            if target_hwnd == fg_before:
                return target_hwnd, fg_before, True

            fg_pid = ctypes.c_ulong()
            target_pid = ctypes.c_ulong()
            self.user32.GetWindowThreadProcessId(fg_before, ctypes.byref(fg_pid))
            self.user32.GetWindowThreadProcessId(target_hwnd, ctypes.byref(target_pid))

            if fg_pid.value != target_pid.value:
                try:
                    my_thread = ctypes.windll.kernel32.GetCurrentThreadId() if hasattr(ctypes, "windll") else 0
                    fg_thread = self.user32.GetWindowThreadProcessId(fg_before, None)
                    attached = False
                    if my_thread and fg_thread and fg_thread != my_thread:
                        attached = bool(self.user32.AttachThreadInput(my_thread, fg_thread, True))
                    try:
                        self.user32.SetForegroundWindow(target_hwnd)
                    finally:
                        if attached:
                            self.user32.AttachThreadInput(my_thread, fg_thread, False)
                    time.sleep(0.05)
                    window_activated = (self.user32.GetForegroundWindow() == target_hwnd)
                except Exception as e:
                    logger.debug(f"Window activation warning: {e}")

        return target_hwnd, fg_before, window_activated

    def actuate_click(self, point: ScreenPoint) -> Dict[str, Any]:
        target_hwnd, fg_before, window_activated = self._ensure_window_activated(point)

        # 1. Physical move to coordinate with position verification
        move_result = self.actuate_move(point, verify=True)
        if not move_result.get("success"):
            return move_result

        # 2. Settle delay so the target window processes WM_MOUSEMOVE
        # and transitions to hover/pointer-over state before button-down.
        # Required for WinUI 3 / XAML controls (e.g., Windows 11 Notepad MenuBarItem).
        time.sleep(0.05)

        # 3. Observe actual physical cursor location immediately prior to button-down
        ok_cur, observed_cur = self.get_cursor_pos_safe()
        cur_x = observed_cur.x if ok_cur else point.x
        cur_y = observed_cur.y if ok_cur else point.y
        discrepancy_x = cur_x - point.x
        discrepancy_y = cur_y - point.y

        # 4. Pure button press and release flags WITHOUT MOUSEEVENTF_MOVE.
        # Including MOUSEEVENTF_MOVE on button-down or button-up can cause modern
        # XAML gesture recognizers to interpret the action as a drag or pan gesture.
        # The cursor is already physically positioned at the exact pixel.
        flags_down = MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        flags_up = MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK

        norm_x, norm_y = self._normalize_coordinates(point)
        inp_down = self._create_mouse_input(norm_x, norm_y, flags_down)
        inp_up = self._create_mouse_input(norm_x, norm_y, flags_up)

        button_down_ok = False
        button_up_ok = False

        # 5. Split mouse-down and mouse-up into separate SendInput calls with
        # realistic physical dwell time (60ms) between them. Modern XAML gesture
        # recognizers discard zero-duration button presses as noise when down+up
        # arrive simultaneously. Using try-finally guarantees button-up is always sent.
        def _click():
            nonlocal button_down_ok, button_up_ok
            try:
                button_down_ok = self._send_input([inp_down])
                if not button_down_ok:
                    return False
                time.sleep(0.06)
            finally:
                button_up_ok = self._send_input([inp_up])
            return button_down_ok and button_up_ok

        success = self._with_dpi_awareness(_click)

        diagnostics = {
            "target_point": {"x": point.x, "y": point.y},
            "move_accepted": move_result.get("success", False),
            "cursor_before_click": {"x": cur_x, "y": cur_y},
            "cursor_discrepancy": {"x": discrepancy_x, "y": discrepancy_y},
            "button_down_accepted": button_down_ok,
            "button_up_accepted": button_up_ok,
            "dwell_ms": 60,
            "settle_ms": 50,
            "target_window_hwnd": target_hwnd,
            "foreground_hwnd_before": fg_before,
            "window_activated": window_activated,
        }

        if success:
            return {
                "success": True,
                "action": "CLICK",
                "verified": TriState.UNKNOWN,
                "diagnostics": diagnostics,
            }
        else:
            return {
                "success": False,
                "error": {
                    "code": "ACTUATION_FAILURE",
                    "message": "OS rejected SendInput for CLICK (button_down or button_up).",
                },
                "diagnostics": diagnostics,
            }

    def actuate_double_click(self, point: ScreenPoint) -> Dict[str, Any]:
        click1 = self.actuate_click(point)
        if not click1.get("success"):
            return click1
            
        click2 = self.actuate_click(point)
        if not click2.get("success"):
            return click2
            
        return {"success": True, "action": "DOUBLE_CLICK", "verified": TriState.UNKNOWN}

    def actuate_right_click(self, point: ScreenPoint) -> Dict[str, Any]:
        """
        Executes a secondary (right) mouse button click at the specified screen coordinate.
        Enforces identical pre-activation checks, coordinate normalization, and 60ms dwell invariants
        as primary click.
        """
        if not self._is_valid_coordinate(point):
            return {
                "success": False,
                "error": {
                    "code": "OUT_OF_BOUNDS",
                    "message": f"Target coordinate ({point.x}, {point.y}) is outside virtual screen bounds.",
                },
                "diagnostics": {"target_point": {"x": point.x, "y": point.y}},
            }

        target_hwnd, fg_before, window_activated = self._ensure_window_activated(point)

        move_result = self.actuate_move(point, verify=True)
        if not move_result.get("success"):
            return move_result

        time.sleep(0.05)

        ok_cur, observed_cur = self.get_cursor_pos_safe()
        cur_x = observed_cur.x if ok_cur else point.x
        cur_y = observed_cur.y if ok_cur else point.y
        discrepancy_x = cur_x - point.x
        discrepancy_y = cur_y - point.y

        flags_down = MOUSEEVENTF_RIGHTDOWN | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        flags_up = MOUSEEVENTF_RIGHTUP | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK

        norm_x, norm_y = self._normalize_coordinates(point)
        inp_down = self._create_mouse_input(norm_x, norm_y, flags_down)
        inp_up = self._create_mouse_input(norm_x, norm_y, flags_up)

        button_down_ok = False
        button_up_ok = False

        def _click():
            nonlocal button_down_ok, button_up_ok
            try:
                button_down_ok = self._send_input([inp_down])
                if not button_down_ok:
                    return False
                time.sleep(0.06)
            finally:
                button_up_ok = self._send_input([inp_up])
            return button_down_ok and button_up_ok

        success = self._with_dpi_awareness(_click)

        diagnostics = {
            "target_point": {"x": point.x, "y": point.y},
            "move_accepted": move_result.get("success", False),
            "cursor_before_click": {"x": cur_x, "y": cur_y},
            "cursor_discrepancy": {"x": discrepancy_x, "y": discrepancy_y},
            "button_down_accepted": button_down_ok,
            "button_up_accepted": button_up_ok,
            "dwell_ms": 60,
            "settle_ms": 50,
            "target_window_hwnd": target_hwnd,
            "foreground_hwnd_before": fg_before,
            "window_activated": window_activated,
        }

        if success:
            return {
                "success": True,
                "action": "RIGHT_CLICK",
                "verified": TriState.UNKNOWN,
                "diagnostics": diagnostics,
            }
        else:
            return {
                "success": False,
                "error": {
                    "code": "ACTUATION_FAILURE",
                    "message": "OS rejected SendInput for RIGHT_CLICK (button_down or button_up).",
                },
                "diagnostics": diagnostics,
            }

    def actuate_scroll(
        self,
        clicks: int = 0,
        delta_x: int = 0,
        delta_y: int = 0,
        point: ScreenPoint | None = None,
    ) -> Dict[str, Any]:
        """
        Executes vertical and/or horizontal mouse wheel scrolling.
        clicks: Number of vertical scroll clicks (positive=up, negative=down).
        delta_y: Alternate specification for vertical scroll clicks.
        delta_x: Number of horizontal scroll clicks (positive=right, negative=left).
        point: Optional screen point to position cursor before scrolling so the target UI container receives the wheel event.
        """
        move_result = None
        if point:
            if not self._is_valid_coordinate(point):
                return {
                    "success": False,
                    "error": {
                        "code": "OUT_OF_BOUNDS",
                        "message": f"Target scroll point ({point.x}, {point.y}) is outside virtual screen bounds.",
                    },
                }
            move_result = self.actuate_move(point, verify=True)
            if not move_result.get("success"):
                return move_result
            time.sleep(0.04)

        effective_vert = clicks if clicks != 0 else delta_y
        inputs = []

        if effective_vert != 0:
            vert_amount = int(effective_vert * WHEEL_DELTA)
            inp_v = INPUT(type=0)
            inp_v.union.mi.dx = 0
            inp_v.union.mi.dy = 0
            inp_v.union.mi.mouseData = ctypes.c_ulong(vert_amount & 0xFFFFFFFF)
            inp_v.union.mi.dwFlags = MOUSEEVENTF_WHEEL
            inp_v.union.mi.time = 0
            inp_v.union.mi.dwExtraInfo = None
            inputs.append(inp_v)

        if delta_x != 0:
            horiz_amount = int(delta_x * WHEEL_DELTA)
            inp_h = INPUT(type=0)
            inp_h.union.mi.dx = 0
            inp_h.union.mi.dy = 0
            inp_h.union.mi.mouseData = ctypes.c_ulong(horiz_amount & 0xFFFFFFFF)
            inp_h.union.mi.dwFlags = MOUSEEVENTF_HWHEEL
            inp_h.union.mi.time = 0
            inp_h.union.mi.dwExtraInfo = None
            inputs.append(inp_h)

        if not inputs:
            return {
                "success": True,
                "action": "SCROLL",
                "message": "Zero scroll delta requested; no-op.",
                "diagnostics": {"clicks": 0, "delta_x": 0, "delta_y": 0},
            }

        success = self._with_dpi_awareness(lambda: self._send_input(inputs))
        diagnostics = {
            "effective_vertical_clicks": effective_vert,
            "horizontal_clicks": delta_x,
            "vertical_wheel_units": int(effective_vert * WHEEL_DELTA),
            "horizontal_wheel_units": int(delta_x * WHEEL_DELTA),
            "packets_sent": len(inputs),
            "target_point": {"x": point.x, "y": point.y} if point else None,
        }

        if success:
            return {
                "success": True,
                "action": "SCROLL",
                "verified": TriState.UNKNOWN,
                "diagnostics": diagnostics,
            }
        else:
            return {
                "success": False,
                "error": {
                    "code": "ACTUATION_FAILURE",
                    "message": "OS rejected SendInput for mouse wheel scroll.",
                },
                "diagnostics": diagnostics,
            }

    def actuate_drag(
        self,
        start_point: ScreenPoint,
        end_point: ScreenPoint,
        button: str = "left",
        steps: int = 10,
        duration_ms: int = 250,
    ) -> Dict[str, Any]:
        """
        Executes a mouse drag-and-drop between start_point and end_point.
        Interpolates intermediate coordinates across `steps` with micro-delays
        to allow OS and window message loops to properly track pointer drag.
        Button release at end_point is strictly guaranteed via try...finally.
        """
        if not self._is_valid_coordinate(start_point):
            return {
                "success": False,
                "error": {
                    "code": "OUT_OF_BOUNDS",
                    "message": f"Start coordinate ({start_point.x}, {start_point.y}) is outside virtual screen bounds.",
                },
            }
        if not self._is_valid_coordinate(end_point):
            return {
                "success": False,
                "error": {
                    "code": "OUT_OF_BOUNDS",
                    "message": f"End coordinate ({end_point.x}, {end_point.y}) is outside virtual screen bounds.",
                },
            }

        self._ensure_window_activated(start_point)

        move_start = self.actuate_move(start_point, verify=True)
        if not move_start.get("success"):
            return move_start
        time.sleep(0.05)

        is_right = (button.lower() == "right")
        flags_down = (MOUSEEVENTF_RIGHTDOWN if is_right else MOUSEEVENTF_LEFTDOWN) | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        flags_up = (MOUSEEVENTF_RIGHTUP if is_right else MOUSEEVENTF_LEFTUP) | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK

        norm_sx, norm_sy = self._normalize_coordinates(start_point)
        inp_down = self._create_mouse_input(norm_sx, norm_sy, flags_down)

        down_ok = False
        up_ok = False
        steps_executed = 0
        step_delay = max(0.005, (duration_ms / 1000.0) / max(1, steps))

        def _drag():
            nonlocal down_ok, up_ok, steps_executed
            try:
                down_ok = self._send_input([inp_down])
                if not down_ok:
                    return False
                time.sleep(0.05)

                actual_steps = max(2, steps)
                for i in range(1, actual_steps + 1):
                    alpha = i / float(actual_steps)
                    interp_x = start_point.x + (end_point.x - start_point.x) * alpha
                    interp_y = start_point.y + (end_point.y - start_point.y) * alpha
                    pt = ScreenPoint(x=int(interp_x), y=int(interp_y))
                    self.actuate_move(pt, verify=False)
                    steps_executed += 1
                    time.sleep(step_delay)

                time.sleep(0.05)
            finally:
                norm_ex, norm_ey = self._normalize_coordinates(end_point)
                inp_up = self._create_mouse_input(norm_ex, norm_ey, flags_up)
                up_ok = self._send_input([inp_up])

            return down_ok and up_ok

        try:
            success = self._with_dpi_awareness(_drag)
            drag_error_msg = "OS rejected SendInput during mouse drag."
        except Exception as e:
            logger.error(f"DRAG_ACTUATION_EXCEPTION: {e}")
            success = False
            drag_error_msg = f"Exception during mouse drag: {e}"

        diagnostics = {
            "start_point": {"x": start_point.x, "y": start_point.y},
            "end_point": {"x": end_point.x, "y": end_point.y},
            "button": "right" if is_right else "left",
            "button_down_accepted": down_ok,
            "button_up_accepted": up_ok,
            "steps_executed": steps_executed,
            "duration_ms": duration_ms,
        }

        if success:
            return {
                "success": True,
                "action": "DRAG",
                "verified": TriState.UNKNOWN,
                "diagnostics": diagnostics,
            }
        else:
            return {
                "success": False,
                "error": {
                    "code": "ACTUATION_FAILURE",
                    "message": drag_error_msg,
                },
                "diagnostics": diagnostics,
            }

mouse_controller = MouseController()
