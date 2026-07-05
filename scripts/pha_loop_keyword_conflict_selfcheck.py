#!/usr/bin/env python3
"""Stage 1E / 4-α.1 selfcheck — tier gates + distiller dry-run."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("PHA_HEALTH_INTENT_CATALOG", "1")

from pha.loop_keyword_conflicts import (  # noqa: E402
    AliasProposal,
    classify_alias_phrase,
    detect_all_keyword_conflicts,
    detect_schema_fuzzy_baseline_debt,
    gate_1e_a_layer_denylist,
    gate_1e_c_narrow_pollution,
    validate_alias_proposals,
)
from pha.universal_catalog_manager import reload_catalog_manager  # noqa: E402


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_baseline_no_hard_conflicts() -> None:
    reload_catalog_manager()
    report = detect_all_keyword_conflicts()
    hard = [c for c in report.conflicts if c.kind != "substring_pollution"]
    _assert(not hard, f"baseline keyword conflicts: {[c.as_error() for c in hard]}")


def test_fuzzy_baseline_cleared() -> None:
    reload_catalog_manager()
    report = detect_schema_fuzzy_baseline_debt()
    _assert(report.ok, f"fuzzy schema debt remains: {report.errors()}")


def test_proposal_rejects_cross_metric_dup() -> None:
    proposals = [
        AliasProposal(layer="catalog", target="hrv", alias="变异探针", metric_id="hrv"),
        AliasProposal(layer="catalog", target="ldl", alias="变异探针", metric_id="ldl"),
    ]
    report = validate_alias_proposals(proposals)
    _assert(not report.ok, "expected cross-metric dup rejection")
    _assert(
        any("proposal_batch_dup" in e or "proposal_catalog_dup" in e for e in report.errors()),
        report.errors(),
    )


def test_proposal_accepts_unique_alias() -> None:
    proposals = [
        AliasProposal(
            layer="catalog",
            target="hrv",
            alias="变异探针",
            metric_id="hrv",
        ),
    ]
    report = validate_alias_proposals(proposals)
    _assert(report.ok, report.errors())


def test_gate_1e_a_blocks_time_and_affective() -> None:
    r_time = gate_1e_a_layer_denylist("昨晚睡多久")
    _assert(not r_time.ok, "time anchor must fail 1E-a")
    r_aff = gate_1e_a_layer_denylist("睡得好吗")
    _assert(not r_aff.ok, "affective phrase must fail 1E-a")
    r_agg = gate_1e_a_layer_denylist("日均多少步")
    _assert(not r_agg.ok, "aggregation must fail 1E-a")


def test_classify_strips_to_tier_a_and_c() -> None:
    c = classify_alias_phrase("昨晚睡多久啊", metric_id="sleep", source_message="昨晚睡多久啊")
    # After Tier-A promote, core「睡多久」already in catalog → reject with slot peel.
    _assert(c.tier in ("rejected", "slot"), c.as_dict())
    _assert(c.core_alias == "睡多久", c.as_dict())
    _assert(any(s.token == "昨晚" for s in c.slot_candidates), c.as_dict())

    c2 = classify_alias_phrase("日均多少步", metric_id="steps", source_message="日均多少步")
    _assert(c2.tier in ("catalog", "rejected", "slot"), c2.as_dict())
    _assert(c2.core_alias in ("多少步", "走了多少步"), c2.as_dict())
    _assert(any(s.token == "日均" for s in c2.slot_candidates), c2.as_dict())

    c3 = classify_alias_phrase("睡得好吗", metric_id="sleep", source_message="睡得好吗")
    _assert(c3.tier == "rejected", c3.as_dict())

    c4 = classify_alias_phrase("走了多少步", metric_id="steps", source_message="走了多少步")
    # Promoted Tier-A alias → distiller should not re-propose.
    _assert(c4.tier == "rejected", c4.as_dict())
    _assert(any("gate_1e_b_catalog_exists" in r for r in c4.reject_reasons), c4.as_dict())


def test_gate_1e_c_blocks_symptom_probe_alias() -> None:
    report = gate_1e_c_narrow_pollution("睡得好吗", metric_id="sleep")
    _assert(not report.ok, "affective sleep alias must fail symptom probe")


def test_harvest_and_distiller_pipeline() -> None:
    harvest = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "pha_telemetry_harvest.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    _assert(harvest.returncode == 0, harvest.stderr or harvest.stdout)

    distill = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "pha_loop_alias_distiller.py"),
            "--dry-run",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    _assert(distill.returncode == 0, distill.stderr or distill.stdout)
    out = distill.stdout
    _assert("Tier-A catalog" in out, out)
    _assert("睡得好吗" not in out or "rejected" in out, out)


def main() -> int:
    test_baseline_no_hard_conflicts()
    print("PASS baseline 1E no hard conflicts")
    test_fuzzy_baseline_cleared()
    print("PASS fuzzy schema baseline cleared")
    test_proposal_rejects_cross_metric_dup()
    print("PASS proposal rejects cross-metric dup")
    test_proposal_accepts_unique_alias()
    print("PASS proposal accepts unique alias")
    test_gate_1e_a_blocks_time_and_affective()
    print("PASS 1E-a blocks time/aggregation/affective")
    test_classify_strips_to_tier_a_and_c()
    print("PASS classify Tier-A/C strip")
    test_gate_1e_c_blocks_symptom_probe_alias()
    print("PASS 1E-c symptom probe")
    test_harvest_and_distiller_pipeline()
    print("PASS harvest + distiller dry-run pipeline")
    print("OK loop keyword conflict selfcheck (Stage 1E / 4-α.1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
