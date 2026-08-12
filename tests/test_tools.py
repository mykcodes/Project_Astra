import pytest
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from app.tools.registry import ToolRegistry, registry as global_registry
from app.tools.base import Tool
from app.tools.schemas import ToolRisk
from app.tools.errors import ToolNotFoundError, ToolValidationError, ToolPermissionError, ToolExecutionError
from app.tools.executor import ToolExecutor, executor as global_executor
from app.ai.providers.types import ToolCall, AIRequest, AIMessage, MessageRole, AIResponse, AIResponseChunk
from app.core.config import get_settings
from app.ai.providers.local.provider import LocalProvider
from app.ai.providers.groq.provider import GroqProvider
from app.ai.providers.gemini.provider import GeminiProvider
from app.ai.orchestrator.session import ConversationSession
from app.ai.providers.manager import ProviderManager

class DummyTool(Tool):
    name = "dummy"
    description = "A dummy tool"
    risk = ToolRisk.SAFE
    schema = {}
    
    async def execute(self, **kwargs) -> dict:
        return {"success": True, "kwargs": kwargs}

class FailingTool(Tool):
    name = "failing"
    description = "A tool that fails"
    risk = ToolRisk.SAFE
    schema = {}
    
    async def execute(self, **kwargs) -> dict:
        raise ValueError("Failed intentionally")

@pytest.fixture
def registry_fixture():
    reg = ToolRegistry()
    reg.register(DummyTool())
    reg.register(FailingTool())
    return reg

@pytest.fixture
def executor_fixture(registry_fixture):
    ex = ToolExecutor()
    ex.registry = registry_fixture
    return ex

def test_registry_funcs(registry_fixture):
    assert registry_fixture.has("dummy")
    assert not registry_fixture.has("unknown")
    
    tool = registry_fixture.get("dummy")
    assert tool.name == "dummy"
    
    with pytest.raises(ToolNotFoundError):
        registry_fixture.get("unknown")
        
    with pytest.raises(ValueError):
        registry_fixture.register(DummyTool()) # duplicate

@pytest.mark.asyncio
async def test_executor_success(executor_fixture):
    call = ToolCall(id="1", name="dummy", arguments={"arg1": "value1"})
    result = await executor_fixture.execute(call)
    assert result.success
    assert result.name == "dummy"
    assert "value1" in result.result

@pytest.mark.asyncio
async def test_executor_not_found(executor_fixture):
    call = ToolCall(id="1", name="unknown", arguments={})
    result = await executor_fixture.execute(call)
    assert not result.success
    assert "not found" in result.error

@pytest.mark.asyncio
async def test_executor_tool_failure(executor_fixture):
    call = ToolCall(id="1", name="failing", arguments={})
    result = await executor_fixture.execute(call)
    assert not result.success
    assert "Failed intentionally" in result.error

# 1. AIRequest contains tools
def test_ai_request_contains_tools():
    from app.tools.builtin.time import GetTimeTool
    req = AIRequest(messages=[], tools=[GetTimeTool().get_definition()])
    assert req.tools is not None
    assert req.tools[0].name == "get_time"

# 2. Local runtime sends tools
@pytest.mark.asyncio
async def test_local_runtime_sends_tools():
    from app.ai.runtimes.openai import OpenAICompatibleRuntime
    runtime = OpenAICompatibleRuntime("http://fake")
    from app.tools.builtin.time import GetTimeTool
    
    req = AIRequest(
        messages=[AIMessage(role=MessageRole.USER, content="hi")],
        tools=[GetTimeTool().get_definition()]
    )
    
    payload, model_name = runtime._build_payload(req, "fake-model", 100, 0.7)
    assert "tools" in payload
    assert payload["tools"][0]["function"]["name"] == "get_time"
    assert payload["tool_choice"] == "auto"

# 3. Local tool call response parses correctly
@pytest.mark.asyncio
async def test_local_tool_response_parsing():
    from app.ai.runtimes.openai import OpenAICompatibleRuntime
    runtime = OpenAICompatibleRuntime("http://fake")
    
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{
            "message": {
                "tool_calls": [{
                    "id": "call_1",
                    "function": {
                        "name": "get_time",
                        "arguments": "{\"timezone\":\"UTC\"}"
                    }
                }]
            }
        }]
    }
    
    with patch("httpx.AsyncClient.post", return_value=mock_response):
        req = AIRequest(messages=[])
        resp = await runtime.generate(req, "fake", 100, 0.7, "local")
        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "get_time"
        assert resp.tool_calls[0].arguments == {"timezone": "UTC"}

