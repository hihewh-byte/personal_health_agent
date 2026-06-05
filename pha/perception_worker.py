"""Stage 3B — Perception Worker: multimodal vision + OCR context + LabelLedger merge."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pha.label_ledger_v1 import (
    LabelLedgerV1,
    PerceptionChannel,
    finalize_parsed_payload,
)
from pha.perception_family import requires_label_ledger_v1
from pha.runtime_capabilities import perception_channel_for_tier
from pha.wearable_snapshot_v1 import finalize_wearable_attachment


def perceive_attachment_path(
    path: str,
    filename: str,
    *,
    source_image_index: int = 0,
) -> Dict[str, Any]:
    """Per-image perception via ``_vision_parse_attachment`` (VLM + OCR context)."""
    from pha.chat_service import _vision_parse_attachment  # lazy: avoid import cycle

    parsed = _vision_parse_attachment(
        path,
        filename,
        user_id="default",
        message_id=None,
        auto_ingest=False,
    )
    parsed["source_image_index"] = source_image_index
    return parsed


def perceive_paths(
    paths: List[str],
    names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Parse and merge multiple attachment paths into one finalized payload."""
    from pha.vision_label_ledger import merge_parsed_payloads

    from pha.perception_family import (
        WEARABLE_FAMILY,
        coerce_wearable_family,
        parts_should_finalize_as_wearable,
    )

    parts = [
        coerce_wearable_family(
            perceive_attachment_path(p, n, source_image_index=i),
        )
        for i, p in enumerate(paths)
        for n in [(names[i] if names and i < len(names) else None) or Path(p).name]
    ]

    if len(parts) > 1 and parts_should_finalize_as_wearable(parts):
        merged: Dict[str, Any] = {
            "ocr_text": "\n\n".join(str(p.get("ocr_text") or "") for p in parts),
            "document_family": WEARABLE_FAMILY,
            "document_type": "apple_watch",
        }
        for p in parts:
            if str(p.get("perception_channel") or "") == "vision_structured":
                merged["perception_channel"] = "vision_structured"
                break
    else:
        merged = merge_parsed_payloads(parts) if len(parts) > 1 else parts[0]
    channel: PerceptionChannel = "ocr_only"
    for p in parts:
        ch = str(p.get("perception_channel") or "")
        if ch == "vision_structured":
            channel = "vision_structured"
            break
        if ch == "ocr_plus_vision_validate":
            channel = "ocr_plus_vision_validate"
    if channel == "ocr_only":
        channel = perception_channel_for_tier()
    return finalize_attachment_parse(
        merged,
        attachment_path_count=len(parts),
        parts=parts,
        perception_channel=channel,
    )


def finalize_attachment_parse(
    parsed: Dict[str, Any],
    *,
    attachment_path_count: int,
    parts: Optional[List[Dict[str, Any]]] = None,
    client_parse_reuse: bool = False,
    perception_channel: Optional[PerceptionChannel] = None,
    user_message: str = "",
) -> Dict[str, Any]:
    """Apply family-specific finalize — LabelLedgerV1 only for supplement family."""
    channel = perception_channel or perception_channel_for_tier()
    count = max(1, attachment_path_count)
    probe = parsed
    if parts:
        for p in parts:
            if requires_label_ledger_v1(p):
                probe = p
                break
    if not requires_label_ledger_v1(probe):
        from pha.perception_family import (
            WEARABLE_FAMILY,
            family_from_parsed,
            parts_should_finalize_as_wearable,
        )

        fam = family_from_parsed(probe)
        use_wearable = fam == WEARABLE_FAMILY or (
            parts and parts_should_finalize_as_wearable(parts)
        )
        if use_wearable:
            return finalize_wearable_attachment(
                parsed,
                attachment_count=count,
                parts=parts,
                perception_channel=channel,
                user_message=user_message,
            )
        out = dict(parsed)
        out["ingredient_rows"] = []
        out.setdefault("parse_confidence", "medium" if str(out.get("ocr_text") or "").strip() else "low")
        out.setdefault("reject_reasons", [])
        out.setdefault("warnings", [])
        out["attachment_count"] = count
        out["perception_channel"] = channel
        return out
    return finalize_parsed_payload(
        parsed,
        attachment_count=count,
        parts=parts,
        perception_channel=channel,
        client_parse_reuse=client_parse_reuse,
    )


def ledger_from_payload(parsed: Optional[Dict[str, Any]]) -> Optional[LabelLedgerV1]:
    if not parsed:
        return None
    raw = parsed.get("label_ledger_v1")
    if isinstance(raw, dict):
        try:
            return LabelLedgerV1.model_validate(raw)
        except Exception:
            pass
    try:
        return LabelLedgerV1(
            schema_version="label_ledger_v1",
            attachment_count=int(parsed.get("attachment_count") or 1),
            brand=str(parsed.get("brand") or ""),
            product_title=str(parsed.get("product_title") or ""),
            package_size=str(parsed.get("package_size") or ""),
            layout_hints=list(parsed.get("layout_hints") or []),
            ingredient_rows=[],
            parse_confidence=str(parsed.get("parse_confidence") or "high"),  # type: ignore[arg-type]
            reject_reasons=list(parsed.get("reject_reasons") or []),
            perception_channel=str(parsed.get("perception_channel") or "ocr_only"),  # type: ignore[arg-type]
            ocr_char_count=int(parsed.get("ocr_char_count") or 0),
            ledger_markdown=str(parsed.get("label_ledger") or parsed.get("vision_summary") or ""),
        )
    except Exception:
        return None


__all__ = [
    "finalize_attachment_parse",
    "ledger_from_payload",
    "perceive_attachment_path",
    "perceive_paths",
]
