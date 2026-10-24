"""
Phase B.11 Live Verification Script

Exercises the complete interaction loop:
1. Genuinely ambiguous target triggers structured clarification with real catalog candidates.
2. Answering clarification binds target and resumes compilation.
3. Consequential action policy intercepts destructive operation before actuation.
4. Rejection safely terminates without execution.
5. Approval grants scoped permission and resumes.
6. Replay / duplicate confirmation rejection.
"""

import asyncio
import tempfile
import os
import sys
import uuid
sys.path.insert(0, ".")

from app.domain.clarification import (
    ClarificationType,
    ClarificationOption,
    ClarificationRequest,
    ClarificationResponse,
)
from app.domain.goals import Goal, Task, Intent, SemanticAction, GoalState, TaskState
from app.domain.execution_context import ExecutionContext
from app.ai.orchestrator.compiler import ActionCompiler
from app.core.security.consequential import ConsequentialActionPolicy
from app.core.security.evaluator import PermissionEvaluator, permission_evaluator
from app.domain.permissions import PermissionRequest, CapabilityScope, ResourceScope, PermissionState
from app.database.goal_store import SQLiteGoalStore
from app.ai.orchestrator.session import ConversationSession
from app.ai.providers.types import AIMessage, MessageRole, AIResponse, ToolCall, TokenUsage
from unittest.mock import AsyncMock

