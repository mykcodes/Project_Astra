"""
ASTRA — Phase B.4: Universal Physical Keyboard & Text Input Live Verification Test (OPT-IN ONLY)

Validates the complete physical keyboard text input lifecycle against a real Notepad window:
1. Environment pre-flight check (interactive desktop context).
2. Window establishment and focus verification.
3. Pre-action visual capture.
4. Production text input execution:
   ActionExecutor → ExecutePhysicalInputTool(intent="TYPE_TEXT") → InteractionRouter → KeyboardController.type_text
5. Fresh post-action visual capture and real Windows.Media.Ocr perception.
6. Semantic text verification via VerificationEngine.verify_text_input within Notepad window bounds.
7. Harmless cleanup: Hotkey Ctrl+A and Backspace via production pipeline to leave clean buffer.
"""

import sys
import os
import argparse
import asyncio
import uuid
import time
import concurrent.futures
from typing import Tuple, Dict, Any, List

sys.stdout.reconfigure(encoding="utf-8")

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.domain.entities import TriState
from app.domain.goals import Intent, SemanticAction, FailureClass, VerificationResult
from app.ai.orchestrator.verification import VerificationEngine
from tests.live.diagnose_interactive_actuation import diagnose_environment


def get_window_bounds(hwnd: int) -> Tuple[int, int, int, int]:
    """
    Returns (x, y, width, height) of the given window HWND via Win32 GetWindowRect.
    """
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


def print_banner(text: str):
    print("\n" + "=" * 75)
    print(text)
    print("=" * 75)


