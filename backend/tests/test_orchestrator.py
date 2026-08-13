import pytest
from app.ai.orchestrator.intent import NormalizedIntent, IntentDomain
from app.ai.orchestrator.action_planner import ActionPlanner
from app.ai.orchestrator.verification import VerificationEngine
from app.tools.desktop.application_state import ApplicationState

def test_planner_desktop_intent():
    planner = ActionPlanner()
    intent = NormalizedIntent.desktop(action="OPEN", target="spotify")
    plan = planner.plan(intent)
    
    assert plan.capability.name == "desktop.execute_intent"
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "execute_application_intent"
    assert plan.steps[0].arguments == {"intent": "OPEN", "application": "spotify"}

def test_planner_system_intent():
    planner = ActionPlanner()
    intent = NormalizedIntent.system(action="get_info", requested_fields=["cpu", "memory"])
    plan = planner.plan(intent)
    
    assert plan.capability.name == "system.get_info"
    assert plan.steps[0].tool_name == "get_system_info"
    assert plan.steps[0].arguments == {"sections": ["cpu", "memory"]}

def test_verification_desktop():
    verifier = VerificationEngine()
    
    # Open should pass if running
    assert verifier.verify_desktop_action("OPEN", "spotify", ApplicationState.RUNNING_FOREGROUND.value, [123])
    assert verifier.verify_desktop_action("OPEN", "spotify", ApplicationState.RUNNING_MINIMIZED.value, [123])
    assert not verifier.verify_desktop_action("OPEN", "spotify", ApplicationState.INSTALLED_NOT_RUNNING.value, [])
    
    # Close should pass if not running
    assert verifier.verify_desktop_action("CLOSE", "spotify", ApplicationState.INSTALLED_NOT_RUNNING.value, [])
    assert not verifier.verify_desktop_action("CLOSE", "spotify", ApplicationState.RUNNING_FOREGROUND.value, [123])
    
    # Focus should pass if foreground
    assert verifier.verify_desktop_action("FOCUS", "spotify", ApplicationState.RUNNING_FOREGROUND.value, [123])
    assert not verifier.verify_desktop_action("FOCUS", "spotify", ApplicationState.RUNNING_BACKGROUND.value, [123])

def test_verification_system():
    verifier = VerificationEngine()
    
    # Should pass if fields exist
    assert verifier.verify_system_action(["cpu", "memory"], {"cpu": {}, "memory": {}, "os": {}})
    # Should fail if field missing
    assert not verifier.verify_system_action(["cpu", "gpu"], {"cpu": {}})
