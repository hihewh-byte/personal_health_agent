"""Vision preprocessing and structured lab-report extraction via Ollama vision models."""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from datetime import date
from typing import Any, Callable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from pha.llm_provider import OllamaProvider, list_ollama_installed_models, load_dotenv_if_present

logger = logging.getLogger(__name__)

VISION_MAX_WIDTH_PX = int(os.environ.get("PHA_VISION_MAX_WIDTH_PX", "1280"))
PDF_RENDER_MATRIX = float(os.environ.get("PHA_PDF_RENDER_MATRIX", "1.25"))
_PDF_MAX_PAGES_RAW = os.environ.get("PHA_VISION_MAX_PAGES", "50").strip()
# 0 = 不限制页数，处理 PDF 全部页面
PDF_MAX_PAGES = int(_PDF_MAX_PAGES_RAW) if _PDF_MAX_PAGES_RAW else 50
VISION_JPEG_QUALITY = int(os.environ.get("PHA_VISION_JPEG_QUALITY", "78"))
VISION_HTTP_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_SECONDS", "300"))
VISION_PAGE_TIMEOUT_S = float(os.environ.get("PHA_VISION_PAGE_TIMEOUT_SECONDS", "120"))


def effective_pdf_pages_to_process(total_pages: int) -> int:
    """Pages to process: all pages when cap is 0, else min(total, cap)."""
    total = max(0, int(total_pages))
    if PDF_MAX_PAGES <= 0:
        return total
    return min(total, PDF_MAX_PAGES)

ProgressCallback = Callable[[int, int, str], None]

VISION_EXTRACTION_SYSTEM_PROMPT = """你是医疗检验/影像报告结构化助手。根据用户提供的报告页面图像，提取可见文字与数值。

必须只输出一个 JSON 对象，不要 Markdown 代码块，不要额外说明。格式严格如下：
{
  "date": "YYYY-MM-DD 或空字符串",
  "title": "报告简述",
  "hospital": "医院名称或空字符串",
  "total_detected_rows_in_page": 0,
  "results": [
    {"item": "项目名", "value": "值", "unit": "单位", "ref": "参考范围"}
  ],
  "narratives": [
    {"category": "板块归类", "content": "非数字的完整原文描述"}
  ]
}

规则：
- date：报告日期或采样日期；无法识别则用 ""。
- title：报告类型或标题摘要。
- hospital：医院/体检机构名称；无法识别则用 ""。
- total_detected_rows_in_page：整数，本页图像中你肉眼能数到的数据行总数（数字检验行 + 描述性段落行；无则 0）。必须诚实估算。
- results：仅放可量化的检验数字行（有项目名+数值）。不要把超声描述、心电图结论、总检建议塞进 results。
- narratives：承接所有非数字叙事（如「超声影像」「心电图结论」「医生总评」「既往病史」）。每条含 category 与 content（完整原文）。无则 []。
- 数字行进 results，文字段落进 narratives；两者之和应尽可能接近 total_detected_rows_in_page。
- 看不清的字段用 ""，禁止编造未在图中出现的数值或诊断。"""

VISION_PAGE_USER_PROMPT = (
    "请阅读本页医疗报告图像，按系统要求输出 JSON。"
    "若本页仅有文字描述无数字，results 可为 []，内容放入 narratives。"
)


