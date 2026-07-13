"""Portable harness.eval_set/v1 load + offline validate (domain catalog injectable)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

SCHEMA_ID = "harness.eval_set/v1"

# Optional plugin hook: (metric, alias) -> (rejected: bool, detail: str)
AliasRejectFn = Callable[[str, str], tuple[bool, str]]


def load_eval_set(path: Path | str) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("eval_set must be a JSON object")
    return doc


def validate_eval_set_shape(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if doc.get("schema") != SCHEMA_ID:
        errors.append(f"schema must be {SCHEMA_ID!r}, got {doc.get('schema')!r}")
    for key in ("id", "domain", "cases"):
        if key not in doc:
            errors.append(f"missing field: {key}")
    cases = doc.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("cases must be a non-empty list")
        return errors
    seen: set[str] = set()
    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"cases[{i}] not an object")
            continue
        cid = case.get("id")
        if not cid or not isinstance(cid, str):
            errors.append(f"cases[{i}].id required")
        elif cid in seen:
            errors.append(f"duplicate case id: {cid}")
        else:
            seen.add(cid)
        turns = case.get("turns")
        if not isinstance(turns, list) or not turns:
            errors.append(f"cases[{cid!r}].turns must be non-empty")
        else:
            for j, turn in enumerate(turns):
                if not isinstance(turn, dict) or not str(turn.get("text") or "").strip():
                    errors.append(f"cases[{cid!r}].turns[{j}] needs non-empty text")
        expects = case.get("expects")
        if not isinstance(expects, list) or not expects:
            errors.append(f"cases[{cid!r}].expects must be non-empty")
    return errors


def catalog_aliases(catalog_path: Path | str, metric: str) -> list[str]:
    doc = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    aliases = (doc.get("metric_aliases") or {}).get(metric) or []
    return [str(a) for a in aliases]


def run_offline_expects(
    doc: dict[str, Any],
    *,
    catalog_path: Path | str | None = None,
    alias_reject_fn: AliasRejectFn | None = None,
) -> list[str]:
    """Execute offline expects. ``alias_must_reject`` needs ``alias_reject_fn`` (plugin)."""
    errors: list[str] = []
    for case in doc.get("cases") or []:
        cid = case.get("id")
        tags = set(case.get("tags") or [])
        turns = case.get("turns") or []
        for exp in case.get("expects") or []:
            if not isinstance(exp, dict):
                errors.append(f"{cid}: expect not object")
                continue
            et = exp.get("type")
            if et in ("live_non_empty_answer", "live_locale"):
                continue
            if et == "non_empty_turn_text":
                if any(not str(t.get("text") or "").strip() for t in turns):
                    errors.append(f"{cid}: empty turn text")
            elif et == "min_turns":
                n = int(exp.get("n") or 0)
                if len(turns) < n:
                    errors.append(f"{cid}: need >= {n} turns, got {len(turns)}")
            elif et == "tag_required":
                tag = str(exp.get("tag") or "")
                if tag and tag not in tags:
                    errors.append(f"{cid}: missing tag {tag!r}")
            elif et == "catalog_alias":
                metric = str(exp.get("metric") or "")
                alias = str(exp.get("alias") or "")
                if not catalog_path:
                    errors.append(f"{cid}: catalog_alias requires catalog_path")
                    continue
                try:
                    aliases = catalog_aliases(catalog_path, metric)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{cid}: catalog load failed: {exc}")
                    continue
                if alias not in aliases:
                    errors.append(f"{cid}: catalog {metric!r} missing alias {alias!r}")
            elif et == "alias_must_reject":
                metric = str(exp.get("metric") or "")
                alias = str(exp.get("alias") or "")
                if alias_reject_fn is None:
                    errors.append(
                        f"{cid}: alias_must_reject requires plugin reject hook "
                        "(use --plugin pha)"
                    )
                    continue
                try:
                    rejected, detail = alias_reject_fn(metric, alias)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{cid}: alias gate failed: {exc}")
                    continue
                if not rejected:
                    errors.append(
                        f"{cid}: expected reject for {metric!r}/{alias!r} "
                        f"but gates accepted ({detail})"
                    )
            else:
                errors.append(f"{cid}: unknown expect type {et!r}")
    return errors


def validate_file(
    path: Path | str,
    *,
    offline: bool = True,
    catalog_path: Path | str | None = None,
    alias_reject_fn: AliasRejectFn | None = None,
) -> list[str]:
    doc = load_eval_set(path)
    errors = validate_eval_set_shape(doc)
    if offline and not errors:
        errors.extend(
            run_offline_expects(
                doc,
                catalog_path=catalog_path,
                alias_reject_fn=alias_reject_fn,
            )
        )
    return errors


__all__ = [
    "SCHEMA_ID",
    "AliasRejectFn",
    "load_eval_set",
    "validate_eval_set_shape",
    "catalog_aliases",
    "run_offline_expects",
    "validate_file",
]
