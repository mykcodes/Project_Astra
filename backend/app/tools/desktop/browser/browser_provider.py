from typing import Optional, Dict, Any
from app.core.logging.logger import get_logger
from app.tools.desktop.browser.browser_session import browser_session
from app.tools.desktop.browser.browser_observation import extract_observation, BrowserObservation
from app.tools.desktop.browser.browser_resolver import browser_resolver
from app.tools.desktop.browser.browser_executor import browser_executor

logger = get_logger(__name__)

class BrowserProvider:
    """
    Coordinates the autonomous browser execution lifecycle:
    OBSERVE -> RESOLVE -> ACT -> RE-OBSERVE -> VERIFY
    """
    
    async def get_state(self) -> dict:
        return await browser_session.get_state()
        
    async def check_challenges(self) -> dict:
        if not browser_session.browser or not browser_session.current_page:
            return {"success": True}
            
        async def _check():
            obs = await extract_observation(browser_session.current_page)
            if obs.human_verification_required:
                return {"success": False, "error": {"code": "HUMAN_VERIFICATION_REQUIRED", "message": "Human verification challenge detected."}}
            return {"success": True, "message": "No challenge detected."}
            
        return await browser_session.run_in_pw_loop(_check())
        
    async def execute_intent(self, intent: str, target: Optional[str] = None) -> dict:
        """Handles high-level navigation intents like SEARCH or NAVIGATE."""
        intent = intent.upper()
        
        # ACT
        if intent == "SEARCH":
            if not target: return {"success": False, "message": "SEARCH intent requires a target query."}
            import urllib.parse
            encoded = urllib.parse.quote_plus(target)
            res = await browser_executor.navigate(f"https://www.google.com/search?q={encoded}")
        elif intent == "NAVIGATE":
            if not target: return {"success": False, "message": "NAVIGATE intent requires a target URL."}
            res = await browser_executor.navigate(target)
        else:
            return {"success": False, "message": f"Unsupported intent: {intent}"}
            
        if not res["success"]:
            return res
            
        # RE-OBSERVE
        obs_res = await self._observe()
        if not obs_res["success"]:
            return obs_res
            
        obs: BrowserObservation = obs_res["observation"]
        
        # VERIFY
        if obs.human_verification_required:
            return {"success": False, "error": {"code": "HUMAN_VERIFICATION_REQUIRED", "message": "Human verification challenge detected."}}
            
        return {"success": True, "message": res["message"], "verified": True}

    async def interact(self, action: str, target_description: Optional[str] = None, value: Optional[str] = None) -> dict:
        """Handles page interactions with semantic resolution."""
        action = action.upper()
        
        # 1. OBSERVE
        obs_res = await self._observe()
        if not obs_res["success"]:
            return obs_res
        obs: BrowserObservation = obs_res["observation"]
        
        if obs.human_verification_required:
            return {"success": False, "error": {"code": "HUMAN_VERIFICATION_REQUIRED", "message": "Human verification challenge detected."}}
            
        target_id = None
        # 2. RESOLVE
        if target_description and action in ("CLICK", "TYPE", "FILL", "HOVER"):
            el = await browser_resolver.resolve(target_description, obs)
            if not el:
                return {"success": False, "message": f"Could not resolve semantic target: {target_description}"}
            target_id = el.id
            
        # 3. ACT
        res = await browser_executor.interact(action, target_id=target_id, value=value)
        if not res["success"]:
            return res
            
        # 4. RE-OBSERVE
        post_obs_res = await self._observe()
        if not post_obs_res["success"]:
            return post_obs_res
        post_obs: BrowserObservation = post_obs_res["observation"]
        
        # 5. VERIFY
        if post_obs.human_verification_required:
            return {"success": False, "error": {"code": "HUMAN_VERIFICATION_REQUIRED", "message": "Human verification challenge detected."}}
            
        # Simple verification: action didn't crash and we aren't blocked by captcha.
        # In a richer implementation, we could verify the exact state change.
        return {"success": True, "message": res.get("message", ""), "content": res.get("content", ""), "verified": True}

    async def _observe(self) -> dict:
        if not browser_session.browser or not browser_session.current_page:
            return {"success": False, "message": "No active browser page."}
            
        async def _run_ext():
            return await extract_observation(browser_session.current_page)
            
        try:
            obs = await browser_session.run_in_pw_loop(_run_ext())
            return {"success": True, "observation": obs}
        except Exception as e:
            return {"success": False, "message": f"Observation failed: {str(e)}"}

browser_provider = BrowserProvider()
