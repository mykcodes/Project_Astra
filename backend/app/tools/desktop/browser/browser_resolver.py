import re
from typing import Optional, List
from app.core.logging.logger import get_logger
from app.tools.desktop.browser.browser_observation import BrowserObservation, BrowserElement

logger = get_logger(__name__)

class BrowserTargetResolver:
    """
    Resolves semantic targets (e.g., "first video", "search button") into 
    concrete DOM elements using deterministic rules and heuristic ranking.
    """

    async def resolve(self, target_description: str, observation: BrowserObservation) -> Optional[BrowserElement]:
        if not target_description or not observation.elements:
            return None
            
        target_description = target_description.lower().strip()
        
        # Level 1: Exact Match or ID Match
        for el in observation.elements:
            # If the LLM somehow already passed the internal ID
            if el.id == target_description:
                return el
            
            # Exact name match
            if el.name.lower().strip() == target_description:
                return el
                
        # Level 2: Deterministic Semantic Ranking
        scored_elements = []
        for el in observation.elements:
            score = 0
            name_lower = el.name.lower()
            role_lower = el.role.lower()
            tag_lower = el.tag.lower()
            href_lower = el.href.lower()
            
            # Partial text match
            if target_description in name_lower:
                score += 5
            
            # Substring text match
            words = target_description.split()
            for word in words:
                if len(word) > 2 and word in name_lower:
                    score += 2
                    
            # Semantic role matching
            if "search" in target_description and ("search" in name_lower or "search" in role_lower):
                score += 10
                
            if "video" in target_description and ("video" in name_lower or "watch" in href_lower or tag_lower == "video"):
                score += 10
                
            if "button" in target_description and (tag_lower == "button" or role_lower == "button"):
                score += 5
                
            if "link" in target_description and (tag_lower == "a" or role_lower == "link"):
                score += 5
                
            if "input" in target_description or "type" in target_description or "field" in target_description:
                if tag_lower in ["input", "textarea"] or role_lower in ["textbox", "search"]:
                    score += 5
                    
            if score > 0:
                scored_elements.append((score, el))
                
        if scored_elements:
            # Sort by score descending
            scored_elements.sort(key=lambda x: x[0], reverse=True)
            
            # If the user asked for "first", "second", etc.
            if "first" in target_description:
                return scored_elements[0][1]
            if "second" in target_description and len(scored_elements) > 1:
                return scored_elements[1][1]
            if "third" in target_description and len(scored_elements) > 2:
                return scored_elements[2][1]
                
            # Otherwise return the highest scoring element
            logger.info(f"Resolved '{target_description}' to element {scored_elements[0][1].id} with score {scored_elements[0][0]}")
            return scored_elements[0][1]
            
        # Level 3: Semantic Fallback
        # In a full implementation, this could call an LLM with the observation.
        # For now, we return None if heuristics fail.
        logger.warning(f"Could not deterministically resolve target: {target_description}")
        return None

browser_resolver = BrowserTargetResolver()
