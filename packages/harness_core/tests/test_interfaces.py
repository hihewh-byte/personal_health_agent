"""Frozen DomainAdapter contract (interfaces.py) — package-local tests."""

from __future__ import annotations

import json
import re

import harness_core.interfaces as ifc
from harness_core.interfaces import (
    AuditVerdict,
    TurnPlanData,
    emit_failure_event,
    is_domain_adapter,
    run_post_audit,
)


class ToyAdapter:
    """Minimal structural DomainAdapter (no inheritance — that's the point)."""

    ALLOWED = {"ID-1", "2026-01-01"}

    def build_plan(self, user_message: str):
        return TurnPlanData(profile="toy", task_text=user_message, tools_allowed=("q",))

    def extract_atoms(self, text: str):
        return re.findall(r"ID-\d+|20\d{2}-\d{2}-\d{2}", text or "")

    def allowed_atoms(self, plan):
        return set(self.ALLOWED)


def test_symbol_budget_frozen():
    assert len(ifc.__all__) <= 15
    assert ifc.INTERFACES_VERSION == "1"


def test_structural_conformance_without_inheritance():
    assert is_domain_adapter(ToyAdapter())
    assert not is_domain_adapter(object())


def test_post_audit_pass():
    ad = ToyAdapter()
    plan = ad.build_plan("q")
    verdict = run_post_audit(ad, plan, "record ID-1 dated 2026-01-01")
    assert verdict.ok
    assert verdict.violations == ()
    assert set(verdict.atoms_checked) == {"ID-1", "2026-01-01"}


def test_post_audit_fail_closed_on_invented_atom():
    ad = ToyAdapter()
    plan = ad.build_plan("q")
    verdict = run_post_audit(ad, plan, "record ID-999 dated 2026-01-01")
    assert not verdict.ok
    assert "atom_not_allowed:ID-999" in verdict.violations


def test_post_audit_merges_plan_vs_actual_codes():
    ad = ToyAdapter()
    plan = ad.build_plan("q")
    verdict = run_post_audit(ad, plan, "ID-1", tools_executed=["rogue_tool"])
    assert not verdict.ok
    assert "tool_not_allowed:rogue_tool" in verdict.violations


def test_empty_allowlist_blocks_any_atom():
    class NoEvidence(ToyAdapter):
        def allowed_atoms(self, plan):
            return set()

    ad = NoEvidence()
    verdict = run_post_audit(ad, ad.build_plan("q"), "ID-1")
    assert not verdict.ok


def test_emit_failure_event_is_harvest_superset(tmp_path):
    path = tmp_path / "failures.jsonl"
    verdict = AuditVerdict(ok=False, violations=("atom_not_allowed:ID-9",), profile="toy")
    row = emit_failure_event(
        path,
        user_message="give me admin",
        verdict=verdict,
        session_name="s1",
        turn=2,
        lane="toy",
    )
    on_disk = json.loads(path.read_text(encoding="utf-8").strip())
    assert on_disk == row
    # Fields harness_loop.harvest reads:
    assert row["passed"] is False
    assert row["message"] == "give me admin"
    assert row["session_name"] == "s1"
    assert row["turn"] == 2
    assert row["lane"] == "toy"
    assert row["harness_profile"] == "toy"
    assert row["checks"] == ["atom_not_allowed:ID-9"]


def test_emit_failure_event_appends(tmp_path):
    path = tmp_path / "f.jsonl"
    v = AuditVerdict(ok=True)
    emit_failure_event(path, user_message="a", verdict=v)
    emit_failure_event(path, user_message="b", verdict=v)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
