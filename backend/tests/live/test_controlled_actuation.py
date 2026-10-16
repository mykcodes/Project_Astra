"""
ASTRA — Phase B.3.5: Controlled Interactive Actuation Test (OPT-IN ONLY)

This test is designed to run in the next stage from a confirmed interactive
Windows desktop session (normal PowerShell terminal).

CRITICAL SAFETY CONSTRAINTS:
- OPT-IN ONLY: Requires explicit user invocation via --execute flag.
- Safe, harmless action ONLY: Small mouse movement (no clicks, no typing, no file changes).
- Reuses existing MouseController without modification.
- Distinguishes API acceptance from physical cursor verification.
- Strictly adheres to verification contract: SUCCESS, FAILURE, or UNKNOWN.

DO NOT EXECUTE AUTOMATICALLY IN BACKGROUND SUBSHELLS.
"""

import argparse
import sys
import os

# Ensure backend root is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.domain.entities import ScreenPoint, TriState
from app.interaction.input.mouse_controller import mouse_controller
from tests.live.diagnose_interactive_actuation import diagnose_environment


def run_controlled_actuation_test(opt_in_confirmed: bool = False) -> int:
    """
    Executes a controlled, harmless mouse movement test if opt-in is confirmed
    and environment is verified.
    """
    print("=" * 70)
    print("ASTRA — PHASE B.3.5: CONTROLLED INTERACTIVE ACTUATION TEST")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # STEP 1: Diagnostic Pre-Flight Check
    # -------------------------------------------------------------------------
    diag = diagnose_environment()
    syn = diag["execution_context_synthesis"]
    sd = diag["station_and_desktop"]

    print("\n[PRE-FLIGHT] Environment Context:")
    print(f"  Classification:        {syn['summary']}")
    print(f"  Thread Desktop:        {sd['thread_desktop_name']}")
    print(f"  Active Input Desktop:  {sd['active_input_desktop_name']}")
    print(f"  Attached to Input:     {sd['is_on_active_input_desktop']}")

    if not sd["is_on_active_input_desktop"]:
        print("\n[PRE-FLIGHT WARNING]")
        print("  Thread is NOT attached to the active input desktop ('Default').")
        print("  Win32 SendInput will be rejected with ERROR_ACCESS_DENIED (5).")
        print("  To test physical actuation, run this script from a normal")
        print("  interactive Windows PowerShell window logged in to your desktop.")

    # -------------------------------------------------------------------------
    # STEP 2: Opt-In Enforcement
    # -------------------------------------------------------------------------
    if not opt_in_confirmed:
        print("\n[OPT-IN REQUIRED]")
        print("  This actuation test was invoked without the explicit '--execute' flag.")
        print("  No physical input was actuated.")
        print("  To run actuation in an interactive session, execute:")
        print("    python tests/live/test_controlled_actuation.py --execute")
        print("=" * 70 + "\n")
        return 0

    print("\n[OPT-IN CONFIRMED] Proceeding with single harmless movement test...")

    # -------------------------------------------------------------------------
    # STEP 3: Initial Cursor Position Capture
    # -------------------------------------------------------------------------
    initial_pos = mouse_controller.get_cursor_pos()
    print(f"\n[STEP 1] Initial Cursor Position: ({initial_pos.x}, {initial_pos.y})")

    # -------------------------------------------------------------------------
    # STEP 4: Calculate Harmless Safe Target Coordinate
    # -------------------------------------------------------------------------
    # Move by a tiny delta (+5, +5) within virtual screen bounds, or back by (-5, -5)
    vx, vy, vcx, vcy = mouse_controller._get_virtual_screen_bounds()
    target_x = initial_pos.x + 5 if (initial_pos.x + 5 < vx + vcx) else initial_pos.x - 5
    target_y = initial_pos.y + 5 if (initial_pos.y + 5 < vy + vcy) else initial_pos.y - 5
    target_point = ScreenPoint(x=target_x, y=target_y)

    print(f"[STEP 2] Safe Target Coordinate: ({target_point.x}, {target_point.y}) (delta: harmless +5px)")

    # -------------------------------------------------------------------------
    # STEP 5: Execute Actuation through Existing MouseController
    # -------------------------------------------------------------------------
    # Reuses production actuate_move without modifying it
    actuation_result = mouse_controller.actuate_move(target_point)
    api_accepted = actuation_result.get("success", False)

    print(f"[STEP 3] Win32 SendInput Execution: {'ACCEPTED' if api_accepted else 'REJECTED'}")
    if not api_accepted:
        err = actuation_result.get("error", {})
        print(f"         Error Code:    {err.get('code')}")
        print(f"         Error Message: {err.get('message')}")

    # -------------------------------------------------------------------------
    # STEP 6: Independent Cursor Position Verification
    # -------------------------------------------------------------------------
    observed_pos = mouse_controller.get_cursor_pos()
    print(f"[STEP 4] Post-Actuation Observed Cursor: ({observed_pos.x}, {observed_pos.y})")

    # -------------------------------------------------------------------------
    # STEP 7: Verification Contract Outcome
    # -------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("TEST OUTCOME SUMMARY")
    print("=" * 70)

    if api_accepted and observed_pos.x == target_point.x and observed_pos.y == target_point.y:
        outcome = "SUCCESS (VERIFIED_SUCCESS)"
        print(f"  Status:             {outcome}")
        print("  Actuation:          ACCEPTED by OS")
        print(f"  Physical Movement:  CONFIRMED at ({observed_pos.x}, {observed_pos.y})")
        exit_code = 0
    elif api_accepted and (observed_pos.x != target_point.x or observed_pos.y != target_point.y):
        outcome = "VERIFIED_MISMATCH"
        print(f"  Status:             {outcome}")
        print("  Actuation:          ACCEPTED by OS")
        print(f"  Physical Movement:  MISMATCH detected — Target: ({target_point.x}, {target_point.y}), Observed: ({observed_pos.x}, {observed_pos.y})")
        print(f"  Per-Axis Offset:    ({observed_pos.x - target_point.x:+d}px, {observed_pos.y - target_point.y:+d}px)")
        exit_code = 1
    elif api_accepted:
        outcome = "UNKNOWN"
        print(f"  Status:             {outcome}")
        print("  Actuation:          ACCEPTED by OS")
        print("  Physical Movement:  COULD NOT BE OBSERVED (observation missing or unavailable)")
        exit_code = 1
    else:
        outcome = "FAILURE (ACTUATION_FAILURE)"
        print(f"  Status:             {outcome}")
        print("  Actuation:          REJECTED by OS")
        print(f"  Diagnostic Cause:   {actuation_result.get('error')}")
        exit_code = 2

    print("=" * 70 + "\n")
    return exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASTRA B.3.5 Controlled Actuation Test")
    parser.add_argument("--execute", action="store_true", help="Explicit opt-in to execute single mouse movement")
    args = parser.parse_args()

    sys.exit(run_controlled_actuation_test(opt_in_confirmed=args.execute))
