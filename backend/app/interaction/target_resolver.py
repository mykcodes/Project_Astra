import time
from typing import List, Dict, Any, Optional, Tuple
from app.interaction.models import UIElement, WindowTarget, InteractionTarget
from app.interaction.ui.engine import ui_engine
from app.environment.window.manager import window_manager
from app.core.logging.logger import get_logger
from app.interaction.capability_manager import capability_manager

logger = get_logger(__name__)

class TargetResolver:
    def __init__(self):
        self.last_resolution_latency: float = 0.0
        
    def resolve_ui_target(self, hwnd: int, query: str, expected_type: Optional[str] = None, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Resolves a natural language query into a specific UI element within a window.
        Returns a strict resolution dictionary.
        """
        start_time = time.time()
        
        if not query:
            return {"status": "INVALID_QUERY", "element": None, "reason": "Empty query provided"}
            
        elements = ui_engine.discover_ui_tree(hwnd, force_refresh=force_refresh)
        
        if not elements:
            cap = capability_manager.inspect_window(hwnd)
            return {
                "status": "UI_AUTOMATION_UNAVAILABLE" if cap["status"] == "UI_AUTOMATION_UNAVAILABLE" else "UI_TREE_EMPTY",
                "element": None,
                "reason": cap["reason"],
                "capability": cap
            }
            
        candidates = self._score_candidates(elements, query, expected_type)
        
        self.last_resolution_latency = time.time() - start_time
        
        if not candidates:
            return {
                "status": "UI_ELEMENT_NOT_FOUND", 
                "element": None, 
                "reason": f"No elements matched '{query}'",
                "diagnostics": {
                    "candidate_count": 0,
                    "resolution_latency_ms": self.last_resolution_latency * 1000
                }
            }
            
        best_score = candidates[0]["score"]
        
        # Check for ambiguity (multiple elements with identical top scores)
        top_candidates = [c for c in candidates if c["score"] == best_score]
        
        if len(top_candidates) > 1 and best_score < 1.0:
            return {
                "status": "UI_ELEMENT_AMBIGUOUS",
                "element": None,
                "reason": f"Found {len(top_candidates)} elements equally matching '{query}'",
                "diagnostics": {
                    "candidate_count": len(candidates),
                    "ambiguous_candidates": [c["element"].name or c["element"].automation_id for c in top_candidates],
                    "best_score": best_score,
                    "resolution_latency_ms": self.last_resolution_latency * 1000
                }
            }
            
        # Top candidate
        best_match = top_candidates[0]
        element = best_match["element"]
        score = best_match["score"]
        
        # Confidence threshold
        if score < 0.6:
            return {
                "status": "UI_ELEMENT_NOT_FOUND",
                "element": None,
                "reason": f"Best match for '{query}' had low confidence ({score})",
                "diagnostics": {
                    "candidate_count": len(candidates),
                    "best_score": score,
                    "matching_properties": best_match["matching_properties"],
                    "resolution_latency_ms": self.last_resolution_latency * 1000
                }
            }
            
        return {
            "status": "RESOLVED",
            "element": element,
            "confidence": score,
            "diagnostics": {
                "candidate_count": len(candidates),
                "selected": element.name or element.automation_id,
                "matching_properties": best_match["matching_properties"],
                "resolution_latency_ms": self.last_resolution_latency * 1000
            }
        }

    def _score_candidates(self, elements: List[UIElement], query: str, expected_type: Optional[str] = None) -> List[Dict[str, Any]]:
        q_lower = query.lower().strip()
        scored = []
        
        for el in elements:
            # Skip invisible elements immediately unless specifically searching for them (rare)
            if not el.visible and not el.bounding_rectangle:
                continue
                
            score = 0.0
            matched_props = []
            
            # 1. Exact Automation ID
            if el.automation_id and q_lower == el.automation_id.lower():
                score = 1.0
                matched_props.append("automation_id")
                
            # 2. Exact Name Match
            elif el.name and q_lower == el.name.lower():
                score = 0.95
                matched_props.append("name_exact")
                if expected_type and expected_type.lower() in el.control_type.lower():
                    score = 0.98
                    matched_props.append("control_type")
                    
            # 3. Contains Name Match
            elif el.name and q_lower in el.name.lower():
                score = 0.8
                matched_props.append("name_contains")
                length_diff = len(el.name) - len(query)
                score -= min(0.15, length_diff * 0.01)
                
            # 4. Class Name fallback
            elif el.class_name and q_lower == el.class_name.lower():
                score = 0.7
                matched_props.append("class_name")
                
            # Control type boost/penalty
            if score > 0:
                if expected_type:
                    if expected_type.lower() in el.control_type.lower():
                        score += 0.02
                        if "control_type" not in matched_props:
                            matched_props.append("control_type")
                    else:
                        score -= 0.1
                        
            if score >= 0.5:
                scored.append({
                    "element": el,
                    "score": score,
                    "matching_properties": matched_props
                })
                
        # Sort descending by score
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored



    def resolve_window_target(self, app_name: str, hwnd_hint: Optional[int] = None) -> Dict[str, Any]:
        """Resolves the most appropriate window for an application"""
        from app.environment.application.state_engine import state_engine
        
        if hwnd_hint:
            cap = ui_engine.check_capability(hwnd_hint)
            return {
                "status": "RESOLVED",
                "window": WindowTarget(
                    hwnd=hwnd_hint,
                    process_id=0,
                    title="",
                    automation_support=cap["status"]
                )
            }
            
        state = state_engine.get_state(app_name)
        if state["state"] in ("UNKNOWN", "NOT_INSTALLED", "INSTALLED_NOT_RUNNING"):
            return {"status": "WINDOW_NOT_FOUND", "window": None, "reason": f"App '{app_name}' is not running"}
            
        windows = state.get("windows", [])
        if not windows:
            return {"status": "WINDOW_NOT_FOUND", "window": None, "reason": f"App '{app_name}' has no visible windows"}
            
        # Prefer foreground, then visible
        best_w = None
        for w in windows:
            if w.get("foreground"):
                best_w = w
                break
                
        if not best_w:
            for w in windows:
                if not w.get("minimized"):
                    best_w = w
                    break
                    
        if not best_w:
            best_w = windows[0]
            
        hwnd = best_w["hwnd"]
        cap = ui_engine.check_capability(hwnd)
        
        return {
            "status": "RESOLVED",
            "window": WindowTarget(
                hwnd=hwnd,
                process_id=best_w.get("pid", 0),
                title=best_w.get("title", ""),
                automation_support=cap["status"]
            )
        }

target_resolver = TargetResolver()
