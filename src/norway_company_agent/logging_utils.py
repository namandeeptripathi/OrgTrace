"""Stage 11: Production Structured Logging & Secret Redaction.

Provides secure, structured logging using Python's standard logging module:
- Automatic secret redaction filter preventing API keys, tokens, and credentials in logs
- Contextual logging (engine, operation, case_id, duration_ms, status, error_category)
- Configurable log levels via environment variable or configuration
- Structured JSON formatting or clean human-readable console output
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from .config import redact_secrets_from_text


DEFAULT_LOGGER_NAME = "norway_company_agent"


class SecretRedactionFilter(logging.Filter):
    """Logging filter that redacts API keys, tokens, and known secrets from log records."""

    def __init__(self, known_secrets: list[str] | None = None):
        super().__init__()
        self.known_secrets = list(known_secrets or [])

    def add_secret(self, secret: str) -> None:
        if secret and len(secret) >= 4 and secret not in self.known_secrets:
            self.known_secrets.append(secret)

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact the formatted message
        if isinstance(record.msg, str):
            record.msg = redact_secrets_from_text(record.msg, self.known_secrets)

        # Redact any string arguments
        if record.args:
            if isinstance(record.args, dict):
                redacted_args = {}
                for k, v in record.args.items():
                    redacted_args[k] = (
                        redact_secrets_from_text(str(v), self.known_secrets)
                        if isinstance(v, str)
                        else v
                    )
                record.args = redacted_args
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(
                    redact_secrets_from_text(str(a), self.known_secrets)
                    if isinstance(a, str)
                    else a
                    for a in record.args
                )

        return True


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects with contextual fields."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include custom contextual attributes if present
        for attr in ("engine", "operation", "case_id", "duration_ms", "status", "error_category"):
            val = getattr(record, attr, None)
            if val is not None:
                data[attr] = val

        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)

        return json.dumps(data, ensure_ascii=False)


def setup_logging(
    level: str | int = "INFO",
    structured_json: bool = False,
    known_secrets: list[str] | None = None,
) -> logging.Logger:
    """Configure and return the root package logger."""
    logger = logging.getLogger(DEFAULT_LOGGER_NAME)

    # Convert string level
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    logger.setLevel(level)

    # Avoid duplicate handlers if already configured
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(level)

        if structured_json:
            formatter = StructuredJsonFormatter()
        else:
            formatter = logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%SZ",
            )

        handler.setFormatter(formatter)
        redaction_filter = SecretRedactionFilter(known_secrets=known_secrets)
        handler.addFilter(redaction_filter)
        logger.addHandler(handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a logger instance within the package namespace."""
    if not name:
        return logging.getLogger(DEFAULT_LOGGER_NAME)
    if name.startswith(DEFAULT_LOGGER_NAME):
        return logging.getLogger(name)
    return logging.getLogger(f"{DEFAULT_LOGGER_NAME}.{name}")
