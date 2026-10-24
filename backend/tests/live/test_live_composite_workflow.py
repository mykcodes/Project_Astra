"""
ASTRA — Phase B.6: Complex Interaction Sequences & Multi-Step Composite Action Orchestration Live Test (OPT-IN ONLY)

Executes the canonical composite interaction workflow through the existing architecture:
  Focus Editor → Type Text → Drag-Select Text → Context Menu → Dismiss/Cleanup

Orchestrated through:
  ActionPlanner.plan_composite_sequence → ActionExecutor.execute_sequence → VerificationEngine
  preserving the observe → act → observe → verify → recover loop.
"""

import sys
import os
import argparse
import asyncio
import time
import uuid
import ctypes
from typing import Tuple, Dict, Any, List

sys.stdout.reconfigure(encoding="utf-8")

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.domain.entities import TriState
from app.domain.goals import Intent, SemanticAction, FailureClass, VerificationResult
from app.domain.composite import (
    CompositeActionSequence,
    CompositeStep,
    CompensationAction,
    StepStatus,
    CompositeTerminalStatus,
    CompositeExecutionResult,
)
from app.ai.orchestrator.action_executor import action_executor
from app.ai.orchestrator.action_planner import action_planner
from app.ai.orchestrator.verification import VerificationEngine
from tests.live.diagnose_interactive_actuation import diagnose_environment


def get_window_bounds(hwnd: int) -> Tuple[int, int, int, int]:
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


from app.interaction.input.keyboard_controller import clear_clipboard, get_clipboard_text


def print_banner(text: str):
    print("\n" + "=" * 75)
    print(text)
    print("=" * 75)