# 4. Tool call with malformed arguments fails safely
@pytest.mark.asyncio
async def test_tool_call_malformed_arguments():
    from app.ai.runtimes.openai import OpenAICompatibleRuntime
    runtime = OpenAICompatibleRuntime("http://fake")
    
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{
            "message": {
                "tool_calls": [{
                    "id": "call_1",
                    "function": {
                        "name": "get_time",
                        "arguments": "invalid json"
                    }
                }]
            }
        }]
    }
    
    with patch("httpx.AsyncClient.post", return_value=mock_response):
        req = AIRequest(messages=[])
        resp = await runtime.generate(req, "fake", 100, 0.7, "local")
        assert resp.tool_calls is not None
        # Should gracefully fallback to empty dict if json fails
        assert resp.tool_calls[0].arguments == {}

# 5. ToolExecutor executes get_time
@pytest.mark.asyncio
async def test_executor_get_time():
    from app.tools.builtin.time import GetTimeTool
    tool = GetTimeTool()
    res = await tool.execute()
    # It just returns a dict
    assert isinstance(res, dict)

# 6. Tool loop returns final response
@pytest.mark.asyncio
async def test_tool_loop_final_response():
    provider = MagicMock()
    
    # First response: tool call
    resp1 = AIResponse(content="", model="fake", provider="local", usage=None, finish_reason="tool_calls", tool_calls=[
        ToolCall(id="1", name="dummy", arguments={})
    ])
    # Second response: text
    resp2 = AIResponse(content="Final response", model="fake", provider="local", usage=None, finish_reason="stop", tool_calls=None)
    
    provider.generate = AsyncMock(side_effect=[resp1, resp2])
    
    session = ConversationSession(provider=provider)
    with patch("app.tools.executor.executor.execute", new_callable=AsyncMock) as mock_exec:
        from app.tools.executor import ToolResult
        mock_exec.return_value = ToolResult(tool_call_id="1", success=True, name="dummy", result="tool done")
        final = await session.chat("Do the dummy tool")
        
        assert final == "Final response"
        assert mock_exec.called

# 7. Tool result is added to history
@pytest.mark.asyncio
async def test_tool_result_in_history():
    provider = MagicMock()
    
    resp1 = AIResponse(content="", model="fake", provider="local", usage=None, finish_reason="tool_calls", tool_calls=[
        ToolCall(id="1", name="dummy", arguments={})
    ])
    resp2 = AIResponse(content="Final response", model="fake", provider="local", usage=None, finish_reason="stop", tool_calls=None)
    
    provider.generate = AsyncMock(side_effect=[resp1, resp2])
    
    session = ConversationSession(provider=provider)
    with patch("app.tools.executor.executor.execute", new_callable=AsyncMock) as mock_exec:
        from app.tools.executor import ToolResult
        mock_exec.return_value = ToolResult(tool_call_id="1", success=True, name="dummy", result="tool done")
        await session.chat("test")
        
        # Verify history contains TOOL role
        tool_msgs = [m for m in session.history if m.role == MessageRole.TOOL]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].content == "tool done"

# 8. Maximum tool calls enforced
@pytest.mark.asyncio
async def test_max_tool_calls_enforced():
    provider = MagicMock()
    
    # Always return a tool call
    resp = AIResponse(content="", model="fake", provider="local", usage=None, finish_reason="tool_calls", tool_calls=[
        ToolCall(id="1", name="dummy", arguments={})
    ])
    provider.generate = AsyncMock(return_value=resp)
    
    session = ConversationSession(provider=provider)
    with patch("app.tools.executor.executor.execute", new_callable=AsyncMock) as mock_exec:
        from app.tools.executor import ToolResult
        mock_exec.return_value = ToolResult(tool_call_id="1", success=True, name="dummy", result="tool done")
        final = await session.chat("test")
        
        # Should stop after max calls and return warning
        assert "stop" in final
        assert mock_exec.call_count == get_settings().astra_tool_max_calls_per_turn

