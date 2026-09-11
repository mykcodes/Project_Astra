import asyncio
import logging
import time
import sys
import psutil
sys.stdout.reconfigure(encoding='utf-8')
from app.domain.goals import Intent, SemanticAction, TargetType, TargetOrdinal
from app.ai.orchestrator.action_executor import action_executor
from app.environment.window.manager import WindowManager
from app.domain.entities import TriState

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

async def verify_phase_b1():
    print("============================================================")
    print("PHASE B.1 — UNIVERSAL PHYSICAL INPUT FOUNDATION LIVE VERIFICATION")
    print("============================================================")

    # 1. SETUP: Open Notepad to create a safe surface
    print("\n[STEP 1] Setting up safe test surface (Notepad)...")
    intent_open = Intent(
        intent_id="b1-open",
        action=SemanticAction.OPEN,
        target="Notepad",
        target_type=TargetType.APPLICATION,
        ordinal=TargetOrdinal.NONE,
        capability_id="desktop.open_application"
    )
    result_open = await action_executor.execute_intent(intent_open, {"intent": "OPEN", "application": "Notepad"}, max_attempts=1)
    if not result_open.get("success"):
        print("❌ FAILED to open Notepad. Cannot proceed with safe physical testing.")
        return
        
    time.sleep(2.0)
    
    # 2. DISCOVERY: Find Notepad's WindowBounds
    window_manager = WindowManager()
    
    time.sleep(1.0)
    
    # Wait for the window to actually appear
    window_entity = None
    for _ in range(10):
        time.sleep(0.5)
        # Find Notepad pid
        pids = [p.pid for p in psutil.process_iter(['name']) if p.info['name'] and 'notepad' in p.info['name'].lower()]
        if pids:
            windows = window_manager.get_windows_for_pids(pids)
            if windows:
                window_entity = windows[0]
                break
            
    if not window_entity:
        print("❌ FAILED to find Notepad window as foreground.")
        return
        
    bounds = window_entity.bounds if hasattr(window_entity, 'bounds') else window_entity
    if not bounds:
        print("❌ FAILED to retrieve Window bounds for Notepad.")
        return
        
    center_x = bounds.x + (bounds.width // 2)
    center_y = bounds.y + (bounds.height // 2)
    print(f"✅ Safe test surface located at Point({center_x}, {center_y})")
    
    # 3. TEST: MOVE_MOUSE
    print("\n[STEP 2] Testing MOVE_MOUSE actuation & TriState TRUE verification...")
    intent_move = Intent(
        intent_id="b1-move",
        action=SemanticAction.MOVE_MOUSE,
        target=f"Point({center_x},{center_y})",
        target_type=TargetType.COORDINATE,
        ordinal=TargetOrdinal.NONE,
        capability_id="desktop.physical_input" # Mapped in registry
    )
    result_move = await action_executor.execute_intent(intent_move, {"intent": "MOVE_MOUSE", "x": center_x, "y": center_y})
    
    if result_move.get("success") and result_move.get("verified") == TriState.TRUE:
        print("✅ MOVE_MOUSE Actuation: SUCCESS")
        print("✅ MOVE_MOUSE Verification: TRUE")
    else:
        print(f"❌ MOVE_MOUSE failed: {result_move}")
        return
        
    time.sleep(1.0)
        
    # 4. TEST: CLICK
    print("\n[STEP 3] Testing CLICK actuation & TriState UNKNOWN verification separation...")
    intent_click = Intent(
        intent_id="b1-click",
        action=SemanticAction.CLICK,
        target=f"Point({center_x},{center_y})",
        target_type=TargetType.COORDINATE,
        ordinal=TargetOrdinal.NONE,
        capability_id="desktop.physical_input"
    )
    result_click = await action_executor.execute_intent(intent_click, {"intent": "CLICK", "x": center_x, "y": center_y})
    
    if result_click.get("success") and result_click.get("verified") == TriState.UNKNOWN:
        print("✅ CLICK Actuation: SUCCESS")
        print("✅ CLICK Verification: UNKNOWN")
    else:
        print(f"❌ CLICK failed or violated TriState contract: {result_click}")
        return
        
    # 5. TEARDOWN
    print("\n[STEP 4] Tearing down test surface...")
    intent_close = Intent(
        intent_id="b1-close",
        action=SemanticAction.CLOSE,
        target="Notepad",
        target_type=TargetType.APPLICATION,
        ordinal=TargetOrdinal.NONE,
        capability_id="desktop.close_application"
    )
    await action_executor.execute_intent(intent_close, {"intent": "CLOSE", "application": "Notepad"}, max_attempts=1)
    print("✅ Teardown complete.")
    
    print("\n============================================================")
    print("PHASE B.1 LIVE VERIFICATION: PASS")
    print("============================================================")

if __name__ == "__main__":
    asyncio.run(verify_phase_b1())
