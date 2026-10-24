import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from app.domain.entities import TriState
from app.domain.goals import Intent, SemanticAction, FailureClass, VerificationResult
from app.domain.permissions import CapabilityScope, PermissionState, AuthorizationDecision, PermissionRequest, ResourceScope
from app.domain.composite import (
    CompositeActionSequence,
    CompositeStep,
    CompensationAction,
    StepStatus,
    CompositeTerminalStatus,
    CompositeExecutionResult,
)
from app.ai.orchestrator.action_executor import ActionExecutor
from app.ai.orchestrator.action_planner import action_planner


@pytest.fixture
def executor():
    return ActionExecutor()


@pytest.mark.asyncio
async def test_composite_sequence_success(executor, monkeypatch):
    """
    Validates a complete multi-step sequence (Click -> Type -> Scroll) where each step
    achieves verified success. Asserts atomic step state tracking and overall SUCCESS.
    """
    step1 = CompositeStep(
        step_id="step_1",
        step_index=0,
        intent=Intent(intent_id="i1", action=SemanticAction.CLICK, capability_id="desktop.physical_input", target="Editor"),
        tool_args={"intent": "CLICK", "x": 100, "y": 200},
        description="Focus Document Canvas",
    )
    step2 = CompositeStep(
        step_id="step_2",
        step_index=1,
        intent=Intent(intent_id="i2", action=SemanticAction.TYPE_TEXT, capability_id="desktop.physical_input", target="Editor"),
        tool_args={"intent": "TYPE_TEXT", "text": "Hello Astra"},
        description="Type Test Text",
    )
    step3 = CompositeStep(
        step_id="step_3",
        step_index=2,
        intent=Intent(intent_id="i3", action=SemanticAction.SCROLL, capability_id="desktop.physical_input", target="Editor"),
        tool_args={"intent": "SCROLL", "clicks": -3},
        description="Scroll Viewport Down",
    )

    sequence = CompositeActionSequence(
        sequence_id="seq_test_success",
        name="Focus_Type_Scroll_Flow",
        steps=[step1, step2, step3],
    )

    async def mock_execute_intent(intent, tool_args, max_attempts=1):
        vr = VerificationResult(
            verified=TriState.TRUE,
            confidence=0.98,
            verification_type=intent.action.value,
            actual_state="Verified State",
            evidence=f"Action {intent.action.value} verified.",
        )
        return {
            "success": True,
            "action_executed": True,
            "verification_result": vr,
            "observation_id": f"obs_{intent.action.value}",
        }

    monkeypatch.setattr(executor, "execute_intent", mock_execute_intent)

    result: CompositeExecutionResult = await executor.execute_sequence(sequence)

    assert result.terminal_status == CompositeTerminalStatus.SUCCESS
    assert result.total_steps == 3
    assert result.completed_steps == 3
    assert result.failed_step_index is None
    assert all(s.status == StepStatus.VERIFIED_SUCCESS for s in result.step_results)
    assert all(s.actuation_accepted is True for s in result.step_results)
    assert all(s.verification_result.verified == TriState.TRUE for s in result.step_results)


@pytest.mark.asyncio
async def test_composite_sequence_intermediate_failure_and_partial_completion(executor, monkeypatch):
    """
    Validates that if Step 2 fails verification:
    1. Step 1 remains VERIFIED_SUCCESS.
    2. Step 2 transitions to FAILED.
    3. Step 3 is SKIPPED.
    4. Terminal outcome is PARTIAL_FAILURE (never claiming total success).
    """
    step1 = CompositeStep(
        step_id="s1",
        step_index=0,
        intent=Intent(intent_id="i1", action=SemanticAction.CLICK, capability_id="desktop.physical_input"),
        description="Open Context Menu",
    )
    step2 = CompositeStep(
        step_id="s2",
        step_index=1,
        intent=Intent(intent_id="i2", action=SemanticAction.CLICK, capability_id="desktop.physical_input"),
        description="Click Missing Submenu Item",
    )
    step3 = CompositeStep(
        step_id="s3",
        step_index=2,
        intent=Intent(intent_id="i3", action=SemanticAction.TYPE_TEXT, capability_id="desktop.physical_input"),
        description="Type Replacement",
    )

    sequence = CompositeActionSequence(
        sequence_id="seq_partial_fail",
        name="Menu_Interaction",
        steps=[step1, step2, step3],
        max_retries_per_step=0,
    )

    async def mock_execute_intent(intent, tool_args, max_attempts=1):
        if intent.intent_id == "i1":
            return {
                "success": True,
                "action_executed": True,
                "verification_result": VerificationResult(verified=TriState.TRUE, verification_type="CLICK"),
            }
        else:
            return {
                "success": False,
                "action_executed": True,
                "error": {"code": "TARGET_NOT_FOUND", "message": "Element not visible"},
                "verification_result": VerificationResult(verified=TriState.FALSE, failure_code=FailureClass.TARGET_NOT_FOUND),
            }

    monkeypatch.setattr(executor, "execute_intent", mock_execute_intent)

    result = await executor.execute_sequence(sequence)

    assert result.terminal_status == CompositeTerminalStatus.PARTIAL_FAILURE
    assert result.total_steps == 3
    assert result.completed_steps == 1
    assert result.failed_step_index == 1
    assert result.step_results[0].status == StepStatus.VERIFIED_SUCCESS
    assert result.step_results[1].status == StepStatus.FAILED
    assert result.step_results[2].status == StepStatus.SKIPPED


