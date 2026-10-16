"""
ASTRA — Phase B.3.5: Read-Only Environment Diagnostic

Diagnostic script to inspect the Windows process, session, desktop station,
token integrity, DPI context, and Win32 API environment.

PURELY READ-ONLY:
- Does NOT actuate mouse movement.
- Does NOT inject clicks or keystrokes.
- Does NOT alter any desktop, window, file, or configuration.
- Does NOT collect sensitive personal data or credentials.
"""

import ctypes
import os
import sys
from ctypes import wintypes
from typing import Any, Dict, Optional, Tuple


def _safe_str(val: Any) -> str:
    if val is None:
        return "UNKNOWN"
    return str(val)


def diagnose_environment() -> Dict[str, Any]:
    """Runs all read-only diagnostic checks and returns structured findings."""
    report: Dict[str, Any] = {}
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    advapi32 = ctypes.windll.advapi32

    # -------------------------------------------------------------------------
    # 1. Python Runtime & Architecture
    # -------------------------------------------------------------------------
    is_64bit = sys.maxsize > 2**32
    report["python"] = {
        "status": "DETECTED",
        "executable": sys.executable,
        "version": sys.version.split()[0],
        "is_64bit": is_64bit,
        "platform": sys.platform,
    }

    # -------------------------------------------------------------------------
    # 2. Process Identity (PID, PPID)
    # -------------------------------------------------------------------------
    pid = os.getpid()
    ppid = os.getppid() if hasattr(os, "getppid") else None
    report["process"] = {
        "status": "DETECTED",
        "pid": pid,
        "ppid": ppid,
    }

    # -------------------------------------------------------------------------
    # 3. Process Token, Integrity Level & Elevation
    # -------------------------------------------------------------------------
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL

    h_token = wintypes.HANDLE()
    TOKEN_QUERY = 0x0008

    if advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(h_token)):
        try:
            # Token Integrity Level
            TokenIntegrityLevel = 25
            needed = wintypes.DWORD()
            advapi32.GetTokenInformation(h_token, TokenIntegrityLevel, None, 0, ctypes.byref(needed))
            buf = ctypes.create_string_buffer(needed.value)

            if advapi32.GetTokenInformation(h_token, TokenIntegrityLevel, buf, needed.value, ctypes.byref(needed)):
                p_sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
                advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
                advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
                advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
                advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)

                subauth_count = advapi32.GetSidSubAuthorityCount(p_sid)[0]
                integrity_val = advapi32.GetSidSubAuthority(p_sid, subauth_count - 1)[0]

                integrity_map = {
                    0x0000: "UNTRUSTED",
                    0x1000: "LOW",
                    0x2000: "MEDIUM",
                    0x2100: "MEDIUM_PLUS",
                    0x3000: "HIGH",
                    0x4000: "SYSTEM",
                    0x5000: "PROTECTED_PROCESS",
                }
                integrity_str = integrity_map.get(integrity_val, f"CUSTOM ({hex(integrity_val)})")
                report["integrity"] = {
                    "status": "DETECTED",
                    "level_raw": hex(integrity_val),
                    "level_name": integrity_str,
                }
            else:
                report["integrity"] = {
                    "status": "DIAGNOSTIC_FAILURE",
                    "error_code": kernel32.GetLastError(),
                    "message": "GetTokenInformation(TokenIntegrityLevel) failed",
                }

            # Token Elevation (UAC)
            TokenElevation = 20
            elevation_val = wintypes.DWORD()
            if advapi32.GetTokenInformation(h_token, TokenElevation, ctypes.byref(elevation_val), ctypes.sizeof(elevation_val), ctypes.byref(needed)):
                report["elevation"] = {
                    "status": "DETECTED",
                    "is_elevated": bool(elevation_val.value != 0),
                }
            else:
                report["elevation"] = {
                    "status": "DIAGNOSTIC_FAILURE",
                    "error_code": kernel32.GetLastError(),
                }
        finally:
            kernel32.CloseHandle(h_token)
    else:
        err = kernel32.GetLastError()
        report["integrity"] = {"status": "DIAGNOSTIC_FAILURE", "error_code": err}
        report["elevation"] = {"status": "DIAGNOSTIC_FAILURE", "error_code": err}

    # -------------------------------------------------------------------------
    # 4. Windows Session
    # -------------------------------------------------------------------------
    session_id = wintypes.DWORD()
    if kernel32.ProcessIdToSessionId(pid, ctypes.byref(session_id)):
        proc_session = session_id.value
        proc_session_status = "DETECTED"
    else:
        proc_session = None
        proc_session_status = "DIAGNOSTIC_FAILURE"

    active_console_session = kernel32.WTSGetActiveConsoleSessionId()
    # 0xFFFFFFFF means no session attached to console
    if active_console_session == 0xFFFFFFFF:
        console_status = "UNAVAILABLE"
        active_session_val = None
    else:
        console_status = "DETECTED"
        active_session_val = active_console_session

    is_interactive_session = (
        proc_session is not None
        and active_session_val is not None
        and proc_session == active_session_val
    )

    report["session"] = {
        "status": proc_session_status,
        "process_session_id": proc_session,
        "active_console_session_id": active_session_val,
        "console_status": console_status,
        "is_attached_to_interactive_session": is_interactive_session,
    }

    # -------------------------------------------------------------------------
    # 5. Window Station & Desktop Context
    # -------------------------------------------------------------------------
    UOI_NAME = 2
    UOI_FLAGS = 1

    # Query Process Window Station
    hwinsta = user32.GetProcessWindowStation()
    winsta_name = None
    winsta_visible = None

    if hwinsta:
        name_buf = ctypes.create_unicode_buffer(512)
        needed = wintypes.DWORD()
        if user32.GetUserObjectInformationW(hwinsta, UOI_NAME, name_buf, ctypes.sizeof(name_buf), ctypes.byref(needed)):
            winsta_name = name_buf.value

        class USEROBJECTFLAGS(ctypes.Structure):
            _fields_ = [
                ("fInherit", wintypes.BOOL),
                ("fReserved", wintypes.BOOL),
                ("dwFlags", wintypes.DWORD),
            ]

        flags = USEROBJECTFLAGS()
        if user32.GetUserObjectInformationW(hwinsta, UOI_FLAGS, ctypes.byref(flags), ctypes.sizeof(flags), ctypes.byref(needed)):
            WSF_VISIBLE = 0x0001
            winsta_visible = bool(flags.dwFlags & WSF_VISIBLE)

    # Query Current Thread Desktop
    tid = kernel32.GetCurrentThreadId()
    hdesk = user32.GetThreadDesktop(tid)
    thread_desk_name = None

    if hdesk:
        name_buf = ctypes.create_unicode_buffer(512)
        needed = wintypes.DWORD()
        if user32.GetUserObjectInformationW(hdesk, UOI_NAME, name_buf, ctypes.sizeof(name_buf), ctypes.byref(needed)):
            thread_desk_name = name_buf.value

    # Query Active Input Desktop
    # DESKTOP_READOBJECTS = 0x0001
    h_input_desk = user32.OpenInputDesktop(0, False, 0x0001)
    input_desk_name = None
    input_desk_error = None

    if h_input_desk:
        name_buf = ctypes.create_unicode_buffer(512)
        needed = wintypes.DWORD()
        if user32.GetUserObjectInformationW(h_input_desk, UOI_NAME, name_buf, ctypes.sizeof(name_buf), ctypes.byref(needed)):
            input_desk_name = name_buf.value
        user32.CloseDesktop(h_input_desk)
    else:
        input_desk_error = kernel32.GetLastError()

    # Desktop comparison
    is_on_active_input_desktop = (
        thread_desk_name is not None
        and input_desk_name is not None
        and thread_desk_name.lower() == input_desk_name.lower()
    )

    report["station_and_desktop"] = {
        "status": "DETECTED" if (winsta_name and thread_desk_name) else "PARTIAL",
        "window_station_handle": hex(hwinsta) if hwinsta else None,
        "window_station_name": winsta_name,
        "window_station_is_visible": winsta_visible,
        "thread_desktop_handle": hex(hdesk) if hdesk else None,
        "thread_desktop_name": thread_desk_name,
        "active_input_desktop_name": input_desk_name,
        "active_input_desktop_open_error": input_desk_error,
        "is_on_active_input_desktop": is_on_active_input_desktop,
    }

    # -------------------------------------------------------------------------
    # 6. DPI-Awareness Context
    # -------------------------------------------------------------------------
    dpi_desc = "UNKNOWN"
    dpi_raw = None
    try:
        if hasattr(user32, "GetThreadDpiAwarenessContext"):
            user32.GetThreadDpiAwarenessContext.restype = wintypes.HANDLE
            ctx = user32.GetThreadDpiAwarenessContext()
            dpi_raw = hex(ctx) if ctx else None

            # Compare against known contexts
            if hasattr(user32, "AreDpiAwarenessContextsEqual"):
                user32.AreDpiAwarenessContextsEqual.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
                user32.AreDpiAwarenessContextsEqual.restype = wintypes.BOOL
                # DPI awareness contexts:
                # -1: Unaware
                # -2: System Aware
                # -3: Per Monitor Aware
                # -4: Per Monitor Aware V2
                # -5: Unaware (GDIScaled)
                DPI_UNAWARE = ctypes.cast(-1, wintypes.HANDLE)
                DPI_SYSTEM = ctypes.cast(-2, wintypes.HANDLE)
                DPI_PER_MONITOR = ctypes.cast(-3, wintypes.HANDLE)
                DPI_PER_MONITOR_V2 = ctypes.cast(-4, wintypes.HANDLE)

                if user32.AreDpiAwarenessContextsEqual(ctx, DPI_PER_MONITOR_V2):
                    dpi_desc = "PER_MONITOR_AWARE_V2"
                elif user32.AreDpiAwarenessContextsEqual(ctx, DPI_PER_MONITOR):
                    dpi_desc = "PER_MONITOR_AWARE"
                elif user32.AreDpiAwarenessContextsEqual(ctx, DPI_SYSTEM):
                    dpi_desc = "SYSTEM_AWARE"
                elif user32.AreDpiAwarenessContextsEqual(ctx, DPI_UNAWARE):
                    dpi_desc = "UNAWARE"
                else:
                    dpi_desc = f"OTHER ({dpi_raw})"
            else:
                dpi_desc = f"RAW ({dpi_raw})"
    except Exception as e:
        dpi_desc = f"QUERY_FAILED ({e})"

    report["dpi"] = {
        "status": "DETECTED" if dpi_desc != "UNKNOWN" else "UNSUPPORTED",
        "context_raw": dpi_raw,
        "description": dpi_desc,
    }

    # -------------------------------------------------------------------------
    # 7. Virtual-Screen Dimensions and Topology
    # -------------------------------------------------------------------------
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79

    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vcx = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    vcy = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

    # Primary monitor fallback
    cx_primary = user32.GetSystemMetrics(0)
    cy_primary = user32.GetSystemMetrics(1)

    report["screen"] = {
        "status": "DETECTED",
        "virtual_origin": {"x": vx, "y": vy},
        "virtual_dimensions": {"width": vcx, "height": vcy},
        "primary_dimensions": {"width": cx_primary, "height": cy_primary},
    }

    # -------------------------------------------------------------------------
    # 8. Win32 API Access Verification (Read-Only)
    # -------------------------------------------------------------------------
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    pt = POINT()
    cursor_ok = bool(user32.GetCursorPos(ctypes.byref(pt)))
    cursor_err = kernel32.GetLastError() if not cursor_ok else 0

    hwnd_fg = user32.GetForegroundWindow()
    fg_title = None
    if hwnd_fg:
        tbuf = ctypes.create_unicode_buffer(512)
        if user32.GetWindowTextW(hwnd_fg, tbuf, ctypes.sizeof(tbuf)):
            fg_title = tbuf.value

    # Check SendInput export presence (without invoking it)
    has_send_input = hasattr(user32, "SendInput")

    report["win32_access"] = {
        "status": "DETECTED",
        "get_cursor_pos_success": cursor_ok,
        "cursor_position": {"x": pt.x, "y": pt.y} if cursor_ok else None,
        "get_cursor_pos_error": cursor_err if not cursor_ok else None,
        "foreground_window_handle": hex(hwnd_fg) if hwnd_fg else None,
        "foreground_window_title": fg_title,
        "send_input_exported": has_send_input,
    }

    # -------------------------------------------------------------------------
    # 9. Environmental Context Synthesis
    # -------------------------------------------------------------------------
    # Determine whether current process is in an interactive or sandboxed/background state
    is_interactive_desktop = bool(
        is_interactive_session
        and winsta_name == "WinSta0"
        and winsta_visible is True
        and is_on_active_input_desktop is True
    )

    report["execution_context_synthesis"] = {
        "is_interactive_desktop": is_interactive_desktop,
        "summary": (
            "INTERACTIVE_DESKTOP" if is_interactive_desktop
            else "NON_INTERACTIVE_OR_ISOLATED_DESKTOP"
        ),
        "desktop_mismatch_detected": (thread_desk_name != input_desk_name),
        "notes": (
            "Process is attached to active input desktop."
            if is_interactive_desktop
            else f"Thread is attached to desktop '{thread_desk_name}', but physical input desktop is '{input_desk_name}'."
        ),
    }

    return report


