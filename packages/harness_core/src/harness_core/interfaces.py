"""Frozen Domain Adapter contract (v1) — attach any agent to harness-core.

This module is the *only* thing an external builder must read to attach.
It is deliberately small: ``DomainAdapter`` (3 methods) plus two portable
functions (``run_post_audit``, ``emit_failure_event``) and their data shapes.

Contract rules (frozen at v1):

- ``harness_core`` never imports domain packages; adapters never subclass
  core internals. The boundary is data: ``TurnPlan`` in, atoms out.
- ``run_post_audit`` is fail-closed and side-effect free: it never rewrites
  the draft, never retries the model, never "heals" a violation. Callers
  block/downgrade the reply themselves when ``verdict.ok`` is False.
- ``emit_failure_event`` rows are a superset of what ``harness_loop``
  harvest consumes (``passed`` / ``message`` / ``session_name`` / ``turn`` /
  ``lane`` / ``harness_profile`` / ``checks``), so any adapter's failures
  are immediately Loop-consumable without adapter-specific glue.

Adding a public symbol here requires a task card; there is a budget of 15.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Collection, Mapping, Protocol, Sequence, runtime_checkable

from harness_core.plan_vs_actual import compute_plan_vs_actual
from harness_core.turn_plan import TurnPlan, TurnPlanData

INTERFACES_VERSION = "1"

#: JSONL schema id for failure events (harvest-compatible superset).
FAILURE_EVENT_SCHEMA = "harness.failure_event/v1"

#: An atom is a normalized evidence token a reply may cite: a value,
#: a date, an ID, a role name. Membership is exact string equality —
#: normalization is the adapter's job (both sides must use the same rules).
Atom = str


@runtime_checkable
class DomainAdapter(Protocol):
    """Everything harness-core needs to know about a domain. Nothing more.

    The same ``extract_atoms`` normalization must be applied when building
    the allowlist and when auditing the draft, otherwise exact-match
    membership is meaningless. Keeping both methods on one object makes
    that invariant hard to break by accident.
    """

    def build_plan(self, user_message: str) -> TurnPlan:
        """Freeze the evidence boundary for this turn *before* composing."""
        ...

    def extract_atoms(self, text: str) -> Sequence[Atom]:
        """Pull auditable atoms out of arbitrary text (draft reply)."""
        ...

    def allowed_atoms(self, plan: TurnPlan) -> Collection[Atom]:
        """The closed set of atoms the reply may cite under this plan."""
        ...


@dataclass(frozen=True)
class AuditVerdict:
    """Result of a post-audit. ``ok`` is False on any violation."""

    ok: bool
    violations: tuple[str, ...] = ()
    atoms_checked: tuple[Atom, ...] = ()
    profile: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "violations": list(self.violations),
            "atoms_checked": list(self.atoms_checked),
            "profile": self.profile,
        }


def run_post_audit(
    adapter: DomainAdapter,
    plan: TurnPlan,
    draft_text: str,
    *,
    tools_executed: Sequence[str] = (),
) -> AuditVerdict:
    """Fail-closed membership audit of a draft reply against a frozen plan.

    Violation codes:

    - ``atom_not_allowed:{atom}`` — draft cites an atom outside the allowlist
    - plus any ``compute_plan_vs_actual`` machine-diff codes (tool drift etc.)

    Empty allowlist + any extracted atom ⇒ violations. That is intentional:
    when in doubt, block.
    """
    atoms: list[Atom] = []
    for atom in adapter.extract_atoms(draft_text or ""):
        if atom and atom not in atoms:
            atoms.append(atom)
    allowed = set(adapter.allowed_atoms(plan))

    violations = [f"atom_not_allowed:{a}" for a in atoms if a not in allowed]
    violations.extend(compute_plan_vs_actual(plan, tools_executed=tools_executed))

    return AuditVerdict(
        ok=not violations,
        violations=tuple(sorted(set(violations))),
        atoms_checked=tuple(atoms),
        profile=str(getattr(plan, "profile", "") or ""),
    )


def emit_failure_event(
    path: Path | str,
    *,
    user_message: str,
    verdict: AuditVerdict,
    session_name: str = "attach",
    turn: int = 0,
    lane: str = "",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one harvest-compatible JSONL row; return the row.

    Rows with ``passed: true`` are legal (harvest skips them), so callers
    may log every turn or only failures — both stay Loop-consumable.
    Do not put raw evidence values in ``extra``; codes only.
    """
    row: dict[str, Any] = {
        "schema": FAILURE_EVENT_SCHEMA,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "passed": verdict.ok,
        "message": str(user_message or ""),
        "session_name": str(session_name or "attach"),
        "turn": int(turn),
        "lane": str(lane or ""),
        "harness_profile": verdict.profile,
        "checks": list(verdict.violations),
    }
    for key, value in dict(extra or {}).items():
        row.setdefault(str(key), value)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def is_domain_adapter(obj: Any) -> bool:
    """Structural + callable conformance check (for selfchecks / CI)."""
    if not isinstance(obj, DomainAdapter):
        return False
    return all(
        callable(getattr(obj, name, None))
        for name in ("build_plan", "extract_atoms", "allowed_atoms")
    )


__all__ = [
    "Atom",
    "AuditVerdict",
    "DomainAdapter",
    "FAILURE_EVENT_SCHEMA",
    "INTERFACES_VERSION",
    "TurnPlan",
    "TurnPlanData",
    "emit_failure_event",
    "is_domain_adapter",
    "run_post_audit",
]