@pytest.mark.asyncio
async def test_composite_sequence_distinguishes_actuation_from_verified_success(executor, monkeypatch):
    """
    Strictly verifies that accepted physical actuation (SendInput succeeded) cannot be
    claimed as verified success if semantic verification reports FALSE.
    """
    step = CompositeStep(
        step_id="s1",
        step_index=0,
        intent=Intent(intent_id="i1", action=SemanticAction.SCROLL, capability_id="desktop.physical_input"),
        description="Scroll Viewport",
    )
    sequence = CompositeActionSequence(
        sequence_id="seq_actuation_vs_verify",
        name="Scroll_Stationary_Test",
        steps=[step],
        max_retries_per_step=0,
    )

    async def mock_execute_intent(intent, tool_args, max_attempts=1):
        # Actuation accepted by OS, but viewport remained stationary
        return {
            "success": False,
            "action_executed": True,
            "verification_result": VerificationResult(
                verified=TriState.FALSE,
                failure_code=FailureClass.CLICK_NO_EFFECT,
                evidence="Viewport content remained stationary.",
            ),
        }

    monkeypatch.setattr(executor, "execute_intent", mock_execute_intent)

    result = await executor.execute_sequence(sequence)

    assert result.terminal_status == CompositeTerminalStatus.FAILED
    assert result.completed_steps == 0
    executed_step = result.step_results[0]
    assert executed_step.status == StepStatus.FAILED
    assert executed_step.actuation_accepted is True # Actuation was accepted
    assert executed_step.verification_result.verified == TriState.FALSE # But verification failed
    assert executed_step.error["code"] == "VERIFICATION_FAILED"


@pytest.mark.asyncio
async def test_composite_sequence_bounded_recovery(executor, monkeypatch):
    """
    Validates that a step that fails verification on attempt 1 initiates bounded recovery
    via RecoveryEngine and succeeds on attempt 2.
    """
    step = CompositeStep(
        step_id="s1",
        step_index=0,
        intent=Intent(intent_id="i1", action=SemanticAction.CLICK, capability_id="desktop.physical_input"),
        description="Click Target with Settle Retry",
    )
    sequence = CompositeActionSequence(
        sequence_id="seq_recovery",
        name="Recovery_Test",
        steps=[step],
        max_retries_per_step=2,
    )

    call_count = 0
    async def mock_execute_intent(intent, tool_args, max_attempts=1):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "success": False,
                "action_executed": True,
                "verification_result": VerificationResult(
                    verified=TriState.FALSE,
                    failure_code=FailureClass.STALE_TARGET,
                    evidence="Target observation was stale.",
                ),
            }
        else:
            return {
                "success": True,
                "action_executed": True,
                "verification_result": VerificationResult(
                    verified=TriState.TRUE,
                    evidence="Target refreshed and click verified.",
                ),
            }

    monkeypatch.setattr(executor, "execute_intent", mock_execute_intent)

    result = await executor.execute_sequence(sequence)

    assert result.terminal_status == CompositeTerminalStatus.SUCCESS
    assert result.completed_steps == 1
    assert call_count == 2
    assert result.step_results[0].status == StepStatus.VERIFIED_SUCCESS


