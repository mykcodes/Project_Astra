import pytest
import json
from unittest.mock import patch, MagicMock
from app.tools.builtin.processes import CloseApplicationTool

@pytest.fixture
def mock_settings():
    with patch('app.tools.builtin.processes.get_settings') as mock:
        settings = MagicMock()
        mock.return_value = settings
        yield settings

@pytest.mark.asyncio
async def test_close_configured_application_new_schema(mock_settings):
    mock_settings.astra_tool_allowed_apps = json.dumps({
        "vscode": {
            "path": "C:\\fake\\Code.exe",
            "process": "Code.exe",
            "aliases": ["vs code"]
        }
    })
    
    tool = CloseApplicationTool()
    
    with patch.object(tool, '_close_process', return_value=1) as mock_close:
        result = await tool.execute("vscode")
        
        assert result["success"] is True
        assert "closed successfully" in result["message"]
        mock_close.assert_called_once_with("Code.exe")

@pytest.mark.asyncio
async def test_close_configured_application_legacy_schema(mock_settings):
    mock_settings.astra_tool_allowed_apps = json.dumps({
        "vscode": "C:\\fake\\Code.exe"
    })
    
    tool = CloseApplicationTool()
    
    with patch.object(tool, '_close_process', return_value=1) as mock_close:
        result = await tool.execute("vscode")
        
        assert result["success"] is True
        mock_close.assert_called_once_with("Code.exe")

@pytest.mark.asyncio
async def test_close_alias_resolution(mock_settings):
    mock_settings.astra_tool_allowed_apps = json.dumps({
        "vscode": {
            "path": "C:\\fake\\Code.exe",
            "aliases": ["vs code", "visual studio code"]
        }
    })
    
    tool = CloseApplicationTool()
    
    with patch.object(tool, '_close_process', return_value=1) as mock_close:
        result = await tool.execute("Visual Studio Code")
        
        assert result["success"] is True
        mock_close.assert_called_once_with("Code.exe")

@pytest.mark.asyncio
async def test_unknown_application_rejected(mock_settings):
    mock_settings.astra_tool_allowed_apps = json.dumps({
        "vscode": "C:\\fake\\Code.exe"
    })
    
    tool = CloseApplicationTool()
    
    result = await tool.execute("chrome")
    assert result["success"] is False
    assert "not configured" in result["message"]

@pytest.mark.asyncio
async def test_already_closed_application(mock_settings):
    mock_settings.astra_tool_allowed_apps = json.dumps({
        "vscode": "C:\\fake\\Code.exe"
    })
    
    tool = CloseApplicationTool()
    
    with patch.object(tool, '_close_process', return_value=0):
        result = await tool.execute("vscode")
        assert result["success"] is False
        assert "not currently running" in result["message"]
