"""Structured logging helpers for PHA stability paths (P2-4)."""

from __future__ import annotations

import logging
from typing import Any


def format_context(**fields: Any) -> str:
    parts: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")
    return " ".join(parts)


def log_warning(logger: logging.Logger, event: str, **context: Any) -> None:
    ctx = format_context(**context)
    message = f"event={event}"
    if ctx:
        message = f"{message} {ctx}"
    logger.warning(message)


def log_exception(
    logger: logging.Logger,
    event: str,
    exc: BaseException,
    *,
    level: int = logging.ERROR,
    **context: Any,
) -> None:
    ctx = format_context(**context)
    message = f"event={event}"
    if ctx:
        message = f"{message} {ctx}"
    logger.log(level, message, exc_info=exc)