def _vision_prompts_for_page(
    *,
    ocr_text: str,
    page_index: int,
    page_total: int,
) -> tuple[str, str]:
    """Pick system/user prompts using OCR document classification."""
    from pha.vision_ocr import classify_document_from_ocr, format_ocr_context_block
    from pha.vision_supplement import (
        SUPPLEMENT_LABEL_VISION_SYSTEM,
        build_supplement_vision_user_message,
    )

    kind = classify_document_from_ocr(ocr_text)
    if kind == "supplement_label":
        return (
            SUPPLEMENT_LABEL_VISION_SYSTEM,
            build_supplement_vision_user_message(
                ocr_text=ocr_text,
                page_index=page_index,
                page_total=page_total,
            ),
        )
    user_msg = VISION_PAGE_USER_PROMPT
    if page_total > 1:
        user_msg = f"这是共 {page_total} 页报告的第 {page_index + 1} 页。{VISION_PAGE_USER_PROMPT}"
    ocr_block = format_ocr_context_block(ocr_text)
    if ocr_block:
        user_msg = f"{ocr_block}\n\n{user_msg}"
    return VISION_EXTRACTION_SYSTEM_PROMPT, user_msg


def _parse_page_with_ocr_fallback(
    llm: OllamaProvider,
    jpeg_bytes: bytes,
    *,
    page_index: int,
    page_total: int,
    raw_reply_holder: Optional[List[str]] = None,
) -> ReportExtraction:
    """Vision parse one page; on JSON failure use OCR-only supplement-safe fallback."""
    from pha.vision_ocr import tesseract_ocr_png
    from pha.vision_parser import VisionJsonParseError
    from pha.vision_supplement import extraction_from_ocr_fallback

    from pha.layout_region import detect_layout_regions, primary_parse_regions, regions_to_telemetry
    from pha.perception_arbitration import arbitrate_ocr_for_page

    full_page_ocr = tesseract_ocr_png(jpeg_bytes)
    layout_regions = detect_layout_regions(jpeg_bytes, source_page_index=page_index)
    primary = primary_parse_regions(layout_regions)
    region_ocrs = [r.ocr_preview or tesseract_ocr_png(r.crop_bytes) for r in primary]
    ocr_text, _ocr_lane = arbitrate_ocr_for_page(full_page_ocr, region_ocrs)
    _layout_telemetry = regions_to_telemetry(layout_regions)
    vlm_bytes = primary[0].crop_bytes if primary else jpeg_bytes

    system_prompt, user_msg = _vision_prompts_for_page(
        ocr_text=ocr_text,
        page_index=page_index,
        page_total=page_total,
    )
    b64 = png_list_to_base64([vlm_bytes])[0]
    raw_reply = llm.chat_with_vision(
        system_prompt=system_prompt,
        user_message=user_msg,
        images=[b64],
    )
    if raw_reply_holder is not None:
        raw_reply_holder.append(raw_reply)
    from pha.vision_ocr import classify_document_from_ocr as _doc_kind

    try:
        data = _extract_json_object(raw_reply)
        ext = _parse_extraction(data)
        if _doc_kind(ocr_text) == "supplement_label":
            ext.results = []
        return ext
    except VisionJsonParseError as exc:
        logger.warning(
            "Page %s vision JSON failed; OCR fallback (%s chars ocr)",
            page_index + 1,
            len(ocr_text),
        )
        transcript = _vision_transcribe_page(
            llm,
            b64,
            page_index=page_index,
            page_total=page_total,
        )
        blended = _blend_ocr_and_transcript(ocr_text, transcript)
        return extraction_from_ocr_fallback(
            blended,
            raw_model_snippet=getattr(exc, "raw_snippet", str(exc))[:2000],
        )


def _vision_transcribe_page(
    llm: OllamaProvider,
    b64_image: str,
    *,
    page_index: int,
    page_total: int,
) -> str:
    """Second-pass transcript when structured JSON is unstable."""
    prompt = (
        "请逐行抄写图中可见印刷文字。仅输出纯文本，不要 JSON，不要解释。"
        "优先抄写标题、品牌、Supplement Facts/Serving Size/Amount per serving、成分剂量行。"
    )
    if page_total > 1:
        prompt = f"这是共 {page_total} 页中的第 {page_index + 1} 页。{prompt}"
    try:
        reply = llm.chat_with_vision(
            system_prompt="你是OCR转写助手，只做忠实抄写，不做总结。",
            user_message=prompt,
            images=[b64_image],
        )
        return (reply or "").strip()
    except Exception:
        logger.debug("vision text transcript fallback failed", exc_info=True)
        return ""


