import ctypes
import time
from typing import Dict, Any, List
from app.core.logging.logger import get_logger
from app.domain.entities import TriState

logger = get_logger(__name__)

# Windows Constants
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001

# Virtual Key Codes
VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12       # Alt key
VK_PAUSE = 0x13
VK_CAPITAL = 0x14    # Caps Lock
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21      # Page Up
VK_NEXT = 0x22       # Page Down
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_DELETE = 0x2E

KEY_NAME_MAP = {
    "enter": VK_RETURN,
    "return": VK_RETURN,
    "tab": VK_TAB,
    "backspace": VK_BACK,
    "bksp": VK_BACK,
    "delete": VK_DELETE,
    "del": VK_DELETE,
    "escape": VK_ESCAPE,
    "esc": VK_ESCAPE,
    "space": VK_SPACE,
    "ctrl": VK_CONTROL,
    "control": VK_CONTROL,
    "shift": VK_SHIFT,
    "alt": VK_MENU,
    "up": VK_UP,
    "down": VK_DOWN,
    "left": VK_LEFT,
    "right": VK_RIGHT,
    "home": VK_HOME,
    "end": VK_END,
    "pageup": VK_PRIOR,
    "pagedown": VK_NEXT,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort),
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", INPUT_UNION),
    ]


