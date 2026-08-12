import pytest
import asyncio
import json
from pathlib import Path
from jsonschema.exceptions import ValidationError

from app.tools.base import Tool
from app.tools.schemas import ToolRisk
from app.tools.errors import ToolNotFoundError, ToolValidationError, ToolExecutionError, ToolPermissionError, ToolTimeoutError
from app.tools.registry import ToolRegistry
from app.tools.executor import ToolExecutor
from app.ai.providers.types import ToolCall
from app.tools.builtin.applications import OpenUrlTool, OpenApplicationTool
from app.tools.builtin.filesystem import resolve_and_verify_path

class DummyTool(Tool):
    name = "dummy_tool"
    description = "A dummy tool"
    risk = ToolRisk.SAFE
    schema = {
        "type": "object",
        "properties": {
            "param": {"type": "string"}
        },
        "required": ["param"]
    }
    async def execute(self, param: str, **kwargs) -> dict:
        return {"success": True, "echo": param}

class BlockedTool(Tool):
    name = "blocked_tool"
    description = "A blocked tool"
    risk = ToolRisk.BLOCKED
    schema = {"type": "object", "properties": {}}
    async def execute(self, **kwargs):
        return {"success": True}

class SlowTool(Tool):
    name = "slow_tool"
    description = "A slow tool"
    risk = ToolRisk.SAFE
    schema = {"type": "object", "properties": {}}
    async def execute(self, **kwargs):
        await asyncio.sleep(0.5)
        return {"success": True}

class OversizedTool(Tool):
    name = "oversize_tool"
    description = "Returns a large string"
    risk = ToolRisk.SAFE
    schema = {"type": "object", "properties": {}}
    async def execute(self, **kwargs):
        return {"success": True, "data": "A" * 20000}

@pytest.fixture
def registry():
    r = ToolRegistry()
    r.register(DummyTool())
    r.register(BlockedTool())
    r.register(SlowTool())
    r.register(OversizedTool())
    return r

@pytest.fixture
def executor(registry):
    exe = ToolExecutor()
    exe.registry = registry
    return exe

@pytest.mark.asyncio
async def test_registry_functions(registry):
    assert registry.has("dummy_tool")
    assert not registry.has("nonexistent")
    
    with pytest.raises(ToolNotFoundError):
        registry.get("nonexistent")
        
    with pytest.raises(ValueError):
        registry.register(DummyTool())

@pytest.mark.asyncio
async def test_executor_validation(executor):
    # Valid arguments
    res = await executor.execute(ToolCall(id="1", name="dummy_tool", arguments={"param": "test"}))
    assert res.success is True
    assert "test" in res.result
    
    # Missing required parameter
    res2 = await executor.execute(ToolCall(id="2", name="dummy_tool", arguments={}))
    assert res2.success is False
    assert "Invalid arguments" in res2.error
    assert "TOOL_VALIDATION_ERROR" in res2.error or "ToolValidationError" in res2.error
    
    # Invalid type
    res3 = await executor.execute(ToolCall(id="3", name="dummy_tool", arguments={"param": 123}))
    assert res3.success is False
    assert "Invalid arguments" in res3.error

@pytest.mark.asyncio
async def test_executor_permissions(executor):
    res = await executor.execute(ToolCall(id="1", name="blocked_tool", arguments={}))
    assert res.success is False
    assert "ToolPermissionError" in res.error

@pytest.mark.asyncio
async def test_executor_timeout(executor, monkeypatch):
    import sys
    import app.tools.executor
    executor_module = sys.modules["app.tools.executor"]
    class MockSettings:
        astra_tool_execution_timeout_seconds = 0.1
        astra_tool_max_result_chars = 12000
    
    monkeypatch.setattr(executor_module, "get_settings", lambda: MockSettings())
    
    res = await executor.execute(ToolCall(id="1", name="slow_tool", arguments={}))
    assert res.success is False
    assert "TOOL_TIMEOUT" in res.error

@pytest.mark.asyncio
async def test_executor_truncation(executor, monkeypatch):
    import sys
    import app.tools.executor
    executor_module = sys.modules["app.tools.executor"]
    class MockSettings:
        astra_tool_execution_timeout_seconds = 5.0
        astra_tool_max_result_chars = 100
    monkeypatch.setattr(executor_module, "get_settings", lambda: MockSettings())
    
    res = await executor.execute(ToolCall(id="1", name="oversize_tool", arguments={}))
    assert res.success is True
    assert len(res.result) <= 150 # 100 + length of truncation suffix
    assert "[Result truncated due to size limits]" in res.result

@pytest.mark.asyncio
async def test_open_url_schemes():
    tool = OpenUrlTool()
    # Invalid scheme
    with pytest.raises(ToolPermissionError):
        await tool.execute("file:///C:/Windows/System32/cmd.exe")
    with pytest.raises(ToolPermissionError):
        await tool.execute("javascript:alert(1)")
        
@pytest.mark.asyncio
async def test_filesystem_traversal():
    root = Path("/fake/root").resolve()
    with pytest.raises(ToolPermissionError):
        resolve_and_verify_path("../../../etc/passwd", root)
    with pytest.raises(ToolPermissionError):
        resolve_and_verify_path("..\\..\\Windows\\System32", root)
    
    # Valid
    valid = resolve_and_verify_path("src/main.py", root)
    assert valid == (root / "src/main.py").resolve()
