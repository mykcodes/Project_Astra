"""ASTRA Common Schemas."""

from typing import Generic, TypeVar, Any
from pydantic import BaseModel, Field

T = TypeVar("T")


class HealthResponse(BaseModel):
    """System health check response."""
    status: str = Field(description="Overall system status")
    version: str = Field(description="Backend application version")
    environment: str = Field(description="Current deployment environment")
    uptime: float = Field(description="Uptime in seconds")
    database_connected: bool = Field(description="Whether the database is reachable")


class ErrorResponse(BaseModel):
    """Standardized error response."""
    code: str = Field(description="Application-specific error code")
    message: str = Field(description="Human-readable error message")
    details: dict[str, Any] | None = Field(default=None, description="Additional error context")
    timestamp: str = Field(description="ISO 8601 timestamp of the error")


class ApiResponse(BaseModel, Generic[T]):
    """Standardized successful API response wrapper."""
    data: T = Field(description="Response payload")
    success: bool = Field(default=True, description="Always true for ApiResponse")
    message: str | None = Field(default=None, description="Optional success message")
    timestamp: str = Field(description="ISO 8601 timestamp")
