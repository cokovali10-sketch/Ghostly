from __future__ import annotations

import json
import logging
import logging.handlers
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        if hasattr(record, "request_data"):
            log_entry["request"] = record.request_data

        if hasattr(record, "response_data"):
            log_entry["response"] = record.response_data

        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms

        return json.dumps(log_entry, default=str)


class PerformanceFilter(logging.Filter):
    """Filter that adds performance context to log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        return True


class RequestLoggingFilter(logging.Filter):
    """Filter that adds request context to log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        return True


def setup_logging(
    log_level: str = "INFO",
    log_dir: str | Path | None = None,
    json_output: bool = True,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 30,
) -> None:
    """Configure structured logging with rotation."""
    root_logger = logging.getLogger("ghostly")
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    if json_output:
        formatter: logging.Formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path / "ghostly.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        error_handler = logging.handlers.RotatingFileHandler(
            log_path / "ghostly_error.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        root_logger.addHandler(error_handler)

    root_logger.addFilter(PerformanceFilter())
    root_logger.addFilter(RequestLoggingFilter())


class RequestLogger:
    """Request/response logger with performance tracking."""

    def __init__(self, logger_name: str = "ghostly.request") -> None:
        self._logger = logging.getLogger(logger_name)

    def log_request(
        self,
        method: str,
        path: str,
        remote_addr: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        return {
            "method": method,
            "path": path,
            "remote_addr": remote_addr,
            "user_agent": user_agent,
        }

    def log_response(
        self,
        method: str,
        path: str,
        status: int,
        duration_ms: float,
        size: int | None = None,
    ) -> None:
        extra: dict[str, Any] = {
            "duration_ms": round(duration_ms, 2),
            "response_data": {
                "status": status,
                "size": size,
            },
        }
        if status >= 500:
            self._logger.error(
                "%s %s %d (%.1fms)", method, path, status, duration_ms, extra=extra
            )
        elif status >= 400:
            self._logger.warning(
                "%s %s %d (%.1fms)", method, path, status, duration_ms, extra=extra
            )
        else:
            self._logger.info(
                "%s %s %d (%.1fms)", method, path, status, duration_ms, extra=extra
            )

    def log_error(
        self,
        method: str,
        path: str,
        error: Exception,
        traceback_str: str | None = None,
    ) -> None:
        extra: dict[str, Any] = {
            "exception": {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback_str,
            }
        }
        self._logger.error(
            "%s %s error: %s", method, path, error, extra=extra
        )


class PerformanceTimer:
    """Context manager for timing operations."""

    def __init__(self, operation: str, logger: logging.Logger | None = None) -> None:
        self._operation = operation
        self._logger = logger or logging.getLogger("ghostly.perf")
        self._start: float = 0.0
        self._duration: float = 0.0

    def __enter__(self) -> PerformanceTimer:
        self._start = time.monotonic()
        return self

    def __exit__(self, *args: Any) -> None:
        self._duration = (time.monotonic() - self._start) * 1000
        self._logger.debug(
            "%s completed in %.2fms", self._operation, self._duration
        )

    @property
    def duration_ms(self) -> float:
        return self._duration
