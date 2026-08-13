import asyncio
import json
import webbrowser
from urllib.parse import urlparse
from app.tools.base import Tool
from app.tools.schemas import ToolRisk
from app.tools.errors import ToolPermissionError, ToolExecutionError
from app.core.config import get_settings
from app.tools.desktop.desktop_controller import desktop_controller
from app.tools.desktop.application_state import ApplicationIntent

class ExecuteApplicationIntentTool(Tool):
    name = "execute_application_intent"
    description = (
        "Executes a user's intent on a desktop application. "
        "Supports OPEN (launch/focus), CLOSE (graceful exit), FOCUS (bring to front), "
        "MINIMIZE, RESTORE, STATUS (check if running), and RESTART. "
        "Use this tool to handle all desktop application interactions. "
        "Do NOT provide conversational instructions on how to use the app, just execute the intent."
    )
    risk = ToolRisk.CONTROLLED
    capabilities = ["APPLICATION_LAUNCH", "APPLICATION_CLOSE", "APPLICATION_FOCUS", "APPLICATION_STATUS"]
    schema = {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["OPEN", "CLOSE", "FOCUS", "MINIMIZE", "RESTORE", "STATUS", "RESTART"],
                "description": "The intent to execute on the application."
            },
            "application": {
                "type": "string",
                "description": "The name of the application (e.g., 'spotify', 'vscode', 'notepad')."
            }
        },
        "required": ["intent", "application"],
        "additionalProperties": False
    }

    async def execute(self, intent: str, application: str, **kwargs) -> dict:
        if not isinstance(application, str):
            return {"success": False, "message": "Application name must be a string."}
            
        settings = get_settings()
        blocked_apps_str = getattr(settings, "astra_tool_blocked_apps", "[]")
        try:
            blocked_apps = json.loads(blocked_apps_str)
        except json.JSONDecodeError:
            blocked_apps = []
            
        try:
            intent_enum = ApplicationIntent(intent)
        except ValueError:
            return {"success": False, "message": f"Invalid intent: {intent}"}
            
        result = await desktop_controller.execute_intent(intent_enum, application, blocked_apps=blocked_apps)
        return result

class OpenUrlTool(Tool):
    name = "open_url"
    description = "Opens an HTTP or HTTPS URL in the system's default web browser."
    risk = ToolRisk.CONTROLLED
    capabilities = ["URL_OPEN"]
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
        if not isinstance(url, str):
            raise ToolPermissionError("URL must be a string.")
            
        parsed = urlparse(url)
        if parsed.scheme not in ["http", "https"]:
            raise ToolPermissionError(f"URL scheme '{parsed.scheme}' is not allowed. Only http and https are permitted.")
            
        success = webbrowser.open(url)
        if not success:
            raise ToolExecutionError(f"Failed to open URL: {url}")
            
        return {"success": True, "message": f"Opened {url} in default browser."}
