import asyncio
import json
import time
from typing import Any
import jsonschema
from jsonschema.exceptions import ValidationError

from app.tools.registry import registry
from app.tools.errors import ToolError, ToolNotFoundError, ToolValidationError, ToolExecutionError, ToolPermissionError, ToolTimeoutError
from app.ai.providers.types import ToolCall, ToolResult
from app.core.logging.logger import get_logger
from app.tools.schemas import ToolRisk
from app.core.config import get_settings

logger = get_logger(__name__)

class ToolExecutor:
    def __init__(self):
        self.registry = registry

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Executes a tool call safely and returns a ToolResult."""
        
        start_time = time.perf_counter()
        settings = get_settings()
        
        logger.info(
            "TOOL_CALL_RECEIVED",
            extra={"tool_name": tool_call.name, "tool_call_id": tool_call.id}
        )
        
        try:
            # 1. Locate tool
            tool = self.registry.get(tool_call.name)
            
            logger.info("TOOL_PERMISSION_CHECKED", extra={"tool_name": tool_call.name, "risk": tool.risk})

            # 2. Check risk/permissions
            if tool.risk == ToolRisk.BLOCKED:
                raise ToolPermissionError(f"Tool {tool.name} is blocked.")
                
            # 3. Validate arguments
            logger.info("TOOL_VALIDATION_STARTED", extra={"tool_name": tool_call.name})
            
            if not isinstance(tool_call.arguments, dict):
                logger.warning("TOOL_VALIDATION_FAILED", extra={"tool_name": tool_call.name, "error": "Arguments must be a dictionary"})
                raise ToolValidationError("Arguments must be a dictionary.")
                
            if "_parsing_error" in tool_call.arguments:
                error_msg = tool_call.arguments["_parsing_error"]
                raw_args = tool_call.arguments.get("_raw_arguments", "")
                logger.warning("TOOL_VALIDATION_FAILED", extra={"tool_name": tool_call.name, "error": f"JSON parsing failed: {error_msg}"})
                raise ToolValidationError(f"Your tool call arguments were malformed JSON: {error_msg}. Raw: {raw_args}")
                
            try:
                jsonschema.validate(instance=tool_call.arguments, schema=tool.schema)
            except ValidationError as ve:
                logger.warning("TOOL_VALIDATION_FAILED", extra={"tool_name": tool_call.name, "error": str(ve)})
                raise ToolValidationError(f"Invalid arguments for '{tool.name}': {ve.message}")
                
            # 4. Execute tool
            logger.info(
                "TOOL_EXECUTION_STARTED", 
                extra={"tool_name": tool_call.name, "tool_call_id": tool_call.id}
            )
            
            try:
                result_data = await asyncio.wait_for(
                    tool.execute(**tool_call.arguments),
                    timeout=float(settings.astra_tool_execution_timeout_seconds)
                )
            except asyncio.TimeoutError:
                raise ToolTimeoutError(f"Tool execution timed out after {settings.astra_tool_execution_timeout_seconds} seconds.")
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
                
            # Enforce max result size
            max_chars = settings.astra_tool_max_result_chars
            if len(result_str) > max_chars:
                result_str = result_str[:max_chars] + "... [Result truncated due to size limits]"
                
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
            
        except ToolTimeoutError as e:
            duration = time.perf_counter() - start_time
            logger.warning(
                "TOOL_EXECUTION_TIMEOUT",
                extra={"tool_name": tool_call.name, "duration_sec": duration}
            )
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                success=False,
                error=json.dumps({"error_type": "TOOL_TIMEOUT", "message": str(e)})
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
                error=json.dumps({"error_type": type(e).__name__, "message": str(e)})
            )
        except Exception as e:
            # Uncaught exceptions
            duration = time.perf_counter() - start_time
            logger.error(
                "TOOL_EXECUTION_FAILED",
                extra={"tool_name": tool_call.name, "error": str(e), "duration_sec": duration}
            )
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                success=False,
                error=json.dumps({"error_type": "UNEXPECTED_ERROR", "message": f"Unexpected error: {str(e)}"})
            )

executor = ToolExecutor()