@pytest.mark.asyncio
async def test_composite_sequence_safe_verified_compensation(executor, monkeypatch):
    """
    Guarantees that when an intermediate step fails, only explicitly reversible actions
    with defined compensation are compensated and verified (no fake transactional rollback
    of irreversible actions).
    """
    # Step 1: Opens a menu (Reversible: compensated via Escape key)
    step1 = CompositeStep(
        step_id="s1",
        step_index=0,
        intent=Intent(intent_id="i1", action=SemanticAction.CLICK, capability_id="desktop.physical_input", target="FileMenu"),
        description="Open File Menu",
        compensation=CompensationAction(
            intent=Intent(intent_id="comp_1", action=SemanticAction.PRESS_KEY, capability_id="desktop.physical_input"),
            tool_args={"intent": "PRESS_KEY", "key": "escape"},
            description="Dismiss File Menu via Escape",
        ),
    )
    # Step 2: Irreversible physical action that fails
    step2 = CompositeStep(
        step_id="s2",
        step_index=1,
        intent=Intent(intent_id="i2", action=SemanticAction.CLICK, capability_id="desktop.physical_input", target="SaveAs"),
        description="Click Save As Dialog",
    )

    sequence = CompositeActionSequence(
        sequence_id="seq_comp_test",
        name="Compensation_Test",
        steps=[step1, step2],
        max_retries_per_step=0,
        allow_compensation=True,
    )

    executed_intents = []
    async def mock_execute_intent(intent, tool_args, max_attempts=1):
        executed_intents.append(intent.intent_id)
        if intent.intent_id == "i1":
            return {
                "success": True,
                "action_executed": True,
                "verification_result": VerificationResult(verified=TriState.TRUE, evidence="Menu opened"),
            }
        elif intent.intent_id == "i2":
            return {
                "success": False,
                "action_executed": False,
                "error": {"code": "TARGET_NOT_FOUND", "message": "SaveAs item not found"},
                "verification_result": VerificationResult(verified=TriState.FALSE, failure_code=FailureClass.TARGET_NOT_FOUND),
            }
        elif intent.intent_id == "comp_1":
            return {
                "success": True,
                "action_executed": True,
                "verification_result": VerificationResult(verified=TriState.TRUE, evidence="Menu dismissed safely via Escape"),
            }

    monkeypatch.setattr(executor, "execute_intent", mock_execute_intent)

    result = await executor.execute_sequence(sequence)

    assert result.terminal_status == CompositeTerminalStatus.PARTIAL_FAILURE
    assert len(result.compensations_executed) == 1
    comp = result.compensations_executed[0]
    assert comp.executed is True
    assert comp.verified == TriState.TRUE
    assert "Dismiss File Menu via Escape" in comp.description
    assert "comp_1" in executed_intents


@pytest.mark.asyncio
async def test_composite_sequence_cancellation(executor, monkeypatch):
    """
    Validates that a running sequence cancelled midway immediately stops,
    marks remaining steps as CANCELLED, and returns terminal status CANCELLED.
    """
    step1 = CompositeStep(
        step_id="s1",
        step_index=0,
        intent=Intent(intent_id="i1", action=SemanticAction.CLICK, capability_id="desktop.physical_input"),
        description="Step 1",
    )
    step2 = CompositeStep(
        step_id="s2",
        step_index=1,
        intent=Intent(intent_id="i2", action=SemanticAction.CLICK, capability_id="desktop.physical_input"),
        description="Step 2",
    )
    step3 = CompositeStep(
        step_id="s3",
        step_index=2,
        intent=Intent(intent_id="i3", action=SemanticAction.CLICK, capability_id="desktop.physical_input"),
        description="Step 3",
    )

    sequence = CompositeActionSequence(
        sequence_id="seq_cancel",
        name="Cancellation_Test",
        steps=[step1, step2, step3],
    )

    cancel_event = asyncio.Event()

    async def mock_execute_intent(intent, tool_args, max_attempts=1):
        if intent.intent_id == "i1":
            cancel_event.set() # Trigger cancellation after step 1
            return {
                "success": True,
                "action_executed": True,
                "verification_result": VerificationResult(verified=TriState.TRUE),
            }
        return {"success": True}

    monkeypatch.setattr(executor, "execute_intent", mock_execute_intent)

    result = await executor.execute_sequence(sequence, cancel_event=cancel_event)

    assert result.terminal_status == CompositeTerminalStatus.CANCELLED
    assert result.completed_steps == 1
    assert result.step_results[0].status == StepStatus.VERIFIED_SUCCESS
    assert result.step_results[1].status == StepStatus.CANCELLED
    assert result.step_results[2].status == StepStatus.CANCELLED


