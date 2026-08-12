from enum import Enum

class ToolRisk(str, Enum):
    SAFE = "SAFE"
    CONTROLLED = "CONTROLLED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    BLOCKED = "BLOCKED"
