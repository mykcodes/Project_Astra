from __future__ import annotations
import asyncio
import sys
import threading
from typing import Optional, List, TYPE_CHECKING
from enum import Enum
from playwright.async_api import async_playwright
if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

from app.core.logging.logger import get_logger
from app.tools.desktop.browser.browser_identity import BrowserIdentity

logger = get_logger(__name__)

class BrowserSessionState(str, Enum):
    UNINITIALIZED = "UNINITIALIZED"
    LAUNCHING = "LAUNCHING"
    READY = "READY"
    RECOVERING = "RECOVERING"
    CLOSED = "CLOSED"

class PlaywrightThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.ready_event = threading.Event()

    def run(self):
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.ready_event.set()
        self.loop.run_forever()

    def stop(self):
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.join()

class BrowserSession:
    """
    Manages the lifecycle of the Playwright browser, context, and pages.
    Provides thread-safe access to Playwright operations.
    Maintains session state without any website-specific logic.
    """
    def __init__(self):
        self._pw_thread = PlaywrightThread()
        self._pw_thread.start()
        self._pw_thread.ready_event.wait()
        
        self.state: BrowserSessionState = BrowserSessionState.UNINITIALIZED
        self.session_id: Optional[str] = None
        self.identity: Optional[BrowserIdentity] = None
        
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.pages: List[Page] = []
        self.current_page_index: int = -1

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        return self._pw_thread.loop

    async def run_in_pw_loop(self, coro):
        """Run an async coroutine inside the Playwright event loop in a thread-safe manner."""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return await asyncio.wrap_future(future)

    async def _ensure_initialized(self):
        if not self.playwright:
            async def _start():
                self.playwright = await async_playwright().start()
            await self.run_in_pw_loop(_start())

    @property
    def current_page(self) -> Optional[Page]:
        return self.get_active_page()

    def get_active_page(self) -> Optional[Page]:
        if self.pages and 0 <= self.current_page_index < len(self.pages):
            return self.pages[self.current_page_index]
        return None
        
    def list_pages(self) -> List[Page]:
        return list(self.pages)

    async def ensure_alive(self, identity: BrowserIdentity) -> bool:
        if self.state == BrowserSessionState.READY and self.browser and self.browser.is_connected() and self.identity and self.identity.canonical_name == identity.canonical_name:
            await self.ensure_context_alive()
            await self.ensure_page_alive()
            return True
            
        # Re-launch
        if self.state != BrowserSessionState.UNINITIALIZED and self.state != BrowserSessionState.CLOSED:
            await self.close()
            
        res = await self.launch_browser(identity)
        return res.get("success", False)

    async def ensure_context_alive(self):
        async def _check():
            if not self.context or not self.browser.contexts:
                self.context = await self.browser.new_context(viewport={"width": 1280, "height": 800})
                self.context.on("page", self._on_page)
                self.context.on("close", self._on_context_close)
        await self.run_in_pw_loop(_check())

    async def ensure_page_alive(self):
        async def _check():
            if not self.pages:
                await self.context.new_page()
        await self.run_in_pw_loop(_check())
        
    async def recover_closed_page(self) -> bool:
        self.state = BrowserSessionState.RECOVERING
        try:
            await self.ensure_context_alive()
            await self.ensure_page_alive()
            self.state = BrowserSessionState.READY
            return True
        except Exception as e:
            logger.error("BROWSER_PAGE_RECOVERY_FAILED", extra={"error": str(e)})
            self.state = BrowserSessionState.CLOSED
            return False

    async def launch_browser(self, identity: BrowserIdentity, headless: bool = False, channel: str = None) -> dict:
        """Launches a persistent browser session."""
        self.state = BrowserSessionState.LAUNCHING
        await self._ensure_initialized()
        
        async def _launch():
            try:
                launch_args = {"headless": headless}
                
                b_type = identity.canonical_name.lower()
                pw_browser = self.playwright.chromium
                
                if b_type == "firefox":
                    pw_browser = self.playwright.firefox
                elif b_type == "webkit":
                    pw_browser = self.playwright.webkit
                elif b_type == "edge":
                    launch_args["channel"] = channel or "msedge"
                elif b_type == "chrome":
                    launch_args["channel"] = channel or "chrome"
                elif channel:
                    launch_args["channel"] = channel
                
                if identity.executable_path:
                    launch_args["executable_path"] = identity.executable_path

                self.browser = await pw_browser.launch(**launch_args)
                self.context = await self.browser.new_context(
                    viewport={"width": 1280, "height": 800}
                )
                
                try:
                    from playwright_stealth import Stealth  # type: ignore
                    await Stealth().apply_stealth_async(self.context)
                except ImportError:
                    logger.warning("playwright-stealth not installed, skipping stealth mode")
                
                # Initialize fields before callbacks
                self.pages.clear()
                self.current_page_index = -1
                self.identity = identity
                
                self.browser.on("disconnected", self._on_browser_disconnected)
                self.context.on("page", self._on_page)
                self.context.on("close", self._on_context_close)
                
                # Initial page
                await self.context.new_page()
                
                self.state = BrowserSessionState.READY
                logger.info("BROWSER_SESSION_STARTED", extra={"type": identity.canonical_name, "headless": headless})
                return {"success": True, "message": f"{identity.canonical_name} browser launched successfully."}
            except Exception as e:
                self.state = BrowserSessionState.CLOSED
                logger.error("BROWSER_LAUNCH_FAILED", extra={"error": str(e)})
                return {"success": False, "message": f"Failed to launch browser: {str(e)}"}
                
        return await self.run_in_pw_loop(_launch())

    def _on_page(self, page: Page):
        self.pages.append(page)
        self.current_page_index = len(self.pages) - 1
        
        async def _init_page():
            try:
                await page.bring_to_front()
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
        
        if self.loop:
            asyncio.run_coroutine_threadsafe(_init_page(), self.loop)
            
        page.on("close", lambda p: self._on_page_close(p))
        page.on("popup", self._on_popup)

    def _on_popup(self, page: Page):
        self._on_page(page)

    def _on_page_close(self, page: Page):
        if page in self.pages:
            idx = self.pages.index(page)
            self.pages.remove(page)
            if self.current_page_index >= idx:
                self.current_page_index = max(0, self.current_page_index - 1)

    def _on_context_close(self, context: BrowserContext):
        self.pages.clear()
        self.current_page_index = -1
        self.context = None

    def _on_browser_disconnected(self, browser: Browser):
        self._on_context_close(None)
        self.browser = None
        self.state = BrowserSessionState.CLOSED

    async def get_state(self) -> dict:
        if not self.browser or self.state != BrowserSessionState.READY:
            return {"running": False, "state": self.state.value}
            
        async def _state():
            tabs = []
            for i, page in enumerate(self.pages):
                try:
                    title = await page.title()
                    url = page.url
                except:
                    title = "Unknown"
                    url = "Unknown"
                tabs.append({"index": i, "title": title, "url": url})
                
            return {
                "running": True,
                "state": self.state.value,
                "identity": self.identity.canonical_name if self.identity else None,
                "tabs_count": len(self.pages),
                "current_tab_index": self.current_page_index,
                "tabs": tabs
            }
        return await self.run_in_pw_loop(_state())

    async def close(self):
        async def _close():
            if self.browser:
                try:
                    await self.browser.close()
                except Exception:
                    pass
                self.browser = None
                self.context = None
                self.pages.clear()
                self.current_page_index = -1
        await self.run_in_pw_loop(_close())
        self.state = BrowserSessionState.CLOSED
        self.identity = None

    async def shutdown(self):
        await self.close()
        async def _stop():
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
        await self.run_in_pw_loop(_stop())
        self._pw_thread.stop()

browser_session = BrowserSession()
