import os
from pathlib import Path
from typing import List, Dict

from app.tools.base import Tool
from app.tools.schemas import ToolRisk
from app.tools.errors import ToolPermissionError, ToolExecutionError, ToolValidationError
from app.core.config import get_settings
from app.core.config import get_settings

def get_allowed_root() -> Path:
    settings = get_settings()
    root_str = getattr(settings, "astra_tool_allowed_fs_root", "")
    if not root_str:
        raise ToolPermissionError("Filesystem tools are disabled (ASTRA_TOOL_ALLOWED_FS_ROOT is not set).")
    
    root_path = Path(root_str).resolve()
    if not root_path.exists() or not root_path.is_dir():
        raise ToolPermissionError(f"Configured allowed filesystem root does not exist or is not a directory: {root_str}")
    return root_path

def resolve_and_verify_path(requested_path: str, allowed_root: Path) -> Path:
    # Handle empty string or "." as root
    if not requested_path or requested_path == ".":
        return allowed_root
        
    # Remove leading slashes so path isn't treated as absolute by Path()
    if requested_path.startswith("/") or requested_path.startswith("\\"):
        requested_path = requested_path.lstrip("/\\")
        
    target_path = (allowed_root / requested_path).resolve()
    
    try:
        # Check if the target_path is relative to the allowed_root
        target_path.relative_to(allowed_root)
    except ValueError:
        raise ToolPermissionError(f"Access to path '{requested_path}' is denied. It is outside the allowed root.")
        
    return target_path

class ListDirectoryTool(Tool):
    name = "list_directory"
    description = "Lists files and directories inside a restricted allowed root path."
    risk = ToolRisk.SAFE
    capabilities = ["FILESYSTEM_DISCOVERY"]
    schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the directory to list (e.g., '.', 'src', 'docs')."
            }
        },
        "additionalProperties": False
    }

    async def execute(self, path: str = ".", **kwargs) -> Dict[str, List[str]]:
        if not isinstance(path, str):
            raise ToolValidationError("Path must be a string.")
            
        root = get_allowed_root()
        target = resolve_and_verify_path(path, root)
        
        if not target.exists() or not target.is_dir():
            raise ToolExecutionError(f"Directory not found: {path}")
            
        try:
            files = []
            dirs = []
            for item in target.iterdir():
                if item.is_dir():
                    dirs.append(item.name)
                else:
                    files.append(item.name)
                    
            return {
                "directories": sorted(dirs),
                "files": sorted(files)
            }
        except Exception as e:
            raise ToolExecutionError(f"Failed to list directory: {str(e)}")

class SearchFilesTool(Tool):
    name = "search_files"
    description = "Searches for filenames containing a specific query within the allowed root path."
    risk = ToolRisk.SAFE
    capabilities = ["FILESYSTEM_SEARCH"]
    schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The string to search for in filenames."
            },
            "path": {
                "type": "string",
                "description": "Optional relative path to restrict the search to."
            }
        },
        "required": ["query"],
        "additionalProperties": False
    }

    async def execute(self, query: str, path: str = ".", **kwargs) -> List[str]:
        if not isinstance(query, str) or not isinstance(path, str):
            raise ToolValidationError("Query and path must be strings.")
            
        root = get_allowed_root()
        target = resolve_and_verify_path(path, root)
        
        if not target.exists() or not target.is_dir():
            raise ToolExecutionError(f"Directory not found: {path}")
            
        results = []
        try:
            for dirpath, _, filenames in os.walk(target):
                for name in filenames:
                    if query.lower() in name.lower():
                        rel_path = Path(dirpath) / name
                        # Get path relative to the allowed root
                        try:
                            results.append(str(rel_path.relative_to(root).as_posix()))
                        except ValueError:
                            pass
            return results
        except Exception as e:
            raise ToolExecutionError(f"Failed to search files: {str(e)}")

class CreateFolderTool(Tool):
    name = "create_folder"
    description = "Creates a new folder inside the restricted allowed root path."
    risk = ToolRisk.CONTROLLED
    capabilities = ["FILE_CREATION"]
    schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path of the new folder to create."
            }
        },
        "required": ["path"],
        "additionalProperties": False
    }

    async def execute(self, path: str, **kwargs) -> dict:
        if not isinstance(path, str):
            raise ToolValidationError("Path must be a string.")
            
        root = get_allowed_root()
        target = resolve_and_verify_path(path, root)
        
        if target.exists():
            raise ToolExecutionError(f"Path already exists: {path}")
            
        try:
            target.mkdir(parents=True)
            return {"success": True, "message": f"Folder created successfully: {path}"}
        except Exception as e:
            raise ToolExecutionError(f"Failed to create folder: {str(e)}")
