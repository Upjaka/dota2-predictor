"""Shared log formatting and async-safe correlation context."""

from __future__ import annotations

import contextvars
import logging
import os
import time
from datetime import datetime, timezone

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
cycle_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("cycle_id", default=None)
task_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("task_id", default=None)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.component = "backend"
        for name, variable in (("request_id", request_id_var), ("cycle_id", cycle_id_var), ("task_id", task_id_var)):
            if not hasattr(record, name):
                setattr(record, name, variable.get())
        return True


class UTCFormatter(logging.Formatter):
    converter = time.gmtime

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(UTCFormatter("%(asctime)s | %(levelname)s | %(component)s | %(name)s | request=%(request_id)s cycle=%(cycle_id)s task=%(task_id)s | %(message)s"))
        root.addHandler(handler)
    for handler in root.handlers:
        handler.setFormatter(UTCFormatter("%(asctime)s | %(levelname)s | %(component)s | %(name)s | request=%(request_id)s cycle=%(cycle_id)s task=%(task_id)s | %(message)s"))
        if not any(isinstance(item, ContextFilter) for item in handler.filters):
            handler.addFilter(ContextFilter())
