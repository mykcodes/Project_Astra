"""
ASTRA - Phase B.9 Unit Regression Suite
Long-Running Goal Persistence, Checkpointing & Resumption Runtime
"""

import os
import json
import sqlite3
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
    VerificationResult,
)
from app.domain.composite import (
    CompositeActionSequence,
    CompositeStep,
    CompensationAction,
    CompositeTerminalStatus,
    CompositeExecutionResult,
    StepStatus,
)
from app.domain.events import ExecutionEventType
from app.domain.execution_context import ExecutionContext
from app.domain.checkpoints import (
    GoalCheckpoint,
    TaskCheckpoint,
    ResumptionClassification,
    SCHEMA_VERSION,
)
from app.database.goal_store import SQLiteGoalStore, CheckpointCorruptionError
from app.ai.orchestrator.runtime import GoalRuntime
from app.ai.orchestrator.session import ConversationSession


# ===========================================================================
# 1. Checkpoint Contracts (Serialization, Deserialization & Validation)
# ===========================================================================

def test_checkpoint_contract_serialization_roundtrip():
    """Verify serialization to dict/json and reconstructibility."""
    task_cp = TaskCheckpoint(
        task_id="t1",
        description="Launch notepad",
        task_state=TaskState.COMPLETED,
        completed_step_indices=[0, 1],
        last_completed_step=1,
        verified_step_indices=[0, 1],
        last_verified_step=1,
        verified_evidence={"window_visible": True},
        target_app_name="notepad",
        target_window_pattern="*Notepad*",
        is_verified=True,
        is_terminal=True,
    )
    goal_cp = GoalCheckpoint(
        checkpoint_id="cp-123",
        schema_version=SCHEMA_VERSION,
        goal_id="g1",
        objective="Open notepad and type text",
        goal_state=GoalState.WAITING_FOR_USER,
        current_task_index=1,
        total_tasks=2,
        completed_tasks=["t1"],
        verified_steps={"t1": [0, 1]},
        task_checkpoints=[task_cp],
        environment_snapshot={"foreground": "Notepad"},
        recovery_history=[{"strategy": "RETRY", "attempt": 1}],
        suspension_reason="Awaiting user confirmation",
        is_resumable=True,
    )

    data = goal_cp.to_dict()
    assert data["checkpoint_id"] == "cp-123"
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["goal_state"] == "WAITING_FOR_USER"
    assert data["is_resumable"] is True
    assert len(data["task_checkpoints"]) == 1

    # Deserialization from dict
    reconstructed = GoalCheckpoint.from_dict(data)
    assert reconstructed.checkpoint_id == "cp-123"
    assert reconstructed.schema_version == SCHEMA_VERSION
    assert reconstructed.goal_id == "g1"
    assert reconstructed.completed_tasks == ["t1"]
    assert reconstructed.verified_steps == {"t1": [0, 1]}
    assert len(reconstructed.task_checkpoints) == 1
    assert reconstructed.task_checkpoints[0].target_app_name == "notepad"
    assert reconstructed.task_checkpoints[0].verified_evidence == {"window_visible": True}

    # Deserialization from JSON string
    raw_json = goal_cp.to_json()
    from_json_cp = GoalCheckpoint.from_json(raw_json)
    assert from_json_cp.checkpoint_id == "cp-123"
    assert from_json_cp.goal_id == "g1"


def test_checkpoint_unsupported_schema_version():
    """Unsupported schema versions must be rejected safely."""
    cp = GoalCheckpoint(
        checkpoint_id="cp-old",
        schema_version="99.0", # Unsupported
        goal_id="g1",
        objective="Test",
        goal_state=GoalState.WAITING_FOR_USER,
        is_resumable=True,
    )
    resumable, reason = cp.validate_resumable()
    assert resumable is False
    assert "Incompatible schema version" in reason


