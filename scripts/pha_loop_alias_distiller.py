#!/usr/bin/env python3
"""Stage 4-α.1 — Loop alias distiller (proposal-only, tiered output).

Reads ``slow_round_candidates.jsonl``, classifies phrases into:
  Tier-A  accepted_catalog  — pure metric cores for health_intent_catalog.json
  Tier-B  accepted_schema   — optional schema trigger proposals (non-fuzzy)
  Tier-C  slot_candidates   — time/aggregation modifiers (never enter catalog)
  rejected                  — failed 1E-a/b/c gates or classic conflict gates

Since Harness Loop 0.1.0a4 the portable stages (phrase extraction, cluster,
tiered admission, budget, patch ops, artifact writing) live in
``harness_loop.distill``; this script keeps only PHA domain knowledge
(catalog lookups, 1E gates, schema asset map, PR budget priorities).

No auto-merge. Human PR review required before promote.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness_loop.distill import (  # noqa: E402
    apply_catalog_patch,
    apply_promote_budget,
    assemble_proposal_doc,
    build_tiered_proposals,
    cluster_rows,
    extract_phrases,
    write_distill_outputs,
)
from pha.health_intent_catalog import (  # noqa: E402
    catalog_metric_aliases,
    load_health_intent_catalog,
)
from pha.loop_keyword_conflicts import (  # noqa: E402
    AliasProposal,
    classify_alias_phrase,
    detect_all_keyword_conflicts,
    validate_alias_proposals,
)

DEFAULT_CANDIDATES = ROOT / "reports" / "loop" / "slow_round_candidates.jsonl"
DEFAULT_PROPOSAL_DIR = ROOT / "reports" / "loop" / "proposals"
CATALOG_PATH = ROOT / "rules" / "health_intent_catalog.json"
SCHEMA_ASSET_FOR_METRIC = {
    "hrv": "wearable_bundle",
    "sleep": "wearable_bundle",
    "steps": "wearable_bundle",
    "rhr": "wearable_bundle",
    "spo2": "wearable_bundle",
    "respiratory_rate": "wearable_bundle",
    "activity_kcal": "wearable_bundle",
    "vo2max": "wearable_bundle",
    "wrist_temp": "wearable_bundle",
    "ldl": "lab_lipid_panel",
}

# Prefer at most this many Tier-A catalog proposals per run (PR draft budget).
_MAX_CATALOG_PROMOTE = 2
_CATALOG_BUDGET_PRIORITY = {"睡多久": 0, "走了多少步": 1, "多少步": 2}


def _load_candidates(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _row_metric(row: dict[str, Any]) -> str | None:
    """PHA cluster rule: known metric families only; holistic/attachment skipped."""
    metric = str(row.get("suggested_metric") or row.get("intent_family") or "").strip()
    if not metric or metric in ("holistic", "attachment"):
        return None
    if metric not in SCHEMA_ASSET_FOR_METRIC and metric not in load_health_intent_catalog().get(
        "metric_aliases",
        {},
    ):
        return None
    return metric


def _phrase_fn(message: str, metric: str) -> list[str]:
    """PHA phrase extraction: skip aliases already curated for this metric."""
    known = {a for a in catalog_metric_aliases(metric)}
    return extract_phrases(message, known_aliases=known)


def _classify_fn(phrase: str, metric: str, source_message: str):
    return classify_alias_phrase(phrase, metric_id=metric, source_message=source_message)


def _validate_fn(proposals: list[AliasProposal]) -> tuple[bool, list[str]]:
    report = validate_alias_proposals(proposals)
    return report.ok, report.errors()


def main() -> int:
    ap = argparse.ArgumentParser(description="Loop alias distiller (Stage 4-α.1, tiered)")
    ap.add_argument("--candidates", default=str(DEFAULT_CANDIDATES))
    ap.add_argument("--out-dir", default=str(DEFAULT_PROPOSAL_DIR))
    ap.add_argument("--dry-run", action="store_true", help="Skip writing proposal files")
    ap.add_argument(
        "--no-budget",
        action="store_true",
        help="Do not cap Tier-A proposals at 2",
    )
    args = ap.parse_args()

    candidates_path = Path(args.candidates)
    out_dir = Path(args.out_dir)
    rows = _load_candidates(candidates_path)
    clusters = cluster_rows(rows, metric_fn=_row_metric)
    accepted_catalog, accepted_schema, slot_candidates, rejected = build_tiered_proposals(
        clusters,
        phrase_fn=_phrase_fn,
        classify_fn=_classify_fn,
        validate_fn=_validate_fn,
        make_proposal=AliasProposal,
        asset_for_metric=SCHEMA_ASSET_FOR_METRIC,
    )

    baseline = detect_all_keyword_conflicts()
    if not baseline.ok:
        print("WARN baseline keyword conflicts (fix before promoting proposals):", file=sys.stderr)
        for err in baseline.errors()[:10]:
            print(f"  {err}", file=sys.stderr)

    catalog_for_pr = (
        accepted_catalog
        if args.no_budget
        else apply_promote_budget(
            accepted_catalog,
            max_promote=_MAX_CATALOG_PROMOTE,
            priority=_CATALOG_BUDGET_PRIORITY,
        )
    )
    deferred = [p.as_dict() for p in accepted_catalog if p not in catalog_for_pr]

    catalog_doc = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    patch_doc = apply_catalog_patch(catalog_doc, catalog_for_pr)
    proposal = assemble_proposal_doc(
        schema="pha.loop_proposal/v2",
        stage="4-alpha-1",
        candidates_path=str(candidates_path),
        candidate_count=len(rows),
        cluster_metrics=list(clusters.keys()),
        accepted_catalog=catalog_for_pr,
        accepted_schema=accepted_schema,
        slot_candidates=slot_candidates,
        rejected=rejected,
        deferred_catalog=deferred,
        patch_ops=patch_doc["patch_ops"],
        notes=(
            "Proposal-only — Tier-A catalog only for human PR. "
            "Tier-C slot_candidates must NEVER enter health_intent_catalog.json. "
            "Do NOT auto-merge. Run nightly 148+164 before promote."
        ),
    )

    print("== loop alias distiller (Stage 4-α.1) ==")
    print(f" candidates file     : {candidates_path} ({len(rows)} rows)")
    print(f" clusters            : {dict((k, len(v)) for k, v in clusters.items())}")
    print(f" Tier-A catalog      : {len(catalog_for_pr)} → {[p.alias for p in catalog_for_pr]}")
    print(f" Tier-B schema       : {len(accepted_schema)}")
    print(f" Tier-C slots        : {len(slot_candidates)} → {[p.alias for p in slot_candidates]}")
    print(f" rejected            : {len(rejected)}")
    if deferred:
        print(f" deferred (budget)   : {[d.get('alias') for d in deferred]}")

    if args.dry_run:
        print(" dry-run: no files written")
        return 0

    paths = write_distill_outputs(
        out_dir,
        proposal_doc=proposal,
        catalog_preview=patch_doc["catalog_preview"],
        slot_candidates=slot_candidates,
    )
    print(f" proposal artifact   : {paths['proposal']}")
    print(f" catalog preview     : {paths['preview']}")
    print(f" slot candidates     : {paths['slots']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