class KeyboardController:
    """
    Physical keyboard actuation via Win32 SendInput.
    Enforces strict 64-bit alignment and 40-byte tagINPUT invariants.
    """
    def __init__(self):
        try:
            if hasattr(ctypes, "windll"):
                self.user32 = ctypes.windll.user32
                self.user32.SendInput.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_int]
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

    def _send_input(self, inputs: List[INPUT]) -> bool:
        if not self.user32:
            return False
        n = len(inputs)
        if n == 0:
            return True
        self._ensure_active_desktop()
        LPINPUT = INPUT * n
        arr = LPINPUT(*inputs)
        sent = self.user32.SendInput(n, ctypes.byref(arr), ctypes.sizeof(INPUT))
        if sent == 0:
            err = ctypes.windll.kernel32.GetLastError() if hasattr(ctypes, "windll") else 0
            if err == 5:  # ERROR_ACCESS_DENIED (desktop isolation retry)
                self._ensure_active_desktop()
                sent = self.user32.SendInput(n, ctypes.byref(arr), ctypes.sizeof(INPUT))
            if sent == 0:
                logger.error(f"SendInput keyboard failed. GetLastError: {ctypes.windll.kernel32.GetLastError() if hasattr(ctypes, 'windll') else 0}")
        return sent == n

    def actuate_key(self, vk: int, scan_code: int = 0, dwell_ms: int = 50) -> Dict[str, Any]:
        """
        Actuates a single key press (down, dwell, up).
        """
        if self.user32 and scan_code == 0:
            scan_code = self.user32.MapVirtualKeyW(vk, 0)

        inp_down = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(wVk=vk, wScan=scan_code, dwFlags=0, time=0, dwExtraInfo=None)),
        )
        inp_up = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(wVk=vk, wScan=scan_code, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)),
        )

        down_ok = self._send_input([inp_down])
        if not down_ok:
            return {"success": False, "error": {"code": "ACTUATION_FAILURE", "message": "OS rejected key-down SendInput."}}

        time.sleep(dwell_ms / 1000.0)
        up_ok = self._send_input([inp_up])
        if not up_ok:
            return {"success": False, "error": {"code": "ACTUATION_FAILURE", "message": "OS rejected key-up SendInput."}}

        return {"success": True, "action": "KEY_PRESS", "vk": vk, "scan_code": scan_code}

    def resolve_key_code(self, key_str: str) -> tuple[int, int]:
        """
        Resolves a key string (e.g. 'ctrl', 'enter', 'a', 'F5') to (virtual_key, scan_code).
        """
        k = key_str.strip().lower()
        if k in KEY_NAME_MAP:
            vk = KEY_NAME_MAP[k]
        elif len(key_str) == 1:
            vk = ord(key_str.upper())
        else:
            return 0, 0

        scan_code = self.user32.MapVirtualKeyW(vk, 0) if self.user32 else 0
        return vk, scan_code

    def type_char_unicode(self, char: str, dwell_ms: int = 20) -> bool:
        """
        Types a single character using Win32 KEYEVENTF_UNICODE.
        Handles newlines and tabs as virtual keys for application compatibility.
        """
        if char == "\n" or char == "\r":
            res = self.actuate_key(VK_RETURN, scan_code=0x1C, dwell_ms=dwell_ms)
            return bool(res.get("success"))
        elif char == "\t":
            res = self.actuate_key(VK_TAB, scan_code=0x0F, dwell_ms=dwell_ms)
            return bool(res.get("success"))

        code = ord(char)
        inp_down = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=None)),
        )
        inp_up = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)),
        )

        down_ok = self._send_input([inp_down])
        if not down_ok:
            return False
        time.sleep(dwell_ms / 1000.0)
        up_ok = self._send_input([inp_up])
        return up_ok

    def type_text(self, text: str, cpm: int = 600, dwell_ms: int = 20) -> Dict[str, Any]:
        """
        Types a text string with human-like inter-character timing using Unicode input.
        """
        if not text:
            return {"success": True, "action": "TYPE_TEXT", "char_count": 0, "verified": TriState.UNKNOWN}

        # Calculate inter-character delay based on characters per minute
        char_delay = max(0.01, (60.0 / max(1, cpm)) - (dwell_ms / 1000.0))
        typed = 0
        for idx, char in enumerate(text):
            ok = self.type_char_unicode(char, dwell_ms=dwell_ms)
            if ok:
                typed += 1
            if idx < len(text) - 1:
                time.sleep(char_delay)

        return {
            "success": typed == len(text),
            "action": "TYPE_TEXT",
            "char_count": typed,
            "total_chars": len(text),
            "verified": TriState.UNKNOWN,
        }

    def actuate_special_key(self, key_name: str, dwell_ms: int = 50) -> Dict[str, Any]:
        """
        Actuates a single special key by name (e.g. 'enter', 'tab', 'backspace').
        """
        vk, scan_code = self.resolve_key_code(key_name)
        if vk == 0:
            return {"success": False, "error": {"code": "UNKNOWN_KEY", "message": f"Unrecognized key: {key_name}"}}
        res = self.actuate_key(vk, scan_code=scan_code, dwell_ms=dwell_ms)
        res["key"] = key_name
        return res

    def actuate_hotkey(self, keys: List[str], dwell_ms: int = 50) -> Dict[str, Any]:
        """
        Actuates a hotkey combination (e.g. ['ctrl', 's'], ['alt', 'f4']).
        Presses keys down in sequence, dwells, and guarantees reverse-order release.
        """
        if not keys:
            return {"success": False, "error": {"code": "EMPTY_HOTKEY", "message": "No keys provided for hotkey."}}

        resolved = []
        for k in keys:
            vk, scan = self.resolve_key_code(k)
            if vk == 0:
                return {"success": False, "error": {"code": "UNKNOWN_KEY", "message": f"Unrecognized key in hotkey: {k}"}}
            resolved.append((k, vk, scan))

        down_inputs = [
            INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=0, time=0, dwExtraInfo=None)))
            for _, vk, scan in resolved
        ]
        up_inputs = [
            INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)))
            for _, vk, scan in reversed(resolved)
        ]

        down_ok = False
        try:
            # Press all keys in sequence
            for inp in down_inputs:
                if not self._send_input([inp]):
                    return {"success": False, "error": {"code": "ACTUATION_FAILURE", "message": "OS rejected hotkey press down."}}
                time.sleep(0.015)
            down_ok = True
            time.sleep(dwell_ms / 1000.0)
        finally:
            # Always guarantee release in reverse order to prevent stuck modifiers
            for inp in up_inputs:
                self._send_input([inp])
                time.sleep(0.015)

        return {
            "success": down_ok,
            "action": "HOTKEY",
            "keys": keys,
            "verified": TriState.UNKNOWN,
        }

    def actuate_escape(self, press_count: int = 2, dwell_ms: int = 50, pause_ms: int = 80) -> Dict[str, Any]:
        """
        Sends bounded Escape key events to dismiss transient popups or menus.
        """
        all_ok = True
        for i in range(press_count):
            res = self.actuate_key(VK_ESCAPE, scan_code=1, dwell_ms=dwell_ms)
            if not res.get("success"):
                all_ok = False
            if i < press_count - 1:
                time.sleep(pause_ms / 1000.0)

        return {
            "success": all_ok,
            "action": "ESCAPE",
            "press_count": press_count,
            "verified": TriState.UNKNOWN,
        }

    def actuate_alt(self, press_count: int = 1, dwell_ms: int = 50) -> Dict[str, Any]:
        """
        Taps the Alt key (VK_MENU) to cancel menu bar focus mode.
        """
        scan_code = self.user32.MapVirtualKeyW(VK_MENU, 0) if self.user32 else 0x38
        all_ok = True
        for _ in range(press_count):
            res = self.actuate_key(VK_MENU, scan_code=scan_code, dwell_ms=dwell_ms)
            if not res.get("success"):
                all_ok = False

        return {
            "success": all_ok,
            "action": "ALT",
            "press_count": press_count,
            "verified": TriState.UNKNOWN,
        }

    def clear_clipboard(self, retries: int = 5, delay: float = 0.05) -> bool:
        """
        Clears the OS clipboard with bounded retries.
        """
        return clear_clipboard(retries=retries, delay=delay)

    def get_clipboard_text(self, retries: int = 5, delay: float = 0.05) -> str:
        """
        Retrieves Unicode text currently stored on the OS clipboard with bounded retries.
        """
        return get_clipboard_text(retries=retries, delay=delay)


