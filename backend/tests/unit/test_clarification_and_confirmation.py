"""
Unit tests for Phase B.11: Proactive Multi-Turn Desktop Task Assistance & User Interaction Clarification Runtime.

Tests:
1. Clarification domain models (ClarificationRequest, ClarificationOption, ClarificationResponse) validation, expiration, and serialization.
2. Grounded candidate disambiguation in ActionCompiler (grounded in catalog/profiles, never hallucinated, explicit overrides memory).
3. ConsequentialActionPolicy deterministic detection and confirmation request generation for destructive operations.
4. Pre-actuation interception and scoped permission gating in ActionExecutor / PermissionEvaluator.
5. Durable persistence of pending_clarification across SQLite store reload and resumption boundaries.
6. Multi-turn conversation routing in ConversationSession (matching responses, rejecting unrelated "yes", handling new goal supersession).
7. Safe cancellation on rejection and prevention of duplicate / replayed executions.
"""

import os
import tempfile
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from app.domain.clarification import (
    ClarificationType,
    ClarificationOption,
    ClarificationRequest,
    ClarificationResponse,
)
from app.domain.goals import (
    Goal,
    Task,
    Intent,
    SemanticAction,
    GoalState,
    TaskState,
    FailureClass,
)
from app.domain.events import ExecutionEvent, ExecutionEventType
from app.domain.execution_context import ExecutionContext
from app.domain.checkpoints import GoalCheckpoint, TaskCheckpoint
from app.core.security.consequential import ConsequentialActionPolicy
from app.core.security.evaluator import PermissionEvaluator, permission_evaluator
from app.domain.permissions import (
    PermissionRequest,
    PermissionState,
    CapabilityScope,
    ResourceScope,
)
from app.database.goal_store import SQLiteGoalStore
from app.ai.orchestrator.compiler import ActionCompiler
from app.ai.orchestrator.session import ConversationSession
from app.ai.orchestrator.runtime import GoalRuntime
from app.ai.providers.types import AIMessage, MessageRole, AIResponse, ToolCall, TokenUsage


# =========================================================================
# 1. Clarification Domain Models Tests
# =========================================================================

def test_clarification_request_and_response_validation():
    """Verifies ClarificationRequest creation, option lookup, and response validation."""
    opts = [
        ClarificationOption(option_id="opt_1", label="Notepad", value="notepad.exe", is_recommended=True),
        ClarificationOption(option_id="opt_2", label="Visual Studio Code", value="code.exe"),
    ]
    req = ClarificationRequest(
        request_id="req-123",
        clarification_type=ClarificationType.AMBIGUOUS_TARGET,
        prompt="Which editor would you like to use?",
        options=opts,
        default_option_id="opt_1",
        target_name="notes editor",
        timeout_seconds=300,
    )

    assert req.request_id == "req-123"
    assert req.clarification_type == ClarificationType.AMBIGUOUS_TARGET
    assert req.get_option("opt_1").label == "Notepad"
    assert req.get_option("unknown") is None
    assert not req.is_expired()

    # Valid response matching option
    valid_resp = ClarificationResponse(request_id="req-123", selected_option_id="opt_2")
    is_valid, err = valid_resp.validate_against(req)
    assert is_valid
    assert err is None

    # Invalid response: mismatched request_id
    bad_req_resp = ClarificationResponse(request_id="other-req", selected_option_id="opt_1")
    is_valid, err = bad_req_resp.validate_against(req)
    assert not is_valid
    assert "does not match" in err

    # Invalid response: invalid option id and no custom input
    bad_opt_resp = ClarificationResponse(request_id="req-123", selected_option_id="opt_nonexistent")
    is_valid, err = bad_opt_resp.validate_against(req)
    assert not is_valid
    assert "not in valid" in err

    # Valid response: custom input allowed
    custom_resp = ClarificationResponse(request_id="req-123", custom_input="Sublime Text")
    is_valid, err = custom_resp.validate_against(req)
    assert is_valid

    # Consequential confirmation validation
    confirm_req = ClarificationRequest(
        request_id="confirm-456",
        clarification_type=ClarificationType.CONSEQUENTIAL_ACTION,
        prompt="Are you sure you want to delete folder?",
        impact_description="Permanent deletion of D:/temp",
        requires_explicit_confirmation=True,
    )
    confirm_resp = ClarificationResponse(request_id="confirm-456", confirmed=True)
    is_valid, err = confirm_resp.validate_against(confirm_req)
    assert is_valid

    unconfirmed_resp = ClarificationResponse(request_id="confirm-456", confirmed=None)
    is_valid, err = unconfirmed_resp.validate_against(confirm_req)
    assert not is_valid
    assert "requires an explicit 'confirmed' boolean" in err


