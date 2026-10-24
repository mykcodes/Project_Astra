"""
ASTRA — Phase B.5: Universal Physical Scroll, Drag & Advanced Mouse Interaction Live Verification Test (OPT-IN ONLY)

Validates the complete physical scroll, right-click, and advanced mouse interaction lifecycle against a real Notepad window:
1. Environment pre-flight check (interactive desktop context).
2. Window establishment and focus verification.
3. Establishing multi-line text buffer for unambiguous viewport displacement testing.
4. Pre-action visual capture and real Windows.Media.Ocr perception.
5. Production scroll execution:
   ActionExecutor → ExecutePhysicalInputTool(intent="SCROLL") → InteractionRouter → MouseController.actuate_scroll
6. Fresh post-action visual capture and real Windows.Media.Ocr perception.
7. Semantic scroll verification via VerificationEngine.verify_scroll within Notepad bounds.
8. Production context menu execution:
   ActionExecutor → ExecutePhysicalInputTool(intent="RIGHT_CLICK") → InteractionRouter → MouseController.actuate_right_click
9. Harmless cleanup: Dismiss context menu with Escape, clear buffer with Ctrl+A and Backspace, and verify clean state.
"""

import sys
import os
import argparse
import asyncio
import time
import uuid
import concurrent.futures
from typing import Tuple, Dict, Any, List
import ctypes

sys.stdout.reconfigure(encoding="utf-8")

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.domain.entities import TriState
from app.domain.goals import Intent, SemanticAction, FailureClass, VerificationResult
from app.ai.orchestrator.verification import VerificationEngine
from tests.live.diagnose_interactive_actuation import diagnose_environment


def get_window_bounds(hwnd: int) -> Tuple[int, int, int, int]:
    import ctypes

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    rect = RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return int(rect.left), int(rect.top), int(rect.right - rect.left), int(rect.bottom - rect.top)


def clear_clipboard(retries: int = 5, delay: float = 0.05) -> bool:
    import ctypes
    u32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
    if not u32:
        return False
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
    import ctypes
    u32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
    k32 = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None
    if not u32 or not k32:
        return ""
    opened = False
    for _ in range(retries):
        if u32.OpenClipboard(0):
            opened = True
            break
        time.sleep(delay)
    if not opened:
        return ""
    try:
        CF_UNICODETEXT = 13
        u32.GetClipboardData.restype = ctypes.c_void_p
        u32.GetClipboardData.argtypes = [ctypes.c_uint]
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalLock.argtypes = [ctypes.c_void_p]
        k32.GlobalUnlock.argtypes = [ctypes.c_void_p]

        h_mem = u32.GetClipboardData(CF_UNICODETEXT)
        if not h_mem:
            return ""
        p_mem = k32.GlobalLock(h_mem)
        if not p_mem:
            return ""
        try:
            return ctypes.c_wchar_p(p_mem).value or ""
        finally:
            k32.GlobalUnlock(h_mem)
    finally:
        u32.CloseClipboard()


def print_banner(text: str):
    print("\n" + "=" * 75)
    print(text)
    print("=" * 75)


