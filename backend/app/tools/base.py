from abc import ABC, abstractmethod
from typing import Any

from app.tools.schemas import ToolRisk
from app.ai.providers.types import ToolDefinition

# Forward reference or late import avoided by keeping it simple, but we can't import Capability from registry directly if registry imports Tool.
# Let's put Capability in schemas.py or just use strings.
# Since it's just a type hint, string 'Capability' is fine as I did, but I'll make sure it's valid if evaluated.

class Tool(ABC):
    """Abstract base class for all tools."""
    
    name: str
    description: str
    risk: ToolRisk
    schema: dict[str, Any]
    capabilities: list['Capability'] = []

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
