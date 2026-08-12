import asyncio
import json
import time
from typing import Any

from app.tools.registry import registry
from app.tools.errors import ToolError, ToolNotFoundError, ToolValidationError, ToolExecutionError, ToolPermissionError
from app.ai.providers.types import ToolCall, ToolResult
from app.core.logging.logger import get_logger
from app.tools.schemas import ToolRisk

logger = get_logger(__name__)

class ToolExecutor:
    def __init__(self):
        self.registry = registry

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Executes a tool call safely and returns a ToolResult."""
        
        start_time = time.perf_counter()
        
        try:
            # 1. Locate tool
            tool = self.registry.get(tool_call.name)
            
            logger.info(
                "TOOL_EXECUTION_STARTED", 
                extra={"tool_name": tool_call.name, "tool_call_id": tool_call.id}
            )

            # 2. Check risk/permissions (For Phase 4.1, we assume all registered tools are permitted, 
            # but tools like OpenApplicationTool will do their own config checks).
            if tool.risk == ToolRisk.BLOCKED:
                raise ToolPermissionError(f"Tool {tool.name} is blocked.")
                
            # 3. Validate arguments (basic structural validation)
            if not isinstance(tool_call.arguments, dict):
                raise ToolValidationError("Arguments must be a dictionary.")
                
            # 4. Execute tool
            try:
                # Add a reasonable timeout for safety (e.g. 30 seconds)
                result_data = await asyncio.wait_for(
                    tool.execute(**tool_call.arguments),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                raise ToolExecutionError("Tool execution timed out.")
            except Exception as e:
                # Catch internal errors of the tool
                if isinstance(e, ToolError):
                    raise
                logger.error(f"Internal tool error in {tool.name}: {e}")
                raise ToolExecutionError(f"Tool execution failed: {str(e)}")
            
            # Serialize result to string for the LLM
            if isinstance(result_data, dict) or isinstance(result_data, list):
                result_str = json.dumps(result_data)
            else:
                result_str = str(result_data)
                
            duration = time.perf_counter() - start_time
            logger.info(
                "TOOL_EXECUTION_COMPLETED",
                extra={"tool_name": tool_call.name, "duration_sec": duration}
            )
            
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                success=True,
                result=result_str
            )
            
        except ToolError as e:
            duration = time.perf_counter() - start_time
            logger.warning(
                "TOOL_EXECUTION_FAILED",
                extra={"tool_name": tool_call.name, "error": str(e), "duration_sec": duration}
            )
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                success=False,
                error=str(e)
            )
        except Exception as e:
            # Uncaught exceptions
            duration = time.perf_counter() - start_time
            logger.error(
                "TOOL_EXECUTION_CRASHED",
                extra={"tool_name": tool_call.name, "error": str(e), "duration_sec": duration}
            )
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                success=False,
                error=f"Unexpected error: {str(e)}"
            )

executor = ToolExecutor()
