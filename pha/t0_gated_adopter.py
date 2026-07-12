"""Loop B · L0 gated adopter — apply reviewed T0 ingest proposals (append-only)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pha.date_parser import safe_parse_date
from pha.medical_storage import MedicalMetricRow, upsert_medical_metrics

_ALLOWED_PROV_TYPES = frozenset({"lab_report", "wearable_import", "attachment_ingest"})
_ALLOWED_CONFIDENCE = frozenset({"high", "medium"})
_USER_STATEMENT = "user_statement"


@dataclass(frozen=True)
class T0AdoptionResult:
    applied: int
    skipped: int
    veto: list[str]
    adoption_id: str
    rows: list[dict[str, Any]]


def _parse_value(text: str) -> float | None:
    raw = (text or "").strip().replace(",", "")
    m = re.search(r"[-+]?\d*\.?\d+", raw)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _parse_report_date(observed_at: str) -> date | None:
    text = (observed_at or "").strip()
    if not text:
        return None
    if len(text) >= 10:
        d = safe_parse_date(text[:10])
        if d:
            return d
    return safe_parse_date(text)


def static_veto_proposal(
    doc: dict[str, Any],
    *,
    allow_user_statement: bool = False,
) -> list[str]:
    veto: list[str] = []
    if doc.get("schema") != "pha.t0_ingest_proposal/v1":
        veto.append("schema_not_pha.t0_ingest_proposal/v1")
    rows = doc.get("rows") or []
    if not isinstance(rows, list) or not rows:
        veto.append("empty_rows")
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            veto.append(f"row_{idx}_not_object")
            continue
        prov = str(row.get("prov_type") or "").strip()
        if prov == _USER_STATEMENT and not allow_user_statement:
            veto.append(f"row_{idx}_user_statement_blocked")
        elif prov not in _ALLOWED_PROV_TYPES and prov != _USER_STATEMENT:
            veto.append(f"row_{idx}_prov_type:{prov or 'missing'}")
        conf = str(row.get("confidence") or "medium").strip().lower()
        if conf not in _ALLOWED_CONFIDENCE:
            veto.append(f"row_{idx}_confidence:{conf}")
        if not str(row.get("source_ref") or "").strip():
            veto.append(f"row_{idx}_missing_source_ref")
        if not str(row.get("item") or "").strip():
            veto.append(f"row_{idx}_missing_item")
        if not str(row.get("value_text") or "").strip():
            veto.append(f"row_{idx}_missing_value")
        if prov == "lab_report" and not str(row.get("observed_at") or "").strip():
            veto.append(f"row_{idx}_lab_missing_observed_at")
    return sorted(set(veto))


def proposal_to_metric_rows(
    doc: dict[str, Any],
    *,
    user_id: str | None = None,
) -> tuple[list[MedicalMetricRow], list[str]]:
    uid = (user_id or doc.get("user_id") or "default").strip() or "default"
    out: list[MedicalMetricRow] = []
    skips: list[str] = []
    for idx, row in enumerate(doc.get("rows") or []):
        if not isinstance(row, dict):
            skips.append(f"row_{idx}_skip:not_object")
            continue
        prov = str(row.get("prov_type") or "").strip()
        if prov not in _ALLOWED_PROV_TYPES:
            skips.append(f"row_{idx}_skip:prov_type:{prov}")
            continue
        item = str(row.get("item") or "").strip()
        val = _parse_value(str(row.get("value_text") or ""))
        if val is None:
            skips.append(f"row_{idx}_skip:unparseable_value")
            continue
        report_d = _parse_report_date(str(row.get("observed_at") or ""))
        if report_d is None:
            skips.append(f"row_{idx}_skip:bad_observed_at")
            continue
        source = str(row.get("source_ref") or row.get("source_filename") or "t0_adopt").strip()
        out.append(
            MedicalMetricRow(
                user_id=uid,
                report_date=report_d,
                metric_name=item,
                value=val,
                unit=str(row.get("unit") or "").strip(),
                reference_range=str(row.get("reference_range") or "").strip(),
                source_filename=source[:240],
                metric_code=item,
                name_en=item,
                name_zh=item,
            ),
        )
    return out, skips


def build_adoption_record(
    doc: dict[str, Any],
    *,
    proposal_path: str,
    applied: int,
    skipped: int,
    veto: list[str],
    metric_rows: list[MedicalMetricRow],
    confirm_token: str = "",
) -> dict[str, Any]:
    payload = json.dumps(doc, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return {
        "schema": "pha.t0_adoption_record/v1",
        "adoption_id": f"t0_adopt_{ts}_{digest}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "proposal_path": proposal_path,
        "proposal_schema": doc.get("schema"),
        "user_id": doc.get("user_id"),
        "confirm_token_present": bool(confirm_token),
        "static_veto": veto,
        "applied_rows": applied,
        "skipped_rows": skipped,
        "metrics": [
            {
                "report_date": r.report_date.isoformat(),
                "metric_name": r.metric_name,
                "value": r.value,
                "unit": r.unit,
                "source_filename": r.source_filename,
            }
            for r in metric_rows
        ],
        "notes": "Append-only adoption via upsert_medical_metrics; prior rows for same day+metric replaced.",
    }


def apply_t0_ingest_proposal(
    doc: dict[str, Any],
    *,
    proposal_path: str = "",
    allow_user_statement: bool = False,
    confirm_token: str = "",
    dry_run: bool = True,
) -> T0AdoptionResult:
    veto = static_veto_proposal(doc, allow_user_statement=allow_user_statement)
    if veto:
        return T0AdoptionResult(
            applied=0,
            skipped=len(doc.get("rows") or []),
            veto=veto,
            adoption_id="",
            rows=[],
        )
    if not dry_run and not (confirm_token or "").strip():
        veto = ["confirm_token_required_for_apply"]
        return T0AdoptionResult(
            applied=0,
            skipped=len(doc.get("rows") or []),
            veto=veto,
            adoption_id="",
            rows=[],
        )

    metric_rows, row_skips = proposal_to_metric_rows(doc)
    if row_skips and not metric_rows:
        veto = sorted(set(row_skips))
        return T0AdoptionResult(
            applied=0,
            skipped=len(doc.get("rows") or []),
            veto=veto,
            adoption_id="",
            rows=[],
        )

    applied = 0
    if not dry_run and metric_rows:
        applied = upsert_medical_metrics(metric_rows)

    record = build_adoption_record(
        doc,
        proposal_path=proposal_path,
        applied=applied if not dry_run else len(metric_rows),
        skipped=len(row_skips),
        veto=[],
        metric_rows=metric_rows,
        confirm_token=confirm_token,
    )
    if dry_run:
        record["dry_run"] = True
        record["would_apply_rows"] = len(metric_rows)

    return T0AdoptionResult(
        applied=applied if not dry_run else 0,
        skipped=len(row_skips),
        veto=[],
        adoption_id=str(record.get("adoption_id") or ""),
        rows=[record],
    )


def write_adoption_record(
    record: dict[str, Any],
    *,
    out_dir: Path,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    aid = str(record.get("adoption_id") or "t0_adopt_unknown")
    path = out_dir / f"{aid}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


__all__ = [
    "T0AdoptionResult",
    "apply_t0_ingest_proposal",
    "build_adoption_record",
    "proposal_to_metric_rows",
    "static_veto_proposal",
    "write_adoption_record",
]
