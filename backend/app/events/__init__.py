"""
ASTRA Event System Architecture

Internal event bus for decoupling application components.

Events can be used for:
- Triggering background tasks
- Updating the UI asynchronously
- Logging important system state changes
"""

from enum import Enum


class EventType(str, Enum):
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    CONVERSATION_CREATED = "conversation.created"
    MESSAGE_RECEIVED = "message.received"
    TOOL_EXECUTED = "tool.executed"
    ERROR_OCCURRED = "error.occurred"
