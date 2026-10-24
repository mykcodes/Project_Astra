"""
ASTRA — Phase B.3.7: End-to-End Verified Visual Interaction Test (OPT-IN ONLY)

Validates the complete real OCR-to-physical-interaction pipeline against a real,
visible Windows application (Windows Notepad):

1. Identifies and establishes the initial Notepad state via existing application/window management.
2. Captures fresh screen evidence (VisualObservation).
3. Detects the real visible "File" menu target via production Windows Media OCR.
4. Selects and grounds the target into valid physical virtual-screen coordinates.
5. Executes the physical click through ASTRA's established production pipeline:
   ActionExecutor → registered ExecuteVisualInteractionTool → VisualInteractionService
   → InteractionRouter → MouseController.
6. Captures a fresh post-action observation and validates freshness invalidation.
7. Analyzes post-action OCR detections to determine if the Notepad File menu visibly opened.
8. Evaluates VerificationEngine to establish VERIFIED_SUCCESS, VERIFIED_FAILURE, or UNKNOWN.
9. Harmless cleanup: toggles the File menu closed without closing Notepad or discarding user data.
10. Reports each stage independently with complete diagnostic provenance.

CRITICAL SAFETY CONSTRAINTS:
- OPT-IN ONLY: Requires explicit user invocation via --execute flag.
- Safe, harmless, reversible interaction ONLY: Clicks "File" menu and toggles it closed.
- Runs only in the interactive desktop session (WinSta0\\Default).
- Strictly adheres to verification contract:
    * ACTUATION_REJECTED
    * ACTUATION_ACCEPTED
    * VERIFIED_SUCCESS
    * VERIFIED_FAILURE
    * UNKNOWN
- ZERO synthetic/forged perception targets; relies solely on real Windows Media OCR.
- DO NOT EXECUTE AUTOMATICALLY IN BACKGROUND SUBSHELLS.
"""

import argparse
import asyncio
import concurrent.futures
import json
import os
import sys
import uuid
from typing import Any, Dict, List, Optional, Tuple

# Ensure backend root is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.domain.entities import TriState
from app.domain.goals import Intent, SemanticAction, VerificationResult
from app.domain.visual import VisualObservation, VisualTarget
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