def _blend_ocr_and_transcript(ocr_text: str, transcript_text: str) -> str:
    ocr = (ocr_text or "").strip()
    trans = (transcript_text or "").strip()
    if not ocr:
        return trans
    if not trans:
        return ocr
    if trans in ocr:
        return ocr
    if ocr in trans:
        return trans
    return f"{ocr}\n\n--- VISION_TRANSCRIPT ---\n{trans}"


class LabResultRow(BaseModel):
    item: str = ""
    value: str = ""
    unit: str = ""
    ref: str = ""


class NarrativeRow(BaseModel):
    category: str = ""
    content: str = ""
    summary: str = ""


class ReportExtraction(BaseModel):
    date: str = ""
    title: str = ""
    hospital: str = ""
    total_detected_rows_in_page: int = 0
    results: List[LabResultRow] = Field(default_factory=list)
    narratives: List[NarrativeRow] = Field(default_factory=list)


class VisionParseResponse(BaseModel):
    ok: bool = True
    vision_model: str
    pages_processed: int = 0
    extraction: ReportExtraction
    summary_text: str = Field(description="Human-readable text for event form回填")
    raw_json: dict[str, Any] = Field(default_factory=dict)
    metrics_preview: List[dict[str, Any]] = Field(default_factory=list)
    abnormal_count: int = 0
    metrics_stored: int = 0


class VisionPageParseResponse(BaseModel):
    """Single-page / single-image parse result for sharded client requests."""

    ok: bool = True
    parse_ok: bool = True
    warning: str = ""
    vision_model: str = ""
    page_index: int = 0
    page_total: int = 1
    total_detected_rows_in_page: int = 0
    extracted_count: int = 0
    metrics_count: int = 0
    narratives_count: int = 0
    extraction: ReportExtraction = Field(default_factory=ReportExtraction)
    metrics_preview: List[dict[str, Any]] = Field(default_factory=list)
    narratives_preview: List[dict[str, Any]] = Field(default_factory=list)
    abnormal_count: int = 0
    parse_mode: str = Field(default="", description="native | scan | image")
    parse_channel: str = Field(default="", description="heuristic | text_llm | vision")