def test_clarification_request_expiration():
    """Verifies that expired clarification requests are correctly identified and rejected."""
    past_time = datetime.now(timezone.utc) - timedelta(seconds=500)
    req = ClarificationRequest(
        request_id="expired-1",
        clarification_type=ClarificationType.MISSING_PARAMETER,
        prompt="Missing parameter",
        created_at=past_time,
        timeout_seconds=60,
    )
    assert req.is_expired()


# =========================================================================
# 2. Grounded Candidate Disambiguation in ActionCompiler
# =========================================================================

@pytest.mark.asyncio
async def test_action_compiler_generates_grounded_clarification_for_ambiguous_target():
    """Verifies that ambiguous targets produce a structured ClarificationRequest with real candidates."""
    compiler = ActionCompiler()

    goal = Goal(
        goal_id="g-test-ambig",
        objective="Open text editor",
        tasks=[
            Task(
                task_id="task-open-editor",
                description="Open notes editor",
                intents=[
                    Intent(
                        intent_id="i-ambig",
                        action=SemanticAction.OPEN,
                        target="notes editor",
                    )
                ],
            )
        ]
    )
    context = ExecutionContext(execution_id="test-exec")

    compiled = await compiler.compile(goal, context)
    assert compiled.state == GoalState.WAITING_FOR_USER
    assert compiled.pending_clarification is not None
    assert context.pending_clarification is not None

    clarif = compiled.pending_clarification
    assert clarif.clarification_type == ClarificationType.AMBIGUOUS_TARGET
    assert clarif.target_name == "notes editor"
    assert len(clarif.options) > 0
    labels = [o.label for o in clarif.options]
    assert any("Notepad" in l or "Code" in l for l in labels)


@pytest.mark.asyncio
async def test_action_compiler_explicit_override_over_memory():
    """Verifies that explicit user intent strictly overrides stored memory preferences."""
    mock_memory = MagicMock()
    mock_memory.recall_application_profile.return_value = None
    mock_profile = MagicMock()
    mock_profile.canonical_name = "WordPad"
    mock_profile.display_name = "WordPad"
    mock_memory.list_application_profiles.return_value = [mock_profile]

    compiler = ActionCompiler(memory_engine=mock_memory)

    goal = Goal(
        goal_id="g-test-explicit",
        objective="Open notepad",
        tasks=[
            Task(
                task_id="task-explicit-notepad",
                description="Open notepad",
                intents=[
                    Intent(
                        intent_id="i-explicit",
                        action=SemanticAction.OPEN,
                        target="notepad",
                    )
                ],
            )
        ]
    )
    context = ExecutionContext(execution_id="test-exec")

    compiled = await compiler.compile(goal, context)
    assert compiled.state != GoalState.WAITING_FOR_USER
    assert compiled.pending_clarification is None


# =========================================================================
# 3. Consequential Action Policy Tests
# =========================================================================

