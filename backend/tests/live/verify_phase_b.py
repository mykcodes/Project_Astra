import asyncio
import logging
from app.domain.goals import Intent, SemanticAction, TargetType, TargetOrdinal
from app.ai.orchestrator.action_executor import action_executor

# Setup logging to output to console for diagnostics
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# We want to specifically see the InteractionRouter and ActionExecutor logs
logger = logging.getLogger("PhaseB_Diagnostic")

async def run_diagnostic():
    print("==================================================")
    print("ASTRA PHASE B.0 LIVE VERIFICATION")
    print("Scenario: Notepad Open -> Focus -> Close via ActionExecutor")
    print("==================================================")
    
    # 1. OPEN Notepad
    print("\n[1] Executing OPEN Notepad via ActionExecutor...")
    intent_open = Intent(
        intent_id="diag-open",
        action=SemanticAction.OPEN,
        target="Notepad",
        target_type=TargetType.APPLICATION,
        ordinal=TargetOrdinal.NONE,
        capability_id="desktop.open_application"
    )
    
    result_open = await action_executor.execute_intent(intent_open, {"intent": "OPEN", "application": "Notepad"}, max_attempts=1)
    
    open_verified = result_open.get("verified", False)
    print(f"    ActionExecutor returned verified: {open_verified}")
    if open_verified:
        vr = result_open.get("verification_result")
        print(f"    Verification Result: {vr.actual_state if vr else 'Unknown'}")
        
    await asyncio.sleep(2.0)
    
    # 2. FOCUS Notepad
    print("\n[2] Executing FOCUS Notepad via ActionExecutor...")
    intent_focus = Intent(
        intent_id="diag-focus",
        action=SemanticAction.FOCUS,
        target="Notepad",
        target_type=TargetType.APPLICATION,
        ordinal=TargetOrdinal.NONE,
        capability_id="desktop.focus_application"
    )
    
    result_focus = await action_executor.execute_intent(intent_focus, {"intent": "FOCUS", "application": "Notepad"}, max_attempts=1)
    
    focus_verified = result_focus.get("verified", False)
    print(f"    ActionExecutor returned verified: {focus_verified}")
    if not focus_verified:
        err = result_focus.get("error", {})
        print(f"    Verification Failure Reason: {err.get('message', err)}")
        if "verification_result" in result_focus:
            vr = result_focus["verification_result"]
            print(f"    Verification Actual State: {vr.actual_state}")
            print(f"    Evidence: {vr.evidence}")
            
    await asyncio.sleep(1.0)
    
    # 3. CLOSE Notepad
    print("\n[3] Executing CLOSE Notepad via ActionExecutor...")
    intent_close = Intent(
        intent_id="diag-close",
        action=SemanticAction.CLOSE,
        target="Notepad",
        target_type=TargetType.APPLICATION,
        ordinal=TargetOrdinal.NONE,
        capability_id="desktop.close_application"
    )
    
    result_close = await action_executor.execute_intent(intent_close, {"intent": "CLOSE", "application": "Notepad"}, max_attempts=1)
    
    close_verified = result_close.get("verified", False)
    print(f"    ActionExecutor returned verified: {close_verified}")
    if not close_verified:
        err = result_close.get("error", {})
        print(f"    Verification Failure Reason: {err.get('message', err)}")
        if "verification_result" in result_close:
            vr = result_close["verification_result"]
            print(f"    Verification Actual State: {vr.actual_state}")
            print(f"    Evidence: {vr.evidence}")
    
    print("\n==================================================")
    print("PHASE B.0 VERIFICATION SUMMARY")
    print("==================================================")
    
    def status_str(result_dict):
        # We handle failures returning success=False and verified=False
        if result_dict.get("verified"):
            return "PASS"
        if result_dict.get("error"):
            return "FAIL"
        return "UNKNOWN"
        
    print(f"Notepad OPEN:   {status_str(result_open)}")
    print(f"Notepad FOCUS:  {status_str(result_focus)}")
    print(f"Notepad CLOSE:  {status_str(result_close)}")
    print("==================================================")
    
    print("\nDiagnostics Note: ")
    print("Observe the console logs above. You should see:")
    print("1. 'ACTION_EXECUTION_ATTEMPT' from action_executor")
    print("2. 'INTERACTION_ROUTED' from InteractionRouter proving delegation.")
    print("3. Execution completing natively without the legacy Verification Loop polling.")

if __name__ == "__main__":
    asyncio.run(run_diagnostic())
