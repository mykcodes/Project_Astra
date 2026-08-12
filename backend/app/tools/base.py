from abc import ABC, abstractmethod
from typing import Any

from app.tools.schemas import ToolRisk
from app.ai.providers.types import ToolDefinition

class Tool(ABC):
    """Abstract base class for all tools."""
    
    name: str
    description: str
    risk: ToolRisk
    schema: dict[str, Any]

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.schema,
            risk=self.risk.value
        )

    @abstractmethod
    async def execute(self, **kwargs) -> str | dict | None:
        """Execute the tool with the given arguments. Should validate its own inputs."""
        pass