async def run_live_composite_workflow(opt_in_confirmed: bool = False) -> int:
    print_banner("ASTRA - PHASE B.6: MULTI-STEP COMPOSITE ACTION WORKFLOW")

    # Ensure current thread is attached to the active input desktop
    if hasattr(ctypes, "windll"):
        try:
            u32 = ctypes.windll.user32
            h_input = u32.OpenInputDesktop(0, False, 0x01FF)
            if h_input:
                u32.SetThreadDesktop(h_input)
                u32.CloseDesktop(h_input)
        except Exception:
            pass

    # STAGE 0: Diagnostic Pre-Flight
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
        print("  To run the full verified composite workflow against Notepad, run:")
        print("    python tests/live/test_live_composite_workflow.py --execute\n")
        print_banner("ASTRA - PHASE B.6: DRY-RUN COMPLETED")
        return 0

    print("\n[OPT-IN CONFIRMED] Explicit execution authorization granted by user.")

    from app.domain.entities import ScreenPoint
    from app.domain.visual import VisualObservation
    from app.environment.window.manager import window_manager
    from app.environment.visual.capture import screen_capture_provider
    from app.environment.visual.perception import _run_windows_media_ocr
    from app.tools.desktop.desktop_controller import ApplicationIntent, desktop_controller

    # STAGE 1: Application State & Window Establishment
    print("\n[STAGE 1] Application State & Target Window Establishment:")
    import subprocess
    # Ensure no stale, orphaned, or multiple overlapping Notepad instances exist
    subprocess.run(["powershell", "-Command", "Stop-Process -Name notepad -Force -ErrorAction SilentlyContinue"], capture_output=True)
    await asyncio.sleep(0.5)

    app_status = desktop_controller.get_application_status("Notepad")
    print(f"  Initial Notepad State: {app_status.get('state')} (Installed: {app_status.get('installed')})")

    open_res = await desktop_controller.execute_intent(ApplicationIntent.OPEN, "Notepad")
    await asyncio.sleep(1.2)

    windows = []
    for _ in range(8):
        refreshed_status = desktop_controller.get_application_status("Notepad")
        windows = refreshed_status.get("windows", [])
        if windows and any(w.get("width", 0) > 200 for w in windows):
            break
        await asyncio.sleep(0.5)

    if not windows or not any(w.get("width", 0) > 200 for w in windows):
        # Fallback to direct launch via Windows execution alias
        subprocess.Popen(["cmd.exe", "/c", "start", "", "notepad.exe"], shell=True)
        for _ in range(10):
            await asyncio.sleep(0.5)
            refreshed_status = desktop_controller.get_application_status("Notepad")
            windows = refreshed_status.get("windows", [])
            if windows and any(w.get("width", 0) > 200 for w in windows):
                break

    if not windows:
        print("  [ERROR] No active Notepad windows found after launch/focus.")
        return 1

    # Filter for real visible Notepad application window (reject IME and zero-size helper windows)
    main_notepad_windows = [
        w for w in windows
        if w.get("width", 0) > 200
        and "ime" not in w.get("title", "").lower()
        and "gdi+" not in w.get("title", "").lower()
    ]
    active_win = main_notepad_windows[0] if main_notepad_windows else windows[0]
    best_hwnd = active_win.get("hwnd")
    window_manager.move_to_main_screen(best_hwnd)
    await asyncio.sleep(0.3)
    window_manager.restore_and_focus(best_hwnd)
    await asyncio.sleep(1.2)

    win_x, win_y, win_w, win_h = (
        get_window_bounds(best_hwnd)
        if window_manager.user32
        else (active_win.get("x", 0), active_win.get("y", 0), active_win.get("width", 1920), active_win.get("height", 1080))
    )

    # In Windows 11 Notepad:
    # - Tabs are at win_y + 50
    # - Menu bar ('File', 'Edit', 'View') is at win_y + 95
    # - Document editor canvas starts at win_y + 115
    doc_x = win_x + 10
    doc_y = win_y + 115
    doc_w = win_w - 20
    doc_h = min(500, win_h - 135)
    doc_bounds = (doc_x, doc_y, doc_w, doc_h)

    # In Notepad, text lines start at win_x + 30, win_y + 140
    line_x = win_x + 30
    line_y = win_y + 140
    focus_x = win_x + 100
    focus_y = win_y + 160

    # Ensure document editor canvas has physical focus before clearing buffer
    from app.interaction.input.mouse_controller import mouse_controller
    mouse_controller.actuate_click(ScreenPoint(x=focus_x, y=focus_y))
    await asyncio.sleep(0.3)

    # Ensure starting document editor buffer is clean
    await action_executor.execute_intent(
        intent=Intent(intent_id=str(uuid.uuid4()), action=SemanticAction.HOTKEY, capability_id="desktop.physical_input", target="Editor"),
        tool_args={"intent": "HOTKEY", "keys": ["ctrl", "a"]},
    )
    await asyncio.sleep(0.15)
    await action_executor.execute_intent(
        intent=Intent(intent_id=str(uuid.uuid4()), action=SemanticAction.PRESS_KEY, capability_id="desktop.physical_input", target="Editor"),
        tool_args={"intent": "PRESS_KEY", "key": "backspace"},
    )
    await asyncio.sleep(0.3)

    print(f"  Target Window HWND:    {best_hwnd} ({win_w}x{win_h} at {win_x},{win_y})")
    print(f"  Document Area Bounds:  x={doc_x}, y={doc_y}, w={doc_w}, h={doc_h}")
    print(f"  Editor Focus Anchor:   ({focus_x}, {focus_y})")
    print(f"  Document Line Anchor:  ({line_x}, {line_y})")

    # STAGE 2: Build the Canonical Composite Sequence
    import secrets
    unique_token = "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz") for _ in range(6))
    test_payload = f"Astra Composite {unique_token} Line"
    drag_start_x = max(doc_x + 15, line_x + 5)
    drag_start_y = line_y
    drag_end_x = min(doc_x + doc_w - 20, line_x + 350)
    drag_end_y = line_y

    print(f"\n[STAGE 2] Formulating Composite Action Sequence (Token: '{unique_token}'):")
    print("  Workflow: Focus Editor → Type Text → Drag-Select Text → Context Menu → Dismiss/Cleanup")

    # Clear clipboard prior to test to ensure pure selection verification
    clear_clipboard()

    # Define steps
    step_focus = CompositeStep(
        step_id="step_focus_editor",
        step_index=0,
        intent=Intent(intent_id=str(uuid.uuid4()), action=SemanticAction.CLICK, capability_id="desktop.physical_input", target="Editor"),
        tool_args={"intent": "CLICK", "x": focus_x, "y": focus_y},
        description="Focus Document Editor Canvas",
        requires_verification=False,
        settle_delay_seconds=0.4,
    )

    step_type = CompositeStep(
        step_id="step_type_payload",
        step_index=1,
        intent=Intent(intent_id=str(uuid.uuid4()), action=SemanticAction.TYPE_TEXT, capability_id="desktop.physical_input", target="Editor"),
        tool_args={"intent": "TYPE_TEXT", "x": line_x, "y": line_y, "text": test_payload + "\n"},
        description=f"Type Payload '{test_payload}'",
        requires_verification=True,
        verifier_type="TEXT_INPUT",
        verifier_args={"expected_text": test_payload, "target_bounds": doc_bounds},
        settle_delay_seconds=1.2,
    )

    step_drag = CompositeStep(
        step_id="step_drag_select",
        step_index=2,
        intent=Intent(intent_id=str(uuid.uuid4()), action=SemanticAction.DRAG, capability_id="desktop.physical_input", target="Editor"),
        tool_args={
            "intent": "DRAG",
            "x": drag_start_x,
            "y": drag_start_y,
            "start_x": drag_start_x,
            "start_y": drag_start_y,
            "end_x": drag_end_x,
            "end_y": drag_end_y,
            "steps": 12,
        },
        description="Drag-Select Text Across Payload",
        requires_verification=True,
        verifier_type="DRAG",
        verifier_args={"target_label": unique_token, "fallback_word": "Composite", "target_bounds": doc_bounds},
        compensation=CompensationAction(
            intent=Intent(intent_id=str(uuid.uuid4()), action=SemanticAction.PRESS_KEY, capability_id="desktop.physical_input"),
            tool_args={"intent": "PRESS_KEY", "key": "right"},
            description="Clear Selection via Right Arrow",
        ),
        settle_delay_seconds=0.4,
    )

    step_context_menu = CompositeStep(
        step_id="step_context_menu",
        step_index=3,
        intent=Intent(intent_id=str(uuid.uuid4()), action=SemanticAction.RIGHT_CLICK, capability_id="desktop.physical_input", target="Editor"),
        tool_args={"intent": "RIGHT_CLICK", "x": line_x + 100, "y": line_y},
        description="Open Context Menu on Selected Editor Canvas",
        requires_verification=True,
        verifier_type="CONTEXT_MENU",
        verifier_args={"click_point": (line_x + 100, line_y), "window_bounds": (win_x, win_y, win_w, win_h), "target_label": unique_token, "fallback_word": "Composite", "target_bounds": doc_bounds},
        compensation=CompensationAction(
            intent=Intent(intent_id=str(uuid.uuid4()), action=SemanticAction.PRESS_KEY, capability_id="desktop.physical_input"),
            tool_args={"intent": "PRESS_KEY", "key": "escape"},
            description="Dismiss Context Menu via Escape",
        ),
        settle_delay_seconds=0.8,
    )

    # Dismiss menu via Escape, then clear editor via Ctrl+A and Backspace
    step_cleanup = CompositeStep(
        step_id="step_cleanup_buffer",
        step_index=4,
        intent=Intent(intent_id=str(uuid.uuid4()), action=SemanticAction.HOTKEY, capability_id="desktop.physical_input", target="Editor"),
        tool_args={"intent": "HOTKEY", "keys": ["ctrl", "a"]},
        description="Dismiss Flyouts & Clear Editor Buffer",
        requires_verification=True,
        verifier_type="TEXT_ABSENT",
        verifier_args={"expected_text": test_payload, "target_bounds": doc_bounds},
        settle_delay_seconds=0.5,
    )

    sequence = CompositeActionSequence(
        sequence_id=f"seq_{uuid.uuid4().hex[:8]}",
        name="Focus_Type_Drag_Menu_Cleanup_Flow",
        steps=[step_focus, step_type, step_drag, step_context_menu, step_cleanup],
        timeout_seconds=90.0,
        max_retries_per_step=1,
        allow_compensation=True,
    )

    # STAGE 3: Execute Sequence via ActionExecutor
    print(f"\n[STAGE 3] Executing Sequence via ActionExecutor.execute_sequence (Sequence ID: {sequence.sequence_id}):")
    t_seq_start = time.perf_counter()
    result: CompositeExecutionResult = await action_executor.execute_sequence(sequence)
    t_seq_end = time.perf_counter()

    print(f"  Sequence Execution Finished in {(t_seq_end - t_seq_start)*1000:.1f}ms")
    print(f"  Terminal Status:       {result.terminal_status.value}")
    print(f"  Total Steps:           {result.total_steps}")
    print(f"  Completed Steps:       {result.completed_steps}")

    print("\n[STAGE 4] Detailed Step Execution Breakdown:")
    for s in result.step_results:
        vr_status = s.verification_result.verified.name if s.verification_result else "N/A"
        evidence_snippet = (s.verification_result.evidence[:50] + "...") if s.verification_result and s.verification_result.evidence else "No evidence"
        print(f"  - Step {s.step_index} [{s.status.value}]: {s.description}")
        print(f"      Actuation Accepted: {s.actuation_accepted} | Verification: {vr_status} ({evidence_snippet})")
        print(f"      Duration: {s.duration_ms:.1f}ms")
        if s.error:
            print(f"      Error: {s.error}")

    if result.compensations_executed:
        print(f"\n[COMPENSATIONS EXECUTED] ({len(result.compensations_executed)}):")
        for c in result.compensations_executed:
            print(f"  - {c.description} (Executed: {c.executed}, Verified: {c.verified.name})")

    # STAGE 5: Final Teardown Safety Pass (Guaranteed Empty Buffer)
    print("\n[STAGE 5] Final Teardown Safety Pass:")
    from app.interaction.input.keyboard_controller import keyboard_controller
    keyboard_controller.actuate_escape(press_count=2)
    await asyncio.sleep(0.3)
    await action_executor.execute_intent(
        intent=Intent(intent_id=str(uuid.uuid4()), action=SemanticAction.HOTKEY, capability_id="desktop.physical_input"),
        tool_args={"intent": "HOTKEY", "keys": ["ctrl", "a"]},
    )
    await asyncio.sleep(0.1)
    await action_executor.execute_intent(
        intent=Intent(intent_id=str(uuid.uuid4()), action=SemanticAction.PRESS_KEY, capability_id="desktop.physical_input"),
        tool_args={"intent": "PRESS_KEY", "key": "backspace"},
    )
    await asyncio.sleep(0.4)
    print("  Safety buffer clear executed.")
    subprocess.run(["powershell", "-Command", "Stop-Process -Name notepad -Force -ErrorAction SilentlyContinue"], capture_output=True)

    overall_pass = (result.terminal_status == CompositeTerminalStatus.SUCCESS)
    print_banner(f"ASTRA - PHASE B.6: RESULT {'PASS' if overall_pass else 'FAIL'}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASTRA Phase B.6 Composite Action Workflow Live Test")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Explicitly authorize physical input actuation against Notepad.",
    )
    args = parser.parse_args()
    exit_code = asyncio.run(run_live_composite_workflow(opt_in_confirmed=args.execute))
    sys.exit(exit_code)
