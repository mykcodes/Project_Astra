from app.tools.base import Tool
from app.tools.schemas import ToolRisk
from app.domain.entities import ScreenPoint

class ExecutePhysicalInputTool(Tool):
    name = "execute_physical_input"
    description = (
        "Executes physical mouse and keyboard input. "
        "Supports mouse actions (MOVE_MOUSE, CLICK, DOUBLE_CLICK, RIGHT_CLICK, SCROLL, DRAG) and "
        "keyboard actions (TYPE_TEXT, PRESS_KEY, HOTKEY, ESCAPE, ALT)."
    )
    risk = ToolRisk.CONTROLLED
    capabilities = ["desktop:input", "physical.mouse_input", "physical.keyboard_input"]
    schema = {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["MOVE_MOUSE", "CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "SCROLL", "DRAG", "ESCAPE", "ALT", "TYPE_TEXT", "PRESS_KEY", "HOTKEY"],
                "description": "The physical intent to execute."
            },
            "x": {
                "type": "integer",
                "description": "Absolute virtual screen X coordinate (for mouse move, click, right_click, scroll position, drag start)."
            },
            "y": {
                "type": "integer",
                "description": "Absolute virtual screen Y coordinate (for mouse move, click, right_click, scroll position, drag start)."
            },
            "start_x": {
                "type": "integer",
                "description": "Starting virtual screen X coordinate for DRAG action (alias for x)."
            },
            "start_y": {
                "type": "integer",
                "description": "Starting virtual screen Y coordinate for DRAG action (alias for y)."
            },
            "end_x": {
                "type": "integer",
                "description": "Ending virtual screen X coordinate for DRAG action."
            },
            "end_y": {
                "type": "integer",
                "description": "Ending virtual screen Y coordinate for DRAG action."
            },
            "duration_ms": {
                "type": "integer",
                "description": "Duration in milliseconds for DRAG action. Defaults to 250."
            },
            "clicks": {
                "type": "integer",
                "description": "Vertical scroll clicks for SCROLL action (positive=up, negative=down)."
            },
            "delta_x": {
                "type": "integer",
                "description": "Horizontal scroll clicks for SCROLL action (positive=right, negative=left)."
            },
            "delta_y": {
                "type": "integer",
                "description": "Vertical scroll clicks for SCROLL action (positive=up, negative=down)."
            },
            "button": {
                "type": "string",
                "enum": ["left", "right"],
                "description": "Mouse button for DRAG action ('left' or 'right'). Defaults to 'left'."
            },
            "steps": {
                "type": "integer",
                "description": "Interpolation steps for DRAG action. Defaults to 10."
            },
            "text": {
                "type": "string",
                "description": "Text to type into focused window (for TYPE_TEXT)."
            },
            "key": {
                "type": "string",
                "description": "Key name to press (for PRESS_KEY, e.g. 'enter', 'tab', 'backspace')."
            },
            "keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of key names to actuate together as hotkey (for HOTKEY, e.g. ['ctrl', 's'])."
            }
        },
        "required": ["intent"],
        "additionalProperties": False
    }

    async def execute(
        self,
        intent: str,
        x: int = 0,
        y: int = 0,
        start_x: int = None,
        start_y: int = None,
        end_x: int = 0,
        end_y: int = 0,
        clicks: int = 0,
        delta_x: int = 0,
        delta_y: int = 0,
        button: str = "left",
        steps: int = 10,
        duration_ms: int = 250,
        text: str = None,
        key: str = None,
        keys: list = None,
        **kwargs
    ) -> dict:
        if start_x is not None and (not x or x == 0):
            x = start_x
        if start_y is not None and (not y or y == 0):
            y = start_y
        point = ScreenPoint(x=x, y=y) if (x or y or intent in ["MOVE_MOUSE", "CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "DRAG"]) else None
        end_point = ScreenPoint(x=end_x, y=end_y) if (end_x or end_y or intent == "DRAG") else None
        from app.interaction.router import interaction_router
        extra_kwargs = {}
        if intent in ("SCROLL", "MOUSE_WHEEL"):
            extra_kwargs = {"clicks": clicks, "delta_x": delta_x, "delta_y": delta_y}
        elif intent in ("DRAG", "DRAG_AND_DROP"):
            extra_kwargs = {"end_point": end_point, "button": button, "steps": steps, "duration_ms": duration_ms}
        elif clicks or delta_x or delta_y or end_point:
            extra_kwargs = {
                "clicks": clicks,
                "delta_x": delta_x,
                "delta_y": delta_y,
                "end_point": end_point,
                "button": button,
                "steps": steps,
                "duration_ms": duration_ms,
            }

        try:
            result = await interaction_router.route(
                intent,
                target_entity=None,
                hwnds=None,
                pids=None,
                point=point,
                text=text,
                key=key,
                keys=keys,
                **extra_kwargs,
            )
            return result
        except Exception as e:
            return {"success": False, "error": {"code": "ROUTER_ERROR", "message": str(e)}}
