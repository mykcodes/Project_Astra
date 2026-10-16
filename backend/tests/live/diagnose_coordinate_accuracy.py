"""
ASTRA — Phase B.3.6: Coordinate Accuracy & Actuation Verification Diagnostic

Inspects and verifies coordinate mapping accuracy between physical screen space
and Win32 SendInput normalized coordinate space (0-65535).

SAFETY CONSTRAINTS:
- OPT-IN ONLY: Requires explicit user invocation via --execute flag.
- Default behavior (without --execute): Pure read-only mathematical analysis.
- Safe action ONLY: Tests absolute movement to safe, centered in-bounds coordinates.
- Reuses existing production MouseController without modification.
- NO clicks, NO keyboard input, NO file alterations, NO window changes.
- Reports per-axis error in pixels and preserves distinction between:
  ACTUATION_REJECTED, ACTUATION_ACCEPTED, VERIFIED_SUCCESS, VERIFIED_MISMATCH, UNKNOWN.
"""

import argparse
import os
import sys
from typing import Any, Dict, List, Tuple

# Ensure backend root is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.domain.entities import ScreenPoint, TriState
from app.interaction.input.mouse_controller import mouse_controller
from tests.live.diagnose_interactive_actuation import diagnose_environment


def simulate_normalization_math(
    points: List[Tuple[int, int]],
    vx: int,
    vy: int,
    vcx: int,
    vcy: int,
) -> None:
    """
    Simulates the mathematical mapping between target pixels, normalized coordinates,
    and Windows win32k fixed-point reconstruction without actuating input.
    """
    print("\n" + "=" * 70)
    print("MATHEMATICAL COORDINATE NORMALIZATION AUDIT")
    print("=" * 70)
    print(f"Virtual Screen Geometry: origin=({vx}, {vy}), dimensions={vcx}x{vcy}\n")

    print(f"{'Target (X, Y)':<16} | {'Legacy Norm (dx, dy)':<22} | {'Legacy Recon (Err)':<20} | {'Corrected Norm':<16} | {'Corrected Recon (Err)'}")
    print("-" * 105)

    for px, py in points:
        # Legacy formula: int(((x - vx) * 65535) / vcx)
        old_nx = int(((px - vx) * 65535) / vcx) if vcx > 0 else 0
        old_ny = int(((py - vy) * 65535) / vcy) if vcy > 0 else 0
        old_rx = vx + ((old_nx * vcx) >> 16)
        old_ry = vy + ((old_ny * vcy) >> 16)
        old_err_x, old_err_y = old_rx - px, old_ry - py

        # Corrected pixel-center formula
        new_nx, new_ny = mouse_controller._normalize_coordinates(ScreenPoint(x=px, y=py))
        new_rx = vx + ((new_nx * vcx) >> 16)
        new_ry = vy + ((new_ny * vcy) >> 16)
        new_err_x, new_err_y = new_rx - px, new_ry - py

        print(
            f"({px:4d}, {py:4d}){'':<6} | "
            f"({old_nx:5d}, {old_ny:5d}){'':<8} | "
            f"({old_rx:4d}, {old_ry:4d}) ({old_err_x:+2d}, {old_err_y:+2d}){'':<4} | "
            f"({new_nx:5d}, {new_ny:5d}){'':<2} | "
            f"({new_rx:4d}, {new_ry:4d}) ({new_err_x:+2d}, {new_err_y:+2d})"
        )

    print("-" * 105)
    print("Mathematical Audit:")
    print("  Legacy:    int((x * 65535) / width) -> truncates downward during Win32 >> 16 (-1px error).")
    print("  Corrected: int(((x + 0.5) * 65536) / width) -> pixel-center fixed-point scaling (0px error).")
    print("=" * 70 + "\n")


