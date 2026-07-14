"""Portable loop_proposal/v2 + promote_verdict/v1 shape validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness_loop import SCHEMA_LOOP_PROPOSAL, SCHEMA_PROMOTE_VERDICT

LOOP_PROPOSAL_SCHEMAS = frozenset(
    {
        SCHEMA_LOOP_PROPOSAL,
        "harness.loop_proposal/v2",  # migration alias (protocol §11.2)
    }
)
PROMOTE_VERDICT_SCHEMAS = frozenset({SCHEMA_PROMOTE_VERDICT})


def load_json(path: Path | str) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("document must be a JSON object")
    return doc


def validate_loop_proposal(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema = doc.get("schema")
    if schema not in LOOP_PROPOSAL_SCHEMAS:
        errors.append(
            f"schema must be one of {sorted(LOOP_PROPOSAL_SCHEMAS)!r}, got {schema!r}"
        )
    for key in ("generated_at", "stage", "source"):
        if not str(doc.get(key) or "").strip():
            errors.append(f"missing or empty field: {key}")
    for list_key in (
        "accepted_catalog",
        "accepted_schema",
        "slot_candidates",
        "rejected",
    ):
        val = doc.get(list_key)
        if val is not None and not isinstance(val, list):
            errors.append(f"{list_key} must be a list when present")
    patch_ops = doc.get("patch_ops")
    if patch_ops is not None and not isinstance(patch_ops, list):
        errors.append("patch_ops must be a list when present")
    code_review = doc.get("code_review_items")
    if code_review is not None and not isinstance(code_review, list):
        errors.append("code_review_items must be a list when present")
    regress = doc.get("suggested_regression")
    if regress is not None and not isinstance(regress, list):
        errors.append("suggested_regression must be a list when present")
    return errors


def validate_promote_verdict(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema = doc.get("schema")
    if schema not in PROMOTE_VERDICT_SCHEMAS:
        errors.append(
            f"schema must be {SCHEMA_PROMOTE_VERDICT!r}, got {schema!r}"
        )
    for key in ("generated_at", "proposal_path"):
        if not str(doc.get(key) or "").strip():
            errors.append(f"missing or empty field: {key}")
    if "passed" not in doc:
        errors.append("missing field: passed")
    elif not isinstance(doc.get("passed"), bool):
        errors.append("passed must be boolean")
    static_veto = doc.get("static_veto")
    if static_veto is not None and not isinstance(static_veto, list):
        errors.append("static_veto must be a list when present")
    checks = doc.get("checks")
    if checks is not None and not isinstance(checks, list):
        errors.append("checks must be a list when present")
    return errors


def validate_proposal_file(path: Path | str) -> list[str]:
    return validate_loop_proposal(load_json(path))


def validate_verdict_file(path: Path | str) -> list[str]:
    return validate_promote_verdict(load_json(path))


def static_veto(
    doc: dict[str, Any],
    *,
    patch_path_prefix: str = "/metric_aliases/",
    require_proposal_schema: bool = True,
) -> list[str]:
    """Portable promote static gates (no regression suites; never applies patches)."""
    veto: list[str] = []
    schema = doc.get("schema")
    if require_proposal_schema and schema not in LOOP_PROPOSAL_SCHEMAS:
        veto.append(f"schema_not_registered:{schema!r}")
    if doc.get("code_review_items"):
        veto.append("code_review_items_present")
    for op in doc.get("patch_ops") or []:
        if not isinstance(op, dict):
            veto.append("patch_op_not_object")
            continue
        path = str(op.get("path") or "")
        if patch_path_prefix and not path.startswith(patch_path_prefix):
            veto.append(f"patch_outside_allowlist:{path}")
    for item in doc.get("slot_candidates") or []:
        if isinstance(item, dict) and (item.get("layer") or "") == "catalog":
            veto.append("tier_c_slot_promoted_to_catalog")
    return sorted(set(veto))


def write_static_promote_verdict(
    proposal_path: Path | str,
    *,
    out_dir: Path | str,
    patch_path_prefix: str = "/metric_aliases/",
) -> tuple[Path, dict[str, Any]]:
    """Shape-check + static veto → write promote_verdict JSON (dry-run only)."""
    from datetime import datetime, timezone

    proposal_path = Path(proposal_path)
    doc = load_json(proposal_path)
    shape_errors = validate_loop_proposal(doc)
    veto = static_veto(doc, patch_path_prefix=patch_path_prefix)
    if shape_errors:
        veto = sorted(set(veto + [f"shape:{e}" for e in shape_errors]))
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    verdict: dict[str, Any] = {
        "schema": SCHEMA_PROMOTE_VERDICT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "proposal_path": str(proposal_path.resolve()),
        "proposal": {
            "schema": doc.get("schema"),
            "source": doc.get("source"),
            "stage": doc.get("stage"),
            "counts": doc.get("counts") or {},
            "suggested_regression": doc.get("suggested_regression") or [],
        },
        "static_veto": veto,
        "checks": [],
        "passed": len(veto) == 0,
        "notes": "static-only promote; dry-run; no auto-merge; no catalog write",
    }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    out_path = out / f"promote_verdict_{ts}.json"
    out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path, verdict


__all__ = [
    "LOOP_PROPOSAL_SCHEMAS",
    "PROMOTE_VERDICT_SCHEMAS",
    "load_json",
    "validate_loop_proposal",
    "validate_promote_verdict",
    "validate_proposal_file",
    "validate_verdict_file",
    "static_veto",
    "write_static_promote_verdict",
]
