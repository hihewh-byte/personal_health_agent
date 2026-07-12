"""Loop B · L0 ingest proposal from parsed attachments (proposal-only)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


@dataclass(frozen=True)
class T0IngestProposalRow:
    prov_type: str
    item: str
    value_text: str
    unit: str = ""
    reference_range: str = ""
    observed_at: str = ""
    source_ref: str = ""
    confidence: str = "medium"
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _metric_name(m: dict[str, Any]) -> str:
    for key in ("item", "name", "metric_name", "label", "metric_id", "id"):
        val = str(m.get(key) or "").strip()
        if val:
            return val
    return ""


def _metric_value(m: dict[str, Any]) -> str:
    for key in ("value_text", "value", "raw_value", "display_value"):
        val = m.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return ""


def _metric_unit(m: dict[str, Any]) -> str:
    return str(m.get("unit") or m.get("units") or "").strip()


def _metric_ref(m: dict[str, Any]) -> str:
    return str(m.get("ref") or m.get("reference_range") or m.get("range") or "").strip()


def _source_ref(parsed: dict[str, Any], *, idx: int) -> str:
    raw = (
        str(parsed.get("attachment_id") or "")
        or str(parsed.get("source_filename") or "")
        or str(parsed.get("asset_name") or "")
        or json.dumps(parsed, ensure_ascii=False, sort_keys=True)[:1000]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"attachment_{digest}_{idx}"


def _observed_at(parsed: dict[str, Any]) -> str:
    return str(
        parsed.get("report_date")
        or parsed.get("observed_at")
        or parsed.get("snapshot_reference_date")
        or "",
    ).strip()


def _proposal_prov_type(parsed: dict[str, Any]) -> str:
    fam = str(parsed.get("document_family") or parsed.get("document_type") or "").strip().lower()
    if fam == "wearable":
        return "wearable_import"
    if fam in ("lab", "medical", "lab_report"):
        return "lab_report"
    return "attachment_ingest"


def extract_t0_ingest_proposal_rows(
    parsed_payload: dict[str, Any],
    *,
    max_rows: int = 24,
) -> list[T0IngestProposalRow]:
    """Extract high-signal parsed metrics into proposal rows.

    This does **not** write T0. It only prepares rows with provenance for human
    review or a future gated adopter.
    """
    parsed = dict(parsed_payload or {})
    metrics = parsed.get("metrics") or parsed.get("wearable_metrics") or []
    if not isinstance(metrics, list):
        return []
    prov = _proposal_prov_type(parsed)
    observed_at = _observed_at(parsed)
    rows: list[T0IngestProposalRow] = []
    for idx, metric in enumerate(metrics[:max_rows], start=1):
        if not isinstance(metric, dict):
            continue
        item = _metric_name(metric)
        value = _metric_value(metric)
        if not item or not value:
            continue
        rows.append(
            T0IngestProposalRow(
                prov_type=prov,
                item=item,
                value_text=value,
                unit=_metric_unit(metric),
                reference_range=_metric_ref(metric),
                observed_at=observed_at,
                source_ref=_source_ref(parsed, idx=idx),
                confidence=str(metric.get("confidence") or parsed.get("parse_confidence") or "medium"),
                reason="high-confidence parsed attachment metric; proposal-only",
            ),
        )
    return rows


def build_t0_ingest_proposal(
    parsed_payloads: Iterable[dict[str, Any]],
    *,
    user_id: str = "default",
) -> dict[str, Any]:
    rows: list[T0IngestProposalRow] = []
    for parsed in parsed_payloads:
        rows.extend(extract_t0_ingest_proposal_rows(parsed))
    return {
        "schema": "pha.t0_ingest_proposal/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user_id": (user_id or "default").strip() or "default",
        "row_count": len(rows),
        "rows": [r.as_dict() for r in rows],
        "notes": (
            "Proposal-only. Do not auto-write medical_events or wearable_daily; "
            "human review or a gated adopter must verify provenance first."
        ),
    }


__all__ = [
    "T0IngestProposalRow",
    "build_t0_ingest_proposal",
    "extract_t0_ingest_proposal_rows",
]