def run_accuracy_diagnostic(opt_in_confirmed: bool = False) -> int:
    """
    Runs the coordinate accuracy diagnostic.
    Without --execute: runs read-only simulation.
    With --execute: runs controlled physical movement test on interactive desktop.
    """
    print("=" * 70)
    print("ASTRA — PHASE B.3.6: COORDINATE ACCURACY & ACTUATION DIAGNOSTIC")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # STEP 1: Pre-Flight Environment Diagnostic
    # -------------------------------------------------------------------------
    diag = diagnose_environment()
    sd = diag["station_and_desktop"]
    syn = diag["execution_context_synthesis"]

    print("\n[PRE-FLIGHT] Environment Context:")
    print(f"  Classification:        {syn['summary']}")
    print(f"  Thread Desktop:        {sd['thread_desktop_name']}")
    print(f"  Active Input Desktop:  {sd['active_input_desktop_name']}")
    print(f"  Attached to Input:     {sd['is_on_active_input_desktop']}")

    vx, vy, vcx, vcy = mouse_controller._get_virtual_screen_bounds()
    print(f"  Virtual Screen Bounds: origin=({vx}, {vy}), size={vcx}x{vcy}")

    # Safe test points: well inside the desktop, away from taskbars and edges
    test_points = [
        (500, 400),
        (759, 721),    # Exact coordinate from Phase B.3.5
        (960, 540),    # Screen center
    ]

    # -------------------------------------------------------------------------
    # STEP 2: Mathematical Simulation (Read-Only)
    # -------------------------------------------------------------------------
    simulate_normalization_math(test_points, vx, vy, vcx, vcy)

    # -------------------------------------------------------------------------
    # STEP 3: Opt-In Enforcement for Physical Actuation
    # -------------------------------------------------------------------------
    if not opt_in_confirmed:
        print("[OPT-IN REQUIRED FOR PHYSICAL ACTUATION]")
        print("  This diagnostic was invoked in READ-ONLY mode (no mouse moved).")
        print("  To execute the physical movement accuracy test from an interactive")
        print("  desktop PowerShell session, run:")
        print("    .\\.venv\\Scripts\\python.exe tests/live/diagnose_coordinate_accuracy.py --execute")
        print("=" * 70 + "\n")
        return 0

    if not sd["is_on_active_input_desktop"]:
        print("\n[ERROR: INCOMPATIBLE DESKTOP]")
        print("  Physical actuation aborted: Thread is NOT on the active input desktop ('Default').")
        print("  Run this command from an interactive Windows PowerShell terminal.")
        print("=" * 70 + "\n")
        return 2

    print("\n[OPT-IN CONFIRMED] Executing controlled physical actuation test...")

    # -------------------------------------------------------------------------
    # STEP 4: Physical Actuation Test with Existing MouseController
    # -------------------------------------------------------------------------
    initial_cursor = mouse_controller.get_cursor_pos()
    print(f"[INITIAL] Starting Cursor Position: ({initial_cursor.x}, {initial_cursor.y})")

    results: List[Dict[str, Any]] = []

    for idx, (tx, ty) in enumerate(test_points, 1):
        target_pt = ScreenPoint(x=tx, y=ty)

        # Normalized values under corrected MouseController
        norm_x, norm_y = mouse_controller._normalize_coordinates(target_pt)

        # Read cursor before
        cursor_before = mouse_controller.get_cursor_pos()

        # Actuate via existing MouseController
        act_res = mouse_controller.actuate_move(target_pt)
        api_accepted = act_res.get("success", False)

        # Read cursor after
        cursor_after = mouse_controller.get_cursor_pos()

        err_x = cursor_after.x - tx
        err_y = cursor_after.y - ty

        # Determine outcome category
        if not api_accepted:
            outcome = "ACTUATION_REJECTED"
        elif cursor_after.x == tx and cursor_after.y == ty:
            outcome = "VERIFIED_SUCCESS"
        elif abs(err_x) > 0 or abs(err_y) > 0:
            outcome = "VERIFIED_MISMATCH"
        else:
            outcome = "UNKNOWN"

        results.append({
            "target": (tx, ty),
            "normalized": (norm_x, norm_y),
            "api_accepted": api_accepted,
            "cursor_before": (cursor_before.x, cursor_before.y),
            "cursor_after": (cursor_after.x, cursor_after.y),
            "error_pixels": (err_x, err_y),
            "outcome": outcome,
        })

        print(f"\n[TEST POINT {idx}] Target: ({tx}, {ty})")
        print(f"  Normalized (dx, dy): ({norm_x}, {norm_y})")
        print(f"  Win32 SendInput:     {'ACCEPTED' if api_accepted else 'REJECTED'}")
        print(f"  Observed Cursor:     ({cursor_after.x}, {cursor_after.y})")
        print(f"  Discrepancy (X, Y):  ({err_x:+d}px, {err_y:+d}px)")
        print(f"  Result Contract:     {outcome}")

    # Restore cursor to initial position
    mouse_controller.actuate_move(initial_cursor)
    print(f"\n[CLEANUP] Cursor restored to initial position: ({initial_cursor.x}, {initial_cursor.y})")

    # -------------------------------------------------------------------------
    # STEP 5: Overall Verification Summary
    # -------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("DIAGNOSTIC TEST SUMMARY")
    print("=" * 70)
    all_accepted = all(r["api_accepted"] for r in results)
    all_exact = all(r["outcome"] == "VERIFIED_SUCCESS" for r in results)
    all_mismatch = all(r["outcome"] == "VERIFIED_MISMATCH" for r in results)

    print(f"  API Acceptance:      {'ALL ACCEPTED' if all_accepted else 'SOME REJECTED'}")
    if all_mismatch:
        sample_err = results[0]["error_pixels"]
        print(f"  Physical Outcome:    CONSISTENT VERIFIED_MISMATCH (Offset: {sample_err})")
        print("  Root Cause:          Empirically confirmed normalization truncation in MouseController.")
        exit_code = 1
    elif all_exact:
        print("  Physical Outcome:    ALL VERIFIED_SUCCESS (Exact pixel match)")
        exit_code = 0
    else:
        print("  Physical Outcome:    MIXED / UNKNOWN")
        exit_code = 1

    print("=" * 70 + "\n")
    return exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASTRA B.3.6 Coordinate Accuracy Diagnostic")
    parser.add_argument("--execute", action="store_true", help="Explicit opt-in to actuate physical mouse movement")
    args = parser.parse_args()

    sys.exit(run_accuracy_diagnostic(opt_in_confirmed=args.execute))
