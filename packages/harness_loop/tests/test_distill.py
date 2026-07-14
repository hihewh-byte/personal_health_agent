"""Package-local tests for portable distill stages (no health domain)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from harness_loop.distill import (
    apply_catalog_patch,
    apply_promote_budget,
    assemble_proposal_doc,
    build_tiered_proposals,
    cluster_rows,
    extract_phrases,
    write_distill_outputs,
)
from harness_loop.gates import SlotCandidate, TierClassification


@dataclass
class Proposal:
    layer: str
    target: str
    alias: str
    metric_id: str | None = None
    source_message: str = ""
    signal: str = ""
    slot_kind: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d = {
            "layer": self.layer,
            "target": self.target,
            "alias": self.alias,
            "metric_id": self.metric_id,
            "signal": self.signal,
            "source_message": self.source_message,
        }
        if self.slot_kind:
            d["slot_kind"] = self.slot_kind
        return d


def test_extract_phrases_prefers_full_short_message_and_dedupes():
    phrases = extract_phrases("open tickets", known_aliases={"backlog"})
    assert phrases[0] == "open tickets"
    assert "open" in phrases and "tickets" in phrases
    assert len(phrases) == len({p.lower() for p in phrases})


def test_extract_phrases_skips_known_aliases_and_caps():
    phrases = extract_phrases(
        "backlog backlog alpha beta gamma delta epsilon", known_aliases={"backlog"}
    )
    assert "backlog" not in [p.lower() for p in phrases]
    assert len(phrases) <= 5


def test_cluster_rows_skips_none_metric():
    rows = [
        {"message": "a", "suggested_metric": "mttr"},
        {"message": "b", "suggested_metric": "skipme"},
    ]
    clusters = cluster_rows(
        rows,
        metric_fn=lambda r: None
        if r.get("suggested_metric") == "skipme"
        else str(r.get("suggested_metric")),
    )
    assert set(clusters) == {"mttr"}


def _mk_classify(verdicts: dict[str, TierClassification]):
    def classify(phrase: str, _metric: str, _src: str) -> TierClassification:
        return verdicts.get(
            phrase, TierClassification(tier="rejected", reject_reasons=["unknown"])
        )

    return classify


def test_build_tiered_proposals_routes_tiers_and_validates():
    clusters = {
        "mttr": [
            {"message": "repair time", "signal": "sig1"},
            {"message": "yesterday total", "signal": "sig2"},
            {"message": "Cancel", "signal": "sig3"},
        ]
    }
    verdicts = {
        "repair time": TierClassification(tier="catalog", core_alias="repair time"),
        "yesterday total": TierClassification(
            tier="slot",
            core_alias="",
            slot_candidates=[
                SlotCandidate(token="yesterday", kind="time"),
                SlotCandidate(token="total", kind="aggregation"),
            ],
            reject_reasons=["core_empty_after_strip"],
        ),
        "Cancel": TierClassification(tier="rejected", reject_reasons=["ocr_junk"]),
    }
    catalog, schema, slots, rejected = build_tiered_proposals(
        clusters,
        phrase_fn=lambda msg, _m: [msg],
        classify_fn=_mk_classify(verdicts),
        validate_fn=lambda props: (True, []),
        make_proposal=Proposal,
    )
    assert [p.alias for p in catalog] == ["repair time"]
    assert schema == []
    assert {(p.alias, p.slot_kind) for p in slots} == {
        ("yesterday", "time"),
        ("total", "aggregation"),
    }
    assert len(rejected) == 2  # slot-with-reasons note + hard reject
    assert any(r.get("note") for r in rejected)


def test_build_tiered_proposals_validator_veto_goes_to_rejected():
    clusters = {"mttr": [{"message": "repair time", "signal": "s"}]}
    verdicts = {
        "repair time": TierClassification(tier="catalog", core_alias="repair time")
    }
    catalog, _schema, _slots, rejected = build_tiered_proposals(
        clusters,
        phrase_fn=lambda msg, _m: [msg],
        classify_fn=_mk_classify(verdicts),
        validate_fn=lambda props: (False, ["dup_alias"]),
        make_proposal=Proposal,
    )
    assert catalog == []
    assert rejected[0]["conflicts"] == ["dup_alias"]


def test_apply_promote_budget_ranks_by_priority():
    props = [
        Proposal(layer="catalog", target="b", alias="zzz"),
        Proposal(layer="catalog", target="a", alias="preferred"),
        Proposal(layer="catalog", target="a", alias="mmm"),
    ]
    kept = apply_promote_budget(props, max_promote=2, priority={"preferred": 0})
    assert [p.alias for p in kept] == ["preferred", "mmm"]


def test_apply_catalog_patch_adds_ops_and_skips_existing():
    doc = {"metric_aliases": {"mttr": ["repair time"]}}
    props = [
        Proposal(layer="catalog", target="mttr", alias="repair time"),  # existing
        Proposal(layer="catalog", target="mttr", alias="time to fix", signal="s"),
        Proposal(layer="slot", target="mttr", alias="yesterday"),  # non-catalog
    ]
    out = apply_catalog_patch(doc, props)
    assert [op["value"] for op in out["patch_ops"]] == ["time to fix"]
    assert out["catalog_preview"]["metric_aliases"]["mttr"] == [
        "repair time",
        "time to fix",
    ]


def test_assemble_and_write_outputs(tmp_path):
    prop = Proposal(layer="catalog", target="mttr", alias="time to fix")
    slot = Proposal(layer="slot", target="mttr", alias="yesterday", slot_kind="time")
    doc = assemble_proposal_doc(
        schema="toy.loop_proposal/v2",
        stage="test",
        candidates_path="c.jsonl",
        candidate_count=3,
        cluster_metrics=["mttr"],
        accepted_catalog=[prop],
        accepted_schema=[],
        slot_candidates=[slot],
        rejected=[],
        deferred_catalog=[],
        patch_ops=[{"op": "add", "path": "/metric_aliases/mttr", "value": "time to fix"}],
        notes="proposal-only",
    )
    assert doc["counts"] == {
        "accepted_catalog": 1,
        "accepted_schema": 0,
        "slot_candidates": 1,
        "rejected": 0,
        "deferred_catalog": 0,
    }
    paths = write_distill_outputs(
        tmp_path,
        proposal_doc=doc,
        catalog_preview={"metric_aliases": {}},
        slot_candidates=[slot],
        timestamp="20260714T000000Z",
    )
    assert paths["proposal"].name == "alias_proposal_20260714T000000Z.json"
    written = json.loads(paths["proposal"].read_text(encoding="utf-8"))
    assert written["schema"] == "toy.loop_proposal/v2"
    slots_lines = paths["slots"].read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(slots_lines[0])["slot_kind"] == "time"
