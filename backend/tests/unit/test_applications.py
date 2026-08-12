import pytest
import json
from unittest.mock import patch, MagicMock
from app.tools.builtin.applications import OpenApplicationTool

@pytest.fixture
def mock_settings():
    with patch('app.tools.builtin.applications.get_settings') as mock:
        settings = MagicMock()
        mock.return_value = settings
        yield settings

@pytest.mark.asyncio
async def test_open_configured_application_new_schema(mock_settings):
    mock_settings.astra_tool_allowed_apps = json.dumps({
        "vscode": {
            "path": "C:\\fake\\Code.exe",
            "aliases": ["vs code"]
        }
    })
    
    tool = OpenApplicationTool()
    
    with patch('asyncio.create_subprocess_exec') as mock_exec:
        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_exec.return_value = mock_process
        
        result = await tool.execute("vscode")
        
        assert result["success"] is True
        mock_exec.assert_called_once_with(
            "C:\\fake\\Code.exe",
            stdout=-3,
            stderr=-3
        )

@pytest.mark.asyncio
async def test_open_configured_application_legacy_schema(mock_settings):
    mock_settings.astra_tool_allowed_apps = json.dumps({
        "vscode": "C:\\fake\\Code.exe"
    })
    
    tool = OpenApplicationTool()
    
    with patch('asyncio.create_subprocess_exec') as mock_exec:
        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_exec.return_value = mock_process
        
        result = await tool.execute("vscode")
        
        assert result["success"] is True
        mock_exec.assert_called_once_with(
            "C:\\fake\\Code.exe",
            stdout=-3,
            stderr=-3
        )

@pytest.mark.asyncio
async def test_alias_resolution(mock_settings):
    mock_settings.astra_tool_allowed_apps = json.dumps({
        "vscode": {
            "path": "C:\\fake\\Code.exe",
            "aliases": ["vs code", "visual studio code"]
        }
    })
    
    tool = OpenApplicationTool()
    
    with patch('asyncio.create_subprocess_exec') as mock_exec:
        mock_exec.return_value = MagicMock()
        
        result = await tool.execute("Visual Studio Code")
        
        assert result["success"] is True
        assert "launched successfully" in result["message"]

@pytest.mark.asyncio
async def test_unknown_application_rejected(mock_settings):
    mock_settings.astra_tool_allowed_apps = json.dumps({
        "vscode": "C:\\fake\\Code.exe"
    })
    
    tool = OpenApplicationTool()
    
    result = await tool.execute("chrome")
    assert result["success"] is False
    assert "not configured" in result["message"]

@pytest.mark.asyncio
async def test_file_not_found(mock_settings):
    mock_settings.astra_tool_allowed_apps = json.dumps({
        "vscode": "C:\\fake\\Code.exe"
    })
    
    tool = OpenApplicationTool()
    
    with patch('asyncio.create_subprocess_exec', side_effect=FileNotFoundError):
        result = await tool.execute("vscode")
        assert result["success"] is False
        assert "not found" in result["message"]