def _coerce_detected_rows(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return max(0, int(float(str(value).strip())))
    except (TypeError, ValueError):
        return 0


def _log_page_alignment_ledger(
    page_num: int,
    detected_rows: int,
    metrics_count: int,
    narratives_count: int,
) -> None:
    total_captured = metrics_count + narratives_count
    sep = "=" * 56
    logger.info(sep)
    logger.info(
        "[Page %s] 视觉可见: %s 行, 数字指标: %s 项, 文本叙事: %s 条, 合计: %s 项",
        page_num,
        detected_rows,
        metrics_count,
        narratives_count,
        total_captured,
    )
    if detected_rows > total_captured:
        logger.warning(
            "[Page %s] 对齐缺口: 可见 %s 行，数字+叙事合计 %s（缺 %s），请前端补录",
            page_num,
            detected_rows,
            total_captured,
            detected_rows - total_captured,
        )
    logger.info(sep)


def _scale_png_to_max_width(png_bytes: bytes, max_width: int = VISION_MAX_WIDTH_PX) -> bytes:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for image scaling; pip install Pillow") from exc

    with Image.open(io.BytesIO(png_bytes)) as img:
        w, h = img.size
        if w <= max_width:
            # Keep original bytes to avoid extra JPEG artifacts on tiny label fonts.
            return png_bytes
        ratio = max_width / float(w)
        new_size = (max_width, max(1, int(h * ratio)))
        resized = img.resize(new_size, Image.Resampling.LANCZOS)
        out = io.BytesIO()
        if resized.mode not in ("RGB", "L", "RGBA"):
            resized = resized.convert("RGB")
        # Prefer PNG to preserve small text edges for OCR and VLM.
        resized.save(out, format="PNG", optimize=True)
        return out.getvalue()


def pdf_bytes_to_png_list(
    pdf_bytes: bytes,
    *,
    max_pages: int = PDF_MAX_PAGES,
    on_progress: Optional[ProgressCallback] = None,
) -> List[bytes]:
    """Render each PDF page to compressed JPEG bytes (scaled to VISION_MAX_WIDTH_PX)."""
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required; pip install pymupdf") from exc

    pages: List[bytes] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        cap = effective_pdf_pages_to_process(doc.page_count) if max_pages == PDF_MAX_PAGES else max(1, max_pages)
        total = min(doc.page_count, cap)
        for page_index in range(total):
            if on_progress:
                on_progress(page_index, total, "render")
            page = doc.load_page(page_index)
            pix = page.get_pixmap(
                matrix=fitz.Matrix(PDF_RENDER_MATRIX, PDF_RENDER_MATRIX),
                alpha=False,
            )
            png = pix.tobytes("png")
            pages.append(_scale_png_to_max_width(png))
    finally:
        doc.close()
    return pages


def image_file_to_png_list(
    raw: bytes,
    *,
    filename: str = "",
    on_progress: Optional[ProgressCallback] = None,
) -> List[bytes]:
    """Normalize upload to scaled JPEG page(s)."""
    lower = (filename or "").lower()
    if lower.endswith(".pdf"):
        return pdf_bytes_to_png_list(raw, on_progress=on_progress)
    return [_scale_png_to_max_width(raw)]


def png_list_to_base64(images: Sequence[bytes]) -> List[str]:
    return [base64.b64encode(blob).decode("ascii") for blob in images]


def pdf_page_count(pdf_bytes: bytes) -> int:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required; pip install pymupdf") from exc

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return int(doc.page_count)
    finally:
        doc.close()


def render_pdf_page_jpeg(pdf_bytes: bytes, page_index: int) -> bytes:
    """Render one PDF page (0-based) to compressed JPEG bytes."""
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required; pip install pymupdf") from exc

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if page_index < 0 or page_index >= doc.page_count:
            raise ValueError(f"page_index {page_index} out of range (0..{doc.page_count - 1})")
        page = doc.load_page(page_index)
        pix = page.get_pixmap(
            matrix=fitz.Matrix(PDF_RENDER_MATRIX, PDF_RENDER_MATRIX),
            alpha=False,
        )
        png = pix.tobytes("png")
    finally:
        doc.close()
    return _scale_png_to_max_width(png)


def _extract_json_object(text: str) -> dict[str, Any]:
    from pha.json_utils import safe_json_object
    from pha.vision_parser import VisionJsonParseError

    raw = (text or "").strip()
    try:
        return safe_json_object(text)
    except (ValueError, json.JSONDecodeError) as exc:
        snip = raw[:2000] if len(raw) > 2000 else raw
        raise VisionJsonParseError(
            f"Vision 输出无法解析为有效 JSON: {exc}",
            raw_snippet=snip,
        ) from exc


def _parse_extraction(data: dict[str, Any]) -> ReportExtraction:
    rows_raw = data.get("results") or []
    rows: List[LabResultRow] = []
    if isinstance(rows_raw, list):
        for entry in rows_raw:
            if not isinstance(entry, dict):
                continue
            rows.append(
                LabResultRow(
                    item=str(entry.get("item") or ""),
                    value=str(entry.get("value") or ""),
                    unit=str(entry.get("unit") or ""),
                    ref=str(entry.get("ref") or ""),
                ),
            )
    narr_raw = data.get("narratives") or []
    narratives: List[NarrativeRow] = []
    if isinstance(narr_raw, list):
        for entry in narr_raw:
            if not isinstance(entry, dict):
                continue
            content = str(entry.get("content") or "").strip()
            if not content:
                continue
            category = str(entry.get("category") or "").strip() or "未分类"
            summary = str(entry.get("summary") or "").strip()
            if not summary:
                summary = content[:50] + ("…" if len(content) > 50 else "")
            narratives.append(NarrativeRow(category=category, content=content, summary=summary))

    ext = ReportExtraction(
        date=str(data.get("date") or ""),
        title=str(data.get("title") or ""),
        hospital=str(data.get("hospital") or ""),
        total_detected_rows_in_page=_coerce_detected_rows(data.get("total_detected_rows_in_page")),
        results=rows,
        narratives=narratives,
    )
    from pha.pdf_hybrid_parser import sanitize_extraction

    return sanitize_extraction(ext)


def merge_extractions(parts: Sequence[ReportExtraction]) -> ReportExtraction:
    """Merge multi-page PDF parse results into one extraction."""
    if not parts:
        return ReportExtraction()
    merged_date = ""
    merged_title = ""
    merged_hospital = ""
    seen: set[Tuple[str, str, str, str]] = set()
    seen_narr: set[Tuple[str, str]] = set()
    merged_rows: List[LabResultRow] = []
    merged_narratives: List[NarrativeRow] = []

    for part in parts:
        if not merged_date and part.date.strip():
            merged_date = part.date.strip()
        if not merged_hospital and part.hospital.strip():
            merged_hospital = part.hospital.strip()
        if not merged_title and part.title.strip():
            merged_title = part.title.strip()
        elif part.title.strip() and part.title.strip() not in merged_title:
            merged_title = (merged_title + " / " + part.title.strip()).strip(" /")

        for row in part.results:
            key = (row.item, row.value, row.unit, row.ref)
            if key in seen:
                continue
            seen.add(key)
            merged_rows.append(row)

        for narr in part.narratives:
            nkey = (narr.category, narr.content)
            if nkey in seen_narr:
                continue
            seen_narr.add(nkey)
            merged_narratives.append(narr)

    return ReportExtraction(
        date=merged_date,
        title=merged_title,
        hospital=merged_hospital,
        results=merged_rows,
        narratives=merged_narratives,
    )


def format_extraction_as_summary(ext: ReportExtraction) -> str:
    lines: List[str] = []
    if ext.title:
        lines.append(f"【报告】{ext.title}")
    if ext.date:
        lines.append(f"【日期】{ext.date}")
    if ext.results:
        lines.append("【检验结果】")
        for r in ext.results:
            seg = " | ".join(
                x for x in [r.item, r.value + (r.unit and f" {r.unit}" or ""), r.ref and f"参考: {r.ref}"] if x
            )
            if seg:
                lines.append(f"- {seg}")
    if ext.narratives:
        lines.append("【文字叙事】")
        for n in ext.narratives:
            head = n.category or "叙事"
            body = (n.content or "").strip()
            if body:
                lines.append(f"- [{head}] {body}")
    if not lines:
        return "（视觉模型未提取到结构化内容）"
    return "\n".join(lines)


def build_vision_page_response(
    extraction: ReportExtraction,
    *,
    page_index: int,
    page_total: int,
    vision_model: str,
    parse_mode: str = "",
    parse_channel: str = "",
) -> VisionPageParseResponse:
    from pha.event_medical import extraction_to_metric_rows, metrics_preview_dicts, narratives_preview_dicts

    detected_rows = extraction.total_detected_rows_in_page
    metrics_count = len(extraction.results)
    narratives_count = len(extraction.narratives)
    extracted_count = metrics_count + narratives_count
    _log_page_alignment_ledger(page_index + 1, detected_rows, metrics_count, narratives_count)
    preview_rows = extraction_to_metric_rows(
        extraction,
        user_id="default",
        report_date=date.today(),
        source_filename="",
    )
    narr_preview = narratives_preview_dicts(extraction.narratives, hospital=extraction.hospital)
    abnormal_n = sum(1 for r in preview_rows if r.is_abnormal)
    return VisionPageParseResponse(
        ok=True,
        parse_ok=True,
        warning="",
        vision_model=vision_model,
        page_index=page_index,
        page_total=page_total,
        total_detected_rows_in_page=detected_rows,
        extracted_count=extracted_count,
        metrics_count=metrics_count,
        narratives_count=narratives_count,
        extraction=extraction,
        metrics_preview=metrics_preview_dicts(preview_rows),
        narratives_preview=narr_preview,
        abnormal_count=abnormal_n,
        parse_mode=parse_mode,
        parse_channel=parse_channel,
    )


class VisionReportParser:
    """End-to-end: bytes (PDF/image) → PNG pages → Ollama vision → merged JSON."""

    def __init__(self, *, llm: Optional[OllamaProvider] = None) -> None:
        self._llm = llm

    def _acquire_vision_llm(self, *, page_request: bool = False) -> OllamaProvider:
        if self._llm is not None and not page_request:
            return self._llm
        from pha.vision_parser import resolve_vision_11b_model

        load_dotenv_if_present()
        base = (
            os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_HOST")
            or "http://127.0.0.1:11434"
        ).rstrip("/")
        probe = float(os.environ.get("LLM_PROBE_TIMEOUT_SECONDS", "10"))
        installed = list_ollama_installed_models(base, timeout_seconds=probe)
        model = resolve_vision_11b_model(installed)
        timeout = VISION_PAGE_TIMEOUT_S if page_request else VISION_HTTP_TIMEOUT_S
        return OllamaProvider(
            base_url=base,
            model=model,
            timeout_seconds=timeout,
        )

    def _empty_page_response(
        self,
        llm: OllamaProvider,
        *,
        page_index: int,
        page_total: int,
        warning: str,
    ) -> VisionPageParseResponse:
        """Soft-fail one page (HTTP 200) so the client queue continues."""
        return VisionPageParseResponse(
            ok=True,
            parse_ok=False,
            warning=warning,
            vision_model=llm.model,
            page_index=page_index,
            page_total=page_total,
            extraction=ReportExtraction(),
            metrics_preview=[],
            abnormal_count=0,
        )

    def parse_single_jpeg(
        self,
        jpeg_bytes: bytes,
        *,
        page_index: int = 0,
        page_total: int = 1,
    ) -> VisionPageParseResponse:
        """Vision-parse one page image; intended for per-request sharded client calls."""
        import httpx

        from pha.vision_parser import VisionJsonParseError

        llm = self._acquire_vision_llm(page_request=True)
        try:
            extraction = _parse_page_with_ocr_fallback(
                llm,
                jpeg_bytes,
                page_index=page_index,
                page_total=page_total,
            )
        except VisionJsonParseError as exc:
            logger.warning("Page %s JSON salvage exhausted: %s", page_index + 1, exc)
            _log_page_alignment_ledger(page_index + 1, 0, 0, 0)
            return self._empty_page_response(
                llm,
                page_index=page_index,
                page_total=page_total,
                warning=str(exc),
            )
        except httpx.TimeoutException:
            logger.warning("Page %s vision timeout", page_index + 1)
            _log_page_alignment_ledger(page_index + 1, 0, 0, 0)
            return self._empty_page_response(
                llm,
                page_index=page_index,
                page_total=page_total,
                warning="单页 Vision 推理超时 (120s)，已跳过本页",
            )
        except Exception as exc:
            err = str(exc).lower()
            if "timeout" in err or "timed out" in err:
                return self._empty_page_response(
                    llm,
                    page_index=page_index,
                    page_total=page_total,
                    warning=f"单页推理超时: {exc}",
                )
            raise

        return build_vision_page_response(
            extraction,
            page_index=page_index,
            page_total=page_total,
            vision_model=llm.model,
            parse_mode="scan",
            parse_channel="vision_ocr_guarded",
        )

    def parse_pdf_page_native(
        self,
        pdf_bytes: bytes,
        page_index: int,
        *,
        page_total: int,
        pdf_model_override: str = "",
    ) -> VisionPageParseResponse:
        from pha.pdf_hybrid_parser import extract_pdf_page_text, native_page_to_extraction

        page_text = extract_pdf_page_text(pdf_bytes, page_index)
        if not page_text.strip():
            logger.warning("Native PDF page %s has no text; falling back to Vision", page_index + 1)
            return self.parse_pdf_page_vision(pdf_bytes, page_index, page_total=page_total)

        extraction, model_label, channel = native_page_to_extraction(
            page_text,
            page_index=page_index,
            page_total=page_total,
            pdf_model_override=pdf_model_override,
        )
        if not extraction.results and not extraction.narratives and len(page_text) > 80:
            logger.info("Native parse empty on page %s; Vision fallback", page_index + 1)
            return self.parse_pdf_page_vision(pdf_bytes, page_index, page_total=page_total)

        return build_vision_page_response(
            extraction,
            page_index=page_index,
            page_total=page_total,
            vision_model=model_label,
            parse_mode="native",
            parse_channel=channel,
        )

    def parse_pdf_page_vision(
        self,
        pdf_bytes: bytes,
        page_index: int,
        *,
        page_total: int,
    ) -> VisionPageParseResponse:
        jpeg = render_pdf_page_jpeg(pdf_bytes, page_index)
        resp = self.parse_single_jpeg(jpeg, page_index=page_index, page_total=page_total)
        resp.parse_mode = "scan"
        resp.parse_channel = "vision"
        return resp

    def parse_pdf_page(
        self,
        pdf_bytes: bytes,
        page_index: int,
        *,
        page_total: Optional[int] = None,
        pdf_model_override: str = "",
    ) -> VisionPageParseResponse:
        total = page_total if page_total is not None else effective_pdf_pages_to_process(pdf_page_count(pdf_bytes))
        from pha.pdf_hybrid_parser import get_pdf_parse_mode

        mode = get_pdf_parse_mode(pdf_bytes)
        if mode == "native":
            return self.parse_pdf_page_native(
                pdf_bytes,
                page_index,
                page_total=total,
                pdf_model_override=pdf_model_override,
            )
        return self.parse_pdf_page_vision(pdf_bytes, page_index, page_total=total)

    def parse_upload(
        self,
        raw: bytes,
        *,
        filename: str = "report",
        on_progress: Optional[ProgressCallback] = None,
    ) -> VisionParseResponse:
        pages = image_file_to_png_list(raw, filename=filename, on_progress=on_progress)
        if not pages:
            raise ValueError("No renderable pages in upload")

        llm = self._acquire_vision_llm()
        page_parts: List[ReportExtraction] = []
        total = len(pages)

        for idx, page_png in enumerate(pages):
            if on_progress:
                on_progress(idx + 1, total, "vision")
            page_parts.append(
                _parse_page_with_ocr_fallback(
                    llm,
                    page_png,
                    page_index=idx,
                    page_total=total,
                ),
            )

        merged = merge_extractions(page_parts)
        summary = format_extraction_as_summary(merged)
        from pha.event_medical import extraction_to_metric_rows, metrics_preview_dicts

        preview_rows = extraction_to_metric_rows(
            merged,
            user_id="default",
            report_date=date.today(),
            source_filename=filename,
        )
        abnormal_n = sum(1 for r in preview_rows if r.is_abnormal)
        return VisionParseResponse(
            vision_model=llm.model,
            pages_processed=len(pages),
            extraction=merged,
            summary_text=summary,
            raw_json=merged.model_dump(mode="python"),
            metrics_preview=metrics_preview_dicts(preview_rows),
            abnormal_count=abnormal_n,
            metrics_stored=0,
        )