@pytest.mark.asyncio
async def test_composite_sequence_timeout(executor, monkeypatch):
    """
    Validates that sequence execution exceeding timeout_seconds terminates with TIMEOUT,
    marking unfinished steps appropriately.
    """
    step1 = CompositeStep(
        step_id="s1",
        step_index=0,
        intent=Intent(intent_id="i1", action=SemanticAction.CLICK, capability_id="desktop.physical_input"),
        description="Slow Step",
    )
    step2 = CompositeStep(
        step_id="s2",
        step_index=1,
        intent=Intent(intent_id="i2", action=SemanticAction.CLICK, capability_id="desktop.physical_input"),
        description="Never Reached Step",
    )

    sequence = CompositeActionSequence(
        sequence_id="seq_timeout",
        name="Timeout_Test",
        steps=[step1, step2],
        timeout_seconds=0.08, # Short timeout
    )

    async def mock_slow_execute(intent, tool_args, max_attempts=1):
        await asyncio.sleep(0.3) # Exceeds timeout
        return {"success": True}

    monkeypatch.setattr(executor, "execute_intent", mock_slow_execute)

    result = await executor.execute_sequence(sequence)

    assert result.terminal_status == CompositeTerminalStatus.TIMEOUT
    assert result.completed_steps == 0
    assert result.error["code"] == "TIMEOUT"


@pytest.mark.asyncio
async def test_composite_sequence_authorization_gate(executor, monkeypatch):
    """
    Validates that consequential actions requiring permission are intercepted before actuation
    and refused if authorization is denied.
    """
    step_safe = CompositeStep(
        step_id="s1",
        step_index=0,
        intent=Intent(intent_id="i1", action=SemanticAction.CLICK, capability_id="desktop.physical_input"),
        description="Safe Click",
        consequential=False,
    )
    step_consequential = CompositeStep(
        step_id="s2",
        step_index=1,
        intent=Intent(intent_id="i2", action=SemanticAction.CLOSE, capability_id="desktop.close_application", target="CrucialProcess"),
        description="Close Important Application",
        consequential=True,
        required_permission=CapabilityScope.APPLICATION_LIFECYCLE,
    )

    sequence = CompositeActionSequence(
        sequence_id="seq_auth",
        name="Authorization_Test",
        steps=[step_safe, step_consequential],
    )

    mock_evaluator = MagicMock()
    # Mock deny
    mock_evaluator.evaluate.return_value = AuthorizationDecision(
        request=PermissionRequest(
            request_id="r1",
            capability=CapabilityScope.APPLICATION_LIFECYCLE,
            resource_scope=ResourceScope(capability=CapabilityScope.APPLICATION_LIFECYCLE),
            reason="Test",
        ),
        decision=PermissionState.DENIED,
        reason="User policy forbids closing application without explicit elevation",
    )

    executed_intents = []
    async def mock_execute(intent, tool_args, max_attempts=1):
        executed_intents.append(intent.intent_id)
        return {
            "success": True,
            "action_executed": True,
            "verification_result": VerificationResult(verified=TriState.TRUE),
        }

    monkeypatch.setattr(executor, "execute_intent", mock_execute)

    result = await executor.execute_sequence(sequence, permission_evaluator=mock_evaluator)

    assert result.terminal_status == CompositeTerminalStatus.PERMISSION_DENIED
    assert result.completed_steps == 1 # Step 1 succeeded
    assert "i1" in executed_intents
    # Step 2 was NEVER actuated
    assert "i2" not in executed_intents
    assert result.step_results[1].status == StepStatus.FAILED
    assert result.step_results[1].error["code"] == "PERMISSION_REQUIRED"


def test_plan_composite_sequence_compiler():
    """
    Validates ActionPlanner.plan_composite_sequence compilation from high-level dicts.
    """
    steps_def = [
        {
            "action": "CLICK",
            "target": "Document",
            "tool_args": {"x": 100, "y": 200},
            "description": "Click Document Canvas",
            "compensation": {
                "action": "PRESS_KEY",
                "tool_args": {"key": "escape"},
                "description": "Dismiss",
            },
        },
        {
            "action": "TYPE_TEXT",
            "target": "Document",
            "tool_args": {"text": "Astra Test"},
            "description": "Type Payload",
            "consequential": True,
            "required_permission": CapabilityScope.COMPUTER_CONTROL,
        },
    ]

    seq = action_planner.plan_composite_sequence(
        sequence_name="Interactive_Workflow",
        steps_def=steps_def,
        timeout_seconds=45.0,
    )

    assert isinstance(seq, CompositeActionSequence)
    assert seq.name == "Interactive_Workflow"
    assert len(seq.steps) == 2
    assert seq.steps[0].step_index == 0
    assert seq.steps[0].intent.action == SemanticAction.CLICK
    assert seq.steps[0].compensation is not None
    assert seq.steps[0].compensation.intent.action == SemanticAction.PRESS_KEY
    assert seq.steps[1].consequential is True
    assert seq.steps[1].required_permission == CapabilityScope.COMPUTER_CONTROL


