#!/usr/bin/env python3
"""Stage 4-α.1 — Loop alias distiller (proposal-only, tiered output).

Reads ``slow_round_candidates.jsonl``, classifies phrases into:
  Tier-A  accepted_catalog  — pure metric cores for health_intent_catalog.json
  Tier-B  accepted_schema   — optional schema trigger proposals (non-fuzzy)
  Tier-C  slot_candidates   — time/aggregation modifiers (never enter catalog)
  rejected                  — failed 1E-a/b/c or classic conflict gates

No auto-merge. Human PR review required before promote.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


def _existing_aliases(metric: str) -> set[str]:
    return {_norm(a) for a in catalog_metric_aliases(metric)}


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _extract_candidate_phrases(message: str, metric: str) -> list[str]:
    """Deterministic phrase extraction — no LLM. Prefer full short messages."""
    msg = (message or "").strip()
    if not msg:
        return []
    existing = _existing_aliases(metric)
    phrases: list[str] = []

    # Full message if short enough and not already known.
    if 2 <= len(msg) <= 16 and _norm(msg) not in existing:
        phrases.append(msg)

    # Metric-specific colloquial n-grams (2–8 CJK chars or ASCII tokens).
    for m in re.finditer(r"[\u4e00-\u9fff]{2,8}|[a-zA-Z]{2,12}", msg):
        tok = m.group(0)
        if _norm(tok) in existing:
            continue
        if len(tok) < 2:
            continue
        phrases.append(tok)

    seen: set[str] = set()
    out: list[str] = []
    for p in phrases:
        n = _norm(p)
        if n in seen:
            continue
        seen.add(n)
        out.append(p)
    return out[:5]


def _cluster_candidates(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        metric = str(row.get("suggested_metric") or row.get("intent_family") or "").strip()
        if not metric or metric in ("holistic", "attachment"):
            continue
        if metric not in SCHEMA_ASSET_FOR_METRIC and metric not in load_health_intent_catalog().get(
            "metric_aliases",
            {},
        ):
            continue
        clusters[metric].append(row)
    return clusters


def _build_tiered_proposals(
    clusters: dict[str, list[dict[str, Any]]],
) -> tuple[
    list[AliasProposal],
    list[AliasProposal],
    list[AliasProposal],
    list[dict[str, Any]],
]:
    """Return (catalog, schema, slots, rejected)."""
    accepted_catalog: list[AliasProposal] = []
    accepted_schema: list[AliasProposal] = []
    slot_candidates: list[AliasProposal] = []
    rejected: list[dict[str, Any]] = []

    seen_catalog: set[str] = set()
    seen_slots: set[str] = set()

    for metric, rows in sorted(clusters.items()):
        asset = SCHEMA_ASSET_FOR_METRIC.get(metric, "")
        for row in rows:
            msg = str(row.get("message") or "")
            signal = str(row.get("signal") or "")
            for phrase in _extract_candidate_phrases(msg, metric):
                classification = classify_alias_phrase(
                    phrase,
                    metric_id=metric,
                    source_message=msg,
                )

                # Always record Tier-C slots peeled from the phrase.
                for slot in classification.slot_candidates:
                    sk = f"{slot.kind}:{_norm(slot.token)}:{metric}"
                    if sk in seen_slots:
                        continue
                    seen_slots.add(sk)
                    slot_candidates.append(
                        AliasProposal(
                            layer="slot",
                            target=metric,
                            alias=slot.token,
                            metric_id=metric,
                            source_message=slot.source_message or msg,
                            signal=signal,
                            slot_kind=slot.kind,
                        ),
                    )

                if classification.tier == "catalog" and classification.core_alias:
                    core = classification.core_alias
                    key = f"catalog:{metric}:{_norm(core)}"
                    if key in seen_catalog:
                        continue
                    prop = AliasProposal(
                        layer="catalog",
                        target=metric,
                        alias=core,
                        metric_id=metric,
                        source_message=msg,
                        signal=signal,
                    )
                    report = validate_alias_proposals(accepted_catalog + [prop])
                    if report.ok:
                        seen_catalog.add(key)
                        accepted_catalog.append(prop)
                    else:
                        rejected.append(
                            {
                                "proposal": prop.as_dict(),
                                "tier_attempted": "catalog",
                                "conflicts": report.errors(),
                                "classification": classification.as_dict(),
                            },
                        )
                elif classification.tier == "schema" and classification.core_alias and asset:
                    core = classification.core_alias
                    prop = AliasProposal(
                        layer="schema",
                        target=asset,
                        alias=core,
                        metric_id=metric,
                        source_message=msg,
                        signal=signal,
                    )
                    report = validate_alias_proposals(accepted_schema + [prop])
                    if report.ok:
                        accepted_schema.append(prop)
                    else:
                        rejected.append(
                            {
                                "proposal": prop.as_dict(),
                                "tier_attempted": "schema",
                                "conflicts": report.errors(),
                                "classification": classification.as_dict(),
                            },
                        )
                elif classification.tier == "slot":
                    # Slots already recorded; if core failed, note rejection of core.
                    if classification.reject_reasons:
                        rejected.append(
                            {
                                "proposal": {
                                    "layer": "catalog",
                                    "target": metric,
                                    "alias": phrase,
                                    "metric_id": metric,
                                    "signal": signal,
                                    "source_message": msg,
                                },
                                "tier_attempted": "catalog",
                                "conflicts": classification.reject_reasons,
                                "classification": classification.as_dict(),
                                "note": "dynamic modifiers peeled to Tier-C; core not catalog-eligible",
                            },
                        )
                elif classification.tier == "rejected":
                    rejected.append(
                        {
                            "proposal": {
                                "layer": "catalog",
                                "target": metric,
                                "alias": phrase,
                                "metric_id": metric,
                                "signal": signal,
                                "source_message": msg,
                            },
                            "tier_attempted": "catalog",
                            "conflicts": classification.reject_reasons,
                            "classification": classification.as_dict(),
                        },
                    )

    return accepted_catalog, accepted_schema, slot_candidates, rejected


def _apply_catalog_proposals(proposals: list[AliasProposal]) -> dict[str, Any]:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    aliases = catalog.setdefault("metric_aliases", {})
    patch_ops: list[dict[str, Any]] = []
    for prop in proposals:
        if prop.layer != "catalog":
            continue
        bucket = aliases.setdefault(prop.target, [])
        if prop.alias in bucket:
            continue
        bucket.append(prop.alias)
        patch_ops.append(
            {
                "op": "add",
                "path": f"/metric_aliases/{prop.target}",
                "value": prop.alias,
                "signal": prop.signal,
                "source_message": prop.source_message,
            },
        )
    return {"catalog_preview": catalog, "patch_ops": patch_ops}


def _prefer_catalog_budget(proposals: list[AliasProposal]) -> list[AliasProposal]:
    """Keep at most N Tier-A proposals for PR draft (prefer sleep/steps cores)."""
    if len(proposals) <= _MAX_CATALOG_PROMOTE:
        return proposals
    priority = {"睡多久": 0, "走了多少步": 1, "多少步": 2}
    ranked = sorted(
        proposals,
        key=lambda p: (priority.get(p.alias, 50), p.target, p.alias),
    )
    return ranked[:_MAX_CATALOG_PROMOTE]


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
    clusters = _cluster_candidates(rows)
    accepted_catalog, accepted_schema, slot_candidates, rejected = _build_tiered_proposals(
        clusters,
    )

    baseline = detect_all_keyword_conflicts()
    if not baseline.ok:
        print("WARN baseline keyword conflicts (fix before promoting proposals):", file=sys.stderr)
        for err in baseline.errors()[:10]:
            print(f"  {err}", file=sys.stderr)

    catalog_for_pr = (
        accepted_catalog if args.no_budget else _prefer_catalog_budget(accepted_catalog)
    )
    deferred = [
        p.as_dict()
        for p in accepted_catalog
        if p not in catalog_for_pr
    ]

    patch_doc = _apply_catalog_proposals(catalog_for_pr)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    proposal = {
        "schema": "pha.loop_proposal/v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage": "4-alpha-1",
        "candidates_path": str(candidates_path),
        "candidate_count": len(rows),
        "cluster_metrics": sorted(clusters.keys()),
        "accepted_catalog": [p.as_dict() for p in catalog_for_pr],
        "accepted_schema": [p.as_dict() for p in accepted_schema],
        "slot_candidates": [p.as_dict() for p in slot_candidates],
        "rejected": rejected,
        "deferred_catalog": deferred,
        "patch_ops": patch_doc["patch_ops"],
        "counts": {
            "accepted_catalog": len(catalog_for_pr),
            "accepted_schema": len(accepted_schema),
            "slot_candidates": len(slot_candidates),
            "rejected": len(rejected),
            "deferred_catalog": len(deferred),
        },
        "notes": (
            "Proposal-only — Tier-A catalog only for human PR. "
            "Tier-C slot_candidates must NEVER enter health_intent_catalog.json. "
            "Do NOT auto-merge. Run nightly 148+164 before promote."
        ),
    }

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

    out_dir.mkdir(parents=True, exist_ok=True)
    proposal_path = out_dir / f"alias_proposal_{ts}.json"
    preview_path = out_dir / f"catalog_preview_{ts}.json"
    slots_path = out_dir / f"slot_candidates_{ts}.jsonl"

    proposal_path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    preview_path.write_text(
        json.dumps(patch_doc["catalog_preview"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with slots_path.open("w", encoding="utf-8") as fh:
        for p in slot_candidates:
            fh.write(json.dumps(p.as_dict(), ensure_ascii=False) + "\n")

    print(f" proposal artifact   : {proposal_path}")
    print(f" catalog preview     : {preview_path}")
    print(f" slot candidates     : {slots_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
