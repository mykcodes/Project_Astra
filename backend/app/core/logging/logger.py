"""ASTRA Logging Configuration."""

import logging
import json
from datetime import datetime
from typing import Any

from app.core.config import get_settings


class JSONFormatter(logging.Formatter):
    """Format logs as JSON for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include extra context if available
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            log_obj["extra"] = record.extra

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj)


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance."""
    settings = get_settings()
    logger = logging.getLogger(name)

    # Avoid duplicate handlers
    if not logger.handlers:
        handler = logging.StreamHandler()
        
        if settings.astra_log_format.lower() == "json":
            handler.setFormatter(JSONFormatter())
        else:
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
                )
            )

        logger.addHandler(handler)
        logger.setLevel(settings.astra_log_level)
        
        # Prevent propagation to the root logger to avoid double logging
        logger.propagate = False

    return logger
