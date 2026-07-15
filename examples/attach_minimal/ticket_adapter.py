"""TicketAdapter — a complete DomainAdapter in ~70 lines.

Domain: an IT ticket / access-change assistant. The evidence base is an
in-memory ticket table. The auditable atoms are ticket IDs, role names,
and approved dates — the things an assistant must never invent or swap.

This file has zero knowledge of harness-core internals; it only returns
data shapes (a TurnPlanData and lists of atom strings).
"""

from __future__ import annotations

import re
from typing import Collection, Sequence

from harness_core.interfaces import Atom, TurnPlan, TurnPlanData

# The "database". In a real agent this would be your ticket system query.
TICKETS = [
    {"id": "TCK-1042", "role": "deploy-bot", "approved_on": "2026-07-01"},
    {"id": "TCK-1055", "role": "read-only-auditor", "approved_on": "2026-07-09"},
]

# Atoms this domain audits: ticket IDs, ISO dates, and known role names.
_TICKET_RE = re.compile(r"TCK-\d+")
_DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
_KNOWN_ROLES = sorted({str(t["role"]) for t in TICKETS}, key=len, reverse=True)


class TicketAdapter:
    """Satisfies harness_core.interfaces.DomainAdapter structurally."""

    def build_plan(self, user_message: str) -> TurnPlan:
        """Freeze the evidence boundary before the model composes anything."""
        return TurnPlanData(
            profile="ticket_lookup",
            slots_tier0=("TASK", "TICKET_TABLE"),
            forbidden=("LLM_COMPUTE",),
            tools_allowed=("ticket_query",),
            task_text=user_message,
        )

    def extract_atoms(self, text: str) -> Sequence[Atom]:
        """Same normalization for allowlist and draft — that's the contract."""
        atoms: list[Atom] = []
        atoms.extend(_TICKET_RE.findall(text or ""))
        atoms.extend(_DATE_RE.findall(text or ""))
        for role in _KNOWN_ROLES:
            if role in (text or ""):
                atoms.append(role)
        return atoms

    def allowed_atoms(self, plan: TurnPlan) -> Collection[Atom]:
        """The closed citation set for this turn: what the table really says."""
        allowed: set[Atom] = set()
        for t in TICKETS:
            allowed.update(self.extract_atoms(" ".join(str(v) for v in t.values())))
        return allowed

    def render_evidence(self) -> str:
        """Helper for the demo prompt (not part of the adapter contract)."""
        return "\n".join(
            f"- {t['id']}: role={t['role']} approved_on={t['approved_on']}"
            for t in TICKETS
        )
