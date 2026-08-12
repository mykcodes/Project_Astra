import asyncio
import json
import webbrowser
from urllib.parse import urlparse
from app.tools.base import Tool
from app.tools.schemas import ToolRisk
from app.tools.errors import ToolPermissionError, ToolExecutionError
from app.core.config import get_settings

class OpenApplicationTool(Tool):
    name = "open_application"
    description = "Opens a desktop application based on an explicitly allowed list."
    risk = ToolRisk.CONTROLLED
    schema = {
        "type": "object",
        "properties": {
            "application": {
                "type": "string",
                "description": "The name of the application to open (e.g., 'vscode', 'notepad')."
            }
        },
        "required": ["application"],
        "additionalProperties": False
    }

    async def execute(self, application: str, **kwargs) -> dict:
        settings = get_settings()
        allowed_apps_str = getattr(settings, "astra_tool_allowed_apps", "{}")
        
        try:
            allowed_apps = json.loads(allowed_apps_str)
        except json.JSONDecodeError:
            allowed_apps = {}
            
        app_key = application.lower()
        if app_key not in allowed_apps:
            raise ToolPermissionError(f"Application '{application}' is not allowlisted.")
            
        executable = allowed_apps[app_key]
        
        try:
            # We use subprocess directly but only with allowlisted executable commands
            process = await asyncio.create_subprocess_exec(
                executable,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            # We don't wait for the process to exit because it's a desktop app
            return {"success": True, "message": f"Opened {application} (PID: {process.pid})"}
        except FileNotFoundError:
            raise ToolExecutionError(f"Executable for '{application}' not found: {executable}")
        except Exception as e:
            raise ToolExecutionError(f"Failed to open '{application}': {str(e)}")

class OpenUrlTool(Tool):
    name = "open_url"
    description = "Opens an HTTP or HTTPS URL in the system's default web browser."
    risk = ToolRisk.CONTROLLED
    schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to open."
            }
        },
        "required": ["url"],
        "additionalProperties": False
    }

    async def execute(self, url: str, **kwargs) -> dict:
        parsed = urlparse(url)
        if parsed.scheme not in ["http", "https"]:
            raise ToolPermissionError(f"URL scheme '{parsed.scheme}' is not allowed. Only http and https are permitted.")
            
        success = webbrowser.open(url)
        if not success:
            raise ToolExecutionError(f"Failed to open URL: {url}")
            
        return {"success": True, "message": f"Opened {url} in default browser."}
