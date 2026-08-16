from typing import Optional
from app.tools.base import Tool
from app.tools.schemas import ToolRisk
from app.tools.desktop.browser import browser_provider

class ExecuteBrowserIntentTool(Tool):
    name = "execute_browser_intent"
    description = (
        "Executes high-level browser intents like SEARCH or NAVIGATE. "
        "Will automatically handle verification and state observation."
    )
    risk = ToolRisk.CONTROLLED
    capabilities = ["browser.navigate", "browser.search", "URL_OPEN"]
    schema = {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["SEARCH", "NAVIGATE", "STATUS"],
                "description": "The high-level action to perform."
            },
            "target": {
                "type": "string",
                "description": "URL for NAVIGATE, or query for SEARCH."
            },
            "_verify_only": {
                "type": "boolean"
            }
        },
        "required": ["intent"],
        "additionalProperties": False
    }

    async def execute(self, intent: str, target: Optional[str] = None, **kwargs) -> dict:
        intent = intent.upper()
        
        if kwargs.get("_verify_only"):
            return await browser_provider.check_challenges()
            
        if intent == "STATUS":
            return await browser_provider.get_state()
            
        return await browser_provider.execute_intent(intent, target)

class InteractBrowserTool(Tool):
    name = "interact_browser"
    description = (
        "Interacts with the current browser page. "
        "CRITICAL: Use semantic descriptions for 'target', like 'first video', 'search field', or 'login button'. "
        "The system will automatically resolve these to the correct elements. "
        "Actions: CLICK, TYPE, FILL, HOVER, READ_DOM, SCROLL, PRESS_KEY."
    )
    risk = ToolRisk.CONTROLLED
    capabilities = ["browser.click", "BROWSER_CONTROL"]
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["CLICK", "TYPE", "FILL", "READ_DOM", "SCROLL", "PRESS_KEY", "HOVER"],
                "description": "The interaction action to perform."
            },
            "target": {
                "type": "string",
                "description": "Semantic description of the target (e.g. 'search field', 'first video')."
            },
            "value": {
                "type": "string",
                "description": "The text to type for the TYPE/FILL action."
            },
            "_verify_only": {
                "type": "boolean"
            }
        },
        "required": ["action"],
        "additionalProperties": False
    }

    async def execute(self, action: str, target: Optional[str] = None, value: Optional[str] = None, **kwargs) -> dict:
        if kwargs.get("_verify_only"):
            return await browser_provider.check_challenges()
            
        return await browser_provider.interact(action, target, value)
