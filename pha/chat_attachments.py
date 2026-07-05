"""PHA chat attachment parsing, OCR, and vision ingestion."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pha.chat_ingest import ingest_chat_message, ingest_parsed_payload
from pha.event_medical import metrics_preview_dicts, narratives_preview_dicts
from pha.health_data import effective_query_reference_date

logger = logging.getLogger(__name__)

_KEY_LAB_MARKERS = ("ldl", "alt", "ast", "hdl", "低密度", "谷氨", "天门冬", "胆固醇")

_LAB_LEDGER_TRIGGERS = (
    "血脂",
    "ldl",
    "hdl",
    "胆固醇",
    "甘油三酯",
    "化验",
    "体检",
    "肝功能",
    "肾功能",
)


def _message_needs_lab_ledger(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in _LAB_LEDGER_TRIGGERS)


def _extract_key_metric_names(metrics: List[Dict[str, Any]]) -> List[str]:
    names: List[str] = []
    for m in metrics or []:
        blob = " ".join(
            str(m.get(k) or "")
            for k in ("metric_name", "item", "metric_code", "id", "label", "name_zh")
        ).lower()
        if any(tok in blob for tok in _KEY_LAB_MARKERS):
            names.append(
                str(m.get("metric_name") or m.get("item") or m.get("label") or m.get("id") or "?"),
            )
    return names[:12]


def _auto_ingest_attachment_payload(
    parsed: Dict[str, Any],
    *,
    user_id: str,
    message_id: int,
    filename: str,
) -> Optional[Dict[str, Any]]:
    metrics = list(parsed.get("metrics") or [])
    narratives = list(parsed.get("narratives") or [])
    if not metrics and not narratives:
        return None

    metrics_count = len(metrics)
    logger.info(
        "[Auto Ingest] Found %s metrics, %s narratives from attachment %s",
        metrics_count,
        len(narratives),
        filename,
    )
    key_names = _extract_key_metric_names(metrics)
    if key_names:
        logger.info("[Auto Ingest] Key labs: %s", ", ".join(key_names))

    try:
        ing = ingest_chat_message(
            message_id,
            user_id=user_id,
            metrics=metrics,
            narratives=narratives,
            report_date=parsed.get("report_date"),
            hospital=parsed.get("hospital", ""),
        )
        logger.info(
            "[Auto Ingest] SUCCESS: %s metrics written to DB (stored=%s)",
            metrics_count,
            ing.get("metrics_stored"),
        )
        return ing
    except Exception as exc:
        logger.error("[Auto Ingest] FAILED: %s", exc)
        return None


def _is_safe_server_attachment_path(user_id: str, attachment_path: str) -> bool:
    from pathlib import Path

    from pha.attachment_storage import STORAGE_ROOT

    uid = (user_id or "default").strip() or "default"
    try:
        p = Path(attachment_path).resolve()
        allowed = (STORAGE_ROOT / uid).resolve()
        return str(p).startswith(str(allowed)) and p.is_file()
    except Exception:
        return False


def record_chat_attachment_parse_failure(
    user_id: str,
    *,
    attachment_path: str,
    attachment_name: str,
    error: str,
) -> None:
    from datetime import date as _date

    from pha.medical_storage import upsert_health_report_asset

    fname = (attachment_name or Path(attachment_path).name).strip() or "attachment"
    upsert_health_report_asset(
        user_id,
        _date.today(),
        source_filename=fname,
        source_kind="chat_attachment_failed",
        vision_model="",
        vision_raw={
            "parse_status": "failed",
            "error": (error or "")[:2500],
            "path": attachment_path,
        },
        metrics_preview="附件解析失败（待重试）",
    )


def parse_chat_attachment_file(
    user_id: str,
    attachment_path: str,
    attachment_name: str = "",
    *,
    auto_ingest: bool = True,
) -> Dict[str, Any]:
    """
    Standalone parse (v2.2.2) — used by ``POST /api/chat/attachments/parse`` after file upload.
    Caller must ensure ``attachment_path`` is under server storage for this user.
    """
    uid = (user_id or "default").strip() or "default"
    if not _is_safe_server_attachment_path(uid, attachment_path):
        raise ValueError("invalid or unsafe attachment_path")
    parsed = _vision_parse_attachment(
        attachment_path,
        attachment_name,
        user_id=uid,
        message_id=None,
        auto_ingest=False,
    )
    from pha.vision_label_ledger import enrich_parsed_payload

    ocr_pre = (parsed.get("ocr_text") or "").strip()
    parsed = enrich_parsed_payload(
        parsed,
        ocr_text=ocr_pre,
        filename=attachment_name or Path(attachment_path).name,
    )
    metrics = list(parsed.get("metrics") or [])
    narratives = list(parsed.get("narratives") or [])
    if metrics:
        parsed["ingest_status"] = "manual_required"
    elif auto_ingest and narratives:
        ing = ingest_parsed_payload(
            user_id=uid,
            report_date=parsed.get("report_date") or "",
            hospital=parsed.get("hospital", ""),
            source_filename=parsed.get("source_filename") or (attachment_name or Path(attachment_path).name),
            source_kind="chat_attach_parse_api",
            metrics=[],
            narratives=narratives,
            vision_raw=parsed,
            vision_model="",
        )
        parsed["ingest"] = ing
        parsed["ingest_status"] = "auto_ok"
    else:
        parsed["ingest_status"] = "auto_skipped"
    from pha.perception_worker import finalize_attachment_parse

    return finalize_attachment_parse(
        parsed,
        attachment_path_count=1,
        parts=[parsed],
        client_parse_reuse=False,
    )


def compute_attachment_ingest_status(parsed: Optional[Dict[str, Any]]) -> str:
    """SSE/UI: manual_required when lab metrics present and not yet ingested."""
    if not parsed:
        return "auto_skipped"
    if parsed.get("ingest_status"):
        return str(parsed["ingest_status"])
    metrics = list(parsed.get("metrics") or [])
    if not metrics:
        return "auto_skipped"
    ing = parsed.get("ingest") or {}
    stored = int(ing.get("metrics_stored") or 0)
    if stored >= len(metrics) and stored > 0:
        return "auto_ok"
    if stored > 0:
        return "auto_partial"
    return "manual_required"


def _ocr_text_from_attachment_bytes(raw: bytes, filename: str) -> str:
    try:
        from pha.vision_engine import image_file_to_png_list
        from pha.vision_ocr import tesseract_ocr_png

        pages = image_file_to_png_list(raw, filename=filename)
        ocr_chunks = [tesseract_ocr_png(p) for p in pages]
        return "\n\n".join(c for c in ocr_chunks if c).strip()
    except Exception:
        logger.debug("attachment ocr read skipped", exc_info=True)
        return ""


def _ocr_with_layout_regions(
    raw: bytes,
    filename: str,
) -> Tuple[str, List[Any], Dict[str, Any]]:
    """L0.2 layout_region crop + OCR arbitration (Wave 3). Falls back to full-page OCR."""
    try:
        from pha.layout_region import (
            layout_hints_from_regions,
            ocr_with_layout_regions,
        )
        from pha.vision_engine import image_file_to_png_list

        pages = image_file_to_png_list(raw, filename=filename)
        if not pages:
            return "", [], {}
        merged_parts: List[str] = []
        all_regions: List[Any] = []
        telem: Dict[str, Any] = {"layout_region_count": 0, "regions": []}
        for idx, page in enumerate(pages):
            text, regions, t = ocr_with_layout_regions(page, source_page_index=idx)
            if text:
                merged_parts.append(text)
            all_regions.extend(regions)
            telem["layout_region_count"] = int(telem.get("layout_region_count", 0)) + t.get(
                "layout_region_count",
                0,
            )
            telem.setdefault("regions", []).extend(t.get("regions") or [])
        telem["layout_hints"] = layout_hints_from_regions(all_regions)
        return "\n\n".join(merged_parts).strip(), all_regions, telem
    except Exception:
        logger.debug("layout_region ocr failed; full-page fallback", exc_info=True)
        return _ocr_text_from_attachment_bytes(raw, filename), [], {}


def _vision_model_available() -> bool:
    """Return True if at least one supported Ollama vision model is installed.

    Uses the same base URL resolution as other llm_provider helpers
    (OLLAMA_BASE_URL / OLLAMA_HOST / http://127.0.0.1:11434).
    """
    import os

    try:
        from pha.llm_provider import find_vision_model, list_ollama_installed_models

        base_url = (
            os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_HOST")
            or "http://127.0.0.1:11434"
        )
        installed = list_ollama_installed_models(base_url, timeout_seconds=5.0)
        return bool(find_vision_model(installed))
    except Exception:
        return False


def _extraction_looks_like_ocr_fallback(extraction: Any) -> bool:
    """True when vision page parse fell back to OCR-only supplement extraction."""
    if extraction is None:
        return True
    narratives = getattr(extraction, "narratives", None) or []
    cats = {str(getattr(n, "category", "") or "") for n in narratives}
    if "vision_raw_snippet" in cats:
        return True
    if not getattr(extraction, "results", None) and "unstructured_vision" in cats:
        return True
    return False


def _wearable_ocr_only_parse(
    *,
    ocr_text: str,
    filename: str,
    raw: bytes = b"",
    parse_channel: str = "ocr_only_no_vlm",
    perception_channel: str = "ocr_only",
    layout_telemetry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {
        "ocr_text": ocr_text,
        "vision_summary": "",
        "perception_channel": perception_channel,
        "parse_channel": parse_channel,
        "ingredient_rows": [],
        "metrics_parsed_count": 0,
        "ingest_status": "auto_skipped",
        "document_family": "wearable",
        "document_type": "apple_watch",
    }
    if layout_telemetry:
        parsed["layout_region_meta"] = layout_telemetry
    return _annotate_attachment_routing(
        parsed,
        raw=raw,
        filename=filename,
        ocr_text=ocr_text,
        layout_telemetry=layout_telemetry,
    )


def _supplement_ocr_only_parse(
    *,
    ocr_text: str,
    filename: str,
    user_id: str,
    message_id: Optional[int],
    auto_ingest: bool,
    raw: bytes = b"",
    parse_channel: str = "ocr_fallback",
    perception_channel: str = "ocr_only",
    layout_telemetry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from pha.vision_label_ledger import enrich_parsed_payload
    from pha.vision_supplement import (
        extraction_from_ocr_fallback,
        parsed_payload_from_extraction,
    )

    fname = filename or "attachment"
    ext = extraction_from_ocr_fallback(ocr_text)
    parsed = parsed_payload_from_extraction(
        ext,
        filename=fname,
        parse_channel=parse_channel,
    )
    parsed["ocr_text"] = ocr_text
    parsed["perception_channel"] = perception_channel
    parsed = enrich_parsed_payload(parsed, ocr_text=ocr_text, filename=fname)
    parsed["metrics_parsed_count"] = 0
    parsed["ingest_status"] = "auto_skipped"
    if auto_ingest and message_id is not None and parsed.get("narratives"):
        ing = _auto_ingest_attachment_payload(
            parsed,
            user_id=user_id,
            message_id=message_id,
            filename=fname,
        )
        parsed["ingest"] = ing
        parsed["ingest_status"] = "auto_ok" if ing else "auto_skipped"
    if layout_telemetry:
        parsed["layout_region_meta"] = layout_telemetry
    return _annotate_attachment_routing(
        parsed,
        raw=raw,
        filename=fname,
        ocr_text=ocr_text,
        layout_telemetry=layout_telemetry,
    )


def _annotate_attachment_routing(
    parsed: Dict[str, Any],
    *,
    raw: bytes,
    filename: str,
    ocr_text: str = "",
    layout_telemetry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from pha.perception_media import attach_perception_routing_metadata

    out = attach_perception_routing_metadata(
        parsed,
        raw=raw,
        filename=filename,
        ocr_text=ocr_text or str(parsed.get("ocr_text") or ""),
    )
    out["media_route"] = out.get("media_route") or "unknown"
    if layout_telemetry:
        out["layout_region_meta"] = layout_telemetry
        hints = layout_telemetry.get("layout_hints") or []
        if hints:
            existing = list(out.get("layout_hints") or [])
            for h in hints:
                if h not in existing:
                    existing.append(h)
            out["layout_hints"] = existing
    return out


def _vision_parse_attachment(
    path: str,
    filename: str,
    *,
    user_id: str = "default",
    message_id: Optional[int] = None,
    auto_ingest: bool = False,
) -> Dict[str, Any]:
    """
    Per-image perception: OCR classifies layout; wearable Lane-O skips VLM when OCR is actionable.
    """
    from pha.vision_engine import VisionReportParser
    from pha.vision_supplement import parsed_payload_from_extraction

    fname = filename or Path(path).name
    raw = Path(path).read_bytes()
    from pha.perception_media import (
        classify_document_family,
        detect_media_route,
        legacy_doc_kind_from_family,
    )

    media_route, _media_meta = detect_media_route(raw, fname)
    ocr_text, _layout_regions, _layout_telem = _ocr_with_layout_regions(raw, fname)
    doc_family = "unknown"
    if ocr_text:
        doc_family, _, _ = classify_document_family(ocr_text)
        doc_kind = legacy_doc_kind_from_family(doc_family)
    else:
        doc_kind = "other"

    from pha.perception_family import should_skip_vlm_for_wearable

    if should_skip_vlm_for_wearable(
        doc_kind=doc_kind,
        document_family=doc_family,
        ocr_text=ocr_text,
    ):
        logger.info("Wearable Lane-O: skip VLM for %s (doc_kind=%s)", fname, doc_kind)
        return _wearable_ocr_only_parse(
            ocr_text=ocr_text,
            filename=fname,
            raw=raw,
            parse_channel="wearable_lane_o",
            perception_channel="ocr_only",
            layout_telemetry=_layout_telem,
        )

    if not _vision_model_available():
        logger.warning(
            "No Ollama vision model; degraded OCR-only parse for %s (doc_kind=%s)",
            fname,
            doc_kind,
        )
        if doc_kind == "supplement_label":
            return _supplement_ocr_only_parse(
                ocr_text=ocr_text,
                filename=fname,
                user_id=user_id,
                message_id=message_id,
                auto_ingest=auto_ingest,
                raw=raw,
                parse_channel="ocr_only_no_vlm",
                layout_telemetry=_layout_telem,
            )
        if doc_kind == "apple_watch":
            return _wearable_ocr_only_parse(
                ocr_text=ocr_text,
                filename=fname,
                raw=raw,
                parse_channel="ocr_only_no_vlm",
                layout_telemetry=_layout_telem,
            )
        raise ValueError(
            "未检测到可用的 Ollama 视觉模型（需 llama3.2-vision 或 llava）。"
            "化验/报告解析无法仅依赖 OCR。",
        )

    try:
        resp = VisionReportParser().parse_upload(raw, filename=fname)
    except Exception as exc:
        logger.exception("VisionReportParser.parse_upload failed for %s", fname)
        if doc_kind == "supplement_label":
            return _supplement_ocr_only_parse(
                ocr_text=ocr_text,
                filename=fname,
                user_id=user_id,
                message_id=message_id,
                auto_ingest=auto_ingest,
                raw=raw,
                parse_channel="vision_failed_ocr_fallback",
                layout_telemetry=_layout_telem,
            )
        if doc_kind == "apple_watch":
            return _wearable_ocr_only_parse(
                ocr_text=ocr_text,
                filename=fname,
                raw=raw,
                parse_channel="vision_failed_ocr_fallback",
                layout_telemetry=_layout_telem,
            )
        raise

    extraction = resp.extraction
    vision_fallback = _extraction_looks_like_ocr_fallback(extraction)
    perception_channel: str = "ocr_only" if vision_fallback else "vision_structured"
    parse_channel = (
        "vision_failed_ocr_fallback"
        if vision_fallback
        else ("vision_supplement" if doc_kind == "supplement_label" else "vision_lab")
    )

    if doc_kind == "apple_watch":
        parsed = {
            "ocr_text": ocr_text,
            "vision_summary": (resp.summary_text or "").strip(),
            "perception_channel": perception_channel,
            "parse_channel": "vision_wearable",
            "vision_model": resp.vision_model,
            "ingredient_rows": [],
            "metrics_parsed_count": 0,
            "ingest_status": "auto_skipped",
        }
        return _annotate_attachment_routing(
            parsed,
            raw=raw,
            filename=fname,
            ocr_text=ocr_text,
            layout_telemetry=_layout_telem,
        )

    if doc_kind == "supplement_label":
        parsed = parsed_payload_from_extraction(
            extraction,
            filename=fname,
            parse_channel=parse_channel,
            vision_summary=(resp.summary_text or "").strip(),
        )
        parsed["ocr_text"] = ocr_text
        parsed["perception_channel"] = perception_channel
        parsed["vision_model"] = resp.vision_model
        from pha.vision_label_ledger import enrich_parsed_payload

        parsed = enrich_parsed_payload(parsed, ocr_text=ocr_text, filename=fname)
        parsed["metrics_parsed_count"] = 0
        parsed["ingest_status"] = "auto_skipped"
        if auto_ingest and message_id is not None and parsed.get("narratives"):
            ing = _auto_ingest_attachment_payload(
                parsed,
                user_id=user_id,
                message_id=message_id,
                filename=fname,
            )
            parsed["ingest"] = ing
            parsed["ingest_status"] = "auto_ok" if ing else "auto_skipped"
        return _annotate_attachment_routing(
            parsed,
            raw=raw,
            filename=fname,
            ocr_text=ocr_text,
            layout_telemetry=_layout_telem,
        )

    metrics = list(resp.metrics_preview or [])
    if not metrics and extraction and extraction.results:
        from pha.event_medical import extraction_to_metric_rows
        from pha.date_parser import safe_parse_date

        rd = safe_parse_date((extraction.date or "")[:10]) or effective_query_reference_date()
        metric_rows = extraction_to_metric_rows(
            extraction,
            user_id=(user_id or "default").strip() or "default",
            report_date=rd,
            source_filename=fname,
        )
        metrics = metrics_preview_dicts(metric_rows)
    narratives = narratives_preview_dicts(
        extraction.narratives if extraction else [],
        hospital=(extraction.hospital if extraction else "") or "",
    )
    report_date = (extraction.date if extraction else "") or ""
    hospital = (extraction.hospital if extraction else "") or ""
    if ocr_text and doc_kind == "supplement_label":
        metrics = []

    parsed: Dict[str, Any] = {
        "metrics": metrics,
        "narratives": narratives,
        "report_date": report_date[:10] if report_date else "",
        "hospital": hospital,
        "source_filename": fname,
        "vision_summary": (resp.summary_text or "").strip(),
        "ocr_text": ocr_text,
        "perception_channel": perception_channel,
        "parse_channel": parse_channel,
        "vision_model": resp.vision_model,
    }
    metrics = list(parsed.get("metrics") or [])
    parsed["metrics_parsed_count"] = len(metrics)
    if metrics:
        parsed["ingest_status"] = "manual_required"
    elif auto_ingest and message_id is not None and narratives:
        ing = _auto_ingest_attachment_payload(
            parsed,
            user_id=user_id,
            message_id=message_id,
            filename=fname,
        )
        parsed["ingest"] = ing
        parsed["ingest_status"] = "auto_ok" if ing else "auto_skipped"
    else:
        parsed["ingest_status"] = "auto_skipped"
    return _annotate_attachment_routing(
        parsed,
        raw=raw,
        filename=fname,
        ocr_text=ocr_text,
        layout_telemetry=_layout_telem,
    )
