import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import httpx
import jsonschema

from app.domain.goals import Intent, SemanticAction, TargetType, TargetOrdinal, Goal, Task, VerificationResult, TriState
from app.ai.orchestrator.action_executor import ActionExecutor
from app.ai.orchestrator.runtime import GoalRuntime
from app.tools.desktop.browser.browser_executor import normalize_browser_url
from app.tools.registry import registry
from app.ai.providers.types import ToolResult, AIRequest, AIMessage, MessageRole
from app.ai.runtimes.openai import OpenAICompatibleRuntime
from app.ai.providers.errors import ProviderUnavailableError

# 1. URL Normalization Tests
def test_normalize_browser_url_common_sites():
    assert normalize_browser_url("YouTube") == "https://www.youtube.com"
    assert normalize_browser_url("youtube") == "https://www.youtube.com"
    assert normalize_browser_url("google") == "https://www.google.com"
    assert normalize_browser_url("github") == "https://github.com"
    assert normalize_browser_url("reddit") == "https://www.reddit.com"
    assert normalize_browser_url("amazon") == "https://www.amazon.com"
    assert normalize_browser_url("chatgpt") == "https://chatgpt.com"

def test_normalize_browser_url_domains():
    assert normalize_browser_url("youtube.com") == "https://youtube.com"
    assert normalize_browser_url("news.ycombinator.com") == "https://news.ycombinator.com"
    assert normalize_browser_url("https://already.qualified/path") == "https://already.qualified/path"
    assert normalize_browser_url("http://insecure.test") == "http://insecure.test"

# 2. ActionExecutor Argument Normalization against Real Tool Schemas
@pytest.mark.asyncio
async def test_action_executor_normalizes_browser_navigate_arguments():
    ae = ActionExecutor()
    intent = Intent(
        intent_id="i_nav",
        action=SemanticAction.NAVIGATE,
        capability_id="browser.navigate",
        target="YouTube",
        target_type=TargetType.WEBSITE,
    )
    raw_args = {
        "action": "NAVIGATE",
        "target": "YouTube",
        "target_type": "WEBSITE",
        "ordinal": "NONE",
        "query": None,
        "browser": "brave",
        "page_context": None,
        "browser_name": "brave",
    }
    
    # Intercept tool.execute to verify arguments passed adhere strictly to schema
    browser_tool = registry.get("execute_browser_intent")
    with patch.object(browser_tool, "execute", new_callable=AsyncMock) as mock_tool_exec:
        mock_tool_exec.return_value = {
            "success": True,
            "action_executed": True,
            "verified": True,
            "message": "Navigated successfully"
        }
        
        res = await ae.execute_intent(intent, raw_args, max_attempts=1)
        
        # Verify schema validation passed without throwing ToolValidationError
        assert res.get("success") is True
        mock_tool_exec.assert_called_once()
        call_kwargs = mock_tool_exec.call_args[1]
        
        # Must conform strictly to ExecuteBrowserIntentTool.schema
        jsonschema.validate(instance=call_kwargs, schema=browser_tool.schema)
        assert call_kwargs["intent"] == "NAVIGATE"
        assert call_kwargs["target"] == "YouTube"
        assert call_kwargs["browser_name"] == "brave"
        assert "action" not in call_kwargs

@pytest.mark.asyncio
async def test_action_executor_normalizes_browser_search_arguments():
    ae = ActionExecutor()
    intent = Intent(
        intent_id="i_search",
        action=SemanticAction.SEARCH,
        capability_id="browser.search",
        target="search query",
        query="astra ai",
    )
    raw_args = {
        "action": "SEARCH",
        "query": "astra ai",
        "target": "search query",
        "browser": "chrome",
    }
    
    browser_tool = registry.get("execute_browser_intent")
    with patch.object(browser_tool, "execute", new_callable=AsyncMock) as mock_tool_exec:
        mock_tool_exec.return_value = {"success": True, "action_executed": True, "verified": True}
        
        res = await ae.execute_intent(intent, raw_args, max_attempts=1)
        
        assert res.get("success") is True
        mock_tool_exec.assert_called_once()
        call_kwargs = mock_tool_exec.call_args[1]
        
        jsonschema.validate(instance=call_kwargs, schema=browser_tool.schema)
        assert call_kwargs["intent"] == "SEARCH"
        assert call_kwargs["target"] == "astra ai"
        assert call_kwargs["browser_name"] == "chrome"

@pytest.mark.asyncio
async def test_action_executor_normalizes_desktop_application_arguments():
    ae = ActionExecutor()
    intent = Intent(
        intent_id="i_app",
        action=SemanticAction.OPEN,
        capability_id="desktop.open_application",
        target="Notepad",
    )
    raw_args = {
        "action": "OPEN",
        "target": "Notepad",
        "ordinal": "NONE",
        "query": None,
    }
    
    app_tool = registry.get("execute_application_intent")
    with patch.object(app_tool, "execute", new_callable=AsyncMock) as mock_tool_exec:
        mock_tool_exec.return_value = {"success": True, "action_executed": True, "canonical_name": "notepad"}
        with patch.object(ae.verifier, "verify_interaction") as mock_verify:
            mock_verify.return_value = VerificationResult(
                verified=TriState.TRUE,
                verification_type="OPEN",
                expected_state="Notepad",
                actual_state="Notepad"
            )
            
            res = await ae.execute_intent(intent, raw_args, max_attempts=1)
            
            assert res.get("success") is True
            mock_tool_exec.assert_called_once()
            call_kwargs = mock_tool_exec.call_args[1]
            
            jsonschema.validate(instance=call_kwargs, schema=app_tool.schema)
            assert call_kwargs["intent"] == "OPEN"
            assert call_kwargs["application"] == "Notepad"
            assert "action" not in call_kwargs