def filter_menu_bar_candidates(
    candidates: List[VisualTarget],
    win_x: int,
    win_y: int,
    win_w: int,
    win_h: int,
    menu_name: str = "file",
) -> List[VisualTarget]:
    """
    Filters visual candidates to identify the menu bar header inside the target window.

    Applies window bounds and menu bar geometry:
    - Target must fall within window bounds (with 10px tolerance for window borders/shadows).
    - Target must be within the top-left menu bar region:
        y in [win_y, win_y + min(160, max(80, win_h // 3))]
        x in [win_x, win_x + min(400, max(200, win_w // 2))]
    - Label match for menu_name (ignoring case, accelerator keys '&', '_', and outer quotes).
    - Plausible menu item dimensions: height <= 60, width <= 200.
    - Candidates sorted: exact word match first, then by proximity to expected top-left menu position.
    """
    if not candidates:
        return []

    max_menu_y = win_y + min(160, max(80, win_h // 3))
    max_menu_x = win_x + min(400, max(200, win_w // 2))
    target_name = menu_name.strip().strip("'\"`&_ ").lower()

    filtered: List[VisualTarget] = []
    for cand in candidates:
        # Check inside window bounds (allow 10px tolerance for DWM drop shadows/borders)
        if not (win_x - 10 <= cand.bbox_x <= win_x + win_w + 10 and win_y - 10 <= cand.bbox_y <= win_y + win_h + 10):
            continue

        # Check inside menu bar strip
        if cand.bbox_y > max_menu_y or cand.bbox_x > max_menu_x:
            continue

        # Check plausible dimensions
        if cand.bbox_height > 60 or cand.bbox_width > 200:
            continue

        # Check label match
        cleaned_label = cand.label.strip().strip("'\"`&_ ").lower()
        if cleaned_label == target_name or cleaned_label.startswith(f"{target_name} "):
            filtered.append(cand)

    # Sort: exact word matches first, then by proximity to expected top-left position (win_x + 30, win_y + 60)
    filtered.sort(
        key=lambda c: (
            0 if c.label.strip().strip("'\"`&_ ").lower() == target_name else 1,
            (c.bbox_y - (win_y + 60)) ** 2 + (c.bbox_x - (win_x + 30)) ** 2,
        )
    )
    return filtered


def validate_actuation_provenance(
    provenance: Optional[Dict[str, Any]],
    window_bounds: Optional[Tuple[int, int, int, int]] = None,
) -> Tuple[bool, str]:
    """
    Validates that the production interaction provenance is complete, consistent,
    and corresponds to the intended UI interaction.

    Requirements:
    1. Provenance dictionary must be non-empty.
    2. Actuation outcome must be 'SUCCESS'.
    3. Observation ID must be a non-empty string.
    4. Target ID must be a non-empty string.
    5. Screen point must contain valid integer coordinates (x, y).
    6. If window_bounds (win_x, win_y, win_w, win_h) is provided:
       - Screen point must be within window bounds.
       - Screen point must fall within the menu bar strip:
           win_y <= y <= win_y + min(160, max(80, win_h // 3))
           win_x <= x <= win_x + min(400, max(200, win_w // 2))

    Returns:
        (True, "OK") if valid.
        (False, error_reason) if invalid or inconsistent.
    """
    if not isinstance(provenance, dict) or not provenance:
        return False, "Provenance data is missing or not a dictionary."

    outcome = provenance.get("actuation_outcome")
    if outcome != "SUCCESS":
        return False, f"Actuation outcome is not SUCCESS (got: '{outcome}')."

    obs_id = provenance.get("observation_id")
    if not isinstance(obs_id, str) or not obs_id.strip():
        return False, "Observation ID is missing or invalid in provenance."

    target_id = provenance.get("target_id")
    if not isinstance(target_id, str) or not target_id.strip():
        return False, "Target ID is missing or invalid in provenance."

    screen_point = provenance.get("screen_point")
    if not isinstance(screen_point, dict):
        return False, "Screen point is missing or not a dictionary in provenance."

    if "x" not in screen_point or "y" not in screen_point:
        return False, "Screen point missing 'x' or 'y' coordinates."

    pt_x = screen_point["x"]
    pt_y = screen_point["y"]
    if not isinstance(pt_x, int) or not isinstance(pt_y, int):
        return False, f"Screen point coordinates must be integers, got ({type(pt_x)}, {type(pt_y)})."

    if window_bounds is not None:
        win_x, win_y, win_w, win_h = window_bounds

        # Check within window
        if not (win_x - 10 <= pt_x <= win_x + win_w + 10 and win_y - 10 <= pt_y <= win_y + win_h + 10):
            return False, (
                f"Actuated screen point ({pt_x}, {pt_y}) falls outside target window bounds "
                f"x=[{win_x}, {win_x + win_w}], y=[{win_y}, {win_y + win_h}]."
            )

        # Check within menu bar strip
        max_menu_y = win_y + min(160, max(80, win_h // 3))
        max_menu_x = win_x + min(400, max(200, win_w // 2))

        if pt_y > max_menu_y or pt_x > max_menu_x:
            return False, (
                f"Actuated screen point ({pt_x}, {pt_y}) falls outside menu bar strip "
                f"(max_x={max_menu_x}, max_y={max_menu_y}). Point appears to be document content."
            )

    return True, "OK"


def derive_verification_anchor(
    provenance: Dict[str, Any],
    query: str = "File",
    anchor_width: int = 30,
    anchor_height: int = 20,
) -> VisualTarget:
    """
    Derives an authoritative VisualTarget verification anchor from validated production provenance.

    Uses the actual actuated physical screen point to establish the anchor bounding box,
    ensuring that the semantic menu verifier's Region of Interest (ROI) is positioned
    directly beneath the exact UI element that was physically clicked.
    """
    screen_point = provenance["screen_point"]
    pt_x = screen_point["x"]
    pt_y = screen_point["y"]

    # Center nominal bounding box on the actuated screen point
    half_w = anchor_width // 2
    half_h = anchor_height // 2
    bbox_x = pt_x - half_w
    bbox_y = pt_y - half_h

    return VisualTarget(
        target_id=provenance["target_id"],
        label=query,
        target_type="text",
        confidence=1.0,
        bbox_x=bbox_x,
        bbox_y=bbox_y,
        bbox_width=anchor_width,
        bbox_height=anchor_height,
        source_observation_id=provenance["observation_id"],
        semantic_attributes={
            "actuated_point": {"x": pt_x, "y": pt_y},
            "provenance_observation_id": provenance["observation_id"],
            "derived_from_production_provenance": True,
        },
    )


def print_banner(title: str):
    print("\n" + "=" * 75)
    print(title)
    print("=" * 75)


def send_escape_key_win32(press_count: int = 2) -> bool:
    """
    Sends bounded hardware-level Escape key events via Win32 SendInput.
    Delegates to KeyboardController which enforces 40-byte tagINPUT invariants.
    """
    from app.interaction.input.keyboard_controller import keyboard_controller
    res = keyboard_controller.actuate_escape(press_count=press_count)
    return res.get("success", False)


async def execute_safe_menu_cleanup(
    target_hwnd: int,
    window_bounds: Tuple[int, int, int, int],
    anchor_target: VisualTarget,
    obs_prior: VisualObservation,
    screen_capture_provider: Any,
    action_executor: Any,
    ocr_worker_fn: Any,
    window_manager: Any = None,
    interaction_tracker: Any = None,
) -> Tuple[bool, str, VerificationResult]:
    """
    Executes a bounded, safe multi-tier cleanup to ensure the dropdown menu is closed:
    - Tier 1: Hardware Escape dismissal via KeyboardController. Enforces 40-byte tagINPUT alignment
      and preserves active popup focus. Captures fresh visual observation and semantically verifies closed state.
    - Tier 2: System-level Alt dismissal via KeyboardController (taps Alt key to cancel menu mode).
      Captures fresh visual observation and semantically verifies closed state.
    - Tier 3 (Fallback): Safe neutral light-dismiss click into the document body area (NOT on the menu header,
      avoiding reopening loops) via the production interaction pipeline, captures fresh observation, and semantically verifies.
    """
    import ctypes
    from app.interaction.input.keyboard_controller import keyboard_controller
    win_x, win_y, win_w, win_h = window_bounds

    # -------------------------------------------------------------------------
    # TIER 1: Hardware Escape Dismissal
    # -------------------------------------------------------------------------
    print("  [CLEANUP TIER 1] Validating target focus and issuing hardware Escape key via KeyboardController...")
    user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
    if user32 and window_manager:
        fg_hwnd = user32.GetForegroundWindow()
        fg_pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(fg_pid))
        target_pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(target_hwnd, ctypes.byref(target_pid))

        # Only bring target to foreground if foreground does not belong to target process.
        # If foreground is already in the target process (e.g. the active MenuFlyout popup),
        # calling restore_and_focus / SetForegroundWindow on the root hwnd steals focus
        # from the popup, causing Escape to be dispatched to the text edit control instead!
        if fg_pid.value != target_pid.value:
            window_manager.restore_and_focus(target_hwnd)
            await asyncio.sleep(0.15)

    keyboard_controller.actuate_escape(press_count=2)
    if interaction_tracker:
        interaction_tracker.record_interaction()
    await asyncio.sleep(0.6)

    # Capture fresh post-cleanup observation
    obs_clean_1_id = f"e2e_clean_1_{uuid.uuid4().hex[:8]}"
    obs_clean_1 = screen_capture_provider.capture_virtual_screen(obs_clean_1_id)
    clean_bytes_1 = screen_capture_provider.store.retrieve(obs_clean_1.image_reference)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        clean_detections_1 = pool.submit(
            ocr_worker_fn,
            clean_bytes_1,
            obs_clean_1.width,
            obs_clean_1.height,
        ).result()

    clean_check_1 = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor_target,
        obs_before=obs_prior,
        obs_after=obs_clean_1,
        detections_after=clean_detections_1,
        expected_menu_open=False,
    )

    if clean_check_1.verified == TriState.TRUE:
        print("  [CLEANUP SUCCESS] Authoritative visual evidence confirms File menu is closed via Escape key.")
        return True, "CLEANUP_SUCCESS", clean_check_1

    # -------------------------------------------------------------------------
    # TIER 2: System Alt Key Dismissal (Cancel Menu Bar Mode)
    # -------------------------------------------------------------------------
    print(f"  [CLEANUP NOTICE] Menu not confirmed closed after Escape (actual_state='{clean_check_1.actual_state}').")
    print("  [CLEANUP TIER 2] Issuing system-level Alt toggle via KeyboardController to cancel menu mode...")
    keyboard_controller.actuate_alt(press_count=1)
    if interaction_tracker:
        interaction_tracker.record_interaction()
    await asyncio.sleep(0.6)

    obs_clean_2_id = f"e2e_clean_2_{uuid.uuid4().hex[:8]}"
    obs_clean_2 = screen_capture_provider.capture_virtual_screen(obs_clean_2_id)
    clean_bytes_2 = screen_capture_provider.store.retrieve(obs_clean_2.image_reference)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        clean_detections_2 = pool.submit(
            ocr_worker_fn,
            clean_bytes_2,
            obs_clean_2.width,
            obs_clean_2.height,
        ).result()

    clean_check_2 = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor_target,
        obs_before=obs_clean_1,
        obs_after=obs_clean_2,
        detections_after=clean_detections_2,
        expected_menu_open=False,
    )

    if clean_check_2.verified == TriState.TRUE:
        print("  [CLEANUP SUCCESS] Authoritative visual evidence confirms File menu is closed via Alt key.")
        return True, "CLEANUP_SUCCESS", clean_check_2

    # -------------------------------------------------------------------------
    # TIER 3: Neutral Light-Dismiss Click (Document Body, NOT Menu Header)
    # -------------------------------------------------------------------------
    print(f"  [CLEANUP NOTICE] Menu not confirmed closed after Alt (actual_state='{clean_check_2.actual_state}').")
    print("  [CLEANUP TIER 3] Fallback: executing neutral light-dismiss click in document body via production pipeline...")

    # Calculate neutral document point safely below menu strip and well to the right of the dropdown flyout
    neutral_x = int(win_x + min(win_w - 150, max(450, int(win_w * 0.65))))
    neutral_y = int(win_y + min(win_h - 150, max(250, int(win_h * 0.5))))

    intent_dismiss = Intent(
        intent_id=str(uuid.uuid4()),
        action=SemanticAction.CLICK,
        capability_id="desktop.physical_input",
        target=f"neutral_document_point_({neutral_x},{neutral_y})",
    )
    await action_executor.execute_intent(
        intent=intent_dismiss,
        tool_args={
            "intent": "CLICK",
            "x": neutral_x,
            "y": neutral_y,
        },
    )
    await asyncio.sleep(0.6)

    # Capture fresh post-click observation
    obs_clean_3_id = f"e2e_clean_3_{uuid.uuid4().hex[:8]}"
    obs_clean_3 = screen_capture_provider.capture_virtual_screen(obs_clean_3_id)
    clean_bytes_3 = screen_capture_provider.store.retrieve(obs_clean_3.image_reference)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        clean_detections_3 = pool.submit(
            ocr_worker_fn,
            clean_bytes_3,
            obs_clean_3.width,
            obs_clean_3.height,
        ).result()

    clean_check_3 = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor_target,
        obs_before=obs_clean_2,
        obs_after=obs_clean_3,
        detections_after=clean_detections_3,
        expected_menu_open=False,
    )

    if clean_check_3.verified == TriState.TRUE:
        print("  [CLEANUP SUCCESS] Authoritative visual evidence confirms File menu is closed via neutral light-dismiss click.")
        return True, "CLEANUP_SUCCESS", clean_check_3
    elif clean_check_3.verified == TriState.FALSE:
        print(f"  [CLEANUP FAILURE] Menu remains open: {clean_check_3.evidence}")
        return False, "CLEANUP_FAILED", clean_check_3
    else:
        print(f"  [CLEANUP UNCONFIRMED] Post-cleanup state ambiguous: {clean_check_3.evidence}")
        return False, "CLEANUP_UNCONFIRMED", clean_check_3


async def run_e2e_visual_interaction_test(opt_in_confirmed: bool = False) -> int:
    """
    Executes the End-to-End Verified Visual Interaction Test.
    Returns 0 on success or safe dry-run, non-zero on test failure.
    """
    print_banner("ASTRA - PHASE B.3.7: END-TO-END VERIFIED VISUAL INTERACTION TEST")

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

    # -------------------------------------------------------------------------
    # STAGE 0.5: Opt-In Enforcement
    # -------------------------------------------------------------------------
    if not opt_in_confirmed:
        print("\n[OPT-IN REQUIRED - SAFETY SAFEGUARD]")
        print("  This live test requires the explicit '--execute' flag.")
        print("  No physical mouse input or window manipulation was actuated.")
        print("\n  Pre-flight readiness check completed.")
        print("  To run the full end-to-end verified interaction against Notepad, run:")
        print("    python tests/live/test_live_e2e_visual_interaction.py --execute")
        print_banner("ASTRA - PHASE B.3.7: DRY-RUN COMPLETED")
        return 0

    if not sd["is_on_active_input_desktop"]:
        print("\n[FATAL ENVIRONMENT CONFLICT]")
        print("  The current process is NOT attached to the active input desktop ('Default').")
        print("  Physical SendInput calls will fail with Win32 ERROR_ACCESS_DENIED (5).")
        print("  Please execute this test from a standard interactive PowerShell terminal on your desktop.")
        return 1

    print("\n[OPT-IN CONFIRMED] Explicit execution authorization granted by user.")

    from app.ai.orchestrator.action_executor import action_executor
    from app.ai.orchestrator.verification import VerificationEngine
    from app.domain.entities import ScreenPoint, TriState
    from app.domain.goals import FailureClass, Intent, SemanticAction, VerificationResult
    from app.domain.visual import GroundedTarget, VisualObservation, VisualTarget
    from app.environment.application.state_engine import state_engine
    from app.environment.visual.capture import screen_capture_provider
    from app.environment.visual.grounding import target_grounding_service
    from app.environment.visual.perception import (
        OcrPerceptionProvider,
        _run_windows_media_ocr,
        ocr_perception_provider,
    )
    from app.environment.visual.selection import target_selection_service
    from app.environment.visual.tracker import interaction_tracker
    from app.environment.window.manager import window_manager
    from app.tools.desktop.desktop_controller import ApplicationIntent, desktop_controller

    # -------------------------------------------------------------------------
    # STAGE 1: Establish Initial Application State (Windows Notepad)
    # -------------------------------------------------------------------------
    print("\n[STAGE 1] Application State & Window Establishment:")
    app_status = desktop_controller.get_application_status("Notepad")
    print(f"  Initial Notepad State: {app_status.get('state')} (Installed: {app_status.get('installed')})")

    # Ensure Notepad is opened and brought to foreground on main screen
    open_res = await desktop_controller.execute_intent(ApplicationIntent.OPEN, "Notepad")
    if not open_res.get("success"):
        print(f"  [ERROR] Failed to establish Notepad application state: {open_res}")
        return 1

    # Give Windows a brief moment to finish window mapping and focus
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
    # Allow window positioning, DWM animation, and XAML render tree to fully settle
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

    # -------------------------------------------------------------------------
    # STAGE 2: Fresh Pre-Action Screen Capture
    # -------------------------------------------------------------------------
    print("\n[STAGE 2] Pre-Action Visual Capture:")
    obs_pre_id = f"e2e_notepad_pre_{uuid.uuid4().hex[:8]}"
    obs_pre = screen_capture_provider.capture_virtual_screen(obs_pre_id)
    print(f"  Observation ID:        {obs_pre.observation_id}")
    print(f"  Capture Timestamp:     {obs_pre.captured_at.isoformat()}")
    print(f"  Screen Dimensions:     {obs_pre.width}x{obs_pre.height}")
    print(f"  Image Reference:       {obs_pre.image_reference}")

    # -------------------------------------------------------------------------
    # STAGE 3: Real OCR Perception & Target Grounding
    # -------------------------------------------------------------------------
    print("\n[STAGE 3] Target Perception & Coordinate Grounding:")

    max_settle_attempts = 4
    menu_candidates = []

    for attempt in range(1, max_settle_attempts + 1):
        if attempt > 1:
            print(
                f"  [UI SETTLING] Menu header not detected yet (attempt {attempt}/{max_settle_attempts}); "
                f"waiting 1.0s for window to finish rendering..."
            )
            await asyncio.sleep(1.0)
            obs_pre_id = f"e2e_notepad_pre_{uuid.uuid4().hex[:8]}"
            obs_pre = screen_capture_provider.capture_virtual_screen(obs_pre_id)

        # Run real Windows.Media.Ocr perception against actual desktop pixels
        raw_bytes = screen_capture_provider.store.retrieve(obs_pre.image_reference)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pre_detections = pool.submit(
                _run_windows_media_ocr,
                raw_bytes,
                obs_pre.width,
                obs_pre.height,
            ).result()

        print(f"  OCR Detections Found:  {len(pre_detections)} elements across screen")

        # Search for visible "File" menu item
        candidates = ocr_perception_provider.find_targets(obs_pre, query="File")
        print(f"  'File' Candidates:     {len(candidates)}")

        # Diagnostics: log all 'File' candidates found across screen
        for idx, c in enumerate(candidates):
            in_w = (win_x - 10 <= c.bbox_x <= win_x + win_w + 10 and win_y - 10 <= c.bbox_y <= win_y + win_h + 10)
            print(f"    Candidate [{idx}]: bbox=({c.bbox_x}, {c.bbox_y}, {c.bbox_width}, {c.bbox_height}), label='{c.label}', in_window={in_w}")

        # Filter candidates located within the Notepad window's menu bar region
        menu_candidates = filter_menu_bar_candidates(
            candidates=candidates,
            win_x=win_x,
            win_y=win_y,
            win_w=win_w,
            win_h=win_h,
            menu_name="File",
        )
        print(f"  Menu Candidates in Window: {len(menu_candidates)}")

        if menu_candidates:
            break

    if not menu_candidates:
        print(
            f"  [ERROR] No 'File' menu header candidate found in Notepad menu bar strip "
            f"(x=[{win_x}, {win_x + 400}], y=[{win_y}, {win_y + 160}]) after {max_settle_attempts} attempts."
        )
        return 1

    try:
        selected_target: VisualTarget = target_selection_service.select_target(
            [menu_candidates[0]], min_confidence=0.7
        )
    except Exception as e:
        print(f"  [ERROR] Target selection rejected candidates: {e}")
        return 1

    print(f"  Selected Target ID:    {selected_target.target_id}")
    print(f"  Target Label:          '{selected_target.label}'")
    print(f"  Target Bounding Box:   x={selected_target.bbox_x}, y={selected_target.bbox_y}, w={selected_target.bbox_width}, h={selected_target.bbox_height}")
    print(f"  Target Confidence:     {selected_target.confidence:.2f}")

    # Ground to physical screen coordinate
    grounded: GroundedTarget = target_grounding_service.ground(selected_target, obs_pre)
    anchor_point: ScreenPoint = grounded.anchor_point
    print(f"  Grounded ScreenPoint:  ({anchor_point.x}, {anchor_point.y})")

    # -------------------------------------------------------------------------
    # STAGE 4: Execute Click through ASTRA Production Pipeline
    # -------------------------------------------------------------------------
    print("\n[STAGE 4] Execution through Production Pipeline:")
    print("  Execution Path: ActionExecutor → ExecuteVisualInteractionTool → VisualInteractionService → InteractionRouter → MouseController")

    # Verify actual foreground window state immediately before actuation
    fg_hwnd = window_manager.user32.GetForegroundWindow() if window_manager.user32 else 0
    if fg_hwnd != best_hwnd:
        print(f"  [FOCUS CHECK] Target window ({best_hwnd}) is NOT foreground (current fg={fg_hwnd}). Restoring focus...")
        focus_ok = window_manager.restore_and_focus(best_hwnd)
        await asyncio.sleep(0.3)
        fg_hwnd = window_manager.user32.GetForegroundWindow() if window_manager.user32 else 0
        print(f"  [FOCUS CHECK] Foreground restored: {focus_ok} (Current FG HWND: {fg_hwnd}, Matches: {fg_hwnd == best_hwnd})")
        if fg_hwnd != best_hwnd:
            print(f"  [ERROR] Foreground window state mismatch immediately before actuation: expected {best_hwnd}, got {fg_hwnd}.")
            return 1

        # Re-observe pre-action screen after focus restoration to guarantee freshness and visibility
        print("  [FOCUS CHECK] Re-capturing pre-action observation after focus restoration...")
        obs_pre_id = f"e2e_notepad_pre_{uuid.uuid4().hex[:8]}"
        obs_pre = screen_capture_provider.capture_virtual_screen(obs_pre_id)

    intent = Intent(
        intent_id=str(uuid.uuid4()),
        action=SemanticAction.CLICK,
        capability_id="desktop.visual_click",
        target="File",
    )

    action_result = await action_executor.execute_intent(
        intent=intent,
        tool_args={
            "query": "File",
            "min_confidence": 0.5,
            "target_bounds": [win_x, win_y, win_w, win_h],
        },
    )

    actuation_accepted = action_result.get("success", False)
    intermediate_status = "ACTUATION_ACCEPTED" if actuation_accepted else "ACTUATION_REJECTED"
    diagnostics = action_result.get("diagnostics", {})
    provenance = diagnostics.get("provenance", {})
    actuator_diag = provenance.get("actuator_diagnostics", {})

    print(f"  Actuation Outcome:     {intermediate_status}")
    print(f"  Production Provenance: obs_id={provenance.get('observation_id')}, target_id={provenance.get('target_id')}")

    # Section 4 Diagnostic Evidence Distinctions:
    print("\n  [DIAGNOSTIC EVIDENCE DISTINCTIONS]")
    print(f"    1. Intended Target:        '{selected_target.label}' at ({anchor_point.x}, {anchor_point.y})")
    print(f"    2. Foreground Window:      HWND={actuator_diag.get('target_window_hwnd')}, Matches Notepad: {actuator_diag.get('target_window_hwnd') == best_hwnd}")
    print(f"    3. Cursor Before Move:     Observed at ({actuator_diag.get('cursor_before_click', {}).get('x')}, {actuator_diag.get('cursor_before_click', {}).get('y')})")
    print(f"    4. Movement Accepted:      {actuator_diag.get('move_accepted')}, Landing Discrepancy: ({actuator_diag.get('cursor_discrepancy', {}).get('x', 0)}, {actuator_diag.get('cursor_discrepancy', {}).get('y', 0)})")
    print(f"    5. Button Inputs Accepted: Down={actuator_diag.get('button_down_accepted')}, Up={actuator_diag.get('button_up_accepted')} (Dwell: {actuator_diag.get('dwell_ms')}ms)")
    print(f"    6. Target Occupied Point:  WindowActivated={actuator_diag.get('window_activated')}")

    if not actuation_accepted:
        print("  [FAILURE] Operating system rejected physical actuation.")
        print(f"  Error details: {action_result.get('error')}")
        print_banner("ASTRA — PHASE B.3.7: TEST FAILED (ACTUATION_REJECTED)")
        return 1

    # -------------------------------------------------------------------------
    # STAGE 5: Fresh Post-Action Observation & Freshness Validation
    # -------------------------------------------------------------------------
    print("\n[STAGE 5] Post-Action Visual Observation & Freshness:")
    # Allow WinUI 3 XAML MenuFlyout open animation to fully render
    await asyncio.sleep(0.8)

    obs_post_id = f"e2e_notepad_post_{uuid.uuid4().hex[:8]}"
    obs_post = screen_capture_provider.capture_virtual_screen(obs_post_id)

    last_interaction = interaction_tracker.get_last_interaction()
    is_fresher_than_pre = obs_post.captured_at > obs_pre.captured_at
    is_fresher_than_actuation = obs_post.captured_at >= last_interaction

    print(f"  Post-Action Obs ID:    {obs_post.observation_id}")
    print(f"  Capture Timestamp:     {obs_post.captured_at.isoformat()}")
    print(f"  Last Interaction Time: {last_interaction.isoformat()}")
    print(f"  Fresher than Pre-Obs:  {is_fresher_than_pre}")
    print(f"  Fresher than Action:   {is_fresher_than_actuation}")

    if not (is_fresher_than_pre and is_fresher_than_actuation):
        print("  [ERROR] Post-action observation failed freshness invariants!")
        return 1

    # Run real OCR perception on post-action screen
    raw_bytes_post = screen_capture_provider.store.retrieve(obs_post.image_reference)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        post_detections = pool.submit(
            _run_windows_media_ocr,
            raw_bytes_post,
            obs_post.width,
            obs_post.height,
        ).result()

    print(f"  Post-Action OCR Items: {len(post_detections)} elements detected")

    # -------------------------------------------------------------------------
    # STAGE 6: Semantic Menu State Verification
    # -------------------------------------------------------------------------
    print("\n[STAGE 6] Semantic UI State Verification:")

    # Refresh current window bounds to validate coordinate consistency
    curr_win_bounds = (
        get_window_bounds(best_hwnd)
        if window_manager.user32
        else (win_x, win_y, win_w, win_h)
    )

    prov_valid, prov_reason = validate_actuation_provenance(
        provenance, window_bounds=curr_win_bounds
    )
    print(f"  Provenance Validation: {'VALID' if prov_valid else 'INVALID'} ({prov_reason})")

    if not prov_valid:
        print(f"  [ERROR] Cannot establish trustworthy verification anchor: {prov_reason}")
        print_banner("ASTRA — PHASE B.3.7: TEST FAILED (INVALID_PROVENANCE)")
        return 1

    anchor_target = derive_verification_anchor(provenance, query="File")
    pt = provenance["screen_point"]
    print(f"  Verification Anchor:   '{anchor_target.label}' (ID={anchor_target.target_id})")
    print(f"  Actuated Screen Point: ({pt['x']}, {pt['y']})")
    print(f"  Anchor Bounding Box:   x={anchor_target.bbox_x}, y={anchor_target.bbox_y}, w={anchor_target.bbox_width}, h={anchor_target.bbox_height}")

    verification_result: VerificationResult = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor_target,
        obs_before=obs_pre,
        obs_after=obs_post,
        detections_after=post_detections,
        expected_dropdown_tokens=["new", "open", "save", "exit", "print", "tab"],
    )

    # If first attempt is not yet open (e.g. slight DWM compositing delay), give one 0.5s settle retry
    if verification_result.verified != TriState.TRUE:
        print("  [UI SETTLING] Dropdown items not yet visible in first capture; waiting 0.5s for compositor...")
        await asyncio.sleep(0.5)
        obs_post_retry_id = f"e2e_notepad_post_retry_{uuid.uuid4().hex[:8]}"
        obs_post_retry = screen_capture_provider.capture_virtual_screen(obs_post_retry_id)
        raw_bytes_retry = screen_capture_provider.store.retrieve(obs_post_retry.image_reference)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            retry_detections = pool.submit(
                _run_windows_media_ocr,
                raw_bytes_retry,
                obs_post_retry.width,
                obs_post_retry.height,
            ).result()

        retry_result = VerificationEngine.verify_visual_menu_state(
            anchor_target=anchor_target,
            obs_before=obs_pre,
            obs_after=obs_post_retry,
            detections_after=retry_detections,
            expected_dropdown_tokens=["new", "open", "save", "exit", "print", "tab"],
        )
        if retry_result.verified == TriState.TRUE:
            verification_result = retry_result
            obs_post = obs_post_retry

    if verification_result.verified == TriState.TRUE:
        contract_status = "VERIFIED_SUCCESS"
    elif verification_result.verified == TriState.FALSE:
        contract_status = "VERIFIED_FAILURE"
    else:
        contract_status = "UNKNOWN"

    print(f"  7. Expected UI State:  '{verification_result.expected_state}' -> Actual: '{verification_result.actual_state}'")
    print(f"  Verification Status:   {contract_status}")
    print(f"  TriState Verified:     {verification_result.verified}")
    print(f"  Confidence:            {verification_result.confidence:.2f}")
    print(f"  Authoritative Evidence:{verification_result.evidence}")
    if verification_result.failure_code:
        print(f"  Failure Class:         {verification_result.failure_code}")

    # -------------------------------------------------------------------------
    # STAGE 7: Harmless Cleanup (Close Menu Without Closing Notepad)
    # -------------------------------------------------------------------------
    print("\n[STAGE 7] Safe Cleanup Interaction:")
    cleanup_success = False
    cleanup_status = "NOT_ATTEMPTED"

    if verification_result.verified == TriState.TRUE:
        try:
            print("  Starting bounded, safe cleanup (closing File menu)...")
            cleanup_success, cleanup_status, clean_res = await execute_safe_menu_cleanup(
                target_hwnd=best_hwnd,
                window_bounds=(win_x, win_y, win_w, win_h),
                anchor_target=anchor_target,
                obs_prior=obs_post,
                screen_capture_provider=screen_capture_provider,
                action_executor=action_executor,
                ocr_worker_fn=_run_windows_media_ocr,
                window_manager=window_manager,
                interaction_tracker=interaction_tracker,
            )
        except Exception as e:
            cleanup_status = "CLEANUP_FAILED"
            print(f"  Cleanup Exception: {e}")
    else:
        cleanup_status = "NOT_NEEDED"
        print("  Menu was not opened; cleanup not required.")

    print(f"  Cleanup Status:        {cleanup_status} (Success: {cleanup_success})")

    # -------------------------------------------------------------------------
    # STAGE 8: Final Summary and Authoritative Contract Report
    # -------------------------------------------------------------------------
    print_banner("ASTRA - PHASE B.3.7: TEST EXECUTION SUMMARY")
    print(f"  Application Target:       Notepad (HWND={best_hwnd})")
    print(f"  Pre-Action Observation:   {obs_pre.observation_id}")
    print(f"  Stage 3 Selected Target:  '{selected_target.label}' (ID={selected_target.target_id}) at ({anchor_point.x}, {anchor_point.y})")
    print(f"  Actuated Target (Prov):   '{anchor_target.label}' (ID={anchor_target.target_id}) at ({pt['x']}, {pt['y']})")
    print(f"  Provenance Observation:   {provenance.get('observation_id')}")
    print(f"  Physical Actuation:       {intermediate_status}")
    print(f"  Post-Action Observation:  {obs_post.observation_id}")
    print(f"  Post-Action Freshness:    VALIDATED (is_stale=False)")
    print(f"  Semantic Verification:    {contract_status}")
    print(f"  Cleanup Outcome:          {cleanup_status}")
    print("=" * 75 + "\n")

    return 0 if (contract_status == "VERIFIED_SUCCESS" and cleanup_success) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASTRA Phase B.3.7 End-to-End Verified Visual Interaction Test")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Explicitly authorize real physical mouse actuation against visible Notepad",
    )
    args = parser.parse_args()
    exit_code = asyncio.run(run_e2e_visual_interaction_test(opt_in_confirmed=args.execute))
    sys.exit(exit_code)
