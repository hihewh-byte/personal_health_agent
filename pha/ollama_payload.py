"""Ollama request payload helpers (no imports from llm_provider)."""

from __future__ import annotations

import os
from typing import Any, Dict

from dotenv import load_dotenv


def ollama_keep_alive_value() -> int | str:
    load_dotenv(override=False)
    raw = (os.environ.get("OLLAMA_KEEP_ALIVE") or "0").strip()
    if raw.lower() in ("0", "false", "no", "off"):
        return 0
    if raw.isdigit():
        return int(raw)
    return raw


def apply_keep_alive(body: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(body)
    out["keep_alive"] = ollama_keep_alive_value()
    return out