# 3. GoalRuntime End-to-End Formatting for Browser Actions
@pytest.mark.asyncio
async def test_goal_runtime_formats_browser_intent_correctly():
    intent = Intent(
        intent_id="i_rt",
        action=SemanticAction.NAVIGATE,
        capability_id="browser.navigate",
        target="YouTube",
        target_type=TargetType.WEBSITE,
        browser="brave",
        parameters={
            "action": "NAVIGATE",
            "target": "YouTube",
            "target_type": "WEBSITE",
            "ordinal": "NONE",
            "query": None,
            "browser": "brave",
            "page_context": None,
        }
    )
    goal = Goal(
        goal_id="g_nav",
        objective="Navigate to YouTube",
        tasks=[Task(task_id="t1", description="Open YouTube", intents=[intent])]
    )
    
    runtime = GoalRuntime(goal)
    
    with patch("app.ai.orchestrator.runtime.action_executor.execute_intent", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {
            "success": True,
            "verified": TriState.TRUE,
            "action_executed": True,
            "verification_result": VerificationResult(
                verified=TriState.TRUE,
                verification_type="NAVIGATE",
                expected_state="YouTube",
                actual_state="Verified by provider"
            )
        }
        
        async for event in runtime.run():
            pass
            
        mock_exec.assert_called_once()
        executed_intent, tool_args = mock_exec.call_args[0][0], mock_exec.call_args[0][1]
        
        assert tool_args["intent"] == "NAVIGATE"
        assert tool_args["target"] == "YouTube"
        assert tool_args["browser_name"] == "brave"
        assert "action" not in tool_args

# 4. OpenAICompatibleRuntime Graceful Error Handling without Terminal Tracebacks
@pytest.mark.asyncio
async def test_openai_runtime_handles_connect_error_gracefully():
    runtime = OpenAICompatibleRuntime(base_url="http://127.0.0.1:9999/v1")
    req = AIRequest(messages=[AIMessage(role=MessageRole.USER, content="hi")])
    
    with patch.object(runtime.client, "post", side_effect=httpx.ConnectError("Connection refused")):
        with pytest.raises(ProviderUnavailableError) as exc_info:
            await runtime.generate(req, "qwen", 100, 0.7, "groq")
        assert "Local runtime unreachable" in str(exc_info.value)
    
    await runtime.close()

# 5. Direct ToolExecutor Sanitization for Optional None Arguments (The exact terminal bug)
@pytest.mark.asyncio
async def test_tool_executor_handles_none_for_optional_arguments():
    from app.tools.executor import executor
    from app.tools.registry import registry
    from app.ai.providers.types import ToolCall
    
    browser_tool = registry.get("execute_browser_intent")
    with patch.object(browser_tool, "execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {"success": True, "action_executed": True, "message": "Success"}
        
        # This is the exact payload that previously crashed in jsonschema:
        # jsonschema.exceptions.ValidationError: None is not of type 'string'
        tool_call = ToolCall(
            id="test_null_arg",
            name="execute_browser_intent",
            arguments={"intent": "NAVIGATE", "target": "YouTube", "browser_name": None}
        )
        
        res = await executor.execute(tool_call)
        assert res.success is True
        mock_exec.assert_called_once()
        assert res.error is None

# 6. ActionExecutor and Runtime Guarantee Against None Propagation
@pytest.mark.asyncio
async def test_action_executor_strips_none_browser_name():
    ae = ActionExecutor()
    intent = Intent(
        intent_id="i_nav_none",
        action=SemanticAction.OPEN,
        capability_id="browser.navigate",
        target="YouTube",
        target_type=TargetType.WEBSITE,
    )
    raw_args = {
        "intent": "NAVIGATE",
        "target": "YouTube",
        "browser_name": None,
    }
    
    browser_tool = registry.get("execute_browser_intent")
    with patch.object(browser_tool, "execute", new_callable=AsyncMock) as mock_tool_exec:
        mock_tool_exec.return_value = {"success": True, "action_executed": True, "verified": True}
        
        res = await ae.execute_intent(intent, raw_args, max_attempts=1)
        assert res.get("success") is True
        mock_tool_exec.assert_called_once()
        call_kwargs = mock_tool_exec.call_args[1]
        assert "browser_name" not in call_kwargs or call_kwargs["browser_name"] is None

@pytest.mark.asyncio
async def test_goal_runtime_never_emits_none_browser_name():
    intent = Intent(
        intent_id="i_rt_none",
        action=SemanticAction.OPEN,
        capability_id="browser.navigate",
        target="YouTube",
        target_type=TargetType.WEBSITE,
        browser=None,
        parameters={
            "action": "OPEN",
            "target": "YouTube",
            "target_type": "WEBSITE",
            "browser": None,
        }
    )
    goal = Goal(
        goal_id="g_nav_none",
        objective="Open YouTube without browser specified",
        tasks=[Task(task_id="t1", description="Open YouTube", intents=[intent])]
    )
    
    runtime = GoalRuntime(goal)
    
    with patch("app.ai.orchestrator.runtime.action_executor.execute_intent", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {
            "success": True,
            "verified": TriState.TRUE,
            "action_executed": True,
            "verification_result": VerificationResult(
                verified=TriState.TRUE,
                verification_type="NAVIGATE",
                expected_state="YouTube",
                actual_state="Verified by provider"
            )
        }
        
        async for event in runtime.run():
            pass
            
        mock_exec.assert_called_once()
        executed_intent, tool_args = mock_exec.call_args[0][0], mock_exec.call_args[0][1]
        
        assert "browser_name" not in tool_args
        assert tool_args == {"intent": "NAVIGATE", "target": "YouTube"}
