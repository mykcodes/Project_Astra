"""
ASTRA — Phase B.7: Multi-Window & Cross-Application Composite Workflow Live Test (OPT-IN ONLY)

Executes a canonical multi-window composite workflow across distinct desktop applications:
  Focus App A (Notepad) → Type Payload → Copy to OS Clipboard → Switch to App B (Calculator) → Verify Multi-Window Focus & State → Clean Dismissal

Orchestrated through:
  ActionPlanner.plan_composite_sequence → ActionExecutor.execute_sequence → VerificationEngine
  preserving the observe → act → observe → verify → recover loop per step.
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
from app.tools.desktop.desktop_controller import DesktopController, ApplicationIntent
from app.environment.window.manager import window_manager
from tests.live.diagnose_interactive_actuation import diagnose_environment
from app.interaction.input.keyboard_controller import clear_clipboard, get_clipboard_text


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


def print_banner(text: str):
    print("\n" + "=" * 75)
    print(text)
    print("=" * 75)


async def run_live_multi_window_workflow(opt_in_confirmed: bool = False) -> int:
    print_banner("ASTRA - PHASE B.7: MULTI-WINDOW & CROSS-APPLICATION WORKFLOW")

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
        print("  No physical cross-window input was actuated.")
        print("\n  Pre-flight readiness check completed.")
        print("  To run the full verified multi-window workflow, run:")
        print("    python tests/live/test_live_multi_window_composite.py --execute\n")
        print_banner("ASTRA - PHASE B.7: DRY-RUN COMPLETED")
        return 0

    print("\n[OPT-IN CONFIRMED] Explicit execution authorization granted by user.")

    import secrets
    import subprocess
    from app.domain.entities import ScreenPoint
    from app.interaction.input.mouse_controller import mouse_controller

    dc = DesktopController()
    unique_token = "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz") for _ in range(6))
    test_payload = f"Astra CrossWin {unique_token} Token"

    # STAGE 1: Target Applications Establishment
    print("\n[STAGE 1] Application State & Window Establishment:")
    app1_name = "notepad"
    app2_name = "calc"

    # Ensure clean starting state: terminate stale processes
    subprocess.run(["powershell", "-Command", "Stop-Process -Name notepad, CalculatorApp -Force -ErrorAction SilentlyContinue"], capture_output=True)
    await asyncio.sleep(0.5)

    app1_stat = dc.get_application_status(app1_name, force_refresh=True)
    print(f"  Initial Notepad State:    {app1_stat['state']} (Installed: {app1_stat['installed']})")
    open_res1 = await dc.execute_intent(ApplicationIntent.OPEN, app1_name)
    print(f"  Spawned Notepad:          Success={open_res1.get('success')}")
    await asyncio.sleep(1.2)

    app1_windows = []
    for _ in range(8):
        refreshed_stat = dc.get_application_status(app1_name, force_refresh=True)
        app1_windows = [
            w for w in refreshed_stat.get("windows", [])
            if (w.get("width", 0) if isinstance(w, dict) else getattr(w, "width", 0)) > 200
            and "ime" not in (w.get("title", "") if isinstance(w, dict) else getattr(w, "title", "")).lower()
        ]
        if app1_windows:
            break
        await asyncio.sleep(0.5)

    if not app1_windows:
        # Fallback to direct launch via execution alias
        subprocess.Popen(["cmd.exe", "/c", "start", "", "notepad.exe"], shell=True)
        for _ in range(10):
            await asyncio.sleep(0.5)
            refreshed_stat = dc.get_application_status(app1_name, force_refresh=True)
            app1_windows = [
                w for w in refreshed_stat.get("windows", [])
                if (w.get("width", 0) if isinstance(w, dict) else getattr(w, "width", 0)) > 200
                and "ime" not in (w.get("title", "") if isinstance(w, dict) else getattr(w, "title", "")).lower()
            ]
            if app1_windows:
                break

    if not app1_windows:
        print("  [ERROR] Notepad window could not be established.")
        return 1

    win1 = app1_windows[0]
    hwnd1 = win1.get("hwnd") if isinstance(win1, dict) else getattr(win1, "hwnd", None)
    if not hwnd1:
        print("  [ERROR] Notepad HWND could not be resolved.")
        return 1

    window_manager.move_to_main_screen(hwnd1)
    await asyncio.sleep(0.2)
    window_manager.restore_and_focus(hwnd1)
    await asyncio.sleep(0.8)

    win1_x, win1_y, win1_w, win1_h = get_window_bounds(hwnd1)
    doc1_x = win1_x + 10
    doc1_y = win1_y + 70
    doc1_w = win1_w - 20
    doc1_h = min(500, win1_h - 90)
    doc1_bounds = (doc1_x, doc1_y, doc1_w, doc1_h)
    line1_x = win1_x + 60
    line1_y = win1_y + 150
    focus1_x = win1_x + 100
    focus1_y = win1_y + 15

    print(f"  Target Notepad Window:    HWND={hwnd1}, Bounds=({win1_x}, {win1_y}, {win1_w}, {win1_h})")
    print(f"  Notepad Document Bounds:  Bounds=({doc1_x}, {doc1_y}, {doc1_w}, {doc1_h})")

    # Clear starting Notepad document buffer
    mouse_controller.actuate_click(ScreenPoint(x=line1_x, y=line1_y))
    await asyncio.sleep(0.3)
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

    # Establish Calculator
    app2_stat = dc.get_application_status(app2_name, force_refresh=True)
    print(f"  Initial Calc State:       {app2_stat['state']} (Installed: {app2_stat['installed']})")
    open_res2 = await dc.execute_intent(ApplicationIntent.OPEN, app2_name)
    print(f"  Spawned Calculator:       Success={open_res2.get('success')}")
    await asyncio.sleep(1.2)

    hwnd2 = None
    win2_x, win2_y, win2_w, win2_h = 500, 300, 400, 500
    for _ in range(12):
        await asyncio.sleep(0.5)
        app2_stat = dc.get_application_status(app2_name, force_refresh=True)
        app2_windows = [
            w for w in app2_stat.get("windows", [])
            if (w.get("width", 0) if isinstance(w, dict) else getattr(w, "width", 0)) > 200
        ]
        if app2_windows:
            win2 = app2_windows[0]
            hwnd2 = win2.get("hwnd") if isinstance(win2, dict) else getattr(win2, "hwnd", None)
            if hwnd2:
                window_manager.move_to_main_screen(hwnd2)
                await asyncio.sleep(0.2)
                bounds = get_window_bounds(hwnd2)
                if bounds[2] > 200:
                    win2_x, win2_y, win2_w, win2_h = bounds
                    break

    calc_click_x = win2_x + int(win2_w * 0.5)
    calc_click_y = win2_y + 35
    if hwnd2:
        print(f"  Target Calc Window:       HWND={hwnd2}, Bounds=({win2_x}, {win2_y}, {win2_w}, {win2_h})")
    else:
        print(f"  [WARN] Calc window not directly resolved; will target by app name '{app2_name}'.")

    # Restore Notepad focus before sequence execution
    window_manager.restore_and_focus(hwnd1)
    await asyncio.sleep(0.5)
    mouse_controller.actuate_click(ScreenPoint(x=focus1_x, y=focus1_y))
    await asyncio.sleep(0.3)

    # STAGE 2: Multi-Window Composite Sequence Formulation
    print("\n[STAGE 2] Multi-Window Composite Action Sequence Formulation:")
    clear_clipboard()

    steps_def = [
        # Step 0: Focus Notepad
        {
            "step_id": "step_0_focus_notepad",
            "action": "CLICK",
            "target": app1_name,
            "target_app_name": app1_name,
            "target_hwnd": hwnd1,
            "ensure_foreground": True,
            "tool_args": {"intent": "CLICK", "x": focus1_x, "y": focus1_y},
            "description": "Step 0: Focus Notepad window and engage caret",
            "requires_verification": True,
            "verifier_type": "WINDOW_FOCUS",
            "verifier_args": {"target_hwnd": hwnd1, "target_app_name": app1_name},
            "settle_delay_seconds": 0.4,
        },
        # Step 1: Type unique payload in Notepad
        {
            "step_id": "step_1_type_payload",
            "action": "TYPE_TEXT",
            "target": app1_name,
            "target_app_name": app1_name,
            "target_hwnd": hwnd1,
            "ensure_foreground": True,
            "tool_args": {"intent": "TYPE_TEXT", "x": line1_x, "y": line1_y, "text": f"{test_payload}\n"},
            "description": f"Step 1: Type payload '{test_payload}' in Notepad",
            "requires_verification": True,
            "verifier_type": "TEXT_INPUT",
            "verifier_args": {"expected_text": test_payload, "target_bounds": doc1_bounds},
            "settle_delay_seconds": 1.0,
        },
        # Step 2: Select all text in Notepad
        {
            "step_id": "step_2_select_all",
            "action": "HOTKEY",
            "target": app1_name,
            "target_app_name": app1_name,
            "target_hwnd": hwnd1,
            "ensure_foreground": True,
            "tool_args": {"intent": "HOTKEY", "keys": ["ctrl", "a"]},
            "description": "Step 2: Select all text in Notepad",
            "requires_verification": False,
            "settle_delay_seconds": 0.3,
        },
        # Step 3: Copy selection to OS clipboard
        {
            "step_id": "step_3_copy_clipboard",
            "action": "HOTKEY",
            "target": app1_name,
            "target_app_name": app1_name,
            "target_hwnd": hwnd1,
            "ensure_foreground": True,
            "tool_args": {"intent": "HOTKEY", "keys": ["ctrl", "c"]},
            "description": "Step 3: Copy selection to OS clipboard",
            "requires_verification": True,
            "verifier_type": "CLIPBOARD",
            "verifier_args": {"expected_content": unique_token},
            "settle_delay_seconds": 0.4,
        },
        # Step 4: Switch focus to Calculator
        {
            "step_id": "step_4_switch_to_calc",
            "action": "CLICK",
            "target": app2_name,
            "target_app_name": app2_name,
            "target_hwnd": hwnd2,
            "ensure_foreground": True,
            "tool_args": {"intent": "CLICK", "x": calc_click_x, "y": calc_click_y},
            "description": "Step 4: Switch focus to Calculator window",
            "requires_verification": True,
            "verifier_type": "WINDOW_FOCUS",
            "verifier_args": {"target_hwnd": hwnd2, "target_app_name": app2_name},
            "settle_delay_seconds": 0.5,
        },
        # Step 5: Verify cross-window data synchronization
        {
            "step_id": "step_5_verify_cross_window",
            "action": "HOTKEY",
            "target": app2_name,
            "target_app_name": app2_name,
            "tool_args": {"intent": "HOTKEY", "keys": ["escape"]},
            "description": "Step 5: Verify cross-window payload transfer and focus integrity",
            "requires_verification": True,
            "verifier_type": "CROSS_WINDOW_SYNC",
            "verifier_args": {
                "expected_content": unique_token,
                "source_window": "Notepad",
                "destination_window": "Calculator",
            },
            "settle_delay_seconds": 0.3,
        },
        # Step 6: Safe Cleanup - Return to Notepad and empty document buffer
        {
            "step_id": "step_6_cleanup_notepad",
            "action": "HOTKEY",
            "target": app1_name,
            "target_app_name": app1_name,
            "target_hwnd": hwnd1,
            "ensure_foreground": True,
            "tool_args": {"intent": "HOTKEY", "keys": ["ctrl", "a"]},
            "description": "Step 6: Clean up Notepad document buffer",
            "requires_verification": True,
            "verifier_type": "TEXT_ABSENT",
            "verifier_args": {"expected_text": test_payload, "target_bounds": doc1_bounds},
            "settle_delay_seconds": 0.5,
        },
    ]

    sequence = action_planner.plan_composite_sequence(
        sequence_name=f"multi_window_workflow_{unique_token}",
        steps_def=steps_def,
        timeout_seconds=90.0,
        max_retries_per_step=2,
    )

    print(f"  Sequence ID:          {sequence.sequence_id}")
    print(f"  Total Steps Defined:  {len(sequence.steps)}")
    for s in sequence.steps:
        print(f"    - [{s.step_index}] {s.step_id} (App: {s.target_app_name or 'N/A'}, Verifier: {s.verifier_type or 'NONE'})")

    # STAGE 3: Execute Multi-Window Composite Sequence
    print("\n[STAGE 3] Executing Multi-Window Composite Action Sequence:")
    t_start = time.perf_counter()
    result = await action_executor.execute_sequence(sequence)
    duration = time.perf_counter() - t_start

    print(f"\n[STAGE 4] Multi-Window Execution Breakdown (Duration: {duration:.2f}s):")
    print(f"  Terminal Status:      {result.terminal_status.value}")
    print(f"  Completed Steps:      {result.completed_steps}/{result.total_steps}")
    print(f"  Verified Steps:       {result.verified_steps}/{result.total_steps}")

    overall_pass = True
    for step in result.step_results:
        vr = step.verification_result
        if step.status == StepStatus.ACTUATION_ACCEPTED and not step.requires_verification:
            v_str = "NOT_REQUIRED (Actuation Accepted)"
        elif vr:
            v_str = f"{vr.verified.value} ({vr.actual_state})"
        else:
            v_str = "N/A"
        print(f"  Step {step.step_index} [{step.step_id}]: Status={step.status.value}, Actuation={step.actuation_accepted}, Verifier={v_str}")
        if step.status not in (StepStatus.VERIFIED_SUCCESS, StepStatus.ACTUATION_ACCEPTED):
            overall_pass = False

    # STAGE 5: Cleanup Application B (Close Calculator)
    print("\n[STAGE 5] Multi-Window Application Teardown & State Restoration:")
    try:
        close_res = await dc.execute_intent(ApplicationIntent.CLOSE, app2_name)
        print(f"  Closed Calculator:    Success={close_res.get('success')}")
    except Exception as e:
        print(f"  Calculator cleanup warning: {e}")
    subprocess.run(["powershell", "-Command", "Stop-Process -Name CalculatorApp -Force -ErrorAction SilentlyContinue"], capture_output=True)
    subprocess.run(["powershell", "-Command", "Stop-Process -Name notepad -Force -ErrorAction SilentlyContinue"], capture_output=True)

    # Check contract result
    print_banner(f"ASTRA - PHASE B.7: RESULT {'PASS' if overall_pass else 'FAIL'}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASTRA Phase B.7 Multi-Window Composite Workflow Live Test")
    parser.add_argument("--execute", action="store_true", help="Authorize live interactive multi-window execution")
    args = parser.parse_args()

    exit_code = asyncio.run(run_live_multi_window_workflow(opt_in_confirmed=args.execute))
    sys.exit(exit_code)
