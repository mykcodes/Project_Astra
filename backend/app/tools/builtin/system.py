from app.tools.base import Tool
from app.tools.schemas import ToolRisk
from app.system.information_service import system_engine

class GetSystemInfoTool(Tool):
    name = "get_system_info"
    description = (
        "Returns the complete Machine Profile, including OS, CPU, RAM, GPU, Storage, Network, and Battery information. "
        "Use this tool when the user asks for their machine specs or any hardware/software information."
    )
    risk = ToolRisk.SAFE
    schema = {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of sections to retrieve (e.g., ['os', 'cpu', 'memory']). Leave empty for all."
            }
        },
        "additionalProperties": False
    }
    capabilities = ["SYSTEM_INFORMATION"]

    async def execute(self, sections: list = None, **kwargs) -> dict:
        return system_engine.get_selected_fields(sections)

class GetCapabilitiesTool(Tool):
    name = "get_capabilities"
    description = (
        "Returns the list of capabilities currently supported by the ASTRA AI assistant on this machine. "
        "Use this tool when the user asks what you can do, what you control, or what you have access to."
    )
    risk = ToolRisk.SAFE
    schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False
    }
    capabilities = []

    async def execute(self, **kwargs) -> dict:
        from app.tools.registry import registry
        return {"capabilities": registry.get_capabilities()}
