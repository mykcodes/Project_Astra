import uuid
import hashlib
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class BrowserElement(BaseModel):
    id: str = Field(description="Internal semantic ID assigned to the element (e.g. ast-obsid-0)")
    tag: str = Field(description="HTML tag name")
    role: str = Field(description="Semantic role or input type")
    name: str = Field(description="Accessible name, text content, or label")
    href: str = Field(default="", description="Link URL if applicable")
    is_visible: bool = Field(default=True, description="Whether the element is currently visible")
    is_enabled: bool = Field(default=True, description="Whether the element is enabled and interactable")

class MediaElement(BaseModel):
    tag: str = Field(description="HTML tag name, typically 'video' or 'audio'")
    src: Optional[str] = Field(default=None, description="Media source URL")
    paused: bool = Field(description="Whether the media is currently paused")
    current_time: float = Field(description="Current playback time in seconds")
    duration: float = Field(description="Total duration in seconds")
    ended: bool = Field(description="Whether playback has ended")
    ready_state: int = Field(description="Media ready state (0-4)")
    muted: bool = Field(description="Whether the media is muted")
    volume: float = Field(description="Current volume (0.0 to 1.0)")

class BrowserObservation(BaseModel):
    observation_id: str = Field(description="Unique ID for this observation instance")
    browser_session_id: str = Field(default="", description="The browser session ID")
    page_id: str = Field(default="", description="The internal page ID")
    url: str = Field(description="Current page URL")
    title: str = Field(description="Current page title")
    page_signature: str = Field(default="", description="Hash representation of page state for change detection")
    navigation_state: str = Field(default="UNKNOWN", description="Current navigation state")
    loading_state: str = Field(default="UNKNOWN", description="Current loading state")
    challenge_state: str = Field(default="NONE", description="CAPTCHA/challenge state")
    elements: List[BrowserElement] = Field(default_factory=list, description="List of interactable semantic elements")
    media_elements: List[MediaElement] = Field(default_factory=list, description="List of media elements on the page")
    iframes_count: int = Field(default=0, description="Number of iframes on the page")
    human_verification_required: bool = Field(default=False, description="True if a human verification challenge is detected")
    page_ready: bool = Field(default=True, description="True if the page DOM has finished loading")
    document_stability: str = Field(default="UNKNOWN", description="Document stability indicator (e.g. complete, interactive, loading)")

async def extract_observation(page, session_id: str = "", page_id: str = "") -> BrowserObservation:
    """
    Extracts generic semantic observation from the Playwright page.
    Does NOT contain website-specific logic.
    """
    obs_id = f"obs-{uuid.uuid4().hex[:8]}"
    if not page:
        return BrowserObservation(
            observation_id=obs_id, browser_session_id=session_id, page_id=page_id,
            url="about:blank", title="No Page", 
            elements=[], media_elements=[], iframes_count=0
        )
        
    try:
        url = page.url
        title = await page.title()
    except Exception:
        url = "Unknown"
        title = "Unknown"

    # Check for challenges
    challenge_script = """
    () => {
        return !!document.querySelector('iframe[src*="challenges.cloudflare.com"], iframe[title*="reCAPTCHA"], iframe[src*="hcaptcha.com"], div#cf-please-wait');
    }
    """
    try:
        has_challenge = await page.evaluate(challenge_script)
    except Exception:
        has_challenge = False
        
    challenge_state = "DETECTED" if has_challenge else "NONE"
    
    try:
        stability = await page.evaluate("() => document.readyState")
    except Exception:
        stability = "UNKNOWN"

    # Extract interactive elements semantically
    extraction_script = f"""
    () => {{
        let elements = document.querySelectorAll('button, input, textarea, a, select, [role="button"], [role="link"], [role="menuitem"], [role="tab"], [tabindex]:not([tabindex="-1"])');
        let interactive = [];
        let id_counter = 0;
        let obs_id = '{obs_id}';
        document.querySelectorAll('[data-astra-id]').forEach(el => el.removeAttribute('data-astra-id'));
        
        elements.forEach(el => {{
            let rect = el.getBoundingClientRect();
            let style = window.getComputedStyle(el);
            let isVisible = rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0';
            
            if (isVisible) {{
                let ast_id = obs_id + '-' + id_counter++;
                el.setAttribute('data-astra-id', ast_id);
                
                let label = el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.title || el.name || '';
                label = label.trim().replace(/\\n/g, ' ').substring(0, 150);
                
                let href = el.getAttribute('href') || '';
                if (href.length > 100) href = href.substring(0, 100) + '...';
                
                let isEnabled = !el.hasAttribute('disabled') && el.getAttribute('aria-disabled') !== 'true';
                
                if (label || el.tagName.toLowerCase() === 'input' || href) {{
                    interactive.push({{
                        id: ast_id,
                        tag: el.tagName.toLowerCase(),
                        role: el.getAttribute('role') || el.getAttribute('type') || '',
                        name: label,
                        href: href,
                        is_visible: isVisible,
                        is_enabled: isEnabled
                    }});
                }}
            }}
        }});
        return interactive;
    }}
    """
    
    try:
        raw_elements = await page.evaluate(extraction_script)
        elements = [BrowserElement(**el) for el in raw_elements]
    except Exception:
        elements = []
        
    media_script = """
    () => {
        let media = document.querySelectorAll('video, audio');
        let results = [];
        media.forEach(m => {
            let src = m.src || m.currentSrc || '';
            if (src.length > 100) { src = src.substring(0, 100) + '...'; }
            
            results.push({
                tag: m.tagName.toLowerCase(),
                src: src,
                paused: m.paused,
                current_time: m.currentTime || 0.0,
                duration: m.duration || 0.0,
                ended: m.ended,
                ready_state: m.readyState,
                muted: m.muted,
                volume: m.volume || 1.0
            });
        });
        return results;
    }
    """
    
    try:
        raw_media = await page.evaluate(media_script)
        media_elements = [MediaElement(**m) for m in raw_media]
    except Exception:
        media_elements = []
        
    try:
        iframes_count = await page.evaluate("() => document.querySelectorAll('iframe').length")
    except Exception:
        iframes_count = 0
        
    sig_content = f"{url}|{len(elements)}|{len(media_elements)}"
    page_sig = hashlib.sha256(sig_content.encode()).hexdigest()[:16]
        
    return BrowserObservation(
        observation_id=obs_id,
        browser_session_id=session_id,
        page_id=page_id,
        url=url,
        title=title,
        page_signature=page_sig,
        navigation_state="IDLE",
        loading_state="COMPLETE",
        challenge_state=challenge_state,
        elements=elements,
        media_elements=media_elements,
        iframes_count=iframes_count,
        human_verification_required=has_challenge,
        page_ready=(stability == "complete"),
        document_stability=stability
    )
