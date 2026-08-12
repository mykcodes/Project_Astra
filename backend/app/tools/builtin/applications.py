import asyncio
import json
import sys
import subprocess
import webbrowser
from urllib.parse import urlparse
from app.tools.base import Tool
from app.tools.schemas import ToolRisk
from app.tools.errors import ToolPermissionError, ToolExecutionError
from app.core.config import get_settings

class OpenApplicationTool(Tool):
    name = "open_application"
    description = (
        "Opens a desktop application based on an explicitly allowed list. "
        "Use this tool to actually launch an application when the user asks to open it. "
        "Do NOT provide conversational instructions on how to open it."
    )
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
        executable = None
        matched_app_name = None
        
        for key, val in allowed_apps.items():
            if isinstance(val, dict):
                aliases = [a.lower() for a in val.get("aliases", [])]
                if app_key == key.lower() or app_key in aliases:
                    executable = val.get("path")
                    matched_app_name = key
                    break
            elif isinstance(val, str):
                if app_key == key.lower():
                    executable = val
                    matched_app_name = key
                    break
                    
        if not executable:
            return {"success": False, "message": f"Application '{application}' is not configured in the ASTRA application allowlist."}
            
        try:
            if sys.platform == "win32":
                DETACHED_PROCESS = 0x00000008
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                process = subprocess.Popen(
                    [executable],
                    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                )
            else:
                process = subprocess.Popen(
                    [executable],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            
            return {"success": True, "message": f"Application '{matched_app_name}' launched successfully."}
        except FileNotFoundError as e:
            return {
                "success": False,
                "message": f"Failed to launch '{matched_app_name}'.",
                "error": f"FileNotFoundError: Executable not found at {executable}"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to launch '{matched_app_name}'.",
                "error": f"{type(e).__name__}: {str(e)}"
            }

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
