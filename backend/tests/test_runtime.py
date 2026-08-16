import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from app.domain.goals import Goal, Task, Intent
from app.domain.events import ExecutionEventType
from app.ai.orchestrator.runtime import GoalRuntime

@pytest.fixture
def mock_action_executor():
    with patch('app.ai.orchestrator.runtime.action_executor') as mock_executor:
        mock_executor.execute_tool_call = AsyncMock()
        yield mock_executor

def create_mock_goal(tasks_count: int = 2) -> Goal:
    tasks = []
    for i in range(tasks_count):
        intent = Intent(intent_id=f"intent_{i}", capability_id=f"cap_{i}", parameters={})
        task = Task(task_id=f"task_{i}", description=f"Mock Task {i}", intents=[intent])
        tasks.append(task)
    return Goal(goal_id="goal_1", objective="Test Objective", tasks=tasks)

@pytest.mark.asyncio
async def test_task_lifecycle(mock_action_executor):
    mock_action_executor.execute_tool_call.return_value = {"success": True, "verified": True}
    goal = create_mock_goal(1)
    runtime = GoalRuntime(goal)
    
    events = []
    async for event in runtime.run():
        events.append(event)
        
    event_types = [e.event_type for e in events]
    assert ExecutionEventType.GOAL_ACCEPTED in event_types
    assert ExecutionEventType.PLAN_CREATED in event_types
    assert ExecutionEventType.TASK_STARTED in event_types
    assert ExecutionEventType.TASK_PROGRESS in event_types
    assert ExecutionEventType.VERIFICATION_STARTED in event_types
    assert ExecutionEventType.VERIFICATION_COMPLETED in event_types
    assert ExecutionEventType.TASK_COMPLETED in event_types
    assert ExecutionEventType.GOAL_COMPLETED in event_types
    assert goal.is_complete is True

@pytest.mark.asyncio
async def test_goal_contains_multiple_tasks(mock_action_executor):
    mock_action_executor.execute_tool_call.return_value = {"success": True, "verified": True}
    goal = create_mock_goal(3)
    runtime = GoalRuntime(goal)
    
    events = [e async for e in runtime.run()]
    
    started_tasks = [e for e in events if e.event_type == ExecutionEventType.TASK_STARTED]
    assert len(started_tasks) == 3
    
    completed_tasks = [e for e in events if e.event_type == ExecutionEventType.TASK_COMPLETED]
    assert len(completed_tasks) == 3
    
    assert events[-1].event_type == ExecutionEventType.GOAL_COMPLETED
    assert mock_action_executor.execute_tool_call.call_count == 3

@pytest.mark.asyncio
async def test_task_continues_after_previous_task(mock_action_executor):
    mock_action_executor.execute_tool_call.return_value = {"success": True, "verified": True}
    goal = create_mock_goal(2)
    runtime = GoalRuntime(goal)
    
    events = [e async for e in runtime.run()]
    
    task0_completed_idx = next(i for i, e in enumerate(events) if e.event_type == ExecutionEventType.TASK_COMPLETED and e.task_id == "task_0")
    task1_started_idx = next(i for i, e in enumerate(events) if e.event_type == ExecutionEventType.TASK_STARTED and e.task_id == "task_1")
    
    assert task0_completed_idx < task1_started_idx

@pytest.mark.asyncio
async def test_verification_failure_triggers_recovery(mock_action_executor):
    # Simulating failure in action_executor (it handles recovery inside, but returns false if totally failed)
    mock_action_executor.execute_tool_call.return_value = {"success": False, "verified": False}
    goal = create_mock_goal(1)
    runtime = GoalRuntime(goal)
    
    events = [e async for e in runtime.run()]
    
    event_types = [e.event_type for e in events]
    assert ExecutionEventType.RECOVERY_STARTED in event_types
    assert ExecutionEventType.RECOVERY_COMPLETED in event_types
    assert ExecutionEventType.TASK_FAILED in event_types
    assert ExecutionEventType.GOAL_FAILED in event_types
    assert goal.is_complete is False

@pytest.mark.asyncio
async def test_bounded_goal_failure(mock_action_executor):
    mock_action_executor.execute_tool_call.return_value = {"success": False, "verified": False}
    goal = create_mock_goal(2)
    runtime = GoalRuntime(goal)
    
    events = [e async for e in runtime.run()]
    
    # Check that task 1 never starts because task 0 failed
    task1_started = any(e.task_id == "task_1" for e in events)
    assert not task1_started
    
    assert events[-1].event_type == ExecutionEventType.GOAL_FAILED

@pytest.mark.asyncio
async def test_progress_event_order(mock_action_executor):
    mock_action_executor.execute_tool_call.return_value = {"success": True, "verified": True}
    goal = create_mock_goal(1)
    runtime = GoalRuntime(goal)
    
    events = [e async for e in runtime.run()]
    types = [e.event_type for e in events]
    
    expected_order = [
        ExecutionEventType.GOAL_ACCEPTED,
        ExecutionEventType.PLAN_CREATED,
        ExecutionEventType.TASK_STARTED,
        ExecutionEventType.TASK_PROGRESS,
        ExecutionEventType.VERIFICATION_STARTED,
        ExecutionEventType.VERIFICATION_COMPLETED,
        ExecutionEventType.TASK_COMPLETED,
        ExecutionEventType.GOAL_COMPLETED
    ]
    
    assert types == expected_order

@pytest.mark.asyncio
async def test_execution_event_serialization(mock_action_executor):
    mock_action_executor.execute_tool_call.return_value = {"success": True, "verified": True}
    goal = create_mock_goal(1)
    runtime = GoalRuntime(goal)
    
    events = [e async for e in runtime.run()]
    for e in events:
        json_str = e.to_sse_json()
        assert "event_type" in json_str
        assert "execution_id" in json_str
        assert "timestamp" in json_str
