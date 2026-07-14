"""Package-local tests for proposal shape validation and static veto."""

from __future__ import annotations

import json
from pathlib import Path

from harness_loop.proposals import (
    static_veto,
    validate_loop_proposal,
    validate_promote_verdict,
    write_static_promote_verdict,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _curated() -> dict:
    return json.loads((FIXTURES / "proposal_curated.json").read_text(encoding="utf-8"))


def test_curated_proposal_shape_valid():
    assert validate_loop_proposal(_curated()) == []


def test_proposal_missing_fields_rejected():
    errors = validate_loop_proposal({"schema": "pha.loop_proposal/v2"})
    assert any("generated_at" in e for e in errors)
    assert any("stage" in e for e in errors)
    assert any("source" in e for e in errors)


def test_proposal_unknown_schema_rejected():
    doc = _curated()
    doc["schema"] = "someone.else/v9"
    assert any("schema" in e for e in validate_loop_proposal(doc))


def test_static_veto_clean_proposal_passes():
    assert static_veto(_curated()) == []


def test_static_veto_blocks_code_review_and_bad_patch_path():
    doc = _curated()
    doc["code_review_items"] = [{"note": "needs code change"}]
    doc["patch_ops"] = [{"op": "add", "path": "/routing/forbidden", "value": 1}]
    veto = static_veto(doc)
    assert "code_review_items_present" in veto
    assert any(v.startswith("patch_outside_allowlist:") for v in veto)


def test_static_veto_blocks_tier_c_slot_to_catalog():
    doc = _curated()
    doc["slot_candidates"] = [{"layer": "catalog", "target": "x"}]
    assert "tier_c_slot_promoted_to_catalog" in static_veto(doc)


def test_write_static_promote_verdict_roundtrip(tmp_path):
    out_path, verdict = write_static_promote_verdict(
        FIXTURES / "proposal_curated.json", out_dir=tmp_path
    )
    assert out_path.is_file()
    assert verdict["passed"] is True
    assert verdict["static_veto"] == []
    assert "no auto-merge" in verdict["notes"]
    assert validate_promote_verdict(json.loads(out_path.read_text(encoding="utf-8"))) == []