@pytest.mark.asyncio
async def test_composite_canonical_workflow_simulation(executor, monkeypatch):
    """
    Simulates the canonical 5-step composite workflow:
      Focus Editor → Type Text → Drag-Select Text → Context Menu → Dismiss/Cleanup
    Validates atomic step progression, verifier routing, and SUCCESS terminal outcome.
    """
    token = "a8b9c0"
    payload = f"Astra Composite {token} Line"

    step_focus = CompositeStep(
        step_id="s0_focus",
        step_index=0,
        intent=Intent(intent_id="i0", action=SemanticAction.CLICK, capability_id="desktop.physical_input", target="Editor"),
        tool_args={"intent": "CLICK", "x": 200, "y": 300},
        description="Focus Editor Canvas",
        requires_verification=False,
    )
    step_type = CompositeStep(
        step_id="s1_type",
        step_index=1,
        intent=Intent(intent_id="i1", action=SemanticAction.TYPE_TEXT, capability_id="desktop.physical_input", target="Editor"),
        tool_args={"intent": "TYPE_TEXT", "text": payload},
        description="Type Text Payload",
        requires_verification=True,
        verifier_type="TEXT_INPUT",
        verifier_args={"expected_text": payload},
    )
    step_drag = CompositeStep(
        step_id="s2_drag",
        step_index=2,
        intent=Intent(intent_id="i2", action=SemanticAction.DRAG, capability_id="desktop.physical_input", target="Editor"),
        tool_args={"intent": "DRAG", "start_x": 200, "start_y": 300, "end_x": 500, "end_y": 300},
        description="Drag-Select Text",
        requires_verification=True,
        verifier_type="DRAG",
        verifier_args={"target_label": token, "clipboard_text": payload},
        compensation=CompensationAction(
            intent=Intent(intent_id="comp_drag", action=SemanticAction.PRESS_KEY, capability_id="desktop.physical_input"),
            tool_args={"intent": "PRESS_KEY", "key": "right"},
            description="Clear Selection via Right Arrow",
        ),
    )
    step_cm = CompositeStep(
        step_id="s3_cm",
        step_index=3,
        intent=Intent(intent_id="i3", action=SemanticAction.RIGHT_CLICK, capability_id="desktop.physical_input", target="Editor"),
        tool_args={"intent": "RIGHT_CLICK", "x": 200, "y": 300},
        description="Open Context Menu",
        requires_verification=True,
        verifier_type="CONTEXT_MENU",
        verifier_args={"click_point": (200, 300)},
        compensation=CompensationAction(
            intent=Intent(intent_id="comp_cm", action=SemanticAction.PRESS_KEY, capability_id="desktop.physical_input"),
            tool_args={"intent": "PRESS_KEY", "key": "escape"},
            description="Dismiss Context Menu via Escape",
        ),
    )
    step_clean = CompositeStep(
        step_id="s4_clean",
        step_index=4,
        intent=Intent(intent_id="i4", action=SemanticAction.HOTKEY, capability_id="desktop.physical_input", target="Editor"),
        tool_args={"intent": "HOTKEY", "keys": ["ctrl", "a"]},
        description="Clear Editor Buffer",
        requires_verification=True,
        verifier_type="TEXT_ABSENT",
        verifier_args={"expected_text": payload},
    )

    sequence = CompositeActionSequence(
        sequence_id="seq_canonical_5step",
        name="Canonical_Interactive_Workflow",
        steps=[step_focus, step_type, step_drag, step_cm, step_clean],
        timeout_seconds=30.0,
    )

    # Mock execute_intent returning actuation and step-appropriate verification
    async def mock_execute_intent(intent, tool_args, max_attempts=1):
        if intent.intent_id == "i0":
            return {"success": True, "action_executed": True}
        elif intent.intent_id == "i1":
            return {
                "success": True,
                "action_executed": True,
                "verification_result": VerificationResult(verified=TriState.TRUE, verification_type="TEXT_INPUT"),
            }
        elif intent.intent_id == "i2":
            return {
                "success": True,
                "action_executed": True,
                "verification_result": VerificationResult(verified=TriState.TRUE, verification_type="DRAG"),
            }
        elif intent.intent_id == "i3":
            return {
                "success": True,
                "action_executed": True,
                "verification_result": VerificationResult(verified=TriState.TRUE, verification_type="CONTEXT_MENU"),
            }
        elif intent.intent_id == "i4":
            return {
                "success": True,
                "action_executed": True,
                "verification_result": VerificationResult(verified=TriState.TRUE, verification_type="TEXT_ABSENT"),
            }
        return {"success": True}

    monkeypatch.setattr(executor, "execute_intent", mock_execute_intent)
    monkeypatch.setattr(
        executor,
        "_run_step_verification",
        lambda step, obs_pre, obs_after, detections_pre, detections_after, last_res: last_res.get("verification_result"),
    )

    result: CompositeExecutionResult = await executor.execute_sequence(sequence)

    assert result.terminal_status == CompositeTerminalStatus.SUCCESS
    assert result.total_steps == 5
    assert result.completed_steps == 5
    assert result.failed_step_index is None
    # Step 0 was actuation-accepted without verification requirement
    assert result.step_results[0].status == StepStatus.ACTUATION_ACCEPTED
    # Steps 1 to 4 were verified successes
    assert result.step_results[1].status == StepStatus.VERIFIED_SUCCESS
    assert result.step_results[2].status == StepStatus.VERIFIED_SUCCESS
    assert result.step_results[3].status == StepStatus.VERIFIED_SUCCESS
    assert result.step_results[4].status == StepStatus.VERIFIED_SUCCESS


