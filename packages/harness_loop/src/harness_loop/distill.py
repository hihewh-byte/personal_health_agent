"""Portable distill stages — phrase extraction, clustering, tiered admission,
budget, patch ops, proposal assembly.

Domain knowledge (catalogs, gate sets, language normalization, proposal
dataclasses) is injected via callables. This module never reads or writes
domain catalogs and never merges anything — proposal-only.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from harness_loop.gates import norm_token

DEFAULT_PHRASE_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,8}|[a-zA-Z]{2,12}")

# (message, metric) -> ordered candidate phrases
PhraseFn = Callable[[str, str], list[str]]
# (phrase, metric, source_message) -> TierClassification-like object
ClassifyFn = Callable[[str, str, str], Any]
# (proposals so far + new one) -> (ok, error strings)
ValidateFn = Callable[[list[Any]], tuple[bool, list[str]]]
# keyword factory for a domain proposal object (needs .as_dict())
MakeProposalFn = Callable[..., Any]


def extract_phrases(
    message: str,
    *,
    known_aliases: set[str] | frozenset[str] = frozenset(),
    pattern: re.Pattern[str] | str = DEFAULT_PHRASE_PATTERN,
    full_message_len: tuple[int, int] = (2, 16),
    min_token_len: int = 2,
    max_phrases: int = 5,
) -> list[str]:
    """Deterministic phrase extraction — no LLM.

    Prefers the full short message, then token n-grams from ``pattern``;
    skips ``known_aliases`` (normalized) and dedupes preserving order.
    """
    msg = (message or "").strip()
    if not msg:
        return []
    pat = re.compile(pattern) if isinstance(pattern, str) else pattern
    known = {norm_token(a) for a in known_aliases}
    phrases: list[str] = []

    lo, hi = full_message_len
    if lo <= len(msg) <= hi and norm_token(msg) not in known:
        phrases.append(msg)

    for m in pat.finditer(msg):
        tok = m.group(0)
        if norm_token(tok) in known:
            continue
        if len(tok) < min_token_len:
            continue
        phrases.append(tok)

    seen: set[str] = set()
    out: list[str] = []
    for p in phrases:
        n = norm_token(p)
        if n in seen:
            continue
        seen.add(n)
        out.append(p)
    return out[:max_phrases]


def cluster_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    metric_fn: Callable[[Mapping[str, Any]], str | None],
) -> dict[str, list[dict[str, Any]]]:
    """Group candidate rows by metric; ``metric_fn`` returns None to skip a row."""
    clusters: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        metric = metric_fn(row)
        if not metric:
            continue
        clusters.setdefault(metric, []).append(dict(row))
    return clusters


def build_tiered_proposals(
    clusters: Mapping[str, list[dict[str, Any]]],
    *,
    phrase_fn: PhraseFn,
    classify_fn: ClassifyFn,
    validate_fn: ValidateFn,
    make_proposal: MakeProposalFn,
    asset_for_metric: Mapping[str, str] | None = None,
) -> tuple[list[Any], list[Any], list[Any], list[dict[str, Any]]]:
    """Tiered admission loop. Returns (catalog, schema, slots, rejected).

    Per phrase: classify → always record peeled Tier-C slots (deduped) →
    admit Tier-A/Tier-B through ``validate_fn`` (batch-aware) or record a
    structured rejection with the classification verdict attached.
    """
    assets = asset_for_metric or {}
    accepted_catalog: list[Any] = []
    accepted_schema: list[Any] = []
    slot_candidates: list[Any] = []
    rejected: list[dict[str, Any]] = []

    seen_catalog: set[str] = set()
    seen_slots: set[str] = set()

    for metric, rows in sorted(clusters.items()):
        asset = assets.get(metric, "")
        for row in rows:
            msg = str(row.get("message") or "")
            signal = str(row.get("signal") or "")
            for phrase in phrase_fn(msg, metric):
                classification = classify_fn(phrase, metric, msg)

                for slot in classification.slot_candidates:
                    sk = f"{slot.kind}:{norm_token(slot.token)}:{metric}"
                    if sk in seen_slots:
                        continue
                    seen_slots.add(sk)
                    slot_candidates.append(
                        make_proposal(
                            layer="slot",
                            target=metric,
                            alias=slot.token,
                            metric_id=metric,
                            source_message=slot.source_message or msg,
                            signal=signal,
                            slot_kind=slot.kind,
                        )
                    )

                raw_proposal = {
                    "layer": "catalog",
                    "target": metric,
                    "alias": phrase,
                    "metric_id": metric,
                    "signal": signal,
                    "source_message": msg,
                }

                if classification.tier == "catalog" and classification.core_alias:
                    core = classification.core_alias
                    key = f"catalog:{metric}:{norm_token(core)}"
                    if key in seen_catalog:
                        continue
                    prop = make_proposal(
                        layer="catalog",
                        target=metric,
                        alias=core,
                        metric_id=metric,
                        source_message=msg,
                        signal=signal,
                    )
                    ok, errors = validate_fn(accepted_catalog + [prop])
                    if ok:
                        seen_catalog.add(key)
                        accepted_catalog.append(prop)
                    else:
                        rejected.append(
                            {
                                "proposal": prop.as_dict(),
                                "tier_attempted": "catalog",
                                "conflicts": errors,
                                "classification": classification.as_dict(),
                            }
                        )
                elif classification.tier == "schema" and classification.core_alias and asset:
                    prop = make_proposal(
                        layer="schema",
                        target=asset,
                        alias=classification.core_alias,
                        metric_id=metric,
                        source_message=msg,
                        signal=signal,
                    )
                    ok, errors = validate_fn(accepted_schema + [prop])
                    if ok:
                        accepted_schema.append(prop)
                    else:
                        rejected.append(
                            {
                                "proposal": prop.as_dict(),
                                "tier_attempted": "schema",
                                "conflicts": errors,
                                "classification": classification.as_dict(),
                            }
                        )
                elif classification.tier == "slot":
                    if classification.reject_reasons:
                        rejected.append(
                            {
                                "proposal": raw_proposal,
                                "tier_attempted": "catalog",
                                "conflicts": list(classification.reject_reasons),
                                "classification": classification.as_dict(),
                                "note": (
                                    "dynamic modifiers peeled to Tier-C; "
                                    "core not catalog-eligible"
                                ),
                            }
                        )
                elif classification.tier == "rejected":
                    rejected.append(
                        {
                            "proposal": raw_proposal,
                            "tier_attempted": "catalog",
                            "conflicts": list(classification.reject_reasons),
                            "classification": classification.as_dict(),
                        }
                    )

    return accepted_catalog, accepted_schema, slot_candidates, rejected


def apply_promote_budget(
    proposals: list[Any],
    *,
    max_promote: int,
    priority: Mapping[str, int] | None = None,
    default_priority: int = 50,
) -> list[Any]:
    """Keep at most ``max_promote`` proposals, ranked by priority/target/alias."""
    if len(proposals) <= max_promote:
        return proposals
    prio = priority or {}
    ranked = sorted(
        proposals,
        key=lambda p: (prio.get(p.alias, default_priority), p.target, p.alias),
    )
    return ranked[:max_promote]


def apply_catalog_patch(
    catalog_doc: dict[str, Any],
    proposals: Sequence[Any],
    *,
    aliases_key: str = "metric_aliases",
) -> dict[str, Any]:
    """Simulate catalog patch on an in-memory doc; emit RFC6902-ish add ops.

    Callers own loading/writing the catalog file — this never touches disk.
    """
    aliases = catalog_doc.setdefault(aliases_key, {})
    patch_ops: list[dict[str, Any]] = []
    for prop in proposals:
        if getattr(prop, "layer", "") != "catalog":
            continue
        bucket = aliases.setdefault(prop.target, [])
        if prop.alias in bucket:
            continue
        bucket.append(prop.alias)
        patch_ops.append(
            {
                "op": "add",
                "path": f"/{aliases_key}/{prop.target}",
                "value": prop.alias,
                "signal": prop.signal,
                "source_message": prop.source_message,
            }
        )
    return {"catalog_preview": catalog_doc, "patch_ops": patch_ops}


def assemble_proposal_doc(
    *,
    schema: str,
    stage: str,
    candidates_path: str,
    candidate_count: int,
    cluster_metrics: Sequence[str],
    accepted_catalog: Sequence[Any],
    accepted_schema: Sequence[Any],
    slot_candidates: Sequence[Any],
    rejected: Sequence[dict[str, Any]],
    deferred_catalog: Sequence[dict[str, Any]],
    patch_ops: Sequence[dict[str, Any]],
    notes: str,
) -> dict[str, Any]:
    """Assemble the loop_proposal document (proposal-only; humans merge)."""
    return {
        "schema": schema,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "candidates_path": candidates_path,
        "candidate_count": candidate_count,
        "cluster_metrics": sorted(cluster_metrics),
        "accepted_catalog": [p.as_dict() for p in accepted_catalog],
        "accepted_schema": [p.as_dict() for p in accepted_schema],
        "slot_candidates": [p.as_dict() for p in slot_candidates],
        "rejected": list(rejected),
        "deferred_catalog": list(deferred_catalog),
        "patch_ops": list(patch_ops),
        "counts": {
            "accepted_catalog": len(accepted_catalog),
            "accepted_schema": len(accepted_schema),
            "slot_candidates": len(slot_candidates),
            "rejected": len(rejected),
            "deferred_catalog": len(deferred_catalog),
        },
        "notes": notes,
    }


def write_distill_outputs(
    out_dir: Path | str,
    *,
    proposal_doc: dict[str, Any],
    catalog_preview: dict[str, Any],
    slot_candidates: Sequence[Any],
    timestamp: str | None = None,
) -> dict[str, Path]:
    """Write proposal / preview / slots artifacts with the Loop naming scheme."""
    ts = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    proposal_path = out / f"alias_proposal_{ts}.json"
    preview_path = out / f"catalog_preview_{ts}.json"
    slots_path = out / f"slot_candidates_{ts}.jsonl"

    proposal_path.write_text(
        json.dumps(proposal_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    preview_path.write_text(
        json.dumps(catalog_preview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with slots_path.open("w", encoding="utf-8") as fh:
        for p in slot_candidates:
            fh.write(json.dumps(p.as_dict(), ensure_ascii=False) + "\n")

    return {"proposal": proposal_path, "preview": preview_path, "slots": slots_path}


__all__ = [
    "DEFAULT_PHRASE_PATTERN",
    "ClassifyFn",
    "MakeProposalFn",
    "PhraseFn",
    "ValidateFn",
    "apply_catalog_patch",
    "apply_promote_budget",
    "assemble_proposal_doc",
    "build_tiered_proposals",
    "cluster_rows",
    "extract_phrases",
    "write_distill_outputs",
]
