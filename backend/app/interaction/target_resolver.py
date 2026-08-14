import time
from typing import List, Dict, Any, Optional
from app.interaction.models import UIElement, UIWindow, UIQueryResult
from app.interaction.ui.engine import ui_engine
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class TargetResolver:
    def __init__(self):
        self.last_resolution_latency: float = 0.0
        
    def resolve_ui_target(self, hwnd: int, query: str, expected_type: Optional[str] = None, force_refresh: bool = False) -> UIQueryResult:
        """Resolves a natural language query into a specific UI element within a window observation."""
        start_time = time.time()
        
        obs = ui_engine.observe_window(hwnd, force=force_refresh)
        elements = list(obs.elements.values())
        
        result = UIQueryResult(
            query=query,
            status="NOT_FOUND",
            candidate_count=0,
            observation_id=obs.observation_id
        )
        
        if not query:
            result.status = "INVALID_QUERY"
            return result
            
        if not elements:
            result.status = "UI_TREE_EMPTY"
            return result
            
        candidates = self._score_candidates(elements, query, expected_type)
        self.last_resolution_latency = time.time() - start_time
        result.candidate_count = len(candidates)
        
        if not candidates:
            return result
            
        best_score = candidates[0]["score"]
        top_candidates = [c for c in candidates if c["score"] == best_score]
        
        if len(top_candidates) > 1 and best_score < 1.0:
            result.status = "TARGET_AMBIGUOUS"
            result.confidence = best_score
            result.ambiguous_candidates = [c["element"].runtime_id for c in top_candidates]
            return result
            
        best_match = top_candidates[0]
        score = best_match["score"]
        
        if score < 0.6:
            result.status = "TARGET_NOT_FOUND" # Low confidence rejection
            result.confidence = score
            result.matching_properties = best_match["matching_properties"]
            return result
            
        result.status = "RESOLVED"
        result.selected_candidate = best_match["element"]
        result.confidence = score
        result.matching_properties = best_match["matching_properties"]
        return result

    def _score_candidates(self, elements: List[UIElement], query: str, expected_type: Optional[str] = None) -> List[Dict[str, Any]]:
        q_lower = query.lower().strip()
        scored = []
        
        for el in elements:
            if not el.state.visible and not el.bounding_rectangle:
                continue
                
            score = 0.0
            matched_props = []
            
            if el.automation_id and q_lower == el.automation_id.lower():
                score = 1.0
                matched_props.append("automation_id")
            elif el.name and q_lower == el.name.lower():
                score = 0.95
                matched_props.append("name_exact")
                if expected_type and expected_type.lower() in el.control_type.lower():
                    score = 0.98
                    matched_props.append("control_type")
            elif el.name and q_lower in el.name.lower():
                score = 0.8
                matched_props.append("name_contains")
                length_diff = len(el.name) - len(query)
                score -= min(0.15, length_diff * 0.01)
            elif el.class_name and q_lower == el.class_name.lower():
                score = 0.7
                matched_props.append("class_name")
                
            if score > 0 and expected_type:
                if expected_type.lower() in el.control_type.lower():
                    score += 0.02
                    if "control_type" not in matched_props: matched_props.append("control_type")
                else:
                    score -= 0.1
                    
            if score >= 0.5:
                scored.append({"element": el, "score": score, "matching_properties": matched_props})
                
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

target_resolver = TargetResolver()
