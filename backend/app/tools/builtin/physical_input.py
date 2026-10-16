from app.tools.base import Tool
from app.tools.schemas import ToolRisk
from app.domain.entities import ScreenPoint

class ExecutePhysicalInputTool(Tool):
    name = "execute_physical_input"
    description = (
        "Executes physical mouse input at specific screen coordinates. "
        "Supports MOVE_MOUSE, CLICK, and DOUBLE_CLICK. "
        "Operates purely on absolute virtual screen coordinates."
    )
    risk = ToolRisk.CONTROLLED
    capabilities = ["desktop:input", "physical.mouse_input"]
    schema = {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["MOVE_MOUSE", "CLICK", "DOUBLE_CLICK"],
                "description": "The physical intent to execute."
            },
            "x": {
                "type": "integer",
                "description": "Absolute virtual screen X coordinate."
            },
            "y": {
                "type": "integer",
                "description": "Absolute virtual screen Y coordinate."
            }
        },
        "required": ["intent", "x", "y"],
        "additionalProperties": False
    }

    async def execute(self, intent: str, x: int, y: int, **kwargs) -> dict:
        point = ScreenPoint(x=x, y=y)
        from app.interaction.router import interaction_router
        try:
            result = await interaction_router.route(intent, target_entity=None, hwnds=None, pids=None, point=point)
            return result
        except Exception as e:
            return {"success": False, "error": {"code": "ROUTER_ERROR", "message": str(e)}}
