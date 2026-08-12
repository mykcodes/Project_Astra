import datetime
from app.tools.base import Tool
from app.tools.schemas import ToolRisk

class GetTimeTool(Tool):
    name = "get_time"
    description = "Returns the current local time and timezone."
    risk = ToolRisk.SAFE
    schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False
    }

    async def execute(self, **kwargs) -> dict:
        now = datetime.datetime.now().astimezone()
        return {
            "local_time": now.isoformat(),
            "timezone": now.tzname()
        }
