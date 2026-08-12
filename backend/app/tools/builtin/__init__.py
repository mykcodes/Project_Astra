from app.tools.registry import registry
from app.tools.builtin.time import GetTimeTool
from app.tools.builtin.system import GetSystemInfoTool
from app.tools.builtin.applications import OpenApplicationTool, OpenUrlTool
from app.tools.builtin.filesystem import ListDirectoryTool, SearchFilesTool, CreateFolderTool

def register_builtin_tools():
    """Registers all builtin tools with the global registry."""
    tools = [
        GetTimeTool(),
        GetSystemInfoTool(),
        OpenApplicationTool(),
        OpenUrlTool(),
        ListDirectoryTool(),
        SearchFilesTool(),
        CreateFolderTool(),
    ]
    
    for tool in tools:
        if not registry.has(tool.name):
            registry.register(tool)

# Register automatically on import
register_builtin_tools()