async def run_live_scroll_drag_test(opt_in_confirmed: bool = False) -> int:
    print_banner("ASTRA - PHASE B.5: PHYSICAL SCROLL, DRAG & ADVANCED MOUSE TEST")

    # -------------------------------------------------------------------------
    # STAGE 0: Pre-Flight Environment Diagnostic Check
    # -------------------------------------------------------------------------
    diag = diagnose_environment()
    syn = diag["execution_context_synthesis"]
    sd = diag["station_and_desktop"]

    print("\n[STAGE 0] Pre-Flight Desktop Context:")
    print(f"  Classification:        {syn['summary']}")
    print(f"  Thread Desktop:        {sd['thread_desktop_name']}")
    print(f"  Active Input Desktop:  {sd['active_input_desktop_name']}")
    print(f"  Attached to Input:     {sd['is_on_active_input_desktop']}")

    if not opt_in_confirmed:
        print("\n[OPT-IN REQUIRED - SAFETY SAFEGUARD]")
        print("  This live test requires the explicit '--execute' flag.")
        print("  No physical mouse input or window manipulation was actuated.")
        print("\n  Pre-flight readiness check completed.")
        print("  To run the full verified scroll & advanced mouse test against Notepad, run:")
        print("    python tests/live/test_live_scroll_drag_interaction.py --execute\n")
        print_banner("ASTRA - PHASE B.5: DRY-RUN COMPLETED")
        return 0

    print("\n[OPT-IN CONFIRMED] Explicit execution authorization granted by user.")

    from app.domain.entities import ScreenPoint
    from app.domain.visual import VisualObservation
    from app.environment.window.manager import window_manager
    from app.environment.visual.capture import screen_capture_provider
    from app.environment.visual.perception import _run_windows_media_ocr
    from app.environment.visual.tracker import interaction_tracker
    from app.tools.desktop.desktop_controller import ApplicationIntent, desktop_controller
    from app.ai.orchestrator.action_executor import action_executor
    from app.interaction.input.keyboard_controller import keyboard_controller

    # -------------------------------------------------------------------------
    # STAGE 1: Application State & Window Establishment
    # -------------------------------------------------------------------------
    print("\n[STAGE 1] Application State & Window Establishment:")
    app_status = desktop_controller.get_application_status("Notepad")
    print(f"  Initial Notepad State: {app_status.get('state')} (Installed: {app_status.get('installed')})")

    open_res = await desktop_controller.execute_intent(ApplicationIntent.OPEN, "Notepad")
    if not open_res.get("success"):
        print(f"  [ERROR] Failed to establish Notepad application state: {open_res}")
        return 1

    await asyncio.sleep(1.0)

    # Re-query active window geometry
    refreshed_status = desktop_controller.get_application_status("Notepad")
    windows = refreshed_status.get("windows", [])
    if not windows:
        print("  [ERROR] No active Notepad windows found after launch/focus.")
        return 1

    active_win = windows[0]
    best_hwnd = active_win.get("hwnd")
    window_manager.move_to_main_screen(best_hwnd)
    await asyncio.sleep(0.3)
    window_manager.restore_and_focus(best_hwnd)
    await asyncio.sleep(1.5)

    win_x, win_y, win_w, win_h = (
        get_window_bounds(best_hwnd)
        if window_manager.user32
        else (
            active_win.get("x", 0),
            active_win.get("y", 0),
            active_win.get("width", 1920),
            active_win.get("height", 1080),
        )
    )
    is_fg = (window_manager.user32.GetForegroundWindow() == best_hwnd) if window_manager.user32 else False

    print(f"  Target Window HWND:    {best_hwnd}")
    print(f"  Window Title:          '{active_win.get('title')}'")
    print(f"  Window Geometry:       x={win_x}, y={win_y}, w={win_w}, h={win_h}")
    print(f"  Window Foreground:     {is_fg}")

    # Calculate document area bounds
    doc_x = win_x + 15
    doc_y = win_y + 90
    doc_w = win_w - 30
    doc_h = min(450, win_h - 220)
    doc_bounds = (doc_x, doc_y, doc_w, doc_h)
    print(f"  Document Area Bounds:  x={doc_x}, y={doc_y}, w={doc_w}, h={doc_h}")

    # Center click coordinate inside document editor
    click_x = doc_x + min(300, doc_w // 3)
    click_y = doc_y + 120
    print(f"  Focusing Document:     Click at ({click_x}, {click_y})")

    await action_executor.execute_intent(
        intent=Intent(
            intent_id=str(uuid.uuid4()),
            action=SemanticAction.CLICK,
            capability_id="desktop.physical_input",
            target="Notepad_Document_Area",
        ),
        tool_args={"intent": "CLICK", "x": click_x, "y": click_y},
    )
    await asyncio.sleep(0.3)

    # Ensure starting document editor buffer is clean
    await action_executor.execute_intent(
        intent=Intent(
            intent_id=str(uuid.uuid4()),
            action=SemanticAction.HOTKEY,
            capability_id="desktop.physical_input",
            target="Notepad_Editor",
        ),
        tool_args={"intent": "HOTKEY", "keys": ["ctrl", "a"]},
    )
    await asyncio.sleep(0.1)
    await action_executor.execute_intent(
        intent=Intent(
            intent_id=str(uuid.uuid4()),
            action=SemanticAction.PRESS_KEY,
            capability_id="desktop.physical_input",
            target="Notepad_Editor",
        ),
        tool_args={"intent": "PRESS_KEY", "key": "backspace"},
    )
    await asyncio.sleep(0.3)

    # -------------------------------------------------------------------------
    # STAGE 2: Populate Multi-line Buffer for Scroll Measurement
    # -------------------------------------------------------------------------
    print("\n[STAGE 2] Populating Multi-line Buffer for Scroll Measurement:")
    unique_token = uuid.uuid4().hex[:6]
    test_prefix = f"Astra Scroll {unique_token}"
    # Build 25 distinct numbered lines with unique token to ensure full vertical scrollability and clean isolation
    lines_text = "\n".join([f"{test_prefix} Line {i:02d} Payload" for i in range(1, 26)])
    print(f"  Typing 25 numbered test lines into document editor (Token: '{unique_token}')...")

    await action_executor.execute_intent(
        intent=Intent(
            intent_id=str(uuid.uuid4()),
            action=SemanticAction.INPUT,
            capability_id="desktop.physical_input",
            target="Notepad_Editor",
        ),
        tool_args={
            "intent": "TYPE_TEXT",
            "x": click_x,
            "y": click_y,
            "text": lines_text + "\n",
        },
    )
    await asyncio.sleep(1.0)

    # Scroll back to top of document via Ctrl+Home
    print("  Repositioning viewport to top via Ctrl+Home...")
    await action_executor.execute_intent(
        intent=Intent(
            intent_id=str(uuid.uuid4()),
            action=SemanticAction.HOTKEY,
            capability_id="desktop.physical_input",
            target="Notepad_Editor",
        ),
        tool_args={"intent": "HOTKEY", "keys": ["ctrl", "home"]},
    )
    await asyncio.sleep(0.8)

    # -------------------------------------------------------------------------
    # STAGE 3: Pre-Action Visual Capture & Perception
    # -------------------------------------------------------------------------
    print("\n[STAGE 3] Pre-Action Visual Observation Capture:")
    obs_pre_id = f"b5_pre_{uuid.uuid4().hex[:8]}"
    obs_pre = screen_capture_provider.capture_virtual_screen(obs_pre_id)
    print(f"  Pre-Action Obs ID:     {obs_pre.observation_id}")
    print(f"  Capture Timestamp:     {obs_pre.captured_at.isoformat()}")

    pre_bytes = screen_capture_provider.store.retrieve(obs_pre.image_reference)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        detections_before = pool.submit(
            _run_windows_media_ocr,
            pre_bytes,
            obs_pre.width,
            obs_pre.height,
        ).result()
    print(f"  Pre-Action OCR Items:  {len(detections_before)} elements detected")

    # -------------------------------------------------------------------------
    # STAGE 4: Production Scroll Actuation
    # -------------------------------------------------------------------------
    print("\n[STAGE 4] Executing Mouse Wheel Scroll via Production Pipeline:")
    print("  Execution Path: ActionExecutor → ExecutePhysicalInputTool(SCROLL) → InteractionRouter → MouseController.actuate_scroll")

    scroll_intent = Intent(
        intent_id=str(uuid.uuid4()),
        action=SemanticAction.SCROLL,
        capability_id="desktop.physical_input",
        target="Notepad_Editor",
    )
    scroll_args = {
        "intent": "SCROLL",
        "clicks": -6,  # Scroll down 6 wheel notches (content shifts upwards)
        "x": click_x,
        "y": click_y,
    }
    t_scroll_start = time.perf_counter()
    scroll_res = await action_executor.execute_intent(scroll_intent, scroll_args, max_attempts=1)
    t_scroll_end = time.perf_counter()

    print(f"  Actuation Success:     {scroll_res.get('success')}")
    print(f"  Action Performed:      {scroll_res.get('action')}")
    print(f"  Actuation Elapsed:     {(t_scroll_end - t_scroll_start)*1000:.1f}ms")

    # Allow DWM compositor settle
    await asyncio.sleep(0.8)

    # -------------------------------------------------------------------------
    # STAGE 5: Fresh Post-Action Visual Capture & Perception
    # -------------------------------------------------------------------------
    print("\n[STAGE 5] Fresh Post-Action Visual Capture:")
    obs_post_id = f"b5_post_{uuid.uuid4().hex[:8]}"
    obs_post = screen_capture_provider.capture_virtual_screen(obs_post_id)
    print(f"  Post-Action Obs ID:    {obs_post.observation_id}")
    print(f"  Fresher than Pre-Obs:  {obs_post.captured_at > obs_pre.captured_at}")

    post_bytes = screen_capture_provider.store.retrieve(obs_post.image_reference)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        detections_after = pool.submit(
            _run_windows_media_ocr,
            post_bytes,
            obs_post.width,
            obs_post.height,
        ).result()
    print(f"  Post-Action OCR Items: {len(detections_after)} elements detected")

    # -------------------------------------------------------------------------
    # STAGE 6: Semantic Scroll Verification
    # -------------------------------------------------------------------------
    print("\n[STAGE 6] Semantic Scroll Verification:")
    scroll_vr: VerificationResult = VerificationEngine.verify_scroll(
        obs_before=obs_pre,
        obs_after=obs_post,
        detections_before=detections_before,
        detections_after=detections_after,
        target_bounds=doc_bounds,
    )

    print(f"  Verification Result:   {scroll_vr.verified.name}")
    print(f"  Actual State:          {scroll_vr.actual_state}")
    print(f"  Confidence:            {scroll_vr.confidence}")
    print(f"  Evidence:              {scroll_vr.evidence}")

    # -------------------------------------------------------------------------
    # STAGE 7: Physical Mouse Drag Actuation & Semantic Drag Verification
    # -------------------------------------------------------------------------
    print("\n[STAGE 7] Executing Mouse Drag via Production Pipeline:")
    print("  Execution Path: ActionExecutor → ExecutePhysicalInputTool(DRAG) → InteractionRouter → MouseController.actuate_drag")

    # In modern GUI automation, mouse drag is authoritatively validated via Text Selection Drag.
    # In WinUI 3 modern apps, title bar dragging is handled via WinRT pointer composition and does not
    # allow synthetic SendInput window moves, while dragging across text exercises physical mouse down,
    # multi-step trajectory interpolation, and guaranteed button release with 100% mathematical fidelity.

    # 1. Locate the typed test payload on screen strictly within document editor bounds.
    # Scoping search to doc_bounds is critical: Notepad's tab bar/title bar also previews
    # the document title/text at the top of the window, which would otherwise be matched first.
    drag_target_text = unique_token
    doc_x, doc_y, doc_w, doc_h = doc_bounds

    candidates = []
    for item in detections_after:
        if len(item) >= 2 and isinstance(item[1], str) and drag_target_text in item[1]:
            box = item[0]
            if len(box) == 4 and isinstance(box[0], (int, float)):
                bx, by, bw, bh = float(box[0]), float(box[1]), float(box[2]), float(box[3])
            elif len(box) == 4 and isinstance(box[0], (list, tuple)):
                xs = [float(p[0]) for p in box]
                ys = [float(p[1]) for p in box]
                bx, by = min(xs), min(ys)
                bw, bh = max(xs) - bx, max(ys) - by
            else:
                continue

            # Must be strictly within document bounds (excluding tab bar, title bar, and bottom margins)
            if doc_x <= bx <= doc_x + doc_w and (doc_y + 10) <= by <= (doc_y + doc_h - 20):
                candidates.append((bx, by, bw, bh, item[1]))

    if candidates:
        # Separate exact word tokens from full line detections
        word_candidates = [c for c in candidates if c[4].strip() == drag_target_text]
        pool = word_candidates if word_candidates else candidates
        target_center_y = doc_y + doc_h / 2
        pool.sort(key=lambda c: abs(c[1] - target_center_y))
        bx, by, bw, bh, matched_str = pool[0]

        # Drag across the candidate token with sufficient horizontal padding
        drag_start_x = max(doc_x + 10, int(bx - 20))
        drag_start_y = int(by + bh / 2)
        drag_end_x = min(doc_x + doc_w - 20, int(bx + bw + 40))
        drag_end_y = int(by + bh / 2)
    else:
        # Fallback to document editor bounds if OCR token was fragmented
        drag_start_x = click_x
        drag_start_y = click_y
        drag_end_x = click_x + 350
        drag_end_y = click_y

    print(f"  Dragging Across Text:  ({drag_start_x}, {drag_start_y}) → ({drag_end_x}, {drag_end_y}) [steps=15]")

    # Clear OS clipboard prior to drag actuation to guarantee no stale payload
    clear_clipboard()

    # Ensure target window has foreground focus before drag
    fg_hwnd = window_manager.user32.GetForegroundWindow() if window_manager.user32 else 0
    if fg_hwnd != best_hwnd:
        window_manager.restore_and_focus(best_hwnd)
        await asyncio.sleep(0.3)

    drag_intent = Intent(
        intent_id=str(uuid.uuid4()),
        action=SemanticAction.DRAG,
        capability_id="desktop.physical_input",
        target="Notepad_Editor",
    )
    drag_args = {
        "intent": "DRAG",
        "x": drag_start_x,
        "y": drag_start_y,
        "start_x": drag_start_x,
        "start_y": drag_start_y,
        "end_x": drag_end_x,
        "end_y": drag_end_y,
        "steps": 15,
    }
    t_drag_start = time.perf_counter()
    drag_res = await action_executor.execute_intent(drag_intent, drag_args, max_attempts=1)
    t_drag_end = time.perf_counter()
    print(f"  Drag Actuation:        {drag_res.get('success')} (Elapsed: {(t_drag_end - t_drag_start)*1000:.1f}ms)")

    # Verify physical button release: In Win32, the high bit (0x8000) indicates the button
    # is currently held down. High bit == 0 proves the button is currently RELEASED / UP.
    user32_mod = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
    button_is_up = ((user32_mod.GetAsyncKeyState(0x01) & 0x8000) == 0) if user32_mod else True
    button_released = button_is_up and drag_res.get("diagnostics", {}).get("button_up_accepted", True)
    print(f"  Button Release Verified: {button_released}")

    # Allow DWM compositor settle
    await asyncio.sleep(0.4)

    # Copy selected text via Ctrl+C to verify physical drag selection via OS clipboard
    await action_executor.execute_intent(
        intent=Intent(
            intent_id=str(uuid.uuid4()),
            action=SemanticAction.HOTKEY,
            capability_id="desktop.physical_input",
            target="Notepad_Editor",
        ),
        tool_args={"intent": "HOTKEY", "keys": ["ctrl", "c"]},
        max_attempts=1,
    )
    await asyncio.sleep(0.3)
    clipboard_content = get_clipboard_text()
    if not clipboard_content:
        # Fallback retry if OS hotkey dispatch needed extra settle
        await asyncio.sleep(0.2)
        await action_executor.execute_intent(
            intent=Intent(
                intent_id=str(uuid.uuid4()),
                action=SemanticAction.HOTKEY,
                capability_id="desktop.physical_input",
                target="Notepad_Editor",
            ),
            tool_args={"intent": "HOTKEY", "keys": ["ctrl", "c"]},
            max_attempts=1,
        )
        await asyncio.sleep(0.3)
        clipboard_content = get_clipboard_text()

    clip_preview = clipboard_content.strip().replace("\n", " ")[:40]
    print(f"  Copied Selection:      '{clip_preview}...' (Length: {len(clipboard_content)})")

    # Capture fresh post-drag observation
    obs_drag_id = f"b5_drag_{uuid.uuid4().hex[:8]}"
    obs_drag = screen_capture_provider.capture_virtual_screen(obs_drag_id)
    drag_bytes = screen_capture_provider.store.retrieve(obs_drag.image_reference)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        detections_drag = pool.submit(
            _run_windows_media_ocr,
            drag_bytes,
            obs_drag.width,
            obs_drag.height,
        ).result()

    # Semantic Drag Verification via VerificationEngine
    drag_vr: VerificationResult = VerificationEngine.verify_drag(
        obs_before=obs_post,
        obs_after=obs_drag,
        target_label=unique_token,
        expected_destination_bounds=(drag_start_x, drag_start_y, drag_end_x - drag_start_x, 30),
        detections_before=detections_after,
        detections_after=detections_drag,
        clipboard_text=clipboard_content,
    )
    drag_verified = (drag_vr.verified == TriState.TRUE)
    print(f"  Drag Verification:     {'TRUE' if drag_verified else 'FALSE'}")
    print(f"  Drag Evidence:         {drag_vr.evidence}")

    # Dismiss text selection cleanly with Right Arrow key so text remains unselected
    await action_executor.execute_intent(
        intent=Intent(
            intent_id=str(uuid.uuid4()),
            action=SemanticAction.PRESS_KEY,
            capability_id="desktop.physical_input",
            target="Notepad_Editor",
        ),
        tool_args={"intent": "PRESS_KEY", "key": "right"},
        max_attempts=1,
    )
    await asyncio.sleep(0.3)

    # -------------------------------------------------------------------------
    # STAGE 8: Right Click Context Menu Actuation & Formal Verification
    # -------------------------------------------------------------------------
    print("\n[STAGE 8] Executing Right Click Context Menu via Production Pipeline:")
    print("  Execution Path: ActionExecutor → ExecutePhysicalInputTool(RIGHT_CLICK) → InteractionRouter → MouseController.actuate_right_click")

    # 1. Guarantee target window is restored and focused before right clicking
    fg_hwnd = window_manager.user32.GetForegroundWindow() if window_manager.user32 else 0
    if fg_hwnd != best_hwnd:
        print(f"  [STAGE 8 FOCUS] Restoring foreground focus to target window ({best_hwnd})...")
        window_manager.restore_and_focus(best_hwnd)
        await asyncio.sleep(0.5)

    # 2. Click document canvas to establish caret and ensure active editor state
    await action_executor.execute_intent(
        intent=Intent(
            intent_id=str(uuid.uuid4()),
            action=SemanticAction.CLICK,
            capability_id="desktop.physical_input",
            target="Notepad_Editor",
        ),
        tool_args={"intent": "CLICK", "x": click_x, "y": click_y},
        max_attempts=1,
    )
    await asyncio.sleep(0.4)

    # 3. Capture clean pre-right-click observation
    obs_rc_pre_id = f"b5_rc_pre_{uuid.uuid4().hex[:8]}"
    obs_rc_pre = screen_capture_provider.capture_virtual_screen(obs_rc_pre_id)
    rc_pre_bytes = screen_capture_provider.store.retrieve(obs_rc_pre.image_reference)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        detections_rc_pre = pool.submit(
            _run_windows_media_ocr,
            rc_pre_bytes,
            obs_rc_pre.width,
            obs_rc_pre.height,
        ).result()

    # 4. Actuate physical RIGHT_CLICK
    rc_intent = Intent(
        intent_id=str(uuid.uuid4()),
        action=SemanticAction.RIGHT_CLICK,
        capability_id="desktop.physical_input",
        target="Notepad_Editor",
    )
    rc_res = await action_executor.execute_intent(
        rc_intent,
        {"intent": "RIGHT_CLICK", "x": click_x, "y": click_y},
        max_attempts=1,
    )
    print(f"  Right Click Success:   {rc_res.get('success')}")
    await asyncio.sleep(0.8)

    # 5. Capture post-right-click observation
    obs_rc_id = f"b5_rc_{uuid.uuid4().hex[:8]}"
    obs_rc = screen_capture_provider.capture_virtual_screen(obs_rc_id)
    rc_bytes = screen_capture_provider.store.retrieve(obs_rc.image_reference)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        detections_rc = pool.submit(
            _run_windows_media_ocr,
            rc_bytes,
            obs_rc.width,
            obs_rc.height,
        ).result()

    # 6. Formal semantic verification via VerificationEngine.verify_context_menu
    cm_vr: VerificationResult = VerificationEngine.verify_context_menu(
        obs_before=obs_rc_pre,
        obs_after=obs_rc,
        click_point=(click_x, click_y),
        window_bounds=(win_x, win_y, win_w, win_h),
        detections_before=detections_rc_pre,
        detections_after=detections_rc,
    )

    # Settle retry if compositor animation was still transitioning
    if cm_vr.verified != TriState.TRUE:
        await asyncio.sleep(0.5)
        obs_rc_retry_id = f"b5_rc_retry_{uuid.uuid4().hex[:8]}"
        obs_rc_retry = screen_capture_provider.capture_virtual_screen(obs_rc_retry_id)
        rc_retry_bytes = screen_capture_provider.store.retrieve(obs_rc_retry.image_reference)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            detections_rc_retry = pool.submit(
                _run_windows_media_ocr,
                rc_retry_bytes,
                obs_rc_retry.width,
                obs_rc_retry.height,
            ).result()
        cm_vr = VerificationEngine.verify_context_menu(
            obs_before=obs_rc_pre,
            obs_after=obs_rc_retry,
            click_point=(click_x, click_y),
            window_bounds=(win_x, win_y, win_w, win_h),
            detections_before=detections_rc_pre,
            detections_after=detections_rc_retry,
        )

    cm_success = (cm_vr.verified == TriState.TRUE)
    print(f"  Context Menu Detected: {cm_success} ({cm_vr.actual_state})")
    print(f"  Context Menu Evidence: {cm_vr.evidence}")

    # -------------------------------------------------------------------------
    # STAGE 9: Harmless Cleanup (Dismiss Context Menu & Clear Buffer)
    # -------------------------------------------------------------------------
    print("\n[STAGE 9] Harmless Cleanup:")

    # Step 9.1: Dismiss context menu with hardware Escape
    print("  Dismissing context menu via Escape keystrokes...")
    keyboard_controller.actuate_escape(press_count=2)
    await asyncio.sleep(0.5)

    # Step 9.2: Ensure Notepad window has foreground focus
    fg_hwnd = window_manager.user32.GetForegroundWindow() if window_manager.user32 else 0
    if fg_hwnd != best_hwnd:
        print(f"  [FOCUS CHECK] Target window ({best_hwnd}) not foreground (current={fg_hwnd}); restoring...")
        window_manager.restore_and_focus(best_hwnd)
        await asyncio.sleep(0.3)

    # Step 9.3: Explicitly click document editor to re-engage caret focus before typing
    print(f"  Re-engaging document caret focus: Click at ({click_x}, {click_y})...")
    await action_executor.execute_intent(
        intent=Intent(
            intent_id=str(uuid.uuid4()),
            action=SemanticAction.CLICK,
            capability_id="desktop.physical_input",
            target="Notepad_Document_Area",
        ),
        tool_args={"intent": "CLICK", "x": click_x, "y": click_y},
        max_attempts=1,
    )
    await asyncio.sleep(0.3)

    # Step 9.4: Clear document editor buffer via Ctrl+A + Backspace
    print("  Clearing document editor buffer via Ctrl+A + Backspace...")
    await action_executor.execute_intent(
        intent=Intent(
            intent_id=str(uuid.uuid4()),
            action=SemanticAction.HOTKEY,
            capability_id="desktop.physical_input",
            target="Notepad_Editor",
        ),
        tool_args={"intent": "HOTKEY", "keys": ["ctrl", "a"]},
        max_attempts=1,
    )
    await asyncio.sleep(0.2)

    await action_executor.execute_intent(
        intent=Intent(
            intent_id=str(uuid.uuid4()),
            action=SemanticAction.PRESS_KEY,
            capability_id="desktop.physical_input",
            target="Notepad_Editor",
        ),
        tool_args={"intent": "PRESS_KEY", "key": "backspace"},
        max_attempts=1,
    )
    await asyncio.sleep(0.6)

    # Step 9.5: Fresh observation to verify clean state
    obs_clean_id = f"b5_clean_{uuid.uuid4().hex[:8]}"
    obs_clean = screen_capture_provider.capture_virtual_screen(obs_clean_id)
    clean_bytes = screen_capture_provider.store.retrieve(obs_clean.image_reference)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        detections_clean = pool.submit(
            _run_windows_media_ocr,
            clean_bytes,
            obs_clean.width,
            obs_clean.height,
        ).result()

    clean_vr = VerificationEngine.verify_text_input(
        expected_text=test_prefix,
        obs_before=obs_pre,
        obs_after=obs_clean,
        detections_after=detections_clean,
        target_bounds=doc_bounds,
    )

    # Settle retry if DWM compositor has not flushed
    if clean_vr.verified != TriState.FALSE:
        await asyncio.sleep(0.6)
        obs_clean_retry_id = f"b5_clean_retry_{uuid.uuid4().hex[:8]}"
        obs_clean_retry = screen_capture_provider.capture_virtual_screen(obs_clean_retry_id)
        clean_retry_bytes = screen_capture_provider.store.retrieve(obs_clean_retry.image_reference)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            clean_retry_detections = pool.submit(
                _run_windows_media_ocr,
                clean_retry_bytes,
                obs_clean_retry.width,
                obs_clean_retry.height,
            ).result()
        clean_vr = VerificationEngine.verify_text_input(
            expected_text=test_prefix,
            obs_before=obs_pre,
            obs_after=obs_clean_retry,
            detections_after=clean_retry_detections,
            target_bounds=doc_bounds,
        )

    # Fallback retry if still present: re-click, Ctrl+A, Delete key
    if clean_vr.verified != TriState.FALSE:
        print("  [CLEANUP RETRY] Retrying buffer clear with click + Ctrl+A + Delete...")
        await action_executor.execute_intent(
            intent=Intent(intent_id=str(uuid.uuid4()), action=SemanticAction.CLICK, capability_id="desktop.physical_input", target="Editor"),
            tool_args={"intent": "CLICK", "x": click_x, "y": click_y},
            max_attempts=1,
        )
        await asyncio.sleep(0.2)
        await action_executor.execute_intent(
            intent=Intent(intent_id=str(uuid.uuid4()), action=SemanticAction.HOTKEY, capability_id="desktop.physical_input", target="Editor"),
            tool_args={"intent": "HOTKEY", "keys": ["ctrl", "a"]},
            max_attempts=1,
        )
        await asyncio.sleep(0.2)
        await action_executor.execute_intent(
            intent=Intent(intent_id=str(uuid.uuid4()), action=SemanticAction.PRESS_KEY, capability_id="desktop.physical_input", target="Editor"),
            tool_args={"intent": "PRESS_KEY", "key": "delete"},
            max_attempts=1,
        )
        await asyncio.sleep(0.6)

        obs_fb_id = f"b5_clean_fb_{uuid.uuid4().hex[:8]}"
        obs_fb = screen_capture_provider.capture_virtual_screen(obs_fb_id)
        fb_bytes = screen_capture_provider.store.retrieve(obs_fb.image_reference)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fb_detections = pool.submit(
                _run_windows_media_ocr,
                fb_bytes,
                obs_fb.width,
                obs_fb.height,
            ).result()
        clean_vr = VerificationEngine.verify_text_input(
            expected_text=test_prefix,
            obs_before=obs_pre,
            obs_after=obs_fb,
            detections_after=fb_detections,
            target_bounds=doc_bounds,
        )

    cleanup_success = (clean_vr.verified == TriState.FALSE)
    print(f"  Buffer Cleared:        {cleanup_success} (Verified Absence: {clean_vr.actual_state})")
    if not cleanup_success:
        print(f"  [CLEANUP EVIDENCE]     {clean_vr.evidence}")

    # -------------------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------------------
    print_banner("ASTRA - PHASE B.5: TEST EXECUTION SUMMARY")
    print(f"  Scroll Actuation:      {scroll_res.get('success')}")
    print(f"  Scroll Verification:   {scroll_vr.verified.name} ({scroll_vr.actual_state})")
    print(f"  Drag Actuation:        {drag_res.get('success')} (Button Release: {button_released})")
    print(f"  Drag Verification:     {'TRUE' if drag_verified else 'FALSE'} ({drag_vr.actual_state})")
    print(f"  Right Click Actuation: {rc_res.get('success')}")
    print(f"  Context Menu Detected: {cm_success} ({cm_vr.actual_state})")
    print(f"  Cleanup Success:       {cleanup_success}")

    overall_pass = (
        scroll_res.get("success")
        and scroll_vr.verified == TriState.TRUE
        and drag_res.get("success")
        and drag_verified
        and button_released
        and rc_res.get("success")
        and cm_success
        and cleanup_success
    )
    print(f"\n  OVERALL RESULT:        {'PASS' if overall_pass else 'FAIL'}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASTRA Phase B.5 Physical Scroll & Drag Test")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Explicitly authorize physical input actuation against Notepad.",
    )
    args = parser.parse_args()
    exit_code = asyncio.run(run_live_scroll_drag_test(opt_in_confirmed=args.execute))
    sys.exit(exit_code)
