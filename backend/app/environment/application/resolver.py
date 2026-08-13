from typing import List, Dict, Any
from app.environment.application.catalog import catalog
from app.environment.models import ApplicationEntity

class ApplicationResolver:
    def resolve(self, application_name: str, blocked_apps: List[str] = None, force_refresh: bool = False) -> Dict[str, Any]:
        if not application_name:
            return {
                "status": "NOT_FOUND",
                "confidence": 0.0,
                "candidate": None,
                "alternatives": []
            }
            
        norm_input = catalog._normalize_name(application_name)
        blocked_apps = [catalog._normalize_name(b) for b in (blocked_apps or [])]
        
        if norm_input in blocked_apps:
            return {
                "status": "BLOCKED",
                "confidence": 1.0,
                "candidate": None,
                "alternatives": []
            }
            
        catalog.refresh(force=force_refresh)
        apps = catalog.get_all()
        
        # 1. Exact canonical match (normalized)
        if norm_input in apps:
            candidate = apps[norm_input]
            if candidate.normalized_name in blocked_apps:
                return {"status": "BLOCKED", "confidence": 1.0, "candidate": None, "alternatives": []}
            return {
                "status": "RESOLVED",
                "confidence": 1.0,
                "candidate": candidate,
                "alternatives": []
            }
            
        # 2. Fuzzy match
        matches = []
        for cached_norm, cached_data in apps.items():
            if norm_input in cached_norm or cached_norm in norm_input:
                matches.append(cached_data)
                
        if len(matches) == 1:
            candidate = matches[0]
            if candidate.normalized_name in blocked_apps:
                return {"status": "BLOCKED", "confidence": 1.0, "candidate": None, "alternatives": []}
            candidate.confidence = 0.8
            return {
                "status": "RESOLVED",
                "confidence": 0.8,
                "candidate": candidate,
                "alternatives": []
            }
            
        if len(matches) > 1:
            return {
                "status": "AMBIGUOUS",
                "confidence": 0.5,
                "candidate": None,
                "alternatives": matches
            }
            
        return {
            "status": "NOT_FOUND",
            "confidence": 0.0,
            "candidate": None,
            "alternatives": []
        }

resolver = ApplicationResolver()
