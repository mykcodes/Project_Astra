"""
ASTRA — Phase B.7 Unit Regression Suite: Multi-Window & Cross-Application Composite Workflow Orchestration
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.domain.entities import TriState
from app.domain.goals import Intent, SemanticAction, VerificationResult, FailureClass, Goal, Task, TargetType
from app.domain.composite import (
    CompositeStep,
    CompositeActionSequence,
    CompositeExecutionResult,
    StepStatus,
    CompositeTerminalStatus,
    CompensationAction,
)
from app.ai.orchestrator.action_planner import action_planner
from app.ai.orchestrator.action_executor import ActionExecutor
from app.ai.orchestrator.compiler import ActionCompiler
from app.ai.orchestrator.verification import VerificationEngine
from app.domain.execution_context import ExecutionContext


def test_composite_step_multi_window_domain_fields():
    """Verify that CompositeStep accepts multi-window targeting fields with safe defaults."""
    intent = Intent(intent_id="intent_mw_1", action=SemanticAction.CLICK, target="notepad")
    step = CompositeStep(

        step_id="step_mw_1",
        step_index=0,
        intent=intent,
        description="Test step 1",
        target_app_name="notepad",
        target_window_title="Untitled - Notepad",
        target_hwnd=12345,
        ensure_foreground=True,
    )


    assert step.target_app_name == "notepad"
    assert step.target_window_title == "Untitled - Notepad"
    assert step.target_hwnd == 12345
    assert step.ensure_foreground is True

    # Test serialization round-trip
    dumped = step.model_dump()
    assert dumped["target_app_name"] == "notepad"
    assert dumped["target_hwnd"] == 12345

    rebuilt = CompositeStep.model_validate(dumped)
    assert rebuilt.target_app_name == "notepad"
    assert rebuilt.target_hwnd == 12345


def test_plan_composite_sequence_multi_window_support():
    """Verify that ActionPlanner.plan_composite_sequence propagates multi-window targeting."""
    steps_def = [
        {
            "action": "CLICK",
            "target": "notepad",
            "target_app_name": "notepad",
            "target_window_title": "Notepad",
            "ensure_foreground": True,
            "requires_verification": True,
            "verifier_type": "WINDOW_FOCUS",
        },
        {
            "action": "TYPE_TEXT",
            "target": "calculator",
            "target_app_name": "calc",
            "target_hwnd": 67890,
            "tool_args": {"text": "42"},
        },
    ]

    seq = action_planner.plan_composite_sequence("multi_window_test", steps_def)
    assert len(seq.steps) == 2
    assert seq.steps[0].target_app_name == "notepad"
    assert seq.steps[0].target_window_title == "Notepad"
    assert seq.steps[0].verifier_type == "WINDOW_FOCUS"
    assert seq.steps[1].target_app_name == "calc"
    assert seq.steps[1].target_hwnd == 67890


@pytest.mark.asyncio
async def test_action_compiler_compiles_desktop_intents_to_composite_sequence():
    """Verify ActionCompiler compiles multiple desktop interaction intents into a CompositeActionSequence."""
    compiler = ActionCompiler()
    context = ExecutionContext(execution_id="test_exec_b7")

    goal = Goal(
        goal_id="g_mw",
        objective="Type in Notepad and switch to Calculator",
        tasks=[
            Task(
                task_id="t_mw",
                description="Cross-app typing workflow",
                intents=[
                    Intent(
                        intent_id="i1",
                        action=SemanticAction.OPEN,
                        target="notepad",
                        target_type=TargetType.APPLICATION,
                    ),
                    Intent(
                        intent_id="i2",
                        action=SemanticAction.INPUT,
                        target="notepad",
                        target_type=TargetType.APPLICATION,
                        parameters={"text": "hello"},
                    ),
                ],
            )
        ],
    )

    compiled = await compiler.compile(goal, context)
    task = compiled.tasks[0]

    assert getattr(task, "composite_sequence", None) is not None
    seq = task.composite_sequence
    assert len(seq.steps) == 2
    assert seq.steps[0].intent.action == SemanticAction.OPEN
    assert seq.steps[1].intent.action == SemanticAction.INPUT


def test_verify_window_focus_hwnd_match():
    """Verify VerificationEngine.verify_window_focus matches target HWND authoritatively."""
    with patch("ctypes.windll.user32.GetForegroundWindow", return_value=54321):
        vr = VerificationEngine.verify_window_focus(target_hwnd=54321)
        assert vr.verified == TriState.TRUE
        assert vr.confidence == 1.0
        assert "matches expected HWND 54321" in vr.evidence


def test_verify_window_focus_mismatch():
    """Verify VerificationEngine.verify_window_focus detects and reports foreground focus mismatch."""
    with patch("ctypes.windll.user32.GetForegroundWindow", return_value=99999), \
         patch("ctypes.windll.user32.GetWindowTextLengthW", return_value=8), \
         patch("ctypes.windll.user32.GetWindowTextW", side_effect=lambda hwnd, buf, length: None):
        vr = VerificationEngine.verify_window_focus(target_hwnd=11111)
        assert vr.verified == TriState.FALSE
        assert vr.failure_code == FailureClass.WINDOW_NOT_FOCUSED
        assert "Target window not in foreground" in vr.evidence


def test_verify_cross_window_sync_success_and_failure():
    """Verify VerificationEngine.verify_cross_window_sync detects payload presence and absence."""
    # Success case: text was transferred across windows
    vr_ok = VerificationEngine.verify_cross_window_sync(
        expected_content="Astra Cross Window 42",
        actual_destination_text="The transferred value is Astra Cross Window 42 in Calc",
        source_window="Notepad",
        destination_window="Calculator",
    )
    assert vr_ok.verified == TriState.TRUE
    assert vr_ok.confidence >= 0.95
    assert "transferred from 'Notepad' confirmed in 'Calculator'" in vr_ok.evidence

    # Failure case: text was lost or missing
    vr_fail = VerificationEngine.verify_cross_window_sync(
        expected_content="Astra Cross Window 42",
        actual_destination_text="0",
        source_window="Notepad",
        destination_window="Calculator",
    )
    assert vr_fail.verified == TriState.FALSE
    assert vr_fail.failure_code == FailureClass.VERIFICATION_FAILED

    # Empty expected content: reports UNKNOWN
    vr_unk = VerificationEngine.verify_cross_window_sync(
        expected_content="",
        actual_destination_text="some text",
    )
    assert vr_unk.verified == TriState.UNKNOWN


@pytest.mark.asyncio
async def test_execute_sequence_multi_window_switching_and_focus():
    """Verify that ActionExecutor.execute_sequence activates each target window before execution."""
    executor = ActionExecutor()

    mock_win_notepad = MagicMock()
    mock_win_notepad.hwnd = 101
    mock_win_notepad.title = "Untitled - Notepad"
    mock_win_notepad.x = 100
    mock_win_notepad.y = 100
    mock_win_notepad.width = 800
    mock_win_notepad.height = 600

    mock_win_calc = MagicMock()
    mock_win_calc.hwnd = 202
    mock_win_calc.title = "Calculator"
    mock_win_calc.x = 900
    mock_win_calc.y = 100
    mock_win_calc.width = 400
    mock_win_calc.height = 500

    activated_hwnds = []

    def mock_restore_and_focus(hwnd):
        activated_hwnds.append(hwnd)
        return True

    def mock_get_app_status(app_name):
        if app_name == "notepad":
            return {"windows": [mock_win_notepad]}
        elif app_name == "calc":
            return {"windows": [mock_win_calc]}
        return {"windows": []}

    seq = action_planner.plan_composite_sequence(
        "multi_window_focus_test",
        [
            {
                "action": "CLICK",
                "target": "notepad",
                "target_app_name": "notepad",
                "tool_args": {"x": 200, "y": 200},
            },
            {
                "action": "CLICK",
                "target": "calc",
                "target_app_name": "calc",
                "tool_args": {"x": 950, "y": 200},
            },
        ],
    )

    with patch("app.tools.desktop.desktop_controller.DesktopController.get_application_status", side_effect=mock_get_app_status), \
         patch("app.environment.window.manager.window_manager.restore_and_focus", side_effect=mock_restore_and_focus), \
         patch.object(executor, "execute_intent", AsyncMock(return_value={"success": True, "action_executed": True})):

        res = await executor.execute_sequence(seq)

        assert res.terminal_status == CompositeTerminalStatus.SUCCESS
        assert res.completed_steps == 2
        # Both application windows must have been authoritatively focused in sequence order
        assert activated_hwnds == [101, 202]


@pytest.mark.asyncio
async def test_execute_sequence_dynamic_perception_rescoping():
    """Verify that window_bounds are dynamically passed to verifier_args for active window."""
    executor = ActionExecutor()

    mock_win = MagicMock()
    mock_win.hwnd = 303
    mock_win.title = "Notepad"
    mock_win.x = 250
    mock_win.y = 150
    mock_win.width = 700
    mock_win.height = 500

    seq = action_planner.plan_composite_sequence(
        "dynamic_rescope_test",
        [
            {
                "action": "TYPE_TEXT",
                "target": "notepad",
                "target_app_name": "notepad",
                "tool_args": {"text": "hello"},
                "requires_verification": True,
                "verifier_type": "TEXT_INPUT",
                "verifier_args": {"expected_text": "hello"},
            }
        ],
    )

    with patch("app.tools.desktop.desktop_controller.DesktopController.get_application_status", return_value={"windows": [mock_win]}), \
         patch("app.environment.window.manager.window_manager.restore_and_focus", return_value=True), \
         patch.object(executor, "execute_intent", AsyncMock(return_value={"success": True, "action_executed": True})), \
         patch.object(executor, "_run_step_verification", return_value=VerificationResult(verified=TriState.TRUE, verification_type="TEXT_INPUT", expected_state="hello", actual_state="hello")):

        res = await executor.execute_sequence(seq)

        assert res.terminal_status == CompositeTerminalStatus.SUCCESS
        # Step verifier_args must have received dynamic target_bounds from active window
        assert res.step_results[0].verifier_args["target_bounds"] == (250, 150, 700, 500)



@pytest.mark.asyncio
async def test_execute_sequence_multi_window_safe_compensation():
    """Verify safe compensation rolls back Window A when Window B encounters an unrecoverable failure."""
    executor = ActionExecutor()

    comp_action = {
        "action": "HOTKEY",
        "target": "notepad",
        "tool_args": {"keys": ["ctrl", "z"]},
        "description": "Undo text in Notepad",
    }

    seq = action_planner.plan_composite_sequence(
        "multi_window_compensation_test",
        [
            {
                "step_id": "step_win_a",
                "action": "TYPE_TEXT",
                "target": "notepad",
                "target_app_name": "notepad",
                "tool_args": {"text": "transfer payload"},
                "compensation": comp_action,
            },
            {
                "step_id": "step_win_b",
                "action": "CLICK",
                "target": "calc",
                "target_app_name": "calc",
                "requires_verification": True,
                "verifier_type": "WINDOW_FOCUS",
                "verifier_args": {"target_hwnd": 9999},  # will fail
            },
        ],
        allow_compensation=True,
    )

    async def mock_execute(intent, tool_args, max_attempts=1):
        if intent.action == SemanticAction.HOTKEY:
            # Compensation executed
            return {"success": True, "action_executed": True}
        return {"success": True, "action_executed": True}

    with patch("app.tools.desktop.desktop_controller.DesktopController.get_application_status", return_value={"windows": []}), \
         patch("app.environment.window.manager.window_manager.restore_and_focus", return_value=False), \
         patch.object(executor, "execute_intent", side_effect=mock_execute), \
         patch.object(executor, "_run_step_verification", return_value=VerificationResult(verified=TriState.FALSE, verification_type="WINDOW_FOCUS", expected_state="9999", actual_state="None", failure_code=FailureClass.WINDOW_NOT_FOCUSED)):

        res = await executor.execute_sequence(seq)

        assert res.terminal_status == CompositeTerminalStatus.PARTIAL_FAILURE
        assert res.completed_steps == 1
        assert res.failed_step_index == 1
        # Safe compensation for Step 0 (Notepad) must have been executed
        assert len(res.compensations_executed) == 1
        assert res.compensations_executed[0].description == "Undo text in Notepad"
        assert res.compensations_executed[0].executed is True


def test_verify_clipboard_matching_and_failure():
    """Verify VerificationEngine.verify_clipboard authoritatively checks clipboard buffer content."""
    # Match case
    vr_ok = VerificationEngine.verify_clipboard(
        expected_content="AstraPayload123",
        actual_clipboard_text="Text containing AstraPayload123 inside clipboard buffer",
    )
    assert vr_ok.verified == TriState.TRUE
    assert vr_ok.confidence >= 0.98
    assert "payload confirmed in clipboard buffer" in vr_ok.evidence

    # Mismatch case
    vr_fail = VerificationEngine.verify_clipboard(
        expected_content="ExpectedToken",
        actual_clipboard_text="Completely different buffer content",
    )
    assert vr_fail.verified == TriState.FALSE
    assert vr_fail.failure_code == FailureClass.VERIFICATION_FAILED
    assert "Clipboard verification failed" in vr_fail.evidence

    # Empty expected content
    vr_unk = VerificationEngine.verify_clipboard(
        expected_content="",
        actual_clipboard_text="Some clipboard content",
    )
    assert vr_unk.verified == TriState.UNKNOWN


@pytest.mark.asyncio
async def test_composite_sequence_verified_steps_and_actuation_only_semantics():
    """
    Validates that:
    1. Steps without verification requirement complete as ACTUATION_ACCEPTED with explicit ACTUATION_ONLY result.
    2. Steps with CLIPBOARD verifier achieve VERIFIED_SUCCESS.
    3. The execution result cleanly decouples verified_steps from completed_steps while reporting SUCCESS.
    """
    executor = ActionExecutor()

    seq = action_planner.plan_composite_sequence(
        "clipboard_workflow_test",
        [
            {
                "step_id": "step_select_all",
                "action": "HOTKEY",
                "target": "notepad",
                "target_app_name": "notepad",
                "tool_args": {"intent": "HOTKEY", "keys": ["ctrl", "a"]},
                "requires_verification": False,
            },
            {
                "step_id": "step_copy_clipboard",
                "action": "HOTKEY",
                "target": "notepad",
                "target_app_name": "notepad",
                "tool_args": {"intent": "HOTKEY", "keys": ["ctrl", "c"]},
                "requires_verification": True,
                "verifier_type": "CLIPBOARD",
                "verifier_args": {"expected_content": "AstraCopyToken42", "clipboard_text": "AstraCopyToken42"},
            },
        ],
    )

    async def mock_execute(intent, tool_args, max_attempts=1):
        return {"success": True, "action_executed": True}

    with patch("app.tools.desktop.desktop_controller.DesktopController.get_application_status", return_value={"windows": []}), \
         patch("app.environment.window.manager.window_manager.restore_and_focus", return_value=True), \
         patch.object(executor, "execute_intent", side_effect=mock_execute):

        res: CompositeExecutionResult = await executor.execute_sequence(seq)

        assert res.terminal_status == CompositeTerminalStatus.SUCCESS
        assert res.total_steps == 2
        assert res.completed_steps == 2
        assert res.verified_steps == 1
        assert res.failed_step_index is None

        # Step 0: ACTUATION_ACCEPTED with explicit ACTUATION_ONLY verification result
        s0 = res.step_results[0]
        assert s0.status == StepStatus.ACTUATION_ACCEPTED
        assert s0.actuation_accepted is True
        assert s0.verification_result is not None
        assert s0.verification_result.verification_type == "ACTUATION_ONLY"
        assert s0.verification_result.verified == TriState.UNKNOWN

        # Step 1: VERIFIED_SUCCESS with CLIPBOARD verification
        s1 = res.step_results[1]
        assert s1.status == StepStatus.VERIFIED_SUCCESS
        assert s1.actuation_accepted is True
        assert s1.verification_result is not None
        assert s1.verification_result.verification_type == "CLIPBOARD"
        assert s1.verification_result.verified == TriState.TRUE


@pytest.mark.asyncio
async def test_composite_sequence_clipboard_verification_failure_halts():
    """Validates that a failed CLIPBOARD verification halts sequence with PARTIAL_FAILURE or FAILED."""
    executor = ActionExecutor()

    seq = action_planner.plan_composite_sequence(
        "clipboard_failure_test",
        [
            {
                "step_id": "step_copy_fail",
                "action": "HOTKEY",
                "target": "notepad",
                "tool_args": {"keys": ["ctrl", "c"]},
                "requires_verification": True,
                "verifier_type": "CLIPBOARD",
                "verifier_args": {"expected_content": "ExpectedSecret", "clipboard_text": "WrongData"},
            },
        ],
        max_retries_per_step=0,
    )

    async def mock_execute(intent, tool_args, max_attempts=1):
        return {"success": True, "action_executed": True}

    with patch("app.tools.desktop.desktop_controller.DesktopController.get_application_status", return_value={"windows": []}), \
         patch("app.environment.window.manager.window_manager.restore_and_focus", return_value=True), \
         patch.object(executor, "execute_intent", side_effect=mock_execute):

        res = await executor.execute_sequence(seq)

        assert res.terminal_status == CompositeTerminalStatus.FAILED
        assert res.completed_steps == 0
        assert res.verified_steps == 0
        assert res.step_results[0].status == StepStatus.FAILED
        assert res.step_results[0].verification_result.verified == TriState.FALSE