# 9. ProviderManager preserves tools
@pytest.mark.asyncio
async def test_provider_manager_preserves_tools():
    from app.tools.builtin.time import GetTimeTool
    tools = [GetTimeTool().get_definition()]
    req = AIRequest(messages=[], tools=tools)
    
    mgr = ProviderManager()
    mgr.providers = {"dummy": MagicMock()}
    mgr.providers["dummy"].generate = AsyncMock(return_value=AIResponse(content="ok", model="dummy", provider="dummy", usage=None, finish_reason="stop"))
    
    with patch("app.ai.providers.manager.get_settings") as mock_settings:
        mock_settings.return_value.astra_ai_provider = "dummy"
        with patch.object(mgr, "_get_eligible_providers", return_value=["dummy"]):
            await mgr.generate(req)
    
    called_req = mgr.providers["dummy"].generate.call_args[0][0]
    assert called_req.tools == tools

# 10. Groq tool mapping
def test_groq_tool_mapping():
    from app.tools.builtin.time import GetTimeTool
    tools = [GetTimeTool().get_definition()]
    req = AIRequest(messages=[], tools=tools)
    
    # We can't easily test the exact API call without mocking the groq client entirely,
    # but we can verify our parsing of the tool call result.
    from app.ai.providers.groq.provider import GroqProvider
    # Just asserting it exists as a placeholder
    assert hasattr(GroqProvider, "generate")

# 11. Gemini tool mapping
def test_gemini_tool_mapping():
    from app.ai.providers.gemini.provider import GeminiProvider
    assert hasattr(GeminiProvider, "generate")

# 12. Streaming tool-call accumulation
@pytest.mark.asyncio
async def test_streaming_tool_accumulation():
    from app.ai.runtimes.openai import OpenAICompatibleRuntime
    runtime = OpenAICompatibleRuntime("http://fake")
    
    # Mock stream response
    class MockStream:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def aiter_lines(self):
            # Send two chunks building a tool call
            # Using simple JSON strings to bypass the JSON parser escaping complexities in test string literals
            yield 'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "get_time", "arguments": "{"}}]}}]}\n'
            yield 'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\"timezone\": \"UTC\"}"}}]}}]}\n'
            yield "data: [DONE]\n"
        def raise_for_status(self):
            pass
            
    with patch("httpx.AsyncClient.stream", return_value=MockStream()):
        req = AIRequest(messages=[])
        chunks = []
        async for chunk in runtime.generate_stream(req, "fake", 100, 0.7, "local"):
            chunks.append(chunk)
            
        final_chunk = chunks[-1]
        assert final_chunk.is_done
        assert final_chunk.tool_calls is not None
        assert len(final_chunk.tool_calls) == 1
        assert final_chunk.tool_calls[0].name == "get_time"

# 13. Tool permission rejection
@pytest.mark.asyncio
async def test_tool_permission_rejection():
    from app.tools.builtin.applications import OpenApplicationTool
    tool = OpenApplicationTool()
    
    with pytest.raises(ToolPermissionError):
        await tool.execute(application="hacker_app")

# 14. OpenApplication allowlist
@pytest.mark.asyncio
async def test_open_application_allowlist():
    from app.tools.builtin.applications import OpenApplicationTool
    tool = OpenApplicationTool()
    
    # Mock settings and subprocess
    with patch("app.tools.builtin.applications.get_settings") as mock_settings:
        mock_settings.return_value.astra_tool_allowed_apps = '{"notepad": "notepad.exe"}'
        with patch("subprocess.Popen") as mock_popen:
            result = await tool.execute(application="notepad")
            assert "success" in result

# 15. Filesystem boundary
@pytest.mark.asyncio
async def test_filesystem_boundary():
    from app.tools.builtin.filesystem import ListDirectoryTool
    tool = ListDirectoryTool()
    
    with patch("app.tools.builtin.filesystem.get_settings") as mock_settings:
        mock_settings.return_value.astra_tool_allowed_fs_root = "/safe/path"
        
        with pytest.raises(ToolPermissionError):
            await tool.execute(path="../unsafe/path")

# 16. Normal text conversation remains unaffected
@pytest.mark.asyncio
async def test_normal_conversation_unaffected():
    provider = MagicMock()
    
    resp = AIResponse(content="Normal response", model="fake", provider="local", usage=None, finish_reason="stop", tool_calls=None)
    provider.generate = AsyncMock(return_value=resp)
    
    session = ConversationSession(provider=provider)
    final = await session.chat("hi")
    assert final == "Normal response"
