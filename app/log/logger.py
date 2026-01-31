import json
import logging
import sys
from collections import deque
from datetime import datetime
from typing import Any, Dict, Optional


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        now_local = datetime.now().astimezone()
        payload: Dict[str, Any] = {
            # Local timestamp for operator readability.
            "ts": now_local.replace(microsecond=0).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "event"):
            payload["event"] = record.event
        if hasattr(record, "correlation_id"):
            payload["correlation_id"] = record.correlation_id
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            payload.update(record.extra_fields)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))


_RECENT_LOG_LINES = deque(maxlen=200)


class RingBufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            _RECENT_LOG_LINES.append(msg)
        except Exception:
            pass


def get_recent_log_lines(limit: int = 20) -> list[str]:
    if limit <= 0:
        return []
    items = list(_RECENT_LOG_LINES)
    return items[-limit:]


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    ring = RingBufferHandler()
    ring.setFormatter(JsonFormatter())
    logger.addHandler(ring)
    logger.propagate = False
    return logger


def log_event(
    logger: logging.Logger,
    event: str,
    message: str,
    correlation_id: Optional[str] = None,
    **fields: Any,
) -> None:
    extra = {"event": event, "extra_fields": fields}
    if correlation_id:
        extra["correlation_id"] = correlation_id
    logger.info(message, extra=extra)
