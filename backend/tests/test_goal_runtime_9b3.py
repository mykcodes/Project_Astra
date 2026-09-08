import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import uuid

from app.domain.goals import Goal, Task, TaskState, GoalState, Intent, FailureClass, SemanticAction, TargetType
from app.ai.orchestrator.runtime import GoalRuntime
from app.domain.events import ExecutionEventType
from app.tools.desktop.browser.browser_observation import BrowserObservation, BrowserElement
from app.domain.entities import Entity, EntityType

@pytest.fixture
def mock_goal():
    task1 = Task(
        task_id="t1",
        description="Navigate to YouTube",
        intents=[Intent(intent_id="i1", action=SemanticAction.NAVIGATE, capability_id="browser.navigate", parameters={"target": "youtube.com"})]
    )
    task2 = Task(
        task_id="t2",
        description="Search Baby",
        intents=[Intent(intent_id="i2", action=SemanticAction.SEARCH, capability_id="browser.search", parameters={"target": "Baby by Justin Bieber"})]
    )
    task3 = Task(
        task_id="t3",
        description="Click first video",
        intents=[Intent(intent_id="i3", action=SemanticAction.CLICK, capability_id="browser.click", target="first video", parameters={"action": "CLICK", "target": "first video"})]
    )
    
    return Goal(
        goal_id="g1",
        objective="Play Baby by Justin Bieber",
        tasks=[task1, task2, task3]
    )

@pytest.mark.asyncio
async def test_false_positive_click_fails_task():
    # Test that if a click returns success=True but verification is False, the task fails.
    task = Task(
        task_id="t_click",
        description="Click first video",
        intents=[Intent(intent_id="i_click", action=SemanticAction.CLICK, capability_id="browser.click", target="first video", parameters={"action": "CLICK", "target": "first video"})]
    )
    goal = Goal(goal_id="g_click", objective="Click it", tasks=[task])
    
    runtime = GoalRuntime(goal)
    
    with patch("app.ai.orchestrator.action_executor.action_executor.execute_intent") as mock_exec:
        # Action executor returns success=False because verification failed inside it
        mock_exec.return_value = {
            "success": False,
            "verified": False,
            "error": {"code": "CLICK_NO_EFFECT", "message": "Click executed but no resulting state change was observed."},
            "attempts": 1,
            "diagnostics": {}
        }
        
        events = []
        async for event in runtime.run():
            events.append(event)
            
        task_failed_events = [e for e in events if e.event_type == ExecutionEventType.TASK_FAILED]
        assert len(task_failed_events) == 1
        assert task.state == TaskState.FAILED
        assert goal.state == GoalState.FAILED

@pytest.mark.asyncio
async def test_stale_target_is_stripped():
    # If the LLM passes a stale 'ast-' ID, GoalRuntime should strip it and force semantic re-resolution
    task = Task(
        task_id="t_stale",
        description="Click stale target",
        intents=[Intent(intent_id="i_stale", action=SemanticAction.CLICK, capability_id="browser.click", target="ast-123-1", parameters={"action": "CLICK", "target": "ast-123-1"})]
    )
    goal = Goal(goal_id="g_stale", objective="Click stale", tasks=[task])
    
    runtime = GoalRuntime(goal)
    
    with patch("app.ai.orchestrator.action_executor.action_executor.execute_intent") as mock_exec:
        mock_exec.return_value = {"success": True, "verified": True}
        
        with patch.object(runtime, "_verify_goal", return_value=True):
            async for event in runtime.run():
                pass
            
            # Check what was passed to execute_intent
            called_intent = mock_exec.call_args[0][0]
            called_tool_args = mock_exec.call_args[0][1]
            assert "ast-" not in called_tool_args["target"]

@pytest.mark.asyncio
async def test_captcha_recovery_reobserves():
    # Test that a CAPTCHA triggers WAITING_FOR_USER, and then continues
    task = Task(
        task_id="t_cap",
        description="Navigate",
        intents=[Intent(intent_id="i_cap", action=SemanticAction.NAVIGATE, capability_id="browser.navigate", parameters={"target": "site.com"})]
    )
    goal = Goal(goal_id="g_cap", objective="Navigate with captcha", tasks=[task])
    
    runtime = GoalRuntime(goal)
    
    attempt = 0
    async def mock_execute(intent, tool_args, max_attempts=1):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            return {"success": False, "error": {"code": "HUMAN_VERIFICATION_REQUIRED"}}
        return {"success": True, "verified": True}
        
    with patch("app.ai.orchestrator.action_executor.action_executor.execute_intent", side_effect=mock_execute):
        with patch.object(runtime, "_check_wait_resolved", return_value=True):
            with patch.object(runtime, "_verify_goal", return_value=True):
                events = []
                async for event in runtime.run():
                    events.append(event)
                    
                wait_events = [e for e in events if e.event_type == ExecutionEventType.WAITING_FOR_USER]
                assert len(wait_events) == 1
                assert attempt == 1
                assert goal.state == GoalState.WAITING_FOR_USER

@pytest.mark.asyncio
async def test_end_to_end_goal_execution(mock_goal):
    # Verify the multi-step goal executes fully without stopping
    runtime = GoalRuntime(mock_goal)
    
    async def mock_execute(intent, tool_args, max_attempts=1):
        return {"success": True, "verified": True}
        
    with patch("app.ai.orchestrator.action_executor.action_executor.execute_intent", side_effect=mock_execute):
        with patch.object(runtime, "_verify_goal", return_value=True):
            events = []
            async for event in runtime.run():
                events.append(event)
                
            task_completed_events = [e for e in events if e.event_type == ExecutionEventType.TASK_COMPLETED]
            assert len(task_completed_events) == 3
            assert mock_goal.state == GoalState.COMPLETED
            assert mock_goal.is_complete == True
