import json
import os
import psutil
import asyncio
from app.tools.base import Tool
from app.tools.schemas import ToolRisk
from app.core.config import get_settings

class CloseApplicationTool(Tool):
    name = "close_application"
    description = (
        "Closes a running desktop application based on an explicitly allowed list. "
        "Use this tool to actually close/terminate an application when the user asks to close it. "
        "Do NOT provide conversational instructions on how to close it."
    )
    risk = ToolRisk.CONTROLLED
    schema = {
        "type": "object",
        "properties": {
            "application": {
                "type": "string",
                "description": "The name of the application to close (e.g., 'vscode', 'notepad')."
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
        process_name = None
        matched_app_name = None
        
        for key, val in allowed_apps.items():
            if isinstance(val, dict):
                aliases = [a.lower() for a in val.get("aliases", [])]
                if app_key == key.lower() or app_key in aliases:
                    process_name = val.get("process")
                    if not process_name and val.get("path"):
                        process_name = os.path.basename(val.get("path"))
                    matched_app_name = key
                    break
            elif isinstance(val, str):
                if app_key == key.lower():
                    process_name = os.path.basename(val)
                    matched_app_name = key
                    break
                    
        if not process_name:
            return {"success": False, "message": f"Application '{application}' is not configured in the ASTRA application allowlist."}
            
        # Since process iteration can be blocking in psutil, use asyncio.to_thread
        closed_count = await asyncio.to_thread(self._close_process, process_name)
        
        if closed_count > 0:
            return {"success": True, "message": f"Application '{matched_app_name}' closed successfully."}
        else:
            return {"success": False, "message": f"Application '{matched_app_name}' is not currently running."}
            
    def _close_process(self, process_name: str) -> int:
        closed_count = 0
        target_name = process_name.lower()
        for proc in psutil.process_iter(['name']):
            try:
                # Catch zombie or dead process errors
                if proc.info['name'] and proc.info['name'].lower() == target_name:
                    proc.terminate()
                    closed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return closed_count
