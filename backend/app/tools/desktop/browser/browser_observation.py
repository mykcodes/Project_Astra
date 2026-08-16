from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class BrowserElement(BaseModel):
    id: str = Field(description="Internal semantic ID assigned to the element (e.g. ast-0)")
    tag: str = Field(description="HTML tag name")
    role: str = Field(description="Semantic role or input type")
    name: str = Field(description="Accessible name, text content, or label")
    href: str = Field(default="", description="Link URL if applicable")
    is_visible: bool = Field(default=True, description="Whether the element is currently visible")
    is_enabled: bool = Field(default=True, description="Whether the element is enabled and interactable")

class BrowserObservation(BaseModel):
    url: str = Field(description="Current page URL")
    title: str = Field(description="Current page title")
    elements: List[BrowserElement] = Field(default_factory=list, description="List of interactable semantic elements")
    human_verification_required: bool = Field(default=False, description="True if a human verification challenge is detected")
    page_ready: bool = Field(default=True, description="True if the page DOM has finished loading")

async def extract_observation(page) -> BrowserObservation:
    """
    Extracts generic semantic observation from the Playwright page.
    Does NOT contain website-specific logic.
    """
    if not page:
        return BrowserObservation(url="about:blank", title="No Page", elements=[])
        
    try:
        url = page.url
        title = await page.title()
    except Exception:
        url = "Unknown"
        title = "Unknown"

    # Check for challenges
    challenge_script = """
    () => {
        return !!document.querySelector('iframe[src*="challenges.cloudflare.com"], iframe[title*="reCAPTCHA"], iframe[src*="hcaptcha.com"]');
    }
    """
    try:
        has_challenge = await page.evaluate(challenge_script)
    except Exception:
        has_challenge = False

    # Extract interactive elements semantically
    extraction_script = """
    () => {
        let elements = document.querySelectorAll('button, input, textarea, a, select, [role="button"], [role="link"], [role="menuitem"], [role="tab"], [tabindex]:not([tabindex="-1"])');
        let interactive = [];
        let id_counter = 0;
        document.querySelectorAll('[data-astra-id]').forEach(el => el.removeAttribute('data-astra-id'));
        
        elements.forEach(el => {
            let rect = el.getBoundingClientRect();
            let style = window.getComputedStyle(el);
            let isVisible = rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0';
            
            if (isVisible) {
                let ast_id = 'ast-' + id_counter++;
                el.setAttribute('data-astra-id', ast_id);
                
                let label = el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.title || el.name || '';
                label = label.trim().replace(/\\n/g, ' ').substring(0, 150);
                
                let href = el.getAttribute('href') || '';
                
                let isEnabled = !el.hasAttribute('disabled') && el.getAttribute('aria-disabled') !== 'true';
                
                if (label || el.tagName.toLowerCase() === 'input' || href) {
                    interactive.push({
                        id: ast_id,
                        tag: el.tagName.toLowerCase(),
                        role: el.getAttribute('role') || el.getAttribute('type') || '',
                        name: label,
                        href: href,
                        is_visible: isVisible,
                        is_enabled: isEnabled
                    });
                }
            }
        });
        return interactive;
    }
    """
    
    try:
        raw_elements = await page.evaluate(extraction_script)
        elements = [BrowserElement(**el) for el in raw_elements]
    except Exception:
        elements = []
        
    return BrowserObservation(
        url=url,
        title=title,
        elements=elements,
        human_verification_required=has_challenge,
        page_ready=True
    )
