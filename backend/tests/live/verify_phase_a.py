import asyncio
import time
from app.environment.awareness.windows import WindowsSystemAwarenessProvider
from app.environment.awareness.diff import compute_diff, WorldStateChangeType
from app.tools.desktop.desktop_controller import desktop_controller
from app.tools.desktop.application_state import ApplicationIntent

async def run_scenario():
    print("==================================================")
    print("ASTRA PHASE A LIVE VERIFICATION")
    print("Scenario: Notepad Open -> Focus -> Close")
    print("==================================================")
    
    provider = WindowsSystemAwarenessProvider()
    
    print("\n[1] Observing initial state...")
    ws_initial = provider.observe_world_state()
    print(f"    Observation status: {ws_initial.observation.status.value}")
    
    # Check if notepad is already running
    notepad_initial = provider.observe_application("notepad")
    if notepad_initial.running == "TRUE":
        print("    WARNING: Notepad is already running. Please close it and restart the test.")
        return

    print("\n[2] Launching Notepad...")
    await desktop_controller.execute_intent(ApplicationIntent.OPEN, "notepad")
    
    # Wait for it to open and settle
    time.sleep(2)
    
    print("\n[3] Observing new state...")
    ws_opened = provider.observe_world_state()
    
    print("\n[4] Computing Diff...")
    diff_opened = compute_diff(ws_initial, ws_opened)
    
    opened_events = [c for c in diff_opened.changes if c.change_type == WorldStateChangeType.APPLICATION_OPENED]
    notepad_opened = any("notepad" in (c.entity_id or "").lower() for c in opened_events)
    print(f"    Application Opened Events: {len(opened_events)}")
    print(f"    Notepad Opened Detected: {notepad_opened}")
    
    print("\n[5] Focusing Notepad...")
    await desktop_controller.execute_intent(ApplicationIntent.FOCUS, "notepad")
    time.sleep(1)
    
    print("\n[6] Observing state...")
    ws_focused = provider.observe_world_state()
    
    print("\n[7] Verifying Foreground...")
    is_notepad_fg = False
    if ws_focused.foreground and "notepad" in ws_focused.foreground.owner_application.lower():
        is_notepad_fg = True
    print(f"    Notepad is Foreground: {is_notepad_fg}")
    
    print("\n[8] Closing Notepad...")
    await desktop_controller.execute_intent(ApplicationIntent.CLOSE, "notepad")
    time.sleep(2)
    
    print("\n[9] Observing final state...")
    ws_closed = provider.observe_world_state()
    
    print("\n[10] Computing Diff...")
    diff_closed = compute_diff(ws_focused, ws_closed)
    
    closed_events = [c for c in diff_closed.changes if c.change_type == WorldStateChangeType.APPLICATION_CLOSED]
    notepad_closed = any("notepad" in (c.entity_id or "").lower() for c in closed_events)
    print(f"    Application Closed Events: {len(closed_events)}")
    print(f"    Notepad Closed Detected: {notepad_closed}")
    
    print("\n==================================================")
    print("VERIFICATION SUMMARY")
    print(f"Notepad Detected Opened:  {'PASS' if notepad_opened else 'FAIL'}")
    print(f"Notepad Detected as FG:   {'PASS' if is_notepad_fg else 'FAIL'}")
    print(f"Notepad Detected Closed:  {'PASS' if notepad_closed else 'FAIL'}")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_scenario())