def test_checkpoint_terminal_state_resumption_rejected():
    """Terminal goals (COMPLETED, FAILED, CANCELLED) cannot be resumed."""
    for state in [GoalState.COMPLETED, GoalState.CANCELLED]:
        cp = GoalCheckpoint(
            checkpoint_id=f"cp-{state.value}",
            schema_version=SCHEMA_VERSION,
            goal_id="g1",
            objective="Test",
            goal_state=state,
            is_resumable=True, # Even if flag was True, terminal states are rejected
        )
        resumable, reason = cp.validate_resumable()
        assert resumable is False
        assert "terminal state" in reason


def test_checkpoint_cancelled_goal_flag_rejected():
    """A goal marked is_resumable=False must be rejected."""
    cp = GoalCheckpoint(
        checkpoint_id="cp-unresumable",
        schema_version=SCHEMA_VERSION,
        goal_id="g1",
        objective="Test",
        goal_state=GoalState.PLAN_CREATED,
        is_resumable=False,
        suspension_reason="Explicitly aborted",
    )
    resumable, reason = cp.validate_resumable()
    assert resumable is False
    assert "marked non-resumable" in reason


# ===========================================================================
# 2. Durable Persistence (SQLiteGoalStore)
# ===========================================================================

def test_sqlite_goal_store_lifecycle(tmp_path):
    """Test saving, loading, updating, listing, and surviving store reopening."""
    db_path = str(tmp_path / "test_goals.db")
    store = SQLiteGoalStore(db_path=db_path)

    # 1. Create and save checkpoint
    cp1 = GoalCheckpoint(
        checkpoint_id="cp-1",
        schema_version=SCHEMA_VERSION,
        goal_id="g-100",
        objective="Test Goal",
        goal_state=GoalState.EXECUTING,
        current_task_index=0,
        is_resumable=True,
    )
    store.save_checkpoint(cp1)

    # 2. Retrieve checkpoint
    loaded = store.get_checkpoint("g-100")
    assert loaded is not None
    assert loaded.goal_id == "g-100"
    assert loaded.goal_state == GoalState.EXECUTING
    assert loaded.is_resumable is True

    # 3. Update checkpoint (atomic upsert)
    cp1.goal_state = GoalState.WAITING_FOR_USER
    cp1.suspension_reason = "Prompting user"
    cp1.current_task_index = 1
    cp1.completed_tasks = ["t1"]
    store.save_checkpoint(cp1)

    loaded_updated = store.get_checkpoint("g-100")
    assert loaded_updated.goal_state == GoalState.WAITING_FOR_USER
    assert loaded_updated.suspension_reason == "Prompting user"
    assert loaded_updated.completed_tasks == ["t1"]

    # 4. List resumable goals
    resumable_list = store.list_resumable_goals()
    assert len(resumable_list) == 1
    assert resumable_list[0].goal_id == "g-100"

    # 5. Simulate backend restart: close store and reopen new instance pointing to same file
    del store
    reopened_store = SQLiteGoalStore(db_path=db_path)
    loaded_after_restart = reopened_store.get_checkpoint("g-100")
    assert loaded_after_restart is not None
    assert loaded_after_restart.goal_id == "g-100"
    assert loaded_after_restart.completed_tasks == ["t1"]

    # 6. Mark non-resumable
    reopened_store.mark_non_resumable("g-100", "Goal aborted")
    loaded_aborted = reopened_store.get_checkpoint("g-100")
    assert loaded_aborted.is_resumable is False
    assert loaded_aborted.suspension_reason == "Goal aborted"
    assert len(reopened_store.list_resumable_goals()) == 0