def test_consequential_action_policy_detection():
    """Verifies deterministic classification of destructive or protected operations."""
    policy = ConsequentialActionPolicy()

    # Intent-level checks
    is_conseq, _, _ = policy.evaluate_intent("close_application", "notepad", {"force": True})
    assert is_conseq
    is_conseq, _, _ = policy.evaluate_intent("execute_command", "powershell", {"command": "Remove-Item -Recurse D:\\temp"})
    assert is_conseq
    is_conseq, _, _ = policy.evaluate_intent("execute_command", "cmd", {"command": "del /f /q C:\\data.txt"})
    assert is_conseq
    is_conseq, _, _ = policy.evaluate_intent("execute_command", "cmd", {"command": "taskkill /f /im chrome.exe"})
    assert is_conseq
    is_conseq, _, _ = policy.evaluate_intent("launch_application", "notepad", {})
    assert not is_conseq

    # Step-level checks
    from app.domain.composite import CompositeStep
    step = CompositeStep(
        step_id="step-1",
        description="Force kill process",
        intent=Intent(
            intent_id="i-1",
            action=SemanticAction.CLOSE,
            target="cmd",
            parameters={"command": "taskkill /F /IM explorer.exe", "force": True}
        ),
    )
    is_conseq, reason, impact = policy.evaluate_step(step)
    assert is_conseq
    assert "kill" in impact.lower() or "terminate" in reason.lower()


def test_consequential_confirmation_request_creation():
    """Verifies confirmation request creation with clear impact description."""
    from app.domain.composite import CompositeStep
    step = CompositeStep(
        step_id="step-del",
        description="Delete project files",
        intent=Intent(
            intent_id="i-del",
            action=SemanticAction.CLOSE,
            target="powershell",
            parameters={"command": "rm -r ./dist", "force": True}
        ),
    )

    req = ConsequentialActionPolicy.create_confirmation_request(
        step,
        goal_id="goal-99",
        task_id="task-1",
        step_index=2,
    )
    assert req.clarification_type == ClarificationType.CONSEQUENTIAL_ACTION
    assert req.requires_explicit_confirmation is True
    assert "Delete project files" in req.prompt
    assert req.goal_id == "goal-99"
    assert req.step_index == 2


# =========================================================================
# 4. Scoped Permission Evaluation & Actuation Interception
# =========================================================================

def test_scoped_permission_grant_and_rejection():
    """Verifies that consequential approval grants strictly scoped permission and rejection blocks it."""
    evaluator = PermissionEvaluator()

    perm_req = PermissionRequest(
        request_id="perm-1",
        requester_task_id="goal-del",
        capability=CapabilityScope.SYSTEM_MODIFICATION,
        resource_scope=ResourceScope(capability=CapabilityScope.SYSTEM_MODIFICATION, resource="del_files"),
        reason="Delete files operation",
    )

    # Initial state: denied / requires permission
    decision = evaluator.evaluate(perm_req)
    assert decision.decision == PermissionState.REQUIRED

    # Grant permission strictly for resource="del_files"
    grant = evaluator.grant(
        perm_req,
        reason="User explicitly approved deletion",
        duration_seconds=60,
    )
    assert grant.state == PermissionState.GRANTED

    # Now authorized for the specific resource
    auth_decision = evaluator.evaluate(perm_req)
    assert auth_decision.decision == PermissionState.GRANTED

    # Unrelated resource is STILL denied
    unrelated_req = PermissionRequest(
        request_id="perm-2",
        requester_task_id="goal-del",
        capability=CapabilityScope.SYSTEM_MODIFICATION,
        resource_scope=ResourceScope(capability=CapabilityScope.SYSTEM_MODIFICATION, resource="other_resource"),
        reason="Format drive",
    )
    unrelated_decision = evaluator.evaluate(unrelated_req)
    assert unrelated_decision.decision == PermissionState.REQUIRED


# =========================================================================
# 5. Checkpoint Persistence and Process Restart
# =========================================================================

