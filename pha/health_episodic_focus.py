"""In-session episodic focus model for HealthTurnResolver (Stage 3C-α)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class WearableWindow:
    start: date
    end: date

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass
class HealthSessionFocus:
    """Episodic state for a single chat session (3C-α in-memory / test fixture)."""

    session_id: str
    focus_profile: str = ""
    focus_metric: str = ""
    focus_lab_years: list[int] = field(default_factory=list)
    focus_wearable_window: WearableWindow | None = None
    focus_summary: str = ""
    focus_tokens: list[str] = field(default_factory=list)
    turns_remaining: int = 0
    last_user_message: str = ""
    last_assistant_digest: str = ""
    focus_goal: str = ""
    focus_domains: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        if self.turns_remaining <= 0:
            return False
        return bool(
            self.focus_profile
            or self.focus_metric
            or self.focus_lab_years
            or self.focus_goal
            or (self.focus_summary or "").strip()
        )

    @classmethod
    def from_session_turn_focus(cls, focus: Any) -> HealthSessionFocus | None:
        """Best-effort adapter from legacy ``SessionTurnFocus`` (attachment-only rows)."""
        if focus is None:
            return None
        profile = "attachment_asset_qa" if (getattr(focus, "document_type", "") or "") else ""
        if (getattr(focus, "focus_summary", "") or "").strip():
            profile = profile or "attachment_asset_qa"
        return cls(
            session_id=str(getattr(focus, "session_id", "") or ""),
            focus_profile=profile,
            focus_summary=str(getattr(focus, "focus_summary", "") or ""),
            focus_tokens=list(getattr(focus, "focus_tokens", None) or []),
            turns_remaining=int(getattr(focus, "turns_remaining", 0) or 0),
        )
