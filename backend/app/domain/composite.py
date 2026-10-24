from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.domain.entities import TriState
from app.domain.goals import Intent, VerificationResult, FailureClass
from app.domain.permissions import CapabilityScope

class StepStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    ACTUATION_ACCEPTED = "ACTUATION_ACCEPTED"
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"

class CompositeTerminalStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    PERMISSION_DENIED = "PERMISSION_DENIED"

class CompensationAction(BaseModel):
    intent: Intent = Field(description="Reversible semantic intent to execute as safe compensation.")
    tool_args: Dict[str, Any] = Field(default_factory=dict, description="Concrete arguments for compensation execution.")
    description: str = Field(description="Human-readable description of the compensation action.")
    executed: bool = Field(default=False, description="Whether compensation was actuated.")
    verified: TriState = Field(default=TriState.UNKNOWN, description="Whether compensation was authoritatively verified.")
    evidence: str = Field(default="", description="Verification evidence for the compensation.")

class CompositeStep(BaseModel):
    step_id: str = Field(description="Unique identifier for this step in the composite sequence.")
    step_index: int = Field(default=0, description="0-indexed order of the step in the sequence.")
    intent: Intent = Field(description="Semantic intent to execute.")
    tool_args: Dict[str, Any] = Field(default_factory=dict, description="Concrete tool arguments for execution.")
    description: str = Field(description="Human-readable description of what this step does.")
    consequential: bool = Field(default=False, description="If True, requires explicit authorization before execution.")
    required_permission: Optional[CapabilityScope] = Field(default=None, description="Specific capability scope required for this step.")
    status: StepStatus = Field(default=StepStatus.PENDING, description="Current lifecycle state of this step.")
    actuation_accepted: bool = Field(default=False, description="Whether physical/tool actuation was accepted by the OS.")
    verification_result: Optional[VerificationResult] = Field(default=None, description="Authoritative semantic verification result.")
    compensation: Optional[CompensationAction] = Field(default=None, description="Explicit safe compensation action if subsequent step fails.")
    error: Optional[Dict[str, Any]] = Field(default=None, description="Error diagnostics if step failed.")
    duration_ms: float = Field(default=0.0, description="Execution duration in milliseconds.")
    observation_before_id: Optional[str] = Field(default=None, description="Observation ID captured before step actuation.")
    observation_after_id: Optional[str] = Field(default=None, description="Observation ID captured after step actuation.")
    requires_verification: bool = Field(default=False, description="Whether authoritative semantic verification is required for step success.")
    verifier_type: Optional[str] = Field(default=None, description="Type of verification to perform (TEXT_INPUT, TEXT_ABSENT, SCROLL, DRAG, CONTEXT_MENU, WINDOW_BOUNDS, WINDOW_FOCUS, CROSS_WINDOW_SYNC).")
    verifier_args: Dict[str, Any] = Field(default_factory=dict, description="Arguments supplied to the verification engine for this step.")
    settle_delay_seconds: float = Field(default=0.3, description="Delay in seconds before capturing post-action observation.")
    target_app_name: Optional[str] = Field(default=None, description="Optional application name targeted by this step (e.g. 'notepad', 'calc').")
    target_window_title: Optional[str] = Field(default=None, description="Optional window title substring targeted by this step.")
    target_hwnd: Optional[int] = Field(default=None, description="Optional authoritative HWND targeted by this step.")
    ensure_foreground: bool = Field(default=True, description="Whether to ensure target window is activated in foreground before physical actuation.")


class CompositeActionSequence(BaseModel):
    sequence_id: str = Field(description="Unique identifier for the composite sequence.")
    name: str = Field(description="Descriptive name of the multi-step interaction workflow.")
    steps: List[CompositeStep] = Field(default_factory=list, description="Ordered list of composite steps.")
    max_retries_per_step: int = Field(default=2, description="Bounded recovery attempts per step on verification failure.")
    timeout_seconds: float = Field(default=60.0, description="Overall sequence timeout in seconds.")
    stop_on_failure: bool = Field(default=True, description="Whether failure of any step halts remaining steps.")
    allow_compensation: bool = Field(default=True, description="Whether to execute explicit safe compensation on failure.")

class CompositeExecutionResult(BaseModel):
    sequence_id: str = Field(description="ID of the executed composite sequence.")
    terminal_status: CompositeTerminalStatus = Field(description="Final terminal outcome of the sequence.")
    total_steps: int = Field(description="Total number of steps in the sequence.")
    completed_steps: int = Field(description="Number of steps that completed successfully according to step requirements (either verified or actuation-accepted).")
    verified_steps: int = Field(default=0, description="Number of steps that achieved authoritative verified success (TriState.TRUE).")
    failed_step_index: Optional[int] = Field(default=None, description="Index of the step where failure occurred, if any.")
    step_results: List[CompositeStep] = Field(default_factory=list, description="State of all steps upon sequence completion.")
    compensations_executed: List[CompensationAction] = Field(default_factory=list, description="History of executed safe compensation actions.")
    error: Optional[Dict[str, Any]] = Field(default=None, description="Terminal error payload if sequence failed or was denied.")
    duration_ms: float = Field(default=0.0, description="Total execution duration in milliseconds.")