def print_diagnostic_report(diag: Dict[str, Any]) -> None:
    """Prints diagnostic report in a clean, human-readable format."""
    print("=" * 70)
    print("ASTRA — PHASE B.3.5: READ-ONLY ENVIRONMENT DIAGNOSTIC")
    print("=" * 70)

    # Python
    py = diag["python"]
    print(f"\n[1] Python Environment: [{py['status']}]")
    print(f"    Executable:   {py['executable']}")
    print(f"    Version:      {py['version']} (64-bit: {py['is_64bit']})")

    # Process
    proc = diag["process"]
    integ = diag["integrity"]
    elev = diag["elevation"]
    print(f"\n[2] Process & Token: [{proc['status']}]")
    print(f"    PID:          {proc['pid']}  |  Parent PID: {proc['ppid']}")
    print(f"    Integrity:    {integ.get('level_name', 'UNKNOWN')} ({integ.get('level_raw', 'UNKNOWN')})")
    print(f"    Elevated:     {elev.get('is_elevated', 'UNKNOWN')}")

    # Session
    sess = diag["session"]
    print(f"\n[3] Windows Session: [{sess['status']}]")
    print(f"    Process Session ID:        {sess['process_session_id']}")
    print(f"    Active Console Session ID: {sess['active_console_session_id']} ({sess['console_status']})")
    print(f"    Interactive Session Match: {sess['is_attached_to_interactive_session']}")

    # Window Station & Desktop
    sd = diag["station_and_desktop"]
    print(f"\n[4] Window Station & Desktop Context: [{sd['status']}]")
    print(f"    Window Station:            {sd['window_station_name']} (Visible: {sd['window_station_is_visible']})")
    print(f"    Thread Desktop:            {sd['thread_desktop_name']}")
    print(f"    Active Input Desktop:      {sd['active_input_desktop_name']}")
    print(f"    Attached to Input Desktop: {sd['is_on_active_input_desktop']}")
    if sd.get("active_input_desktop_open_error"):
        print(f"    OpenInputDesktop Error:    {sd['active_input_desktop_open_error']}")

    # DPI
    dpi = diag["dpi"]
    print(f"\n[5] DPI-Awareness Context: [{dpi['status']}]")
    print(f"    Awareness:                 {dpi['description']}")

    # Screen
    scr = diag["screen"]
    print(f"\n[6] Screen Geometry: [{scr['status']}]")
    print(f"    Virtual Screen Origin:     ({scr['virtual_origin']['x']}, {scr['virtual_origin']['y']})")
    print(f"    Virtual Dimensions:        {scr['virtual_dimensions']['width']}x{scr['virtual_dimensions']['height']}")
    print(f"    Primary Monitor:           {scr['primary_dimensions']['width']}x{scr['primary_dimensions']['height']}")

    # Win32 Access
    w32 = diag["win32_access"]
    print(f"\n[7] Win32 API Access (Read-Only): [{w32['status']}]")
    print(f"    GetCursorPos:              {'OK' if w32['get_cursor_pos_success'] else 'FAILED'} (Pos: {w32['cursor_position']})")
    print(f"    Foreground Window:         {w32['foreground_window_handle']} (Title: '{w32['foreground_window_title']}')")
    print(f"    SendInput Exported:        {w32['send_input_exported']}")

    # Synthesis
    syn = diag["execution_context_synthesis"]
    print(f"\n[8] Execution Context Synthesis:")
    print(f"    Classification:            {syn['summary']}")
    print(f"    Desktop Mismatch:          {syn['desktop_mismatch_detected']}")
    print(f"    Assessment:                {syn['notes']}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    report = diagnose_environment()
    print_diagnostic_report(report)