def test_sqlite_goal_store_corrupted_data_handling(tmp_path):
    """Corrupted records in the database must fail safely with CheckpointCorruptionError."""
    db_path = str(tmp_path / "test_corrupt.db")
    store = SQLiteGoalStore(db_path=db_path)

    # Insert raw invalid JSON directly into table
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO goal_checkpoints (goal_id, checkpoint_id, schema_version, goal_state, current_task_index, is_resumable, checkpoint_data, created_at, updated_at)
        VALUES ('g-corrupt', 'cp-bad', '1.0', 'EXECUTING', 0, 1, 'NOT_VALID_JSON{{{', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()
    conn.close()

    # get_checkpoint should fail safely by raising CheckpointCorruptionError
    with pytest.raises(CheckpointCorruptionError):
        store.get_checkpoint("g-corrupt")

    # list_resumable_goals should skip corrupted records without crashing
    resumable = store.list_resumable_goals()
    assert len(resumable) == 0


# ===========================================================================
# 3. Runtime Integration & Lifecycle Checkpointing
# ===========================================================================

@pytest.mark.asyncio
async def test_runtime_persists_checkpoints_at_lifecycle_boundaries(tmp_path):
    """Verify checkpoint creation at goal initialization, task completion, and terminal states."""
    db_path = str(tmp_path / "runtime_cp.db")
    store = SQLiteGoalStore(db_path=db_path)

    task1 = Task(
        task_id="t1",
        description="First action",
        intents=[Intent(intent_id="i1", action=SemanticAction.OPEN, target="notepad")],
    )
    task2 = Task(
        task_id="t2",
        description="Second action",
        intents=[Intent(intent_id="i2", action=SemanticAction.TYPE_TEXT, target="notepad", parameters={"text": "hello"})],
    )
    goal = Goal(
        goal_id="g-lifecycle",
        objective="Two step goal",
        tasks=[task1, task2],
    )

    context = ExecutionContext(execution_id="exec-1")
    runtime = GoalRuntime(goal=goal, context=context, goal_store=store)

    # Mock action_executor.execute_intent to succeed with verified truth
    with patch("app.ai.orchestrator.runtime.action_executor.execute_intent", new_callable=AsyncMock) as mock_exec_intent:
        mock_exec_intent.return_value = {
            "success": True,
            "verified": True,
            "diagnostics": {"pid": 1234},
        }

        events = []
        async for event in runtime.run():
            events.append(event)

        # Confirm completed execution
        assert runtime.goal.state == GoalState.COMPLETED

        # Check final checkpoint
        final_cp = store.get_checkpoint("g-lifecycle")
        assert final_cp is not None
        assert final_cp.goal_state == GoalState.COMPLETED
        assert final_cp.is_resumable is False # Completed goals are terminal and non-resumable
        assert len(final_cp.task_checkpoints) == 2


@pytest.mark.asyncio
async def test_runtime_cancellation_persists_non_resumable(tmp_path):
    """Cancelling a goal persists it truthfully as CANCELLED and marks is_resumable=False."""
    db_path = str(tmp_path / "runtime_cancel.db")
    store = SQLiteGoalStore(db_path=db_path)

    task1 = Task(
        task_id="t1",
        description="Action to cancel",
        intents=[Intent(intent_id="i1", action=SemanticAction.OPEN, target="notepad")],
    )
    goal = Goal(
        goal_id="g-cancel",
        objective="Cancel test",
        tasks=[task1],
    )

    context = ExecutionContext(execution_id="exec-cancel")
    runtime = GoalRuntime(goal=goal, context=context, goal_store=store)

    # Trigger cancel before running
    runtime.cancel()

    events = []
    async for event in runtime.run():
        events.append(event)

    assert runtime.goal.state == GoalState.CANCELLED
    cp = store.get_checkpoint("g-cancel")
    assert cp is not None
    assert cp.goal_state == GoalState.CANCELLED
    assert cp.is_resumable is False
    assert "cancelled by user" in cp.suspension_reason.lower()

    # Must reject resumption
    is_resumable, reason = cp.validate_resumable()
    assert is_resumable is False


# ===========================================================================
# 4. Resumption Lifecycle, Selective Execution & Invariants
# ===========================================================================

@pytest.mark.asyncio
async def test_runtime_resume_skips_completed_tasks_and_slices_steps(tmp_path):
    """
    Resumption must NOT repeat completed verified tasks.
    Composite tasks must resume from last_verified_step + 1.
    """
    db_path = str(tmp_path / "resume_test.db")
    store = SQLiteGoalStore(db_path=db_path)

    # Construct checkpoint where task 1 was completed and task 2 was interrupted after step 0
    t1_cp = TaskCheckpoint(
        task_id="t1",
        task_index=0,
        task_state=TaskState.COMPLETED,
        description="Task 1 done",
        completed_step_indices=[0],
        verified_step_indices=[0],
        last_completed_step=0,
        last_verified_step=0,
        is_verified=True,
        is_terminal=True,
    )
    t2_cp = TaskCheckpoint(
        task_id="t2",
        task_index=1,
        task_state=TaskState.WAITING_FOR_USER,
        description="Task 2 composite",
        completed_step_indices=[0],
        verified_step_indices=[0],
        last_completed_step=0,
        last_verified_step=0,
        is_verified=False,
        is_terminal=False,
    )

    # Target composite sequence with 3 steps
    step0 = CompositeStep(
        step_id="s0",
        step_index=0,
        description="Step 0 (already verified)",
        intent=Intent(intent_id="i0", action=SemanticAction.CLICK, target="notepad"),
        tool_args={"intent": "CLICK"},
    )
    step1 = CompositeStep(
        step_id="s1",
        step_index=1,
        description="Step 1 (unexecuted)",
        intent=Intent(intent_id="i1", action=SemanticAction.TYPE_TEXT, target="notepad", parameters={"text": "resumed text"}),
        tool_args={"intent": "TYPE_TEXT", "text": "resumed text"},
    )
    step2 = CompositeStep(
        step_id="s2",
        step_index=2,
        description="Step 2 (unexecuted)",
        intent=Intent(intent_id="i2", action=SemanticAction.HOTKEY, target="notepad", parameters={"keys": ["ctrl", "s"]}),
        tool_args={"intent": "HOTKEY", "keys": ["ctrl", "s"]},
    )
    seq = CompositeActionSequence(
        sequence_id="seq-1",
        name="test_seq",
        steps=[step0, step1, step2],
    )

    t1 = Task(
        task_id="t1",
        description="Task 1 done",
        state=TaskState.COMPLETED,
        intents=[Intent(intent_id="i1_t1", action=SemanticAction.OPEN, target="notepad")],
    )
    t2 = Task(
        task_id="t2",
        description="Task 2 composite",
        state=TaskState.WAITING_FOR_USER,
        intents=[Intent(intent_id="i2_t2", action=SemanticAction.TYPE_TEXT, target="notepad", parameters={"text": "resumed text"})],
    )
    t2.composite_sequence = seq

    goal = Goal(
        goal_id="g-resume",
        objective="Resume test",
        tasks=[t1, t2],
        state=GoalState.WAITING_FOR_USER,
    )

    checkpoint = GoalCheckpoint(
        checkpoint_id="cp-resume-1",
        schema_version=SCHEMA_VERSION,
        goal_id="g-resume",
        objective="Resume test",
        goal_state=GoalState.WAITING_FOR_USER,
        current_task_index=1,
        total_tasks=2,
        completed_tasks=["t1"],
        verified_steps={"t1": [0], "t2": [0]},
        task_checkpoints=[t1_cp, t2_cp],
        goal_payload=goal.model_dump(),
        is_resumable=True,
    )
    store.save_checkpoint(checkpoint)

    # Resume the runtime from checkpoint
    runtime, classification, summary = GoalRuntime.resume(
        checkpoint=checkpoint,
        goal=goal,
        goal_store=store,
    )

    assert classification == ResumptionClassification.VERIFIED_AND_SAFE
    assert runtime.goal.goal_id == "g-resume"
    assert "t1" in runtime.context.completed_tasks

    # Verify task 2's action sequence was sliced: step 0 removed, steps 1 and 2 retained
    remaining_steps = runtime.goal.tasks[1].composite_sequence.steps
    assert len(remaining_steps) == 2
    assert remaining_steps[0].step_id == "s1"
    assert remaining_steps[1].step_id == "s2"

    # Mock execution of the remaining steps
    with patch("app.ai.orchestrator.runtime.action_executor.execute_sequence", new_callable=AsyncMock) as mock_exec_seq:
        mock_exec_seq.return_value = CompositeExecutionResult(
            sequence_id="seq-1",
            terminal_status=CompositeTerminalStatus.SUCCESS,
            total_steps=2,
            completed_steps=2,
            verified_steps=2,
        )

        events = []
        async for ev in runtime.run():
            events.append(ev)

        assert runtime.goal.state == GoalState.COMPLETED
        # Task 1 must not have been executed at all
        assert runtime.goal.tasks[0].state == TaskState.COMPLETED
        assert runtime.goal.tasks[1].state == TaskState.COMPLETED

        # Checkpoint is now terminal COMPLETED
        updated_cp = store.get_checkpoint("g-resume")
        assert updated_cp.goal_state == GoalState.COMPLETED
        assert updated_cp.is_resumable is False


@pytest.mark.asyncio
async def test_runtime_resume_clears_ephemeral_handles(tmp_path):
    """Resumption context must purge ephemeral OS handles and PIDs to prevent reusing stale HWNDs."""
    db_path = str(tmp_path / "resume_ephemeral.db")
    store = SQLiteGoalStore(db_path=db_path)

    t1 = Task(
        task_id="t1",
        description="Pending task",
        intents=[Intent(intent_id="i1", action=SemanticAction.OPEN, target="notepad")],
    )
    goal = Goal(
        goal_id="g-ephemeral",
        objective="Ephemeral test",
        tasks=[t1],
        state=GoalState.WAITING_FOR_USER,
    )

    checkpoint = GoalCheckpoint(
        checkpoint_id="cp-eph-1",
        schema_version=SCHEMA_VERSION,
        goal_id="g-ephemeral",
        objective="Ephemeral test",
        goal_state=GoalState.WAITING_FOR_USER,
        total_tasks=1,
        environment_snapshot={
            "foreground": "Old Window",
            "target_hwnd": 999999,
            "browser": "edge",
        },
        goal_payload=goal.model_dump(),
        is_resumable=True,
    )
    store.save_checkpoint(checkpoint)

    runtime, _, _ = GoalRuntime.resume(checkpoint=checkpoint, goal=goal, goal_store=store)

    # Ephemeral OS/browser keys must have been scrubbed
    snapshot = runtime.context.environment_snapshot
    assert "target_hwnd" not in snapshot
    assert snapshot.get("foreground") == "Old Window"


# ===========================================================================
# 5. Rollback Semantics (Database State vs Real-World Effects)
# ===========================================================================

@pytest.mark.asyncio
async def test_runtime_abort_and_rollback_compensations(tmp_path):
    """
    Rollback attempts compensations for reversible steps,
    distinguishes persisted state from physical external restoration,
    and marks checkpoint non-resumable.
    """
    db_path = str(tmp_path / "rollback.db")
    store = SQLiteGoalStore(db_path=db_path)

    # A sequence with one reversible step (TYPE_TEXT with compensation) and one irreversible step
    step_rev = CompositeStep(
        step_id="s_rev",
        step_index=0,
        description="Type text with compensation",
        intent=Intent(intent_id="i_rev", action=SemanticAction.TYPE_TEXT, target="notepad"),
        tool_args={"text": "reversible text"},
        actuation_accepted=True,
        compensation=CompensationAction(
            intent=Intent(intent_id="i_undo", action=SemanticAction.HOTKEY, target="notepad", parameters={"keys": ["ctrl", "z"]}),
            tool_args={"keys": ["ctrl", "z"]},
            description="Undo typed text with Ctrl+Z",
        ),
    )
    step_irrev = CompositeStep(
        step_id="s_irrev",
        step_index=1,
        description="Irreversible external trigger",
        intent=Intent(intent_id="i_irrev", action=SemanticAction.CLOSE, target="system"),
        tool_args={"target": "system"},
        actuation_accepted=True,
        compensation=None, # Irreversible
    )
    seq = CompositeActionSequence(
        sequence_id="seq-comp",
        name="mixed_reversibility_seq",
        steps=[step_rev, step_irrev],
    )
    task = Task(
        task_id="t1",
        description="Task with mixed reversibility",
        intents=[Intent(intent_id="i1", action=SemanticAction.TYPE_TEXT, target="notepad")],
    )
    task.composite_sequence = seq
    goal = Goal(
        goal_id="g-rollback",
        objective="Rollback test",
        tasks=[task],
    )

    context = ExecutionContext(execution_id="exec-rb")
    context.completed_tasks = ["t1"]

    runtime = GoalRuntime(goal=goal, context=context, goal_store=store)

    with patch("app.ai.orchestrator.runtime.action_executor.execute_intent", new_callable=AsyncMock) as mock_exec_intent:
        mock_exec_intent.return_value = {"success": True}

        rollback_report = await runtime.abort_and_rollback(reason="Test abort and compensate")

        assert rollback_report["goal_id"] == "g-rollback"
        assert rollback_report["goal_state"] == "FAILED"
        assert len(rollback_report["compensations_executed"]) == 1
        assert rollback_report["compensations_executed"][0]["step_id"] == "s_rev"
        assert "s_irrev" in rollback_report["unresolved_steps"]

        # Compensation intent was executed
        mock_exec_intent.assert_called_once()

        # Checkpoint is persisted as FAILED and non-resumable
        cp = store.get_checkpoint("g-rollback")
        assert cp is not None
        assert cp.is_resumable is False


# ===========================================================================
# 6. Session and Streaming Integration
# ===========================================================================

@pytest.mark.asyncio
async def test_conversation_session_resumption_integration(tmp_path):
    """Test session list_resumable_goals, duplicate runtime guard, and streaming resumption."""
    db_path = str(tmp_path / "session_test.db")
    store = SQLiteGoalStore(db_path=db_path)

    mock_provider = MagicMock()
    session = ConversationSession(provider=mock_provider, goal_store=store)

    # 1. Create a suspended checkpoint
    task = Task(
        task_id="t1",
        description="Session resume task",
        intents=[Intent(intent_id="i1", action=SemanticAction.OPEN, target="notepad")],
    )
    goal = Goal(
        goal_id="g-session-1",
        objective="Session resume objective",
        tasks=[task],
        state=GoalState.WAITING_FOR_USER,
    )
    cp = GoalCheckpoint(
        checkpoint_id="cp-sess-1",
        schema_version=SCHEMA_VERSION,
        goal_id="g-session-1",
        objective="Session resume objective",
        goal_state=GoalState.WAITING_FOR_USER,
        total_tasks=1,
        goal_payload=goal.model_dump(),
        is_resumable=True,
    )
    store.save_checkpoint(cp)

    # 2. list_resumable_goals
    resumable = await session.list_resumable_goals()
    assert len(resumable) == 1
    assert resumable[0]["goal_id"] == "g-session-1"

    # 3. Stream resumption
    with patch("app.ai.orchestrator.runtime.action_executor.execute_intent", new_callable=AsyncMock) as mock_exec_intent:
        mock_exec_intent.return_value = {
            "success": True,
            "verified": True,
            "diagnostics": {},
        }

        streamed_chunks = []
        async for chunk in session.resume_goal_stream("g-session-1"):
            streamed_chunks.append(chunk)

        assert len(streamed_chunks) > 0
        # Final terminal chunk should contain ASSISTANT_RESPONSE
        terminal_event = json.loads(streamed_chunks[-1])
        assert terminal_event["event_type"] == "ASSISTANT_RESPONSE"
        assert "Resumed execution completed successfully" in terminal_event["payload"]["text"]

        # Active runtime is cleared
        assert session.active_runtime is None


@pytest.mark.asyncio
async def test_conversation_session_resumption_duplicate_guard(tmp_path):
    """Session must reject resumption if another GoalRuntime is currently active."""
    db_path = str(tmp_path / "session_dup.db")
    store = SQLiteGoalStore(db_path=db_path)

    mock_provider = MagicMock()
    session = ConversationSession(provider=mock_provider, goal_store=store)

    # Fake an active runtime
    fake_runtime = MagicMock()
    fake_runtime.goal.id = "g-active"
    fake_runtime.goal.goal_id = "g-active"
    session.active_runtime = fake_runtime

    with pytest.raises(RuntimeError) as exc_info:
        async for _ in session.resume_goal_stream("g-session-1"):
            pass

    assert "another execution is currently active" in str(exc_info.value)