def clear_clipboard(retries: int = 5, delay: float = 0.05) -> bool:
    """
    Clears the OS clipboard with bounded retries.
    """
    u32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
    if not u32:
        return False
    try:
        h_input = u32.OpenInputDesktop(0, False, 0x01FF)
        if h_input:
            u32.SetThreadDesktop(h_input)
    except Exception:
        pass
    for _ in range(retries):
        if u32.OpenClipboard(0):
            try:
                u32.EmptyClipboard()
                return True
            finally:
                u32.CloseClipboard()
        time.sleep(delay)
    return False


def get_clipboard_text(retries: int = 5, delay: float = 0.05) -> str:
    """
    Retrieves Unicode text currently stored on the OS clipboard with bounded retries.
    """
    u32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
    k32 = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None
    if not u32 or not k32:
        return ""
    try:
        h_input = u32.OpenInputDesktop(0, False, 0x01FF)
        if h_input:
            u32.SetThreadDesktop(h_input)
    except Exception:
        pass
    for _ in range(retries):
        if u32.OpenClipboard(0):
            try:
                CF_UNICODETEXT = 13
                u32.GetClipboardData.restype = ctypes.c_void_p
                u32.GetClipboardData.argtypes = [ctypes.c_uint]
                k32.GlobalLock.restype = ctypes.c_void_p
                k32.GlobalLock.argtypes = [ctypes.c_void_p]
                k32.GlobalUnlock.argtypes = [ctypes.c_void_p]

                h_mem = u32.GetClipboardData(CF_UNICODETEXT)
                if h_mem:
                    p_mem = k32.GlobalLock(h_mem)
                    if p_mem:
                        try:
                            val = ctypes.c_wchar_p(p_mem).value
                            if val:
                                return val
                        finally:
                            k32.GlobalUnlock(h_mem)
            finally:
                u32.CloseClipboard()
        time.sleep(delay)
    return ""


keyboard_controller = KeyboardController()

