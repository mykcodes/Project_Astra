from pydantic import BaseModel, Field
from typing import Optional, List, Dict
import logging
from app.environment.application.catalog import catalog

logger = logging.getLogger(__name__)

class BrowserIdentity(BaseModel):
    browser_id: str = Field(description="Unique ID for this specific browser session if launched")
    canonical_name: str = Field(description="Canonical browser name (e.g. chrome, brave)")
    display_name: str = Field(description="Display name of the browser")
    executable_path: str = Field(description="Path to the executable")
    process_id: Optional[int] = Field(default=None, description="Main process ID if running")
    window_handle: Optional[int] = Field(default=None, description="Main window handle if available")
    playwright_context_id: Optional[str] = Field(default=None, description="Associated Playwright context ID")
    session_id: Optional[str] = Field(default=None, description="Associated ASTRA session ID")
    pages: List[str] = Field(default_factory=list, description="List of page IDs")
    active_page_id: Optional[str] = Field(default=None, description="Currently active page ID")
    is_running: bool = Field(default=False, description="Whether the browser is currently running")
    is_focused: bool = Field(default=False, description="Whether the browser is currently focused")

class BrowserIdentityRegistry:
    def __init__(self):
        self.aliases: Dict[str, str] = {
            "google chrome": "chrome",
            "chrome": "chrome",
            "brave browser": "brave",
            "brave": "brave",
            "microsoft edge": "edge",
            "edge": "edge",
            "firefox": "firefox",
            "mozilla firefox": "firefox"
        }
        
    def resolve_browser(self, name: str) -> Optional[BrowserIdentity]:
        """Resolves a natural language name to a concrete installed browser identity."""
        if not name:
            return None
            
        norm_name = name.lower().strip()
        canonical = self.aliases.get(norm_name, norm_name)
        
        catalog.refresh()
        apps = catalog.get_all()
        
        catalog_map = {
            "chrome": "googlechrome",
            "brave": "brave",
            "edge": "microsoftedge",
            "firefox": "firefox"
        }
        
        catalog_key = catalog_map.get(canonical, canonical)
        
        if catalog_key in apps:
            app_entity = apps[catalog_key]
            if app_entity.installed and app_entity.executable_path:
                return BrowserIdentity(
                    browser_id="",  # Set upon launch
                    canonical_name=canonical,
                    display_name=app_entity.display_name,
                    executable_path=app_entity.executable_path
                )
                
        # Fuzzy matching fallback
        for app_norm, app_entity in apps.items():
            if canonical in app_norm or app_norm in canonical:
                if app_entity.installed and app_entity.executable_path:
                    if any(b in app_norm for b in ["chrome", "brave", "edge", "firefox", "browser"]):
                        return BrowserIdentity(
                            browser_id="",
                            canonical_name=canonical,
                            display_name=app_entity.display_name,
                            executable_path=app_entity.executable_path
                        )
                        
        logger.warning(f"Could not resolve browser identity for requested name: {name}")
        return None

browser_registry = BrowserIdentityRegistry()