@pytest.mark.asyncio
async def test_goal_runtime_executes_composite_sequence(monkeypatch):
    """
    Validates that GoalRuntime._execute_task transparently integrates and executes
    composite sequences through ActionExecutor, populating actions_taken and completing.
    """
    from app.domain.goals import Task, TaskState, Goal, GoalState
    from app.ai.orchestrator.runtime import GoalRuntime

    step1 = CompositeStep(
        step_id="step_a",
        step_index=0,
        intent=Intent(intent_id="ia", action=SemanticAction.CLICK, capability_id="desktop.physical_input"),
        description="Step A",
    )
    step2 = CompositeStep(
        step_id="step_b",
        step_index=1,
        intent=Intent(intent_id="ib", action=SemanticAction.TYPE_TEXT, capability_id="desktop.physical_input"),
        description="Step B",
    )
    sequence = CompositeActionSequence(
        sequence_id="seq_gr",
        name="GoalRuntime_Sequence",
        steps=[step1, step2],
    )

    task = Task(
        task_id="task_comp_1",
        description="Task containing composite sequence",
        composite_sequence=sequence,
    )
    goal = Goal(
        goal_id="goal_comp_1",
        objective="Execute composite goal",
        tasks=[task],
    )

    runtime = GoalRuntime(goal=goal)

    async def mock_execute_seq(seq, cancel_event=None, permission_evaluator=None):
        return CompositeExecutionResult(
            sequence_id=seq.sequence_id,
            terminal_status=CompositeTerminalStatus.SUCCESS,
            total_steps=2,
            completed_steps=2,
            step_results=[
                CompositeStep(
                    step_id="step_a",
                    step_index=0,
                    intent=Intent(intent_id="ia", action=SemanticAction.CLICK, capability_id="desktop.physical_input"),
                    description="Step A",
                    status=StepStatus.ACTUATION_ACCEPTED,
                    verification_result=VerificationResult(verified=TriState.TRUE),
                ),
                CompositeStep(
                    step_id="step_b",
                    step_index=1,
                    intent=Intent(intent_id="ib", action=SemanticAction.TYPE_TEXT, capability_id="desktop.physical_input"),
                    description="Step B",
                    status=StepStatus.VERIFIED_SUCCESS,
                    verification_result=VerificationResult(verified=TriState.TRUE),
                ),
            ],
        )

    from app.ai.orchestrator.action_executor import action_executor
    monkeypatch.setattr(action_executor, "execute_sequence", mock_execute_seq)

    success, wait_user, fc = await runtime._execute_task(task)

    assert success is True
    assert wait_user is False
    assert fc is None
    assert len(task.actions_taken) == 2
    assert task.actions_taken[0].action_id == "step_a"
    assert task.actions_taken[1].action_id == "step_b"