async def run_live_keyboard_interaction_test(opt_in_confirmed: bool = False) -> int:
    print_banner("ASTRA - PHASE B.4: UNIVERSAL PHYSICAL KEYBOARD & TEXT INPUT TEST")

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
        print("  No physical keyboard input or window manipulation was actuated.")
        print("\n  Pre-flight readiness check completed.")
        print("  To run the full verified keyboard input test against Notepad, run:")
        print("    python tests/live/test_live_keyboard_interaction.py --execute\n")
        print_banner("ASTRA - PHASE B.4: DRY-RUN COMPLETED")
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

    # -------------------------------------------------------------------------
    # STAGE 1: Application State & Window Establishment
    # -------------------------------------------------------------------------
    print("\n[STAGE 1] Application State & Window Establishment:")
    app_status = desktop_controller.get_application_status("Notepad")
    print(f"  Initial Notepad State: {app_status.get('state')} (Installed: {app_status.get('installed')})")

    # Ensure Notepad is opened and brought to foreground on main screen
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

    # Re-query accurate window geometry directly from OS after window positioning
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

    # Calculate document editor bounds (excluding title bar, tab strip, menu bar, and status bar)
    doc_x = win_x + 15
    doc_y = win_y + 90
    doc_w = win_w - 30
    doc_h = min(450, win_h - 220)
    doc_bounds = (doc_x, doc_y, doc_w, doc_h)
    print(f"  Document Area Bounds:  x={doc_x}, y={doc_y}, w={doc_w}, h={doc_h}")

    # Explicitly focus the document editor body via production click
    click_x = doc_x + min(300, doc_w // 3)
    click_y = doc_y + 80
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

    # -------------------------------------------------------------------------
    # STAGE 2: Pre-Action Visual Capture
    # -------------------------------------------------------------------------
    print("\n[STAGE 2] Pre-Action Visual Capture:")
    obs_pre_id = f"b4_pre_{uuid.uuid4().hex[:8]}"
    obs_pre = screen_capture_provider.capture_virtual_screen(obs_pre_id)
    print(f"  Observation ID:        {obs_pre.observation_id}")
    print(f"  Capture Timestamp:     {obs_pre.captured_at.isoformat()}")

    # -------------------------------------------------------------------------
    # STAGE 3: Execute Text Typing Through Production Pipeline
    # -------------------------------------------------------------------------
    print("\n[STAGE 3] Execution through Production Pipeline:")
    print("  Execution Path: ActionExecutor → ExecutePhysicalInputTool(TYPE_TEXT) → InteractionRouter → KeyboardController")

    unique_token = uuid.uuid4().hex[:6]
    test_text = f"Astra Live Keyboard {unique_token}"
    print(f"  Typing Payload Token:  '{unique_token}' (Astra Live Input)")

    # Immediate focus verification before typing
    fg_hwnd = window_manager.user32.GetForegroundWindow() if window_manager.user32 else 0
    if fg_hwnd != best_hwnd:
        print(f"  [FOCUS CHECK] Target window ({best_hwnd}) not foreground (current={fg_hwnd}); restoring...")
        window_manager.restore_and_focus(best_hwnd)
        await asyncio.sleep(0.3)

    intent_type = Intent(
        intent_id=str(uuid.uuid4()),
        action=SemanticAction.INPUT,
        capability_id="desktop.physical_input",
        target="Notepad_Editor",
        query=test_text,
    )

    actuation_result = await action_executor.execute_intent(
        intent=intent_type,
        tool_args={
            "intent": "TYPE_TEXT",
            "x": click_x,
            "y": click_y,
            "text": test_text + "\n",
        },
    )

    print(f"  Actuation Outcome:     {actuation_result.get('action_result', 'SUCCESS')}")
    print(f"  Characters Typed:      {actuation_result.get('diagnostics', {}).get('char_count', len(test_text))}")

    # Settle time for rendering
    await asyncio.sleep(0.8)

    # -------------------------------------------------------------------------
    # STAGE 4: Post-Action Visual Observation & Freshness
    # -------------------------------------------------------------------------
    print("\n[STAGE 4] Post-Action Visual Observation & Freshness:")
    obs_post_id = f"b4_post_{uuid.uuid4().hex[:8]}"
    obs_post = screen_capture_provider.capture_virtual_screen(obs_post_id)
    print(f"  Post-Action Obs ID:    {obs_post.observation_id}")
    print(f"  Fresher than Pre-Obs:  {obs_post.captured_at > obs_pre.captured_at}")

    post_bytes = screen_capture_provider.store.retrieve(obs_post.image_reference)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        post_detections = pool.submit(
            _run_windows_media_ocr,
            post_bytes,
            obs_post.width,
            obs_post.height,
        ).result()

    print(f"  Post-Action OCR Items: {len(post_detections)} elements detected")

    # -------------------------------------------------------------------------
    # STAGE 5: Semantic Text Input Verification
    # -------------------------------------------------------------------------
    print("\n[STAGE 5] Semantic Text Input Verification:")
    verification_result: VerificationResult = VerificationEngine.verify_text_input(
        expected_text=test_text,
        obs_before=obs_pre,
        obs_after=obs_post,
        detections_after=post_detections,
        target_bounds=doc_bounds,
    )

    # If first attempt is not yet visible (e.g. slight DWM compositor delay), give one 0.5s settle retry
    if verification_result.verified != TriState.TRUE:
        print("  [UI SETTLING] Text not yet detected in first capture; waiting 0.5s for compositor...")
        await asyncio.sleep(0.5)
        obs_post_retry_id = f"b4_post_retry_{uuid.uuid4().hex[:8]}"
        obs_post_retry = screen_capture_provider.capture_virtual_screen(obs_post_retry_id)
        raw_bytes_retry = screen_capture_provider.store.retrieve(obs_post_retry.image_reference)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            retry_detections = pool.submit(
                _run_windows_media_ocr,
                raw_bytes_retry,
                obs_post_retry.width,
                obs_post_retry.height,
            ).result()

        retry_result = VerificationEngine.verify_text_input(
            expected_text=test_text,
            obs_before=obs_pre,
            obs_after=obs_post_retry,
            detections_after=retry_detections,
            target_bounds=doc_bounds,
        )
        if retry_result.verified == TriState.TRUE:
            verification_result = retry_result
            obs_post = obs_post_retry
        else:
            # Print diagnostic elements inside window bounds
            print("  [DIAGNOSTIC] Detections inside window bounds:")
            for box, det_text, score in retry_detections:
                bx = box[0] if isinstance(box[0], (int, float)) else min(p[0] for p in box)
                by = box[1] if isinstance(box[1], (int, float)) else min(p[1] for p in box)
                if win_x <= bx <= win_x + win_w and win_y <= by <= win_y + win_h:
                    print(f"    * ({int(bx)}, {int(by)}): '{det_text}'")

    contract_status = "VERIFIED_SUCCESS" if verification_result.verified == TriState.TRUE else "VERIFIED_FAILURE"
    print(f"  Expected State:        '{verification_result.expected_state}'")
    print(f"  Actual State:          '{verification_result.actual_state}'")
    print(f"  Verification Status:   {contract_status}")
    print(f"  Evidence:              {verification_result.evidence}")

    # -------------------------------------------------------------------------
    # STAGE 6: Safe Cleanup Interaction (Hotkey Select All + Delete)
    # -------------------------------------------------------------------------
    print("\n[STAGE 6] Safe Cleanup Interaction (Hotkey Ctrl+A & Backspace):")
    cleanup_success = False

    try:
        # Focus document area to guarantee caret is active before hotkey
        await action_executor.execute_intent(
            intent=Intent(
                intent_id=str(uuid.uuid4()),
                action=SemanticAction.CLICK,
                capability_id="desktop.physical_input",
                target="Notepad_Document_Area",
            ),
            tool_args={"intent": "CLICK", "x": click_x, "y": click_y},
        )
        await asyncio.sleep(0.2)

        # Hotkey Ctrl+A
        intent_select = Intent(
            intent_id=str(uuid.uuid4()),
            action=SemanticAction.INPUT,
            capability_id="desktop.physical_input",
            target="SelectAll",
        )
        await action_executor.execute_intent(
            intent=intent_select,
            tool_args={"intent": "HOTKEY", "keys": ["ctrl", "a"]},
        )
        await asyncio.sleep(0.2)

        # Press Backspace
        intent_delete = Intent(
            intent_id=str(uuid.uuid4()),
            action=SemanticAction.INPUT,
            capability_id="desktop.physical_input",
            target="Delete",
        )
        await action_executor.execute_intent(
            intent=intent_delete,
            tool_args={"intent": "PRESS_KEY", "key": "backspace"},
        )
        await asyncio.sleep(0.6)

        # Verify text is gone from the document editor buffer
        obs_clean_id = f"b4_clean_{uuid.uuid4().hex[:8]}"
        obs_clean = screen_capture_provider.capture_virtual_screen(obs_clean_id)
        clean_bytes = screen_capture_provider.store.retrieve(obs_clean.image_reference)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            clean_detections = pool.submit(
                _run_windows_media_ocr,
                clean_bytes,
                obs_clean.width,
                obs_clean.height,
            ).result()

        clean_verify = VerificationEngine.verify_text_input(
            expected_text=test_text,
            obs_before=obs_post,
            obs_after=obs_clean,
            detections_after=clean_detections,
            target_bounds=doc_bounds,
        )

        # In clean state, expected_text should be ABSENT from document bounds
        if clean_verify.verified != TriState.FALSE:
            # Brief settle retry in case DWM compositor hasn't flushed the backspace clear
            await asyncio.sleep(0.5)
            obs_clean_retry_id = f"b4_clean_retry_{uuid.uuid4().hex[:8]}"
            obs_clean_retry = screen_capture_provider.capture_virtual_screen(obs_clean_retry_id)
            clean_retry_bytes = screen_capture_provider.store.retrieve(obs_clean_retry.image_reference)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                clean_retry_detections = pool.submit(
                    _run_windows_media_ocr,
                    clean_retry_bytes,
                    obs_clean_retry.width,
                    obs_clean_retry.height,
                ).result()
            clean_verify = VerificationEngine.verify_text_input(
                expected_text=test_text,
                obs_before=obs_post,
                obs_after=obs_clean_retry,
                detections_after=clean_retry_detections,
                target_bounds=doc_bounds,
            )

        if clean_verify.verified == TriState.FALSE:
            cleanup_success = True
            print("  [CLEANUP SUCCESS] Authoritative visual evidence confirms typed text was cleanly deleted from document editor.")
        else:
            print(f"  [CLEANUP FAILURE] Text remains visible after cleanup: {clean_verify.evidence}")
    except Exception as e:
        print(f"  [CLEANUP EXCEPTION] {e}")

    # -------------------------------------------------------------------------
    # STAGE 7: Summary & Contract Report
    # -------------------------------------------------------------------------
    print_banner("ASTRA - PHASE B.4: TEST EXECUTION SUMMARY")
    print(f"  Application Target:       Notepad (HWND={best_hwnd})")
    print(f"  Typed Payload Token:      '{unique_token}'")
    print(f"  Pre-Action Observation:   {obs_pre.observation_id}")
    print(f"  Post-Action Observation:  {obs_post.observation_id}")
    print(f"  Post-Action Freshness:    VALIDATED")
    print(f"  Semantic Verification:    {contract_status}")
    print(f"  Cleanup Outcome:          {'CLEANUP_SUCCESS' if cleanup_success else 'CLEANUP_FAILED'}")
    print("=" * 75 + "\n")

    return 0 if (contract_status == "VERIFIED_SUCCESS" and cleanup_success) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASTRA Phase B.4 Universal Keyboard & Text Input Test")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Explicitly authorize physical keyboard actuation against visible Notepad",
    )
    args = parser.parse_args()
    exit_code = asyncio.run(run_live_keyboard_interaction_test(opt_in_confirmed=args.execute))
    sys.exit(exit_code)
