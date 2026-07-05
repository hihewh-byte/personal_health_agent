#!/usr/bin/env python3
"""Stage 3H selfcheck: universal attachment grounded fallback lane.

Validates the three崩塌点 fixes from rfc-stage3h-universal-attachment-lane.md:
  A. resolve_attachment_qa_mode no longer kicks lab/medication/unknown to "none";
     they route to "grounded" (and never degrade to lifestyle/warehouse).
  B. build_turn_evidence_plan(grounded) physically isolates ALL warehouse slots
     (forbidden) and runs with tools_allowed == [].
  C. focus_summary_from_parsed serializes metrics[] into a deterministic fact table.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["PHA_UNIVERSAL_ATTACHMENT_LANE"] = "1"
os.environ.setdefault("PHA_HEALTH_INTENT_CATALOG", "1")

from pha.attachment_asset_qa import (  # noqa: E402
    resolve_attachment_qa_mode,
    universal_attachment_lane_enabled,
)
from pha.chat_turn_routing import resolve_turn_routing  # noqa: E402
from pha.harness_plan import build_turn_evidence_plan  # noqa: E402
from pha.session_turn_focus import focus_summary_from_parsed  # noqa: E402

# Warehouse / history slots that must be physically forbidden in the grounded lane.
_FORBIDDEN_WAREHOUSE = {
    "GET_HEALTH_DATA",
    "GET_TEMPORAL_HISTORY_DOSSIER",
    "LDL_AUTHORITY",
    "PATIENT_STATE_LAB",
    "PATIENT_STATE_WEARABLE",
    "WEARABLE_90D_SUMMARY",
    "WEARABLE_COMPARE_TABLE",
    "DOSSIER_LAB",
    "DOSSIER_CLINICAL_COMPACT",
    "NUMERICS_MANIFEST",
}


def test_flag_default_off() -> bool:
    """Flag must default OFF so legacy behavior is preserved on rollback."""
    prev = os.environ.pop("PHA_UNIVERSAL_ATTACHMENT_LANE", None)
    try:
        assert universal_attachment_lane_enabled() is False
        # Legacy: lab kicked out to "none".
        mode = resolve_attachment_qa_mode(
            "分析检验结果",
            has_parsed_attachment=True,
            session_focus_active=False,
            document_family="lab",
        )
        assert mode == "none", f"flag off lab should be none, got {mode!r}"
    finally:
        if prev is not None:
            os.environ["PHA_UNIVERSAL_ATTACHMENT_LANE"] = prev
        else:
            os.environ["PHA_UNIVERSAL_ATTACHMENT_LANE"] = "1"
    return True


def test_a_lab_medication_unknown_route_grounded() -> bool:
    for fam in ("lab", "medication", "unknown", "other"):
        mode = resolve_attachment_qa_mode(
            "分析检验结果",
            has_parsed_attachment=True,
            session_focus_active=False,
            document_family=fam,
        )
        assert mode == "grounded", f"family {fam!r} should be grounded, got {mode!r}"
    return True


def test_a_wearable_not_grounded() -> bool:
    """Wearable keeps its specialized lane (returns none here, handled by routing)."""
    mode = resolve_attachment_qa_mode(
        "HRV 怎么样",
        has_parsed_attachment=True,
        session_focus_active=False,
        document_family="wearable",
    )
    assert mode == "none", f"wearable should not be grounded, got {mode!r}"
    return True


def test_a_explicit_cross_year_defers_to_specialized() -> bool:
    """Explicit cross-year lab intent must defer to lab_cross_year, not grounded."""
    mode = resolve_attachment_qa_mode(
        "帮我对比历年血脂趋势",
        has_parsed_attachment=True,
        session_focus_active=False,
        document_family="lab",
    )
    assert mode == "none", f"hard lab pivot should defer (none), got {mode!r}"
    return True


def test_a_corrupt_structural_routing_sets_grounded_flag() -> bool:
    decision = resolve_turn_routing(
        "帮我看看这些数据",
        health_turn_scope=None,
        health_episodic_focus=None,
        route_focus=None,
        parsed_payload={
            "document_family": "",
            "vision_summary": "肝肾功能",
            "metrics": [{"item": "CREA", "value": 110}],
        },
        paths_in=["/tmp/corrupt.png"],
        has_parse=True,
        attach_family="",
    )
    assert decision.attachment_grounded_review is True, "structural backstop must set grounded flag"
    assert decision.qa_mode == "grounded"
    return True


def test_a_routing_sets_grounded_flag() -> bool:
    decision = resolve_turn_routing(
        "分析检验结果",
        health_turn_scope=None,
        health_episodic_focus=None,
        route_focus=None,
        parsed_payload={"document_family": "lab", "metrics": [{"item": "CO2", "value": 27}]},
        paths_in=["/tmp/lab.png"],
        has_parse=True,
        attach_family="lab",
    )
    assert decision.attachment_grounded_review is True, "grounded flag not set"
    assert decision.attachment_asset_qa is False
    assert decision.wearable_screenshot_review is False
    assert decision.qa_mode == "grounded"
    return True


def test_b_plan_isolates_warehouse() -> bool:
    plan = build_turn_evidence_plan("分析检验结果", attachment_grounded_review=True)
    assert plan.profile == "attachment_grounded_review", plan.profile
    assert plan.tools_allowed == [], plan.tools_allowed
    forbidden = set(plan.forbidden or [])
    missing = _FORBIDDEN_WAREHOUSE - forbidden
    assert not missing, f"grounded plan missing forbidden warehouse slots: {sorted(missing)}"
    # Must surface the attachment fact block + task, never warehouse numerics in tier0.
    t0 = set(plan.slots_tier0 or [])
    assert "ATTACHMENT_LABEL" in t0
    assert "TASK" in t0
    assert "NUMERICS_MANIFEST" not in t0
    assert "PATIENT_STATE_LAB" not in t0
    return True


def test_c_metrics_serialized_fact_table() -> bool:
    parsed = {
        "label_ledger": "",
        "vision_summary": "肝肾功能检验报告",
        "metrics": [
            {"item": "CO2", "value_text": "27", "unit": "mmol/L", "reference_range": "22.0-29.0", "is_abnormal": False},
            {"metric_name": "GFR", "value": 92.26, "unit": "mL/(min*1.73m2)", "ref": "", "is_abnormal": False},
            {"item": "CREA", "value_text": "110", "unit": "umol/L", "reference_range": "57-97", "is_abnormal": True},
        ],
    }
    out = focus_summary_from_parsed(parsed)
    assert "附件解析事实" in out, out
    assert "CO2" in out and "27" in out
    assert "GFR" in out and "92.26" in out
    assert "CREA" in out and "异常" in out
    # metrics table must win over vision_summary prose.
    assert out.startswith("【附件解析事实"), out[:40]
    return True


def test_c_empty_metrics_unchanged() -> bool:
    """No metrics → behavior unchanged (pure-additive; ledger/summary path)."""
    assert focus_summary_from_parsed({"label_ledger": "成分定账块"}) == "成分定账块"
    assert focus_summary_from_parsed({"metrics": [], "vision_summary": "X"}) == "X"
    return True


def test_gamma_wearable_insufficient_with_lab_metrics() -> bool:
    """3H-γ: wearable lane empty but metrics[] present → specialized insufficient."""
    from pha.attachment_grounded_fallback import specialized_lane_insufficient

    parsed = {
        "document_family": "wearable",
        "wearable_metrics": [],
        "metrics": [{"item": "CREA", "value_text": "110", "unit": "umol/L"}],
    }
    assert specialized_lane_insufficient("wearable_screenshot_review", parsed, wearable_compare_table=None)
    assert not specialized_lane_insufficient(
        "wearable_screenshot_review",
        {"wearable_metrics": [{"id": "hrv"}], "metrics": []},
        wearable_compare_table=type("T", (), {"rows": [type("R", (), {"snapshot_value": "34"})()]})(),
    )
    return True


def test_gamma_supplement_insufficient_with_metrics() -> bool:
    from pha.attachment_grounded_fallback import specialized_lane_insufficient

    parsed = {
        "label_ledger": "",
        "ingredient_rows": [],
        "metrics": [{"item": "ALT", "value_text": "23.7"}],
    }
    assert specialized_lane_insufficient("attachment_asset_qa", parsed)
    assert not specialized_lane_insufficient(
        "attachment_asset_qa",
        {"label_ledger": "成分定账", "metrics": []},
    )
    return True


def test_gamma_fallback_rebind_plan() -> bool:
    from pha.attachment_grounded_fallback import try_specialized_fallback_to_grounded

    parsed = {
        "metrics": [{"item": "CO2", "value_text": "27", "unit": "mmol/L"}],
    }
    from pha.harness_plan import TurnEvidencePlan

    worn_plan = TurnEvidencePlan(
        profile="wearable_screenshot_review",
        slots_tier0=["TASK"],
        slots_tier1=[],
        forbidden=[],
        tools_allowed=[],
        task_text="wearable",
        legacy_question_type=None,
    )
    fb = try_specialized_fallback_to_grounded(
        plan=worn_plan,
        parsed=parsed,
        wearable_compare_table=None,
        user_id="default",
        user_message="分析检验结果",
    )
    assert fb is not None
    assert fb.plan.profile == "attachment_grounded_review"
    assert fb.from_profile == "wearable_screenshot_review"
    assert "CO2" in fb.attachment_label
    assert "NUMERICS_MANIFEST" in (fb.plan.forbidden or [])
    return True


def test_gamma_registry_fallback_contract() -> bool:
    from pha.attachment_grounded_fallback import SPECIALIZED_ATTACHMENT_PROFILES
    from pha.harness_profile_registry import _PROFILE_GROUNDED_FALLBACK

    for prof in SPECIALIZED_ATTACHMENT_PROFILES:
        assert _PROFILE_GROUNDED_FALLBACK.get(prof) == "attachment_grounded_review"
    return True


def test_corrupt_empty_family_structural_grounded() -> bool:
    """corrupt/异形 family + paths + metrics[] → grounded (never none/lifestyle)."""
    mode = resolve_attachment_qa_mode(
        "帮我看看这些数据",
        has_parsed_attachment=True,
        session_focus_active=False,
        document_family="",
        has_attachment_paths=True,
        parsed_payload={
            "vision_summary": "肝肾功能检验报告",
            "metrics": [{"item": "UA", "value_text": "282.2", "unit": "umol/L"}],
        },
    )
    assert mode == "grounded", f"empty family with facts should be grounded, got {mode!r}"
    mode2 = resolve_attachment_qa_mode(
        "这张图怎么样",
        has_parsed_attachment=True,
        session_focus_active=False,
        document_family="corrupt",
        has_attachment_paths=True,
        parsed_payload={"vision_summary": "血常规报告片段"},
    )
    assert mode2 == "grounded", f"corrupt family with vision_summary should be grounded, got {mode2!r}"
    return True


def test_structural_backstop_defers_hard_lab_pivot() -> bool:
    mode = resolve_attachment_qa_mode(
        "帮我对比历年血脂趋势",
        has_parsed_attachment=True,
        session_focus_active=False,
        document_family="",
        has_attachment_paths=True,
        parsed_payload={"metrics": [{"item": "LDL", "value_text": "2.4"}]},
    )
    assert mode == "none", f"hard lab pivot must defer, got {mode!r}"
    return True


def main() -> int:
    tests = [
        test_flag_default_off,
        test_a_lab_medication_unknown_route_grounded,
        test_a_wearable_not_grounded,
        test_a_explicit_cross_year_defers_to_specialized,
        test_a_corrupt_structural_routing_sets_grounded_flag,
        test_a_routing_sets_grounded_flag,
        test_b_plan_isolates_warehouse,
        test_c_metrics_serialized_fact_table,
        test_c_empty_metrics_unchanged,
        test_gamma_wearable_insufficient_with_lab_metrics,
        test_gamma_supplement_insufficient_with_metrics,
        test_gamma_fallback_rebind_plan,
        test_gamma_registry_fallback_contract,
        test_corrupt_empty_family_structural_grounded,
        test_structural_backstop_defers_hard_lab_pivot,
    ]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print("pha_universal_attachment_lane_selfcheck: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
