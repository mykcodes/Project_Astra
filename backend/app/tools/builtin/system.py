import platform
import psutil
from app.tools.base import Tool
from app.tools.schemas import ToolRisk

class GetSystemInfoTool(Tool):
    name = "get_system_info"
    description = "Returns safe system information such as OS, CPU, and RAM."
    risk = ToolRisk.SAFE
    schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False
    }

    async def execute(self, **kwargs) -> dict:
        return {
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "cpu_count": psutil.cpu_count(logical=True),
            "ram_total_gb": round(psutil.virtual_memory().total / (1024 ** 3), 2),
            "ram_available_gb": round(psutil.virtual_memory().available / (1024 ** 3), 2)
        }
