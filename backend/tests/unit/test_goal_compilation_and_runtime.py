"""
ASTRA — Phase B.8 Unit Regression Suite
High-Level Natural Language Goal Compilation & Adaptive Execution Runtime
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.domain.entities import TriState
from app.domain.goals import (
    Goal,
    Task,
    Intent,
    SemanticAction,
    TargetType,
    GoalState,
    TaskState,
    FailureClass,
    PlanValidationResult,
    VerificationResult,
)
from app.domain.composite import (
    CompositeActionSequence,
    CompositeStep,
    CompositeTerminalStatus,
    CompositeExecutionResult,
    StepStatus,
)
from app.domain.events import ExecutionEventType
from app.domain.execution_context import ExecutionContext
from app.domain.memory import RecoveryStrategy
from app.ai.orchestrator.compiler import action_compiler, ActionCompiler
from app.ai.orchestrator.runtime import GoalRuntime


# ===========================================================================
# 1. Plan Validation Tests (Separation of Planning & Trusted Execution)
# ===========================================================================

def test_validate_plan_empty_objective_and_tasks():
    """Verify that empty objective or empty tasks list is rejected with structured errors."""
    compiler = ActionCompiler()

    # Empty objective
    g_empty_obj = Goal(goal_id="g1", objective="", tasks=[])
    v_res1 = compiler.validate_plan(g_empty_obj)
    assert v_res1.is_valid is False
    assert any("objective cannot be empty" in e for e in v_res1.errors)

    # Empty tasks
    g_empty_tasks = Goal(goal_id="g2", objective="Open Notepad", tasks=[])
    v_res2 = compiler.validate_plan(g_empty_tasks)
    assert v_res2.is_valid is False
    assert any("contains no tasks" in e for e in v_res2.errors)


def test_validate_plan_unsupported_application():
    """Verify that uninstalled or unknown applications are caught during plan validation."""
    compiler = ActionCompiler()

    goal = Goal(
        goal_id="g_unknown_app",
        objective="Open FictionalAppXYZ",
        tasks=[
            Task(
                task_id="t1",
                description="Open unknown app",
                intents=[
                    Intent(
                        intent_id="i1",
                        action=SemanticAction.OPEN,
                        target="FictionalAppXYZ_12345",
                    )
                ],
            )
        ],
    )

    with patch("app.environment.application.catalog.catalog.get_all", return_value={"notepad": MagicMock()}):
        res = compiler.validate_plan(goal)
        assert res.is_valid is False
        assert res.failure_class == FailureClass.TARGET_NOT_FOUND
        assert any("is not installed or recognized" in e for e in res.errors)


def test_validate_plan_missing_required_parameters():
    """Verify that intents lacking required parameters (e.g. text for typing, keys for hotkey) fail validation."""
    compiler = ActionCompiler()

    # TYPE_TEXT without text
    g_no_text = Goal(
        goal_id="g_no_text",
        objective="Type in Notepad",
        tasks=[
            Task(
                task_id="t1",
                description="Type missing text",
                intents=[
                    Intent(
                        intent_id="i1",
                        action=SemanticAction.TYPE_TEXT,
                        target="notepad",
                        parameters={},  # Missing text
                    )
                ],
            )
        ],
    )
    res_no_text = compiler.validate_plan(g_no_text)
    assert res_no_text.is_valid is False
    assert any("missing required text payload" in e for e in res_no_text.errors)

    # HOTKEY without keys
    g_no_keys = Goal(
        goal_id="g_no_keys",
        objective="Press hotkey in Notepad",
        tasks=[
            Task(
                task_id="t2",
                description="Hotkey missing keys",
                intents=[
                    Intent(
                        intent_id="i2",
                        action=SemanticAction.HOTKEY,
                        target="notepad",
                        parameters={},  # Missing keys
                    )
                ],
            )
        ],
    )
    res_no_keys = compiler.validate_plan(g_no_keys)
    assert res_no_keys.is_valid is False
    assert any("missing or empty 'keys'" in e for e in res_no_keys.errors)


# ===========================================================================
# 2. Goal Compilation to Composite Action Sequence
# ===========================================================================

def test_compile_goal_to_composite_sequence_generates_verified_workflow():
    """
    Validates that a multi-step high-level goal compiles into an authoritative
    CompositeActionSequence with correct verifiers, args, and compensations.
    """
    compiler = ActionCompiler()

    goal = Goal(
        goal_id="g_multi_step",
        objective="Type in Notepad and copy to clipboard",
        tasks=[
            Task(
                task_id="t_notepad",
                description="Type and Copy Workflow",
                intents=[
                    Intent(
                        intent_id="i1",
                        action=SemanticAction.OPEN,
                        target="notepad",
                    ),
                    Intent(
                        intent_id="i2",
                        action=SemanticAction.TYPE_TEXT,
                        target="notepad",
                        parameters={"text": "Astra Compilation 42"},
                    ),
                    Intent(
                        intent_id="i3",
                        action=SemanticAction.HOTKEY,
                        target="notepad",
                        parameters={"keys": ["ctrl", "a"]},
                    ),
                    Intent(
                        intent_id="i4",
                        action=SemanticAction.HOTKEY,
                        target="notepad",
                        parameters={"keys": ["ctrl", "c"]},
                    ),
                ],
            )
        ],
    )

    seq = compiler.compile_goal_to_composite_sequence(goal, sequence_name="TestNotepadWorkflow")

    assert len(seq.steps) == 4
    # Step 0: Open Notepad -> WINDOW_FOCUS
    s0 = seq.steps[0]
    assert s0.intent.action == SemanticAction.OPEN
    assert s0.requires_verification is True
    assert s0.verifier_type == "WINDOW_FOCUS"
    assert s0.target_app_name == "notepad"

    # Step 1: Type text -> TEXT_INPUT with expected text and undo compensation
    s1 = seq.steps[1]
    assert s1.intent.action == SemanticAction.TYPE_TEXT
    assert s1.requires_verification is True
    assert s1.verifier_type == "TEXT_INPUT"
    assert s1.verifier_args["expected_text"] == "Astra Compilation 42"
    assert s1.compensation is not None
    assert s1.compensation.tool_args["keys"] == ["ctrl", "z"]

    # Step 2: Select all -> HOTKEY Ctrl+A (requires_verification=False)
    s2 = seq.steps[2]
    assert s2.intent.action == SemanticAction.HOTKEY
    assert s2.requires_verification is False

    # Step 3: Copy to clipboard -> HOTKEY Ctrl+C (requires_verification=True, CLIPBOARD)
    s3 = seq.steps[3]
    assert s3.intent.action == SemanticAction.HOTKEY
    assert s3.requires_verification is True
    assert s3.verifier_type == "CLIPBOARD"
    assert s3.verifier_args["expected_content"] == "Astra Compilation 42"


@pytest.mark.asyncio
async def test_action_compiler_compile_pipeline_rejects_invalid_plan():
    """Validates that ActionCompiler.compile marks GoalState.FAILED when plan validation fails."""
    compiler = ActionCompiler()
    context = ExecutionContext(execution_id="ctx_test")

    invalid_goal = Goal(
        goal_id="g_bad",
        objective="Invalid Goal",
        tasks=[
            Task(
                task_id="t_bad",
                description="Bad Task",
                intents=[
                    Intent(
                        intent_id="i_bad",
                        action=SemanticAction.OPEN,
                        target="",  # Missing target
                    )
                ],
            )
        ],
    )

    compiled = await compiler.compile(invalid_goal, context)
    assert compiled.state == GoalState.FAILED
    assert len(compiled.validation_errors) > 0


# ===========================================================================
# 3. GoalRuntime Stateful Execution & Fast-Fail
# ===========================================================================

@pytest.mark.asyncio
async def test_goal_runtime_fast_fails_on_validation_errors():
    """Validates that GoalRuntime immediately yields GOAL_FAILED if goal has validation errors."""
    failed_goal = Goal(
        goal_id="g_failed_val",
        objective="Broken Goal",
        tasks=[],
        state=GoalState.FAILED,
        validation_errors=["Application 'Unknown' not found."],
    )

    runtime = GoalRuntime(failed_goal)
    events = []
    async for ev in runtime.run():
        events.append(ev)

    assert len(events) == 2
    assert events[0].event_type == ExecutionEventType.GOAL_ACCEPTED
    assert events[1].event_type == ExecutionEventType.GOAL_FAILED
    assert events[1].state == "VALIDATION_FAILED"
    assert "Application 'Unknown' not found." in events[1].progress_label


@pytest.mark.asyncio
async def test_goal_runtime_successful_composite_execution(monkeypatch):
    """Validates a successful multi-step composite workflow execution through GoalRuntime."""
    compiler = ActionCompiler()
    context = ExecutionContext(execution_id="ctx_success")

    goal = Goal(
        goal_id="g_run_success",
        objective="Type in Notepad",
        tasks=[
            Task(
                task_id="t1",
                description="Notepad Typing Task",
                intents=[
                    Intent(intent_id="i1", action=SemanticAction.OPEN, target="notepad"),
                    Intent(intent_id="i2", action=SemanticAction.TYPE_TEXT, target="notepad", parameters={"text": "Hello"}),
                ],
            )
        ],
    )

    compiled_goal = await compiler.compile(goal, context)
    assert compiled_goal.tasks[0].composite_sequence is not None

    async def mock_execute_sequence(seq, cancel_event=None):
        return CompositeExecutionResult(
            sequence_id=seq.sequence_id,
            terminal_status=CompositeTerminalStatus.SUCCESS,
            total_steps=2,
            completed_steps=2,
            verified_steps=2,
            step_results=[
                CompositeStep(
                    step_id="s0",
                    step_index=0,
                    intent=Intent(intent_id="i1", action=SemanticAction.OPEN, capability_id="desktop.open_application"),
                    description="Open Notepad",
                    status=StepStatus.VERIFIED_SUCCESS,
                    verification_result=VerificationResult(verified=TriState.TRUE),
                ),
                CompositeStep(
                    step_id="s1",
                    step_index=1,
                    intent=Intent(intent_id="i2", action=SemanticAction.TYPE_TEXT, capability_id="desktop.physical_input"),
                    description="Type Hello",
                    status=StepStatus.VERIFIED_SUCCESS,
                    verification_result=VerificationResult(verified=TriState.TRUE),
                ),
            ],
        )

    from app.ai.orchestrator.action_executor import action_executor
    monkeypatch.setattr(action_executor, "execute_sequence", mock_execute_sequence)

    runtime = GoalRuntime(compiled_goal, context=context)
    events = []
    async for ev in runtime.run():
        events.append(ev)

    assert runtime.goal.state == GoalState.COMPLETED
    assert runtime.goal.is_complete is True
    event_types = [e.event_type for e in events]
    assert ExecutionEventType.GOAL_ACCEPTED in event_types
    assert ExecutionEventType.TASK_STARTED in event_types
    assert ExecutionEventType.TASK_COMPLETED in event_types
    assert ExecutionEventType.GOAL_COMPLETED in event_types


# ===========================================================================
# 4. Adaptive Dynamic Re-planning on Step Failure
# ===========================================================================

@pytest.mark.asyncio
async def test_goal_runtime_adaptive_replanning_on_step_failure(monkeypatch):
    """
    Validates that when an intermediate composite step encounters a recoverable failure,
    GoalRuntime queries RecoveryEngine, performs adaptive re-planning, and re-executes.
    """
    compiler = ActionCompiler()
    context = ExecutionContext(execution_id="ctx_replan")

    goal = Goal(
        goal_id="g_replan",
        objective="Workflow with intermediate failure and recovery",
        tasks=[
            Task(
                task_id="t_replan",
                description="Adaptive Replan Task",
                intents=[
                    Intent(intent_id="i1", action=SemanticAction.OPEN, target="notepad"),
                    Intent(intent_id="i2", action=SemanticAction.TYPE_TEXT, target="notepad", parameters={"text": "Payload"}),
                ],
            )
        ],
    )

    compiled_goal = await compiler.compile(goal, context)
    assert compiled_goal.tasks[0].composite_sequence is not None

    call_count = 0

    async def mock_execute_sequence(seq, cancel_event=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First execution: Step 1 fails with WINDOW_NOT_FOCUSED
            return CompositeExecutionResult(
                sequence_id=seq.sequence_id,
                terminal_status=CompositeTerminalStatus.PARTIAL_FAILURE,
                total_steps=2,
                completed_steps=1,
                verified_steps=1,
                failed_step_index=1,
                error={"code": "WINDOW_NOT_FOCUSED", "message": "Window lost foreground"},
                step_results=[
                    CompositeStep(
                        step_id="s0",
                        step_index=0,
                        intent=Intent(intent_id="i1", action=SemanticAction.OPEN, capability_id="desktop.open_application"),
                        description="Open Notepad",
                        status=StepStatus.VERIFIED_SUCCESS,
                        verification_result=VerificationResult(verified=TriState.TRUE),
                    ),
                    CompositeStep(
                        step_id="s1",
                        step_index=1,
                        intent=Intent(intent_id="i2", action=SemanticAction.TYPE_TEXT, capability_id="desktop.physical_input"),
                        description="Type Payload",
                        status=StepStatus.FAILED,
                        target_app_name="notepad",
                        verification_result=VerificationResult(verified=TriState.FALSE, failure_code=FailureClass.WINDOW_NOT_FOCUSED),
                    ),
                ],
            )
        else:
            # Second execution: Re-planned remainder succeeds
            return CompositeExecutionResult(
                sequence_id=seq.sequence_id,
                terminal_status=CompositeTerminalStatus.SUCCESS,
                total_steps=len(seq.steps),
                completed_steps=len(seq.steps),
                verified_steps=len(seq.steps),
                step_results=[
                    CompositeStep(
                        step_id=f"step_{idx}",
                        step_index=idx,
                        intent=s.intent,
                        description=s.description,
                        status=StepStatus.VERIFIED_SUCCESS,
                        verification_result=VerificationResult(verified=TriState.TRUE),
                    )
                    for idx, s in enumerate(seq.steps)
                ],
            )

    from app.ai.orchestrator.action_executor import action_executor
    monkeypatch.setattr(action_executor, "execute_sequence", mock_execute_sequence)

    runtime = GoalRuntime(compiled_goal, context=context)
    success, wait_user, fc = await runtime._execute_task(compiled_goal.tasks[0])

    assert success is True
    assert wait_user is False
    assert fc is None
    assert call_count == 2
    # Verify adaptive re-planning history was recorded
    assert len(context.recovery_history) == 1
    assert context.recovery_history[0]["replan_attempt"] == 1
    assert context.recovery_history[0]["strategy"] == "INSPECT_STATE"


# ===========================================================================
# 5. Goal Cancellation Handling
# ===========================================================================

@pytest.mark.asyncio
async def test_goal_runtime_cancellation():
    """Validates that signalling cancel on GoalRuntime sets GoalState.CANCELLED cleanly."""
    goal = Goal(
        goal_id="g_cancel",
        objective="Long Running Goal",
        tasks=[
            Task(
                task_id="t1",
                description="Task to be cancelled",
                intents=[
                    Intent(intent_id="i1", action=SemanticAction.CLICK, target="notepad"),
                ],
            )
        ],
    )

    runtime = GoalRuntime(goal)
    runtime.cancel()  # Signal cancellation immediately

    events = []
    async for ev in runtime.run():
        events.append(ev)

    assert runtime.goal.state == GoalState.CANCELLED
    event_types = [e.event_type for e in events]
    assert ExecutionEventType.GOAL_CANCELLED in event_types


# ===========================================================================
# 6. ConversationSession Request Path Integrity
# ===========================================================================

@pytest.mark.asyncio
async def test_conversation_session_chat_accumulates_assistant_response_events():
    """Validates that ConversationSession.chat extracts text from ASSISTANT_RESPONSE events."""
    from app.ai.orchestrator.session import ConversationSession
    from app.ai.providers.types import AIResponse, TokenUsage

    class MockProvider:
        async def generate(self, request):
            return AIResponse(
                content="Hello from ASTRA assistant!",
                model="mock-model",
                provider="mock-provider",
                usage=TokenUsage(10, 10, 20),
                finish_reason="stop",
            )

    session = ConversationSession(provider=MockProvider())
    response = await session.chat("Hello ASTRA")
    assert response == "Hello from ASTRA assistant!"


@pytest.mark.asyncio
async def test_conversation_session_cancellation_and_api_endpoint():
    """Validates ConversationSession cancellation behavior when idle and via API endpoint."""
    from app.ai.orchestrator.session import ConversationSession
    from app.ai.providers.types import AIResponse, TokenUsage
    from app.api.routes.conversation import cancel_execution

    class MockProvider:
        async def generate(self, request):
            return AIResponse(
                content="Idle response",
                model="mock-model",
                provider="mock-provider",
                usage=TokenUsage(10, 10, 20),
                finish_reason="stop",
            )

    session = ConversationSession(provider=MockProvider())
    # When no goal is executing, cancel returns False cleanly
    assert session.cancel() is False

    # Verify route handler responds cleanly
    res = await cancel_execution()
    assert isinstance(res, dict)
    assert res.get("cancelled") is False


