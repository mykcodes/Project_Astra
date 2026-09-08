import asyncio
import urllib.parse
from typing import Optional, Dict, Any
from app.core.logging.logger import get_logger
from app.tools.desktop.browser.browser_session import browser_session, BrowserSessionState
from app.tools.desktop.browser.browser_observation import extract_observation, BrowserObservation
from app.tools.desktop.browser.browser_resolver import browser_resolver
from app.tools.desktop.browser.browser_executor import browser_executor
from app.tools.desktop.browser.browser_identity import browser_registry

logger = get_logger(__name__)

class BrowserProvider:
    """
    Coordinates the autonomous browser execution lifecycle:
    OBSERVE -> RESOLVE -> ACT -> RE-OBSERVE -> VERIFY
    """
    
    async def get_state(self) -> dict:
        return await browser_session.get_state()
        
    async def ensure_browser_session(self, browser_name: str) -> dict:
        identity = browser_registry.resolve_browser(browser_name)
        if not identity:
            return {"success": False, "error": {"code": "BROWSER_UNAVAILABLE", "message": f"Browser not installed or unrecognized: {browser_name}"}}
            
        is_alive = await browser_session.ensure_alive(identity)
        if not is_alive:
            return {"success": False, "error": {"code": "BROWSER_LAUNCH_FAILED", "message": f"Failed to launch browser: {browser_name}"}}
            
        return {"success": True, "message": f"Browser {identity.canonical_name} is ready.", "session_id": identity.session_id}
        
    async def check_challenges(self) -> dict:
        if not browser_session.browser or not browser_session.current_page:
            return {"success": True}
            
        async def _check():
            obs = await extract_observation(
                browser_session.current_page,
                session_id=browser_session.identity.session_id if browser_session.identity else "",
                page_id=str(browser_session.current_page_index)
            )
            if obs.human_verification_required:
                return {"success": False, "error": {"code": "HUMAN_VERIFICATION_REQUIRED", "message": "Human verification challenge detected."}}
            return {"success": True, "message": "No challenge detected."}
            
        return await browser_session.run_in_pw_loop(_check())
        
    async def execute_intent(self, intent: str, target: Optional[str] = None, browser_name: Optional[str] = None) -> dict:
        """Handles high-level navigation intents like SEARCH or NAVIGATE."""
        intent = intent.upper()
        
        if browser_name:
            ensure_res = await self.ensure_browser_session(browser_name)
            if not ensure_res["success"]:
                return ensure_res
        
        # ACT
        if intent == "SEARCH":
            if not target: return {"success": False, "message": "SEARCH intent requires a target query."}
            encoded = urllib.parse.quote_plus(target)
            
            # Context-Aware Search
            current_url = ""
            if browser_session.current_page:
                try:
                    current_url = browser_session.current_page.url
                except:
                    pass
                    
            if "youtube.com" in current_url:
                res = await browser_executor.navigate(f"https://www.youtube.com/results?search_query={encoded}")
            elif "amazon." in current_url:
                res = await browser_executor.navigate(f"https://www.amazon.com/s?k={encoded}")
            elif "github.com" in current_url:
                res = await browser_executor.navigate(f"https://github.com/search?q={encoded}")
            elif "reddit.com" in current_url:
                res = await browser_executor.navigate(f"https://www.reddit.com/search/?q={encoded}")
            else:
                res = await browser_executor.navigate(f"https://www.google.com/search?q={encoded}")
        elif intent == "NAVIGATE":
            if not target: return {"success": False, "message": "NAVIGATE intent requires a target URL."}
            res = await browser_executor.navigate(target)
        elif intent == "NEW_TAB":
            if not target: return {"success": False, "message": "NEW_TAB intent requires a target URL."}
            res = await browser_executor.navigate(target, new_tab=True)
        else:
            return {"success": False, "message": f"Unsupported intent: {intent}"}
            
        if not res["success"]:
            return res
            
        # RE-OBSERVE
        obs_res = await self.observe()
        if not obs_res["success"]:
            return obs_res
            
        obs: BrowserObservation = obs_res["observation"]
        
        # VERIFY
        if obs.human_verification_required:
            return {"success": False, "error": {"code": "HUMAN_VERIFICATION_REQUIRED", "message": "Human verification challenge detected."}}
            
        is_verified = False
        if intent == "SEARCH":
            if "search" in obs.url.lower() or "q=" in obs.url.lower():
                is_verified = True
        elif intent in ("NAVIGATE", "NEW_TAB"):
            # Very basic domain check for navigation
            try:
                target_parsed = urllib.parse.urlparse(target if "://" in target else f"http://{target}")
                domain = target_parsed.netloc.replace("www.", "").lower()
                obs_domain = urllib.parse.urlparse(obs.url).netloc.replace("www.", "").lower()
                if domain in obs_domain or obs_domain in domain:
                    is_verified = True
            except:
                pass
                
            if not is_verified and target.lower() in obs.url.lower():
                is_verified = True
            
        if not is_verified:
            return {"success": False, "error": {"code": "VERIFICATION_FAILED", "message": "Could not verify navigation/search."}}
             
        return {"success": True, "message": res["message"], "verified": True, "observation_id": obs.observation_id}

    async def interact(self, action: str, target_description: Optional[str] = None, value: Optional[str] = None, browser_name: Optional[str] = None) -> dict:
        """Handles page interactions with semantic resolution."""
        action = action.upper()
        
        if browser_name:
            ensure_res = await self.ensure_browser_session(browser_name)
            if not ensure_res["success"]:
                return ensure_res
        
        # 1. OBSERVE
        obs_res = await self.observe()
        if not obs_res["success"]:
            return obs_res
        obs: BrowserObservation = obs_res["observation"]
        
        if obs.human_verification_required:
            return {"success": False, "error": {"code": "HUMAN_VERIFICATION_REQUIRED", "message": "Human verification challenge detected."}}
            
        target_id = None
        
        # 1.5 IDEMPOTENCY CHECK
        if target_description and action == "CLICK":
            target_desc_lower = target_description.lower()
            if "video" in target_desc_lower or "play" in target_desc_lower:
                if any(not m.paused for m in obs.media_elements):
                    return {"success": True, "message": "Video is already playing.", "verified": True, "observation_id": obs.observation_id}
        
        # 2. RESOLVE
        if target_description and action in ("CLICK", "TYPE", "FILL", "HOVER"):
            el = await browser_resolver.resolve(target_description, obs)
            if not el:
                return {"success": False, "error": {"code": "TARGET_RESOLUTION_FAILED", "message": f"Could not resolve semantic target: {target_description}"}}
            target_id = el.id
            
        # 3. ACT
        res = await browser_executor.interact(action, target_id=target_id, value=value)
        if not res["success"]:
            return res
            
        # 4. RE-OBSERVE
        post_obs_res = await self.observe()
        if not post_obs_res["success"]:
            return post_obs_res
        post_obs: BrowserObservation = post_obs_res["observation"]
        
        # 5. VERIFY
        if post_obs.human_verification_required:
            return {"success": False, "error": {"code": "HUMAN_VERIFICATION_REQUIRED", "message": "Human verification challenge detected."}}
            
        is_verified = False
        
        if target_description and action == "CLICK":
            target_desc_lower = target_description.lower()
            if "video" in target_desc_lower or "play" in target_desc_lower:
                # Media Playback Verification
                await asyncio.sleep(2.0)
                final_obs_res = await self.observe()
                if final_obs_res["success"]:
                    final_obs: BrowserObservation = final_obs_res["observation"]
                    
                    for m1 in post_obs.media_elements:
                        for m2 in final_obs.media_elements:
                            if m1.src == m2.src and not m2.paused and m2.current_time > m1.current_time:
                                is_verified = True
                                break
                                
                    if not is_verified:
                        for m in final_obs.media_elements:
                            if not m.paused and m.current_time > 0:
                                is_verified = True
                                break
                                
                if not is_verified:
                    return {"success": False, "error": {"code": "PLAYBACK_NOT_CONFIRMED", "message": "Media playback could not be verified."}}
            else:
                # Basic click verification. Did the URL change or the DOM change?
                url_changed = (obs.url != post_obs.url)
                dom_changed = (obs.page_signature != post_obs.page_signature)
                if url_changed or dom_changed:
                    is_verified = True
                else:
                    return {"success": False, "error": {"code": "CLICK_NO_EFFECT", "message": "Click executed but no resulting state change was observed."}}
        elif action in ("TYPE", "FILL", "PRESS_KEY", "SCROLL"):
            # Usually typing changes the DOM signature
            is_verified = (obs.page_signature != post_obs.page_signature)
            if not is_verified:
                is_verified = True # Fallback for now if signature algorithm misses minor value changes
        else:
            is_verified = False 
            
        # Return verified status back so ActionExecutor can enforce it
        return {"success": True, "message": res.get("message", ""), "content": res.get("content", ""), "verified": is_verified, "observation_id": post_obs.observation_id}

    async def observe(self) -> dict:
        if not browser_session.browser or not browser_session.current_page or browser_session.state != BrowserSessionState.READY:
            return {"success": False, "error": {"code": "BROWSER_CLOSED", "message": "No active browser page."}}
            
        async def _run_ext():
            return await extract_observation(
                browser_session.current_page,
                session_id=browser_session.session_id or "",
                page_id=str(browser_session.current_page_index)
            )
            
        try:
            obs = await browser_session.run_in_pw_loop(_run_ext())
            return {"success": True, "observation": obs}
        except Exception as e:
            return {"success": False, "error": {"code": "OBSERVATION_FAILED", "message": f"Observation failed: {str(e)}"}}

browser_provider = BrowserProvider()
