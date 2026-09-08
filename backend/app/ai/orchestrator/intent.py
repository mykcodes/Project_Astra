from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field

class IntentDomain(str, Enum):
    DESKTOP = "desktop"
    SYSTEM = "system"
    BROWSER = "browser"
    FILESYSTEM = "filesystem"
    INTERACTION = "interaction"
    UNKNOWN = "unknown"

class NormalizedIntent(BaseModel):
    domain: IntentDomain
    action: str
    target: Optional[str] = None
    browser_name: Optional[str] = None
    expected_outcome: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    
    @classmethod
    def desktop(cls, action: str, target: str, expected_outcome: Optional[str] = None, **kwargs):
        return cls(domain=IntentDomain.DESKTOP, action=action, target=target, expected_outcome=expected_outcome, parameters=kwargs)
        
    @classmethod
    def system(cls, action: str, expected_outcome: Optional[str] = None, **kwargs):
        return cls(domain=IntentDomain.SYSTEM, action=action, expected_outcome=expected_outcome, parameters=kwargs)
        
    @classmethod
    def browser(cls, action: str, target: str, browser_name: Optional[str] = None, expected_outcome: Optional[str] = None, **kwargs):
        return cls(domain=IntentDomain.BROWSER, action=action, target=target, browser_name=browser_name, expected_outcome=expected_outcome, parameters=kwargs)
        
    @classmethod
    def filesystem(cls, action: str, target: str, expected_outcome: Optional[str] = None, **kwargs):
        return cls(domain=IntentDomain.FILESYSTEM, action=action, target=target, expected_outcome=expected_outcome, parameters=kwargs)
