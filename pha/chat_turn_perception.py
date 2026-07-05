"""P0 — Chat turn attachment perception & session parse reuse phases."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from pha.chat_attachments import record_chat_attachment_parse_failure
from pha.chat_storage import (
    get_latest_session_attachment_message_id,
    get_latest_session_attachment_parse,
    update_message_parsed_json,
)

logger = logging.getLogger(__name__)


@dataclass
class TurnAttachmentContext:
    uid: str
    sid: str
    msg: str
    raw_user_msg: str
    prior_user_msg: str
    paths_in: List[str]
    names_in: List[str]
    att_path: str
    att_name: str
    user_row_id: int
    parsed_payload: Optional[Dict[str, Any]] = None
    attach_status_suffix: str = ""
    attach_client_reuse: bool = False
    attach_parse_failed: bool = False


def iter_attachment_upload_phase(ctx: TurnAttachmentContext) -> Iterator[str]:
    """PERCEPTION phase: server-authoritative OCR + vision parse."""
    if not ctx.paths_in:
        return
    yield json.dumps(
        {
            "event": "status",
            "message": f"📎 正在 OCR + 视觉解析（{len(ctx.paths_in)} 个附件）…",
        },
        ensure_ascii=False,
    )
    try:
        from pha.perception_family import requires_label_ledger_v1
        from pha.perception_worker import perceive_chat_attachment_paths

        ctx.attach_client_reuse = False
        if len(ctx.paths_in) > 1:
            yield json.dumps(
                {
                    "event": "status",
                    "message": (
                        f"📎 并行 OCR + 视觉解析（{len(ctx.paths_in)} 个附件）…"
                    ),
                    "attachment_total": len(ctx.paths_in),
                },
                ensure_ascii=False,
            )
        ctx.parsed_payload = perceive_chat_attachment_paths(
            ctx.paths_in,
            ctx.names_in,
            user_id=ctx.uid,
            message_id=ctx.user_row_id,
            user_message=ctx.raw_user_msg,
        )
        if (
            requires_label_ledger_v1(ctx.parsed_payload)
            and len(ctx.paths_in) >= 2
            and int(ctx.parsed_payload.get("attachment_count") or 0) < len(ctx.paths_in)
        ):
            ctx.parsed_payload["parse_confidence"] = "low"
            _rr = list(ctx.parsed_payload.get("reject_reasons") or [])
            if "merge_incomplete" not in _rr:
                _rr.append("merge_incomplete")
            ctx.parsed_payload["reject_reasons"] = _rr
        _fam_attach = str(ctx.parsed_payload.get("document_family") or "")
        _ing_n = len(ctx.parsed_payload.get("ingredient_rows") or [])
        _wear_metric_n = len(
            ctx.parsed_payload.get("wearable_metrics") or ctx.parsed_payload.get("metrics") or [],
        )
        logger.info(
            "[Chat Attach] paths=%s merged_parts=%s ingredients=%s wearable_metrics=%s client_reuse=%s",
            len(ctx.paths_in),
            int(ctx.parsed_payload.get("attachment_count") or len(ctx.paths_in)),
            _ing_n,
            _wear_metric_n,
            ctx.attach_client_reuse,
        )
        update_message_parsed_json(
            ctx.user_row_id,
            json.dumps(ctx.parsed_payload, ensure_ascii=False),
        )
        parsed_n = int(
            ctx.parsed_payload.get("metrics_parsed_count")
            or len(ctx.parsed_payload.get("metrics") or [])
        )
        ing = ctx.parsed_payload.get("ingest") or {}
        stored_n = int(ing.get("metrics_stored") or 0)
        rd = (ctx.parsed_payload.get("report_date") or "")[:10]
        logger.info(
            "[Chat Attach] parsed=%s stored=%s report_date=%s",
            parsed_n,
            stored_n,
            rd,
        )
        if parsed_n and stored_n < parsed_n:
            yield json.dumps(
                {
                    "event": "status",
                    "message": (
                        f"⚠️ 附件解析 {parsed_n} 项，写入账本 {stored_n} 项"
                        f"（report_date={rd or '未知'}）；请以 Patient State 为准。"
                    ),
                },
                ensure_ascii=False,
            )
        _ac = int(ctx.parsed_payload.get("attachment_count") or len(ctx.paths_in))
        if _fam_attach == "wearable":
            if _ac > 1 or len(ctx.paths_in) > 1:
                ctx.attach_status_suffix = (
                    f"已合并 {max(_ac, len(ctx.paths_in))} 张·穿戴 KPI {_wear_metric_n} 项"
                )
            elif _wear_metric_n:
                ctx.attach_status_suffix = f"穿戴 KPI {_wear_metric_n} 项"
        elif _ac > 1 or len(ctx.paths_in) > 1:
            ctx.attach_status_suffix = (
                f"已合并 {max(_ac, len(ctx.paths_in))} 张"
                f"·已读取 {_ing_n} 行"
                + ("·复用选图解析" if ctx.attach_client_reuse else "")
            )
        elif _ing_n:
            ctx.attach_status_suffix = f"已读取 {_ing_n} 行"
        if (ctx.parsed_payload.get("parse_confidence") or "") == "low":
            _reasons = ctx.parsed_payload.get("reject_reasons") or []
            _fam_low = str(ctx.parsed_payload.get("document_family") or "")
            _low_hint = (
                "：截图指标未完全识别，将结合历史记录对比"
                if _fam_low == "wearable"
                else "：回答将避免编造剂量，建议补拍 Supplement Facts 面"
            )
            yield json.dumps(
                {
                    "event": "status",
                    "message": (
                        "⚠️ 识别置信度偏低"
                        + (f"（{','.join(_reasons[:3])}）" if _reasons else "")
                        + _low_hint
                    ),
                },
                ensure_ascii=False,
            )
        _ledger_prev = (
            ctx.parsed_payload.get("label_ledger") or ctx.parsed_payload.get("vision_summary") or ""
        )
        _prev_cap = int(os.environ.get("PHA_CHAT_ATTACH_PREVIEW_MAX", "2200"))
        preview = _ledger_prev[:_prev_cap] if _ledger_prev else ""
        if preview:
            ctx.msg = f"{ctx.msg}\n\n【附件解析摘要 · 供核对】\n{preview}"
    except Exception as exc:
        logger.exception("chat attachment vision parse failed")
        ctx.attach_parse_failed = True
        ocr_text = ""
        try:
            from pha.vision_engine import image_file_to_png_list
            from pha.vision_ocr import tesseract_ocr_png
            from pha.vision_supplement import (
                extraction_from_ocr_fallback,
                parsed_payload_from_extraction,
            )

            pages = image_file_to_png_list(Path(ctx.att_path).read_bytes(), filename=ctx.att_name)
            if pages:
                ocr_text = tesseract_ocr_png(pages[0])
            fb_ext = extraction_from_ocr_fallback(ocr_text, raw_model_snippet=str(exc)[:2000])
            ctx.parsed_payload = parsed_payload_from_extraction(
                fb_ext,
                filename=ctx.att_name or Path(ctx.att_path).name,
                parse_channel="ocr_fallback",
            )
            update_message_parsed_json(
                ctx.user_row_id,
                json.dumps(ctx.parsed_payload, ensure_ascii=False),
            )
            preview = (ctx.parsed_payload.get("vision_summary") or "")[:800]
            if preview:
                ctx.msg = f"{ctx.msg}\n\n【附件 OCR 兜底摘要 · 未写入化验指标】\n{preview}"
            ctx.attach_parse_failed = False
        except Exception:
            logger.exception("chat attachment OCR fallback failed")
        try:
            from pha.chat_background import store_unstructured_vision_note

            store_unstructured_vision_note(
                ctx.uid,
                ocr_text=ocr_text,
                error=str(exc),
                source_message_id=ctx.user_row_id,
                session_id=ctx.sid or "",
            )
        except Exception:
            logger.exception("store_unstructured_vision_note failed")
        try:
            record_chat_attachment_parse_failure(
                ctx.uid,
                attachment_path=ctx.att_path,
                attachment_name=ctx.att_name or Path(ctx.att_path).name,
                error=str(exc),
            )
        except Exception:
            logger.exception("record_chat_attachment_parse_failure failed")
        if ctx.attach_parse_failed:
            yield json.dumps(
                {
                    "event": "attach_error",
                    "code": "vision_parse_failed",
                    "message": str(exc)[:800],
                },
                ensure_ascii=False,
            )
            yield json.dumps(
                {
                    "event": "status",
                    "message": f"附件解析失败（已保留原文件）: {exc}",
                },
                ensure_ascii=False,
            )
        else:
            yield json.dumps(
                {
                    "event": "status",
                    "message": "⚠️ Vision JSON 失败，已用 OCR 兜底写入背景（未污染化验菜单）",
                },
                ensure_ascii=False,
            )


def iter_session_parse_reuse_phase(ctx: TurnAttachmentContext) -> Iterator[str]:
    """PARSE_REUSE phase: reload session attachment parse without re-upload."""
    if ctx.parsed_payload or ctx.paths_in or not ctx.sid:
        return
    from pha.perception_family import ocr_suggests_wearable_ui
    from pha.wearable_compare_table_v1 import (
        user_message_needs_wearable_session_reuse,
        user_requests_snapshot_correction,
    )
    from pha.wearable_snapshot_v1 import (
        remerge_wearable_parsed_payload,
        user_requests_wearable_snapshot_remerge,
    )

    _reuse_parse = user_message_needs_wearable_session_reuse(
        ctx.raw_user_msg,
        ctx.prior_user_msg,
    )
    if not _reuse_parse:
        return
    _prev_parse = get_latest_session_attachment_parse(ctx.sid or "")
    if not _prev_parse:
        return
    ctx.parsed_payload = _prev_parse
    _wearable_prev = bool(
        ctx.parsed_payload.get("wearable_snapshot_v1")
        or ctx.parsed_payload.get("wearable_metrics")
        or ocr_suggests_wearable_ui(str(ctx.parsed_payload.get("ocr_text") or "")),
    )
    if _wearable_prev and (
        user_requests_wearable_snapshot_remerge(ctx.raw_user_msg)
        or user_requests_snapshot_correction(ctx.raw_user_msg)
    ):
        ctx.parsed_payload = remerge_wearable_parsed_payload(
            ctx.parsed_payload,
            user_message=ctx.raw_user_msg,
        )
        _attach_msg_id = get_latest_session_attachment_message_id(ctx.sid or "")
        if _attach_msg_id:
            update_message_parsed_json(
                _attach_msg_id,
                json.dumps(ctx.parsed_payload, ensure_ascii=False),
            )
        ctx.attach_status_suffix = "已根据截图重新识别"
        yield json.dumps(
            {
                "event": "status",
                "message": "📎 已根据会话内截图 OCR 重新合并指标（无需重新上传）",
            },
            ensure_ascii=False,
        )
    elif not (ctx.parsed_payload.get("wearable_metrics") or []):
        _ocr = str(ctx.parsed_payload.get("ocr_text") or "")
        if _ocr and ocr_suggests_wearable_ui(_ocr):
            from pha.wearable_snapshot_v1 import finalize_wearable_attachment

            ctx.parsed_payload = finalize_wearable_attachment(
                {
                    "ocr_text": _ocr,
                    "document_family": "wearable",
                    "document_type": "apple_watch",
                },
                attachment_count=max(
                    1,
                    int(ctx.parsed_payload.get("attachment_count") or 1),
                ),
                user_message=ctx.raw_user_msg,
            )
        ctx.attach_status_suffix = "复用上一轮附件解析"
        yield json.dumps(
            {
                "event": "status",
                "message": "📎 本轮未附带图片，已复用本会话最近一次附件解析结果",
            },
            ensure_ascii=False,
        )
    else:
        ctx.attach_status_suffix = "复用上一轮附件解析"
        yield json.dumps(
            {
                "event": "status",
                "message": "📎 本轮未附带图片，已复用本会话最近一次附件解析结果",
            },
            ensure_ascii=False,
        )


__all__ = [
    "TurnAttachmentContext",
    "iter_attachment_upload_phase",
    "iter_session_parse_reuse_phase",
]
