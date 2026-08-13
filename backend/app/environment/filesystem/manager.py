import os
import glob
from typing import List, Optional
from pathlib import Path
import json
from app.core.config import get_settings
from app.environment.models import FileEntity
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class FilesystemManager:
    def __init__(self):
        self._allowed_roots = self._load_allowed_roots()

    def _load_allowed_roots(self) -> List[Path]:
        settings = get_settings()
        roots_str = getattr(settings, "astra_allowed_fs_roots", "")
        
        default_roots = [
            os.environ.get("USERPROFILE", ""),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
        ]
        
        roots = []
        if roots_str:
            try:
                roots = json.loads(roots_str)
            except json.JSONDecodeError:
                roots = [r.strip() for r in roots_str.split(",") if r.strip()]
                
        roots.extend(default_roots)
        
        valid_roots = []
        for r in roots:
            if not r: continue
            try:
                path = Path(r).resolve()
                if path.exists() and path.is_dir() and path not in valid_roots:
                    # Traversal prevention
                    if str(path) in ("C:\\", "c:\\", "C:\\Windows", "c:\\windows"):
                        continue
                    valid_roots.append(path)
            except Exception:
                pass
        return valid_roots

    def _is_path_allowed(self, target_path: Path) -> bool:
        target = target_path.resolve()
        for root in self._allowed_roots:
            try:
                if root in target.parents or root == target:
                    return True
            except Exception:
                pass
        return False

    def list_directory(self, path: str) -> List[FileEntity]:
        try:
            target = Path(path).resolve()
            if not self._is_path_allowed(target):
                logger.warning(f"Access denied to path: {path}")
                return []
                
            if not target.is_dir():
                return []
                
            entities = []
            for item in target.iterdir():
                entities.append(self._create_entity(item))
            return entities
        except Exception as e:
            logger.warning(f"Error listing directory {path}: {e}")
            return []

    def search_files(self, path: str, query: str, max_depth: int = 3, max_results: int = 50) -> List[FileEntity]:
        try:
            target = Path(path).resolve()
            if not self._is_path_allowed(target):
                logger.warning(f"Search access denied to path: {path}")
                return []
                
            results = []
            
            def _search(current_dir: Path, current_depth: int):
                if current_depth > max_depth or len(results) >= max_results:
                    return
                try:
                    for item in current_dir.iterdir():
                        if len(results) >= max_results:
                            break
                            
                        if query.lower() in item.name.lower():
                            results.append(self._create_entity(item))
                            
                        if item.is_dir():
                            # Skip common heavy directories
                            if item.name.lower() in ("node_modules", ".git", "venv", "__pycache__"):
                                continue
                            _search(item, current_depth + 1)
                except (PermissionError, OSError):
                    pass
                    
            _search(target, 0)
            return results
        except Exception as e:
            logger.warning(f"Error searching path {path}: {e}")
            return []

    def _create_entity(self, path: Path) -> FileEntity:
        try:
            stat = path.stat()
            return FileEntity(
                path=str(path),
                name=path.name,
                extension=path.suffix.lower(),
                size=stat.st_size,
                modified_time=stat.st_mtime,
                is_directory=path.is_dir(),
                is_executable=path.is_file() and path.suffix.lower() in {".exe", ".bat", ".cmd"}
            )
        except Exception:
            return FileEntity(
                path=str(path),
                name=path.name,
                extension=path.suffix.lower(),
                size=0,
                modified_time=0.0,
                is_directory=False,
                is_executable=False
            )

fs_manager = FilesystemManager()
