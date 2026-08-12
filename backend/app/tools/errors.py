class ToolError(Exception):
    """Base class for all tool-related errors."""
    pass

class ToolNotFoundError(ToolError):
    """Raised when a requested tool does not exist in the registry."""
    def __init__(self, name: str):
        super().__init__(f"Tool '{name}' not found.")
        self.name = name

class ToolValidationError(ToolError):
    """Raised when tool arguments fail validation."""
    pass

class ToolExecutionError(ToolError):
    """Raised when a tool encounters an error during execution."""
    pass

class ToolPermissionError(ToolError):
    """Raised when a tool is blocked due to permission/security policies."""
    pass
