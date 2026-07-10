"""plan_vs_actual + integrity helpers."""

from harness_core import (
    IntegrityResult,
    SlotIntegrityRow,
    TurnPlanData,
    compute_plan_vs_actual,
)


def test_tool_not_allowed() -> None:
    plan = TurnPlanData(
        profile="general",
        tools_allowed=("reply_only",),
        forbidden=("LLM_COMPUTE",),
        slots_tier0=("TASK",),
    )
    diffs = compute_plan_vs_actual(plan, tools_executed=["invent_fx"])
    assert "tool_not_allowed:invent_fx" in diffs


def test_missing_tier0_slot() -> None:
    plan = TurnPlanData(
        profile="compute",
        slots_tier0=("NUMERICS_MANIFEST", "TASK"),
        tools_allowed=("compute_tax",),
    )
    diffs = compute_plan_vs_actual(
        plan,
        slot_contents={"NUMERICS_MANIFEST": ""},
    )
    assert "missing_tier0_slot:NUMERICS_MANIFEST" in diffs


def test_integrity_errors_merge() -> None:
    plan = TurnPlanData(profile="x", slots_tier0=("TASK",), tools_allowed=())
    integrity = IntegrityResult(
        errors=["protected_slot_empty:NUMERICS_MANIFEST"],
        warnings=["tier0_not_materialized:TASK"],
        slots=[SlotIntegrityRow(slot_id="TASK", present=True)],
    )
    diffs = compute_plan_vs_actual(plan, integrity=integrity)
    assert "protected_slot_empty:NUMERICS_MANIFEST" in diffs
    assert "tier0_not_materialized:TASK" in diffs
