from __future__ import annotations
import asyncio
import sys
import threading
from typing import Optional, List, TYPE_CHECKING
from playwright.async_api import async_playwright
if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

from app.core.logging.logger import get_logger

logger = get_logger(__name__)

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
        
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.pages: List[Page] = []
        self.current_page_index: int = -1

    async def run_in_pw_loop(self, coro):
        """Run an async coroutine inside the Playwright event loop in a thread-safe manner."""
        future = asyncio.run_coroutine_threadsafe(coro, self._pw_thread.loop)
        return await asyncio.wrap_future(future)

    async def _ensure_initialized(self):
        if not self.playwright:
            async def _start():
                self.playwright = await async_playwright().start()
            await self.run_in_pw_loop(_start())

    @property
    def current_page(self) -> Optional[Page]:
        if 0 <= self.current_page_index < len(self.pages):
            return self.pages[self.current_page_index]
        return None

    async def launch_browser(self, browser_type: str = "brave", headless: bool = False, channel: str = None, executable_path: str = None) -> dict:
        """Launches a persistent browser session."""
        await self._ensure_initialized()
        
        if self.browser:
            return {"success": True, "message": "Browser is already running."}

        async def _launch():
            try:
                launch_args = {"headless": headless}
                
                b_type = browser_type.lower()
                pw_browser = self.playwright.chromium
                
                if b_type == "firefox":
                    pw_browser = self.playwright.firefox
                elif b_type == "webkit":
                    pw_browser = self.playwright.webkit
                elif b_type == "brave":
                    launch_args["executable_path"] = executable_path or r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
                elif b_type == "edge":
                    launch_args["channel"] = channel or "msedge"
                elif b_type == "chrome":
                    launch_args["channel"] = channel or "chrome"
                elif channel:
                    launch_args["channel"] = channel
                elif executable_path:
                    launch_args["executable_path"] = executable_path

                self.browser = await pw_browser.launch(**launch_args)
                self.context = await self.browser.new_context(
                    viewport={"width": 1280, "height": 800}
                )
                
                try:
                    from playwright_stealth import Stealth  # type: ignore
                    await Stealth().apply_stealth_async(self.context)
                except ImportError:
                    logger.warning("playwright-stealth not installed, skipping stealth mode")
                
                self.context.on("page", self._on_page)
                self.context.on("close", self._on_context_close)
                
                # Initial page
                await self.context.new_page()
                
                logger.info("BROWSER_SESSION_STARTED", extra={"type": browser_type, "headless": headless})
                return {"success": True, "message": f"{browser_type} browser launched successfully."}
            except Exception as e:
                logger.error("BROWSER_LAUNCH_FAILED", extra={"error": str(e)})
                return {"success": False, "message": f"Failed to launch browser: {str(e)}"}
                
        return await self.run_in_pw_loop(_launch())

    def _on_page(self, page: Page):
        self.pages.append(page)
        self.current_page_index = len(self.pages) - 1
        page.on("close", lambda p: self._on_page_close(p))

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

    async def get_state(self) -> dict:
        if not self.browser:
            return {"running": False}
            
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
                "tabs_count": len(self.pages),
                "current_tab_index": self.current_page_index,
                "tabs": tabs
            }
        return await self.run_in_pw_loop(_state())

    async def close_browser(self):
        async def _close():
            if self.browser:
                await self.browser.close()
                self.browser = None
                self.context = None
                self.pages.clear()
                self.current_page_index = -1
        await self.run_in_pw_loop(_close())

    async def shutdown(self):
        await self.close_browser()
        async def _stop():
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
        await self.run_in_pw_loop(_stop())
        self._pw_thread.stop()

browser_session = BrowserSession()
