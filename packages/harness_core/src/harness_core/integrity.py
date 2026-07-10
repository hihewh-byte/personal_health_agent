"""Tier0 integrity result shape — codes only, no domain slot semantics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass
class SlotIntegrityRow:
    slot_id: str
    present: bool = False
    protected: bool = False
    level: str = "full"
    chars: int = 0
    materialized: bool = False


@dataclass
class IntegrityResult:
    budget_limit: int = 0
    used_chars: int = 0
    slots: list[SlotIntegrityRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    assertions: list[str] = field(default_factory=list)
    profile: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_limit": self.budget_limit,
            "used_chars": self.used_chars,
            "slots": [
                {
                    "slot_id": s.slot_id,
                    "present": s.present,
                    "protected": s.protected,
                    "level": s.level,
                    "chars": s.chars,
                    "materialized": s.materialized,
                }
                for s in self.slots
            ],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "assertions": list(self.assertions),
            "profile": self.profile,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> IntegrityResult:
        if not data:
            return cls()
        rows: list[SlotIntegrityRow] = []
        for raw in data.get("slots") or []:
            if not isinstance(raw, Mapping):
                continue
            rows.append(
                SlotIntegrityRow(
                    slot_id=str(raw.get("slot_id") or ""),
                    present=bool(raw.get("present")),
                    protected=bool(raw.get("protected")),
                    level=str(raw.get("level") or "full"),
                    chars=int(raw.get("chars") or 0),
                    materialized=bool(raw.get("materialized")),
                )
            )
        return cls(
            budget_limit=int(data.get("budget_limit") or 0),
            used_chars=int(data.get("used_chars") or 0),
            slots=rows,
            errors=[str(x) for x in (data.get("errors") or [])],
            warnings=[str(x) for x in (data.get("warnings") or [])],
            assertions=[str(x) for x in (data.get("assertions") or [])],
            profile=str(data.get("profile") or ""),
        )


def integrity_diff_codes(integrity: IntegrityResult | Mapping[str, Any] | None) -> list[str]:
    """Flatten hard integrity errors (+ selected warnings) into plan_vs_actual codes."""
    if integrity is None:
        return []
    obj = integrity if isinstance(integrity, IntegrityResult) else IntegrityResult.from_mapping(integrity)
    diffs: list[str] = list(obj.errors)
    for warn in obj.warnings:
        if str(warn).startswith("tier0_not_materialized:"):
            diffs.append(str(warn))
    return sorted(set(diffs))


__all__ = [
    "IntegrityResult",
    "SlotIntegrityRow",
    "integrity_diff_codes",
]
