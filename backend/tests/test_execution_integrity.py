import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from app.domain.goals import Goal, Task, Intent, VerificationResult, FailureClass
from app.domain.events import ExecutionEventType
from app.ai.orchestrator.runtime import GoalRuntime
from app.ai.orchestrator.action_executor import action_executor
from app.ai.providers.types import ToolCall
from app.tools.executor import executor
from app.tools.desktop.browser.browser_provider import browser_provider

# Test 8: GoalRuntime/session execution-ID propagation
def test_execution_id_propagation():
    goal = Goal(goal_id="test_id", objective="Test", tasks=[])
    runtime = GoalRuntime(goal)
    assert runtime.execution_id is not None
    assert runtime.execution_id == runtime.context.execution_id

# Test 3: Successful tool execution followed by successful verification
@pytest.mark.asyncio
async def test_successful_execution_and_verification():
    intent = Intent(intent_id="i1", action="NAVIGATE", capability_id="browser.navigate", parameters={"target": "youtube.com"})
    
    with patch('app.tools.executor.executor.execute', new_callable=AsyncMock) as mock_exec:
        from app.ai.providers.types import ToolResult
        # executor completes successfully and returns verified: True
        result_json = '{"success": true, "verified": true, "observation_id": "obs_1"}'
        mock_exec.return_value = ToolResult(tool_call_id="1", name="browser.navigate", success=True, result=result_json)
        
        result = await action_executor.execute_intent(intent, tool_args={"target": "youtube.com"}, max_attempts=1)
        
        assert result["success"] is True
        assert result["verified"] is True
        assert result["action_executed"] is True

# Test 4 & 10: Successful tool execution followed by verification failure
@pytest.mark.asyncio
async def test_successful_execution_verification_failure():
    intent = Intent(intent_id="i2", action="NAVIGATE", capability_id="browser.navigate", parameters={"target": "https://www.google.com"})
    
    with patch('app.tools.executor.executor.execute', new_callable=AsyncMock) as mock_exec:
        from app.ai.providers.types import ToolResult
        # executor completes successfully but provider returns verified: False
        result_json = '{"success": true, "verified": false, "message": "Navigated"}'
        mock_exec.return_value = ToolResult(tool_call_id="2", name="browser.navigate", success=True, result=result_json)
        
        result = await action_executor.execute_intent(intent, tool_args={"target": "https://www.google.com"}, max_attempts=1)
        
        assert result["success"] is False
        assert result.get("verification_result").verified is False
        assert result["action_executed"] is True # This proves TOOL_EXECUTION_COMPLETED + verification failure != action not executed
        assert getattr(result.get("verification_result").failure_code, "name", "") == "VERIFICATION_FAILED"

# Test 5 & 12: Successful tool execution followed by result-publication failure
@pytest.mark.asyncio
async def test_successful_execution_result_publication_failure():
    intent = Intent(intent_id="i3", action="CONTINUE", capability_id="browser.status", parameters={})
    
    with patch('app.tools.executor.executor.execute', new_callable=AsyncMock) as mock_exec:
        from app.ai.providers.types import ToolResult
        # executor completes successfully but returns invalid JSON
        mock_exec.return_value = ToolResult(tool_call_id="3", name="browser.status", success=True, result="This is not JSON")
        
        result = await action_executor.execute_intent(intent, tool_args={}, max_attempts=1)
        
        assert result["success"] is False
        assert result["action_executed"] is True
        assert result["error"]["code"] == "RESULT_PUBLICATION_ERROR"

# Test 1 & 16: Successful browser navigation
@pytest.mark.asyncio
async def test_successful_browser_navigation():
    from app.tools.desktop.browser.browser_provider import browser_provider
    from app.tools.desktop.browser.browser_executor import browser_executor
    
    with patch.object(browser_executor, 'navigate', new_callable=AsyncMock) as mock_nav, \
         patch.object(browser_provider, 'observe', new_callable=AsyncMock) as mock_obs:
         
         mock_nav.return_value = {"success": True, "message": "Navigated"}
         from app.tools.desktop.browser.browser_observation import BrowserObservation
         obs = BrowserObservation(observation_id="obs_1", url="https://www.google.com/", title="Google")
         mock_obs.return_value = {"success": True, "observation": obs}
         
         result = await browser_provider.execute_intent("NAVIGATE", "https://www.google.com")
         assert result["success"] is True
         assert result["verified"] is True

# Test 18: Browser new-tab behavior
@pytest.mark.asyncio
async def test_browser_new_tab_behavior():
    from app.tools.desktop.browser.browser_provider import browser_provider
    from app.tools.desktop.browser.browser_executor import browser_executor
    
    with patch.object(browser_executor, 'navigate', new_callable=AsyncMock) as mock_nav, \
         patch.object(browser_provider, 'observe', new_callable=AsyncMock) as mock_obs:
         
         mock_nav.return_value = {"success": True, "message": "Navigated"}
         from app.tools.desktop.browser.browser_observation import BrowserObservation
         obs = BrowserObservation(observation_id="obs_2", url="https://www.youtube.com/", title="YouTube")
         mock_obs.return_value = {"success": True, "observation": obs}
         
         result = await browser_provider.execute_intent("NEW_TAB", "https://www.youtube.com")
         assert result["success"] is True
         assert result["verified"] is True
         mock_nav.assert_called_once_with("https://www.youtube.com", new_tab=True)
