import asyncio
from typing import Optional
from app.core.logging.logger import get_logger
from app.tools.desktop.browser.browser_session import browser_session

logger = get_logger(__name__)

class BrowserActionExecutor:
    """
    Executes concrete browser actions on Playwright.
    """
    
    async def navigate(self, url: str) -> dict:
        if not browser_session.browser or not browser_session.current_page:
            res = await browser_session.launch_browser()
            if not res["success"]:
                return res

        async def _nav():
            try:
                nav_url = url
                if not nav_url.startswith(("http://", "https://", "file://")):
                    nav_url = "https://" + nav_url
                    
                page = browser_session.current_page
                try:
                    await page.goto(nav_url, wait_until="commit", timeout=15000)
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning(f"Navigation error for {nav_url}: {e}")
                    await asyncio.sleep(2.0)
                
                return {"success": True, "message": f"Navigated to {nav_url}"}
            except Exception as e:
                return {"success": False, "message": f"Navigation failed: {str(e)}"}
                
        return await browser_session.run_in_pw_loop(_nav())
        
    async def interact(self, action: str, target_id: Optional[str] = None, value: Optional[str] = None) -> dict:
        if not browser_session.browser or not browser_session.current_page:
            return {"success": False, "message": "No active browser page."}
            
        async def _act():
            try:
                page = browser_session.current_page
                selector = f"[data-astra-id='{target_id}']" if target_id else None
                
                if action == "CLICK":
                    if not selector: return {"success": False, "message": "CLICK requires a target."}
                    try:
                        await page.click(selector, timeout=3000)
                    except Exception:
                        await page.evaluate("(sel) => { const el = document.querySelector(sel); if(el) el.click(); else throw new Error('Element not found'); }", selector)
                    
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=2000)
                    except Exception:
                        pass
                    await asyncio.sleep(1.0)
                    return {"success": True, "message": f"Clicked on target"}
                    
                elif action in ("TYPE", "FILL"):
                    if not selector or not value: return {"success": False, "message": f"{action} requires target and value."}
                    try:
                        await page.fill(selector, value, timeout=3000)
                    except Exception:
                        await page.evaluate("(args) => { const el = document.querySelector(args[0]); if(el){ el.value = args[1]; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); } else throw new Error('Element not found'); }", [selector, value])
                    
                    if action == "TYPE":
                        # Also press Enter automatically if it's a search field, often helpful
                        try:
                            await page.press(selector, "Enter", timeout=1000)
                            await asyncio.sleep(1.0)
                        except:
                            pass
                    
                    return {"success": True, "message": f"Typed text into target"}
                    
                elif action == "PRESS_KEY":
                    key = target_id or value
                    if not key: return {"success": False, "message": "PRESS_KEY requires a key string."}
                    await page.keyboard.press(key)
                    return {"success": True, "message": f"Pressed key {key}"}
                    
                elif action == "SCROLL":
                    direction = (target_id or "down").lower()
                    amount = 500 if direction == "down" else -500
                    await page.evaluate(f"window.scrollBy(0, {amount})")
                    return {"success": True, "message": f"Scrolled {direction}"}
                    
                elif action == "READ_DOM":
                    if selector:
                        element = await page.query_selector(selector)
                        if element:
                            text = await element.inner_text()
                            return {"success": True, "content": text}
                        return {"success": False, "message": f"Target not found."}
                    else:
                        text = await page.evaluate("document.body.innerText")
                        return {"success": True, "content": text[:5000]}
                        
                return {"success": False, "message": f"Unknown action: {action}"}
            except Exception as e:
                return {"success": False, "message": f"Interaction failed: {str(e)}"}
                
        return await browser_session.run_in_pw_loop(_act())

browser_executor = BrowserActionExecutor()