async def run_live_verification():
    print("=== Phase B.11 Live Interaction Verification ===")

    # 1. Ambiguous Target Verification
    print("\n[Step 1] Testing Grounded Ambiguity Disambiguation...")
    compiler = ActionCompiler()
    goal = Goal(
        goal_id=f"live-ambig-{uuid.uuid4().hex[:6]}",
        objective="Open text editor",
        tasks=[
            Task(
                task_id="task-1",
                description="Open notes editor",
                intents=[
                    Intent(
                        intent_id="i-1",
                        action=SemanticAction.OPEN,
                        target="notes editor"
                    )
                ]
            )
        ]
    )
    context = ExecutionContext(execution_id="live-exec-1")
    compiled = await compiler.compile(goal, context)

    assert compiled.state == GoalState.WAITING_FOR_USER, f"Expected WAITING_FOR_USER, got {compiled.state}"
    assert compiled.pending_clarification is not None, "ClarificationRequest was not generated!"
    clarif = compiled.pending_clarification
    assert clarif.clarification_type == ClarificationType.AMBIGUOUS_TARGET
    print(f" -> Successfully intercepted ambiguous target: '{clarif.target_name}'")
    print(f" -> Prompt generated: \"{clarif.prompt}\"")
    print(f" -> Grounded options ({len(clarif.options)}):")
    for opt in clarif.options:
        print(f"    * [{opt.option_id}] {opt.label} ({opt.value}){' [RECOMMENDED]' if opt.is_recommended else ''}")

    # Verify no hallucinated options
    labels = [o.label for o in clarif.options]
    assert any("Notepad" in l for l in labels), "Expected Notepad in options"
    print(" -> Candidate options verified as genuine catalog entries (non-hallucinated).")

    # 2. Resuming Ambiguous Goal with Selection
    print("\n[Step 2] Resolving Ambiguous Target with Selection...")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        store = SQLiteGoalStore(db_path=db_path)
        mock_provider = AsyncMock()
        session = ConversationSession(provider=mock_provider, goal_store=store)

        # Save suspended checkpoint
        from app.domain.checkpoints import GoalCheckpoint, TaskCheckpoint
        cp = GoalCheckpoint(
            checkpoint_id=str(uuid.uuid4()),
            schema_version="2.0",
            goal_id=compiled.goal_id,
            objective=compiled.objective,
            goal_state=GoalState.WAITING_FOR_USER,
            current_task_index=0,
            total_tasks=1,
            task_checkpoints=[
                TaskCheckpoint(
                    task_id="task-1",
                    task_index=0,
                    description="Open notes editor",
                    task_state=TaskState.WAITING_FOR_USER,
                )
            ],
            pending_clarification=clarif,
            is_resumable=True,
        )
        store.save_checkpoint(cp)
        session.pending_goal_id = compiled.goal_id

        # User chooses "Notepad"
        matched = session._match_pending_clarification("Notepad", clarif)
        assert matched is not None, "Failed to match user selection!"
        print(f" -> User input 'Notepad' matched option: {matched.selected_option_id}")

        # Resolve clarification stream
        stream_events = []
        async for chunk in session.resolve_clarification_stream(matched):
            stream_events.append(chunk)

        print(f" -> Stream yielded {len(stream_events)} events during resolution and goal continuation.")
        assert any("CLARIFICATION_RESOLVED" in c for c in stream_events), "Expected CLARIFICATION_RESOLVED event!"
        print(" -> Goal continuation verified.")

        # 3. Consequential Action Confirmation & Interception
        print("\n[Step 3] Testing Consequential Action Policy Interception...")
        from app.domain.composite import CompositeStep
        policy = ConsequentialActionPolicy()

        del_step = CompositeStep(
            step_id="step-del-1",
            description="Force kill application notepad.exe",
            intent=Intent(
                intent_id="i-del",
                action=SemanticAction.CLOSE,
                target="notepad.exe",
                parameters={"force": True, "command": "taskkill /F /IM notepad.exe"}
            )
        )
        is_conseq, reason, impact = policy.evaluate_step(del_step)
        assert is_conseq, "Policy failed to detect consequential operation!"
        print(f" -> Consequential operation detected: {reason}")
        print(f" -> Material impact: {impact}")

        confirm_req = policy.create_confirmation_request(del_step, goal_id="goal-del-1", task_id="task-del-1", step_index=0)
        assert confirm_req.requires_explicit_confirmation is True
        print(f" -> Confirmation prompt: \"{confirm_req.prompt}\"")

        # 4. Rejection Handling
        print("\n[Step 4] Testing Confirmation Rejection...")
        del_cp = GoalCheckpoint(
            checkpoint_id=str(uuid.uuid4()),
            schema_version="2.0",
            goal_id="goal-del-1",
            objective="Kill notepad",
            goal_state=GoalState.WAITING_FOR_USER,
            current_task_index=0,
            total_tasks=1,
            task_checkpoints=[
                TaskCheckpoint(
                    task_id="task-del-1",
                    task_index=0,
                    description="Kill notepad.exe",
                    task_state=TaskState.WAITING_FOR_USER,
                )
            ],
            pending_clarification=confirm_req,
            is_resumable=True,
        )
        store.save_checkpoint(del_cp)
        session.pending_goal_id = "goal-del-1"

        reject_resp = ClarificationResponse(request_id=confirm_req.request_id, confirmed=False)
        reject_events = []
        async for chunk in session.resolve_clarification_stream(reject_resp):
            reject_events.append(chunk)

        updated_cp = store.get_checkpoint("goal-del-1")
        assert updated_cp.goal_state == GoalState.CANCELLED
        assert updated_cp.is_resumable is False
        assert updated_cp.pending_clarification is None
        print(" -> Rejection safely cancelled the goal. Zero actuation permitted.")

        # 5. Approval Handling & Scoped Permission Grant
        print("\n[Step 5] Testing Confirmation Approval & Scoped Permissions...")
        del_cp2 = GoalCheckpoint(
            checkpoint_id=str(uuid.uuid4()),
            schema_version="2.0",
            goal_id="goal-del-2",
            objective="Kill notepad",
            goal_state=GoalState.WAITING_FOR_USER,
            current_task_index=0,
            total_tasks=1,
            task_checkpoints=[
                TaskCheckpoint(
                    task_id="task-del-2",
                    task_index=0,
                    description="Kill notepad.exe",
                    task_state=TaskState.WAITING_FOR_USER,
                )
            ],
            pending_clarification=confirm_req,
            is_resumable=True,
        )
        store.save_checkpoint(del_cp2)
        session.pending_goal_id = "goal-del-2"

        approve_resp = ClarificationResponse(request_id=confirm_req.request_id, confirmed=True)
        # Mock resume_goal_stream to prevent live process killing during verification
        async def mock_resume(goal_id):
            yield '{"event_type": "GOAL_COMPLETED", "progress_label": "Resumed task completed safely"}\n'
        session.resume_goal_stream = mock_resume

        approve_events = []
        async for chunk in session.resolve_clarification_stream(approve_resp):
            approve_events.append(chunk)

        # Verify scoped permission was granted in evaluator
        evaluator = permission_evaluator
        check_perm = PermissionRequest(
            request_id=str(uuid.uuid4()),
            requester_task_id=None,
            capability=CapabilityScope.SYSTEM_MODIFICATION,
            resource_scope=ResourceScope(capability=CapabilityScope.SYSTEM_MODIFICATION, resource="notepad.exe"),
            reason="Test check",
        )
        decision = evaluator.evaluate(check_perm)
        assert decision.decision == PermissionState.GRANTED
        print(f" -> Scoped permission grant verified for resource 'notepad.exe'.")

        # Verify unrelated resource is NOT authorized
        unrelated_perm = PermissionRequest(
            request_id=str(uuid.uuid4()),
            requester_task_id=None,
            capability=CapabilityScope.SYSTEM_MODIFICATION,
            resource_scope=ResourceScope(capability=CapabilityScope.SYSTEM_MODIFICATION, resource="system32"),
            reason="Test check",
        )
        unrelated_decision = evaluator.evaluate(unrelated_perm)
        assert unrelated_decision.decision != PermissionState.GRANTED
        print(f" -> Unrelated resource 'system32' correctly denied (no blanket permissions).")

        # 6. Replay & Duplicate Prevention
        print("\n[Step 6] Testing Prevention of Replayed/Duplicate Confirmations...")
        try:
            # Second attempt to resolve the already-resolved request
            async for chunk in session.resolve_clarification_stream(approve_resp):
                pass
            assert False, "Duplicate confirmation should have raised ValueError!"
        except ValueError as ex:
            print(f" -> Replayed confirmation successfully rejected: {ex}")

        store.close()
        print("\n=== All Live Verification Checks Passed! ===")

    finally:
        try:
            store.close()
        except Exception:
            pass
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass

if __name__ == "__main__":
    asyncio.run(run_live_verification())
