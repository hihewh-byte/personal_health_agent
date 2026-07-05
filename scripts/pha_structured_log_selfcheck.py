#!/usr/bin/env python3
"""P2-4 selfcheck: structured_log helpers."""

from __future__ import annotations

import logging
import sys
from io import StringIO

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.structured_log import format_context, log_exception, log_warning  # noqa: E402


def test_format_context() -> bool:
    s = format_context(user_id="default", job_id=42, skip=None)
    if s != "user_id=default job_id=42":
        print("FAIL format_context", repr(s))
        return False
    print("OK format_context")
    return True


def test_log_exception_includes_event() -> bool:
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    logger = logging.getLogger("pha.selfcheck.structured_log")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    try:
        raise ValueError("probe")
    except ValueError as exc:
        log_exception(logger, "import_background_failed", exc, job_id="j1", user_id="u1")
    out = buf.getvalue()
    if "event=import_background_failed" not in out or "job_id=j1" not in out:
        print("FAIL log_exception output", out)
        return False
    print("OK log_exception event context")
    return True


def test_log_warning() -> bool:
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    logger = logging.getLogger("pha.selfcheck.structured_log.warn")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    log_warning(logger, "ollama_probe_failed", host="127.0.0.1:11434")
    out = buf.getvalue()
    if "event=ollama_probe_failed" not in out:
        print("FAIL log_warning", out)
        return False
    print("OK log_warning")
    return True


def main() -> int:
    ok = all(
        [
            test_format_context(),
            test_log_exception_includes_event(),
            test_log_warning(),
        ],
    )
    print("pha_structured_log_selfcheck:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
