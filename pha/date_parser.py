"""Robust ISO / Apple Health datetime parsing for PHA (Python 3.9+)."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)

DateLike = Union[str, date, datetime, None]

# 2025-12-07, 2025-12-07T23:59:59, 2025-12-07 23:59:59.123+08:00
_ISO_PREFIX_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T\s](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?"
    r"(?:\s*([Zz]|([+-])(\d{2}):?(\d{2})))?$",
)


def safe_parse_datetime(value: DateLike) -> Optional[datetime]:
    """
    Parse timestamps from SQLite TEXT, Apple Health export, or medical_reports.

    Never raises — returns ``None`` on unrecoverable input.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)

    raw = str(value).strip()
    if not raw:
        return None

    s = raw.replace("Z", "+00:00").replace("z", "+00:00")
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)

    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass

    m = _ISO_PREFIX_RE.match(raw.strip())
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh = int(m.group(4) or 0)
        mm = int(m.group(5) or 0)
        ss = int(m.group(6) or 0)
        try:
            return datetime(y, mo, d, hh, mm, ss)
        except ValueError:
            pass

    try:
        from dateutil import parser as dateutil_parser  # type: ignore

        return dateutil_parser.parse(raw)
    except ImportError:
        pass
    except (ValueError, TypeError, OverflowError):
        pass

    if len(raw) >= 10:
        try:
            d = date.fromisoformat(raw[:10])
            return datetime.combine(d, time.min)
        except ValueError:
            pass

    logger.warning("safe_parse_datetime: could not parse %r", value)
    return None


def safe_parse_date(value: DateLike) -> Optional[date]:
    """
    Parse calendar dates from ``YYYY-MM-DD`` or ``YYYY-MM-DDTHH:MM:SS`` storage.

    ``date.fromisoformat`` rejects time components on Python 3.9 — this helper
  always normalizes to a ``date``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    raw = str(value).strip()
    if not raw:
        return None

    if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            pass

    dt = safe_parse_datetime(raw)
    if dt is not None:
        return dt.date()

    logger.warning("safe_parse_date: could not parse %r", value)
    return None


def safe_parse_date_required(value: DateLike, *, field: str = "date") -> date:
    """Like ``safe_parse_date`` but raises ``ValueError`` with context."""
    parsed = safe_parse_date(value)
    if parsed is None:
        raise ValueError(f"Invalid {field}: {value!r}")
    return parsed
