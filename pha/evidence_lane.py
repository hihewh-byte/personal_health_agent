"""Shared helpers for evidence injection (Tier0 wearable summary, etc.)."""

from __future__ import annotations

from pha.agent_tools import SNAPSHOT_MARKER


def wearable_block_has_user_snapshot(wearable_summary: str) -> bool:
    """True when Tier0 already contains a precomputed User Data Snapshot block."""
    body = (wearable_summary or "").strip()
    return bool(body) and SNAPSHOT_MARKER in body


__all__ = ["wearable_block_has_user_snapshot"]
