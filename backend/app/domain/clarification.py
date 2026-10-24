from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import uuid
from pydantic import BaseModel, Field

CLARIFICATION_SCHEMA_VERSION = "1.0"

class ClarificationType(str, Enum):
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    CONSEQUENTIAL_ACTION = "CONSEQUENTIAL_ACTION"
    HUMAN_INTERVENTION = "HUMAN_INTERVENTION"

class ClarificationOption(BaseModel):
    option_id: str = Field(description="Unique identifier for the option within the request.")
    label: str = Field(description="Human-readable label for UI display.")
    value: str = Field(description="Machine-readable value or canonical identifier (e.g. application name).")
    description: Optional[str] = Field(default=None, description="Detailed explanation of the option.")
    is_recommended: bool = Field(default=False, description="Whether this is the recommended or default choice.")

class ClarificationRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique identifier for the clarification request.")
    schema_version: str = Field(default=CLARIFICATION_SCHEMA_VERSION, description="Schema version for serialization.")
    clarification_type: ClarificationType = Field(description="The category of clarification required.")
    prompt: str = Field(description="Concise conversational prompt suitable for TTS and chat UI.")
    options: List[ClarificationOption] = Field(default_factory=list, description="List of candidate options for selection.")
    default_option_id: Optional[str] = Field(default=None, description="ID of default option if user confirms without specifying.")
    goal_id: Optional[str] = Field(default=None, description="Associated Goal ID.")
    task_id: Optional[str] = Field(default=None, description="Associated Task ID.")
    step_index: Optional[int] = Field(default=None, description="Associated composite step index, if any.")
    action_type: Optional[str] = Field(default=None, description="Action requiring clarification or confirmation.")
    target_name: Optional[str] = Field(default=None, description="Target name or identifier under consideration.")
    impact_description: Optional[str] = Field(default=None, description="Explanation of material impact for consequential actions.")
    requires_explicit_confirmation: bool = Field(default=False, description="Whether an explicit affirmative approval is mandatory.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Creation timestamp.")
    expires_at: Optional[datetime] = Field(default=None, description="Optional expiration timestamp.")
    timeout_seconds: Optional[int] = Field(default=None, description="Optional timeout duration in seconds.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context metadata.")

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        current_time = now or datetime.now(timezone.utc)
        if self.expires_at and current_time > self.expires_at:
            return True
        if self.timeout_seconds is not None:
            elapsed = (current_time - self.created_at).total_seconds()
            if elapsed > self.timeout_seconds:
                return True
        return False

    def get_option(self, option_id_or_val: str) -> Optional[ClarificationOption]:
        norm = option_id_or_val.strip().lower()
        for opt in self.options:
            if opt.option_id.lower() == norm or opt.value.lower() == norm or opt.label.lower() == norm:
                return opt
        return None

class ClarificationResponse(BaseModel):
    request_id: str = Field(description="The request_id being answered.")
    selected_option_id: Optional[str] = Field(default=None, description="ID of the selected option, if an option was chosen.")
    custom_input: Optional[str] = Field(default=None, description="User's write-in or spoken input if not selecting an option.")
    confirmed: Optional[bool] = Field(default=None, description="True for approved, False for rejected (for confirmations).")
    remember_as_preference: bool = Field(default=False, description="Whether to persist the chosen preference into long-term memory.")
    responded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp of response.")

    def validate_against(self, request: ClarificationRequest) -> tuple[bool, Optional[str]]:
        """Validates that this response is valid and non-stale for the given request."""
        if self.request_id != request.request_id:
            return False, f"Response request_id '{self.request_id}' does not match pending request '{request.request_id}'."
        if request.is_expired():
            return False, f"Clarification request '{request.request_id}' has expired."

        if request.clarification_type == ClarificationType.CONSEQUENTIAL_ACTION:
            if self.confirmed is None:
                return False, "Consequential action confirmation requires an explicit 'confirmed' boolean (True/False)."
            return True, None

        if request.options and not self.custom_input:
            if not self.selected_option_id:
                return False, "Response must select a valid option or provide custom input."
            opt = request.get_option(self.selected_option_id)
            if not opt:
                return False, f"Selected option '{self.selected_option_id}' is not in valid request options."

        return True, None