def test_pending_clarification_checkpoint_durability():
    """Verifies that pending_clarification survives SQLite persistence and restart."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        store = SQLiteGoalStore(db_path=db_path)

        clarif = ClarificationRequest(
            request_id="req-persist-1",
            clarification_type=ClarificationType.AMBIGUOUS_TARGET,
            prompt="Select browser",
            options=[
                ClarificationOption(option_id="b1", label="Brave", value="brave.exe"),
                ClarificationOption(option_id="b2", label="Chrome", value="chrome.exe"),
            ],
            target_name="browser",
        )

        cp = GoalCheckpoint(
            checkpoint_id="cp-1",
            schema_version="2.0",
            goal_id="goal-durability",
            objective="Search web",
            goal_state=GoalState.WAITING_FOR_USER,
            current_task_index=0,
            total_tasks=1,
            task_checkpoints=[
                TaskCheckpoint(
                    task_id="t1",
                    task_index=0,
                    description="Open browser",
                    task_state=TaskState.WAITING_FOR_USER,
                )
            ],
            pending_clarification=clarif,
            suspension_reason="Waiting for user to choose browser",
            is_resumable=True,
        )

        store.save_checkpoint(cp)
        store.close()

        # Reopen store (simulating process restart)
        reopened_store = SQLiteGoalStore(db_path=db_path)
        loaded_cp = reopened_store.get_checkpoint("goal-durability")

        assert loaded_cp is not None
        assert loaded_cp.goal_state == GoalState.WAITING_FOR_USER
        assert loaded_cp.pending_clarification is not None
        assert loaded_cp.pending_clarification.request_id == "req-persist-1"
        assert loaded_cp.pending_clarification.target_name == "browser"
        assert len(loaded_cp.pending_clarification.options) == 2
        assert loaded_cp.pending_clarification.options[0].label == "Brave"
        reopened_store.close()

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


# =========================================================================
# 6. Multi-Turn Session Routing & Resumption Tests
# =========================================================================

@pytest.mark.asyncio
async def test_session_resolves_ambiguous_clarification():
    """Verifies that answering a pending clarification binds the target and compiles execution."""
    mock_provider = AsyncMock()
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        store = SQLiteGoalStore(db_path=db_path)
        session = ConversationSession(provider=mock_provider, goal_store=store)

        clarif = ClarificationRequest(
            request_id="req-multi-1",
            clarification_type=ClarificationType.AMBIGUOUS_TARGET,
            prompt="Which application for notes?",
            options=[
                ClarificationOption(option_id="opt_np", label="Notepad", value="Notepad"),
                ClarificationOption(option_id="opt_vs", label="VS Code", value="Visual Studio Code"),
            ],
            target_name="notes app",
        )

        cp = GoalCheckpoint(
            checkpoint_id="cp-m1",
            schema_version="2.0",
            goal_id="goal-m1",
            objective="Take notes in notes app",
            goal_state=GoalState.WAITING_FOR_USER,
            current_task_index=0,
            total_tasks=1,
            task_checkpoints=[
                TaskCheckpoint(
                    task_id="t-m1",
                    task_index=0,
                    description="Open notes app",
                    task_state=TaskState.WAITING_FOR_USER,
                )
            ],
            pending_clarification=clarif,
            is_resumable=True,
        )
        store.save_checkpoint(cp)
        session.pending_goal_id = "goal-m1"

        # Match user selecting "1" or "Notepad"
        matched = session._match_pending_clarification("Notepad", clarif)
        assert matched is not None
        assert matched.selected_option_id == "opt_np"

        # Match user selecting "2"
        matched_num = session._match_pending_clarification("2", clarif)
        assert matched_num is not None
        assert matched_num.selected_option_id == "opt_vs"

        # An unrelated "yes" does NOT resolve an ambiguous target
        matched_unrelated = session._match_pending_clarification("yes", clarif)
        assert matched_unrelated is None

        store.close()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


@pytest.mark.asyncio
async def test_session_consequential_confirmation_and_rejection():
    """Verifies approval vs rejection matching for consequential actions."""
    mock_provider = AsyncMock()
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        store = SQLiteGoalStore(db_path=db_path)
        session = ConversationSession(provider=mock_provider, goal_store=store)

        confirm_req = ClarificationRequest(
            request_id="req-conf-1",
            clarification_type=ClarificationType.CONSEQUENTIAL_ACTION,
            prompt="Confirm terminating notepad.exe?",
            requires_explicit_confirmation=True,
            target_name="notepad.exe",
        )

        # Explicit positive affirmations
        for yes_word in ["yes", "confirm", "approve", "proceed", "go ahead"]:
            matched = session._match_pending_clarification(yes_word, confirm_req)
            assert matched is not None
            assert matched.confirmed is True

        # Explicit negative affirmations
        for no_word in ["no", "cancel", "stop", "abort", "reject", "nevermind"]:
            matched = session._match_pending_clarification(no_word, confirm_req)
            assert matched is not None
            assert matched.confirmed is False

        # Rejection cancels goal safely
        cp = GoalCheckpoint(
            checkpoint_id="cp-c1",
            schema_version="2.0",
            goal_id="goal-c1",
            objective="Kill notepad",
            goal_state=GoalState.WAITING_FOR_USER,
            current_task_index=0,
            total_tasks=1,
            task_checkpoints=[
                TaskCheckpoint(
                    task_id="t-c1",
                    task_index=0,
                    description="Kill notepad.exe",
                    task_state=TaskState.WAITING_FOR_USER,
                )
            ],
            pending_clarification=confirm_req,
            is_resumable=True,
        )
        store.save_checkpoint(cp)
        session.pending_goal_id = "goal-c1"

        reject_response = ClarificationResponse(request_id="req-conf-1", confirmed=False)
        events = []
        async for chunk in session.resolve_clarification_stream(reject_response):
            events.append(chunk)

        # Verify goal cancelled and not resumable
        updated_cp = store.get_checkpoint("goal-c1")
        assert updated_cp.goal_state == GoalState.CANCELLED
        assert updated_cp.is_resumable is False
        assert updated_cp.pending_clarification is None

        store.close()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


@pytest.mark.asyncio
async def test_session_unrelated_instruction_supersedes_suspended_goal():
    """Verifies that an unrelated new goal safely supersedes a suspended goal without resolving it."""
    mock_provider = AsyncMock()
    mock_provider.generate.return_value = AIResponse(
        content="I will check the weather.",
        model="mock-model",
        provider="mock-provider",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        finish_reason="stop",
        tool_calls=[]
    )

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        store = SQLiteGoalStore(db_path=db_path)
        session = ConversationSession(provider=mock_provider, goal_store=store)

        clarif = ClarificationRequest(
            request_id="req-unrelated-1",
            clarification_type=ClarificationType.AMBIGUOUS_TARGET,
            prompt="Which editor?",
            options=[ClarificationOption(option_id="o1", label="Notepad", value="notepad")],
            target_name="editor",
        )

        cp = GoalCheckpoint(
            checkpoint_id="cp-u1",
            schema_version="2.0",
            goal_id="goal-suspended-1",
            objective="Edit file",
            goal_state=GoalState.WAITING_FOR_USER,
            current_task_index=0,
            total_tasks=1,
            task_checkpoints=[
                TaskCheckpoint(
                    task_id="t-u1",
                    task_index=0,
                    description="Open editor",
                    task_state=TaskState.WAITING_FOR_USER,
                )
            ],
            pending_clarification=clarif,
            is_resumable=True,
        )
        store.save_checkpoint(cp)
        session.pending_goal_id = "goal-suspended-1"

        # User asks unrelated instruction: "What is the weather in Paris?"
        events = []
        async for chunk in session.chat_stream("What is the weather in Paris?"):
            events.append(chunk)

        # Suspended goal should be preserved/marked superseded, not resolved as editor choice
        updated_cp = store.get_checkpoint("goal-suspended-1")
        assert "Superseded" in (updated_cp.suspension_reason or "")
        assert session.pending_goal_id is None

        store.close()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
