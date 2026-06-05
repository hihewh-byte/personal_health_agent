"""PDF medical report → text extraction (PyMuPDF) → LLM/heuristic structuring → SQLite."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from pha.json_utils import safe_json_object
from pha.llm_provider import (
    OllamaProvider,
    PdfLlmResolution,
    load_dotenv_if_present,
    smart_resolve_pdf_llm,
)
from pha.data_audit import (
    extract_ldl_snippet_from_text,
    ldl_value_from_metrics_blob,
    record_ingest_ldl_trace,
)
from pha.metric_customs import INGEST_DECOUPLE_SYSTEM
from pha.medical_storage import (
    upsert_medical_metrics,
    normalize_and_enrich_row,
    save_health_report_asset,
    _metrics_preview_from_rows,
    query_ldl_metrics_for_calendar_years,
    sanitize_ldl_value,
)
from pha.vision_parser import (
    VisionModelNotReadyError,
    VisionOomError,
    VisionParser,
    VISION_11B_MODEL,
)
from pha.models import WearableDailySummary
from pha.sqlite_storage import load_wearable_rows, upsert_wearable_rows

logger = logging.getLogger(__name__)


PDF_TEXT_MAX_CHARS = 14_000
PDF_OCR_FALLBACK_MIN_CHARS = 80
PDF_OCR_MAX_PAGES = 4

MEDICAL_CLEAN_SYSTEM_PROMPT = (
    INGEST_DECOUPLE_SYSTEM
    + '\n根对象需含 "report_date": "YYYY-MM-DD"（无法确定时用空字符串）。'
)


class MedicalMetricExtracted(BaseModel):
    metric_name: str = ""
    value: Optional[float] = None
    unit: str = ""
    reference_range: str = ""


class MedicalReportExtraction(BaseModel):
    report_date: str = ""
    metrics: List[MedicalMetricExtracted] = Field(default_factory=list)


IMAGE_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".heic",
)


class MedicalReportUploadResult(BaseModel):
    ok: bool = True
    status: str = "success"
    extracted_count: int = 0
    user_id: str
    report_date: str = ""
    metrics_stored: int = 0
    abnormal_count: int = 0
    extraction_model: str = ""
    vision_model: str = ""
    used_vision_fallback: bool = False
    parse_mode: str = "text"
    upload_kind: str = "medical_report"
    toast_message: str = ""
    models_unloaded: List[str] = Field(default_factory=list)
    source_filename: str = ""
    message: str = ""
    abnormal_metrics: List[Dict[str, Any]] = Field(default_factory=list)
    asset_id: Optional[int] = None


def _ollama_base_url() -> str:
    load_dotenv_if_present()
    return (
        os.environ.get("OLLAMA_BASE_URL")
        or os.environ.get("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).rstrip("/")


def pdf_bytes_to_text(pdf_bytes: bytes, *, max_chars: int = PDF_TEXT_MAX_CHARS) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required; pip install pymupdf") from exc

    parts: List[str] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            parts.append(page.get_text("text") or "")
    finally:
        doc.close()
    text = "\n".join(parts)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_chars]


def is_image_upload(filename: str) -> bool:
    lower = (filename or "").strip().lower()
    return any(lower.endswith(ext) for ext in IMAGE_SUFFIXES)


def _float_or_none(raw: Any) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _vision_parser_for(llm: Optional[OllamaProvider]) -> VisionParser:
    extra: List[str] = []
    if llm and llm.model:
        extra.append(llm.model)
    return VisionParser(base_url=_ollama_base_url(), extra_models_to_unload=extra)


def _vision_parse_image(
    raw_bytes: bytes,
    *,
    filename: str,
    llm: Optional[OllamaProvider] = None,
) -> tuple[dict[str, Any], str, List[str]]:
    parser = _vision_parser_for(llm)
    try:
        data = parser.parse_image_json(raw_bytes, filename=filename)
        return data, parser.model_name or VISION_11B_MODEL, parser.models_unloaded
    except VisionOomError:
        logger.warning("Vision 11B OOM — no gemma fallback for images per policy")
        raise


def _vision_parse_pdf_scan(
    pdf_bytes: bytes,
    *,
    llm: Optional[OllamaProvider] = None,
) -> tuple[dict[str, Any], str, List[str]]:
    parser = _vision_parser_for(llm)
    data = parser.parse_pdf_scan_json(pdf_bytes, max_pages=PDF_OCR_MAX_PAGES)
    return data, parser.model_name or VISION_11B_MODEL, parser.models_unloaded


def _upsert_wearable_from_screenshot(
    user_id: str,
    report_d: date,
    *,
    hrv_ms: Optional[float],
    rhr_bpm: Optional[float],
) -> WearableDailySummary:
    uid = (user_id or "default").strip() or "default"
    existing = load_wearable_rows(uid, start_date=report_d, end_date=report_d)
    if existing:
        row = existing[0]
        if hrv_ms is not None:
            row.hrv_rmssd_ms = hrv_ms
        if rhr_bpm is not None:
            row.resting_heart_rate_bpm = rhr_bpm
    else:
        row = WearableDailySummary(
            user_id=uid,
            day=report_d,
            hrv_rmssd_ms=hrv_ms,
            resting_heart_rate_bpm=rhr_bpm,
        )
    upsert_wearable_rows([row])
    return row


def _screenshot_toast_message(report_d: date, row: WearableDailySummary) -> str:
    if row.hrv_rmssd_ms is not None:
        return (
            f"✅ 截图识别成功：已记录 {report_d.isoformat()} 的 "
            f"HRV 数值 ({row.hrv_rmssd_ms:g}ms)。"
        )
    if row.resting_heart_rate_bpm is not None:
        return (
            f"✅ 截图识别成功：已记录 {report_d.isoformat()} 的 "
            f"静息心率 ({row.resting_heart_rate_bpm:g}bpm)。"
        )
    return f"✅ 截图识别成功：已记录 {report_d.isoformat()} 的健康数据。"


def _ocr_image_upload(
    raw_bytes: bytes,
    *,
    filename: str,
    llm: Optional[OllamaProvider] = None,
) -> tuple[str, str, str, List[str]]:
    """
    Single-page image OCR. Returns (text, parse_mode, vision_model_name, unloaded_models).
    """
    pages = image_file_to_png_list(raw_bytes, filename=filename)
    if not pages:
        raise ValueError("无法读取图片文件")

    base = _ollama_base_url()
    probe = float(os.environ.get("LLM_PROBE_TIMEOUT_SECONDS", "10"))
    installed = list_ollama_installed_models(base, timeout_seconds=probe)
    vision_name = find_vision_model(installed)
    unloaded: List[str] = []

    if vision_name:
        try:
            extra: List[str] = []
            if llm and llm.model:
                extra.append(llm.model)
            unloaded = suspend_text_models_for_vision(extra_models=extra)
            vision_llm = OllamaProvider(
                base_url=base,
                model=vision_name,
                timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "120")),
            )
            text = _vision_ocr_png_pages(pages, llm=vision_llm)
            suspend_vision_model_after_use(vision_name)
            if text.strip():
                return text, "vision_ocr", vision_name, unloaded
        except Exception:
            logger.exception("Vision image OCR failed; trying tesseract")

    from pha.vision_ocr import tesseract_ocr_png

    tess = tesseract_ocr_png(pages[0])
    if tess.strip():
        return tess, "tesseract_ocr", "", unloaded

    if not vision_name:
        raise VisionModelNotReadyError(
            "⏳ 正在等待视觉模型下载，暂无法处理截图；请稍后重试，或安装 pytesseract 作为本地备选。"
        )
    raise ValueError("无法从图片识别文字，请确认截图清晰且包含可读检验数据")


def _parse_extraction(data: dict[str, Any]) -> MedicalReportExtraction:
    metrics_raw = data.get("metrics") or []
    metrics: List[MedicalMetricExtracted] = []
    if isinstance(metrics_raw, list):
        for entry in metrics_raw:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("metric_name") or entry.get("name") or "").strip()
            if not name:
                continue
            raw_val = entry.get("value")
            value: Optional[float] = None
            if raw_val is not None and raw_val != "":
                try:
                    value = float(str(raw_val).replace(",", ""))
                except ValueError:
                    value = None
            metrics.append(
                MedicalMetricExtracted(
                    metric_name=name,
                    value=value,
                    unit=str(entry.get("unit") or ""),
                    reference_range=str(
                        entry.get("reference_range") or entry.get("ref") or "",
                    ),
                ),
            )
    return MedicalReportExtraction(
        report_date=str(data.get("report_date") or ""),
        metrics=metrics,
    )


def _resolve_report_date(raw: str, *, fallback: date) -> date:
    from pha.date_parser import safe_parse_date

    return safe_parse_date(raw) or fallback


def heuristic_pdf_text_to_extraction(raw_text: str) -> MedicalReportExtraction:
    """Pure regex/pdfplumber-style structuring — no LLM."""
    from pha.data_sanitizer import parse_numeric_value
    from pha.pdf_hybrid_parser import heuristic_text_to_extraction

    ext = heuristic_text_to_extraction(raw_text)
    metrics: List[MedicalMetricExtracted] = []
    for row in ext.results:
        item = (row.item or "").strip()
        if not item:
            continue
        val = parse_numeric_value(str(row.value)) if row.value else None
        metrics.append(
            MedicalMetricExtracted(
                metric_name=item,
                value=val,
                unit=(row.unit or "").strip(),
                reference_range=(row.ref or "").strip(),
            ),
        )
    return MedicalReportExtraction(report_date=ext.date, metrics=metrics)


class MedicalReportParser:
    """Parse PDF lab reports and persist structured metrics."""

    def __init__(
        self,
        *,
        llm: Optional[OllamaProvider] = None,
        pdf_model_override: str = "",
    ) -> None:
        self._llm = llm
        self._pdf_model_override = (pdf_model_override or "").strip()

    def _resolve_pdf_llm(self) -> PdfLlmResolution:
        probe = float(os.environ.get("LLM_PROBE_TIMEOUT_SECONDS", "10"))
        return smart_resolve_pdf_llm(
            override=self._pdf_model_override,
            base_url=_ollama_base_url(),
            timeout_seconds=probe,
        )

    def _medical_llm(self) -> OllamaProvider:
        if self._llm is not None:
            return self._llm
        resolution = self._resolve_pdf_llm()
        if resolution.mode != "llm" or not resolution.model:
            raise ValueError(
                "No text LLM available for PDF structuring; use heuristic mode or install a chat model.",
            )
        timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "120"))
        return OllamaProvider(
            base_url=_ollama_base_url(),
            model=resolution.model,
            timeout_seconds=timeout,
        )

    def extract_from_pdf_text(self, raw_text: str, *, llm: Optional[OllamaProvider] = None) -> MedicalReportExtraction:
        provider = llm or self._medical_llm()
        user_msg = (
            "以下是从 PDF 体检报告提取的原始文本。请清洗为 JSON。\n\n"
            f"--- PDF TEXT ---\n{raw_text}\n--- END ---"
        )
        reply = provider.chat_completion(
            system_prompt=MEDICAL_CLEAN_SYSTEM_PROMPT,
            user_message=user_msg,
        )
        data = safe_json_object(reply)
        return _parse_extraction(data)

    def parse_upload(
        self,
        raw_bytes: bytes,
        *,
        user_id: str,
        filename: str = "report.pdf",
        pdf_model_override: str = "",
    ) -> MedicalReportUploadResult:
        if pdf_model_override:
            self._pdf_model_override = pdf_model_override.strip()
        if is_image_upload(filename):
            return self._parse_image_and_store(raw_bytes, user_id=user_id, filename=filename)
        return self.parse_and_store(raw_bytes, user_id=user_id, filename=filename)

    def _parse_image_and_store(
        self,
        raw_bytes: bytes,
        *,
        user_id: str,
        filename: str,
    ) -> MedicalReportUploadResult:
        uid = (user_id or "default").strip() or "default"
        llm_pre = self._llm

        vision_data, vision_model_name, unloaded = _vision_parse_image(
            raw_bytes,
            filename=filename,
            llm=llm_pre,
        )

        image_type = str(vision_data.get("image_type") or "").lower()
        hrv_ms = _float_or_none(vision_data.get("hrv_rmssd_ms"))
        rhr_bpm = _float_or_none(vision_data.get("resting_heart_rate_bpm"))
        report_d = _resolve_report_date(
            str(vision_data.get("report_date") or ""),
            fallback=date.today(),
        )

        is_watch = image_type == "apple_watch" or (
            image_type != "lab_report" and (hrv_ms is not None or rhr_bpm is not None)
        )

        if is_watch and (hrv_ms is not None or rhr_bpm is not None):
            row = _upsert_wearable_from_screenshot(
                uid,
                report_d,
                hrv_ms=hrv_ms,
                rhr_bpm=rhr_bpm,
            )
            try:
                from pha.store import store

                store.import_wearable_rows(uid, [row])
            except Exception:
                logger.exception("In-memory wearable sync after screenshot failed")

            toast = _screenshot_toast_message(report_d, row)
            stored_n = sum(1 for v in (hrv_ms, rhr_bpm) if v is not None)
            asset_id = save_health_report_asset(
                uid,
                report_d,
                source_filename=filename,
                source_kind="screenshot",
                vision_model=vision_model_name,
                vision_raw=vision_data,
            )
            return MedicalReportUploadResult(
                ok=True,
                status="success",
                extracted_count=stored_n,
                user_id=uid,
                report_date=report_d.isoformat(),
                metrics_stored=stored_n,
                abnormal_count=0,
                extraction_model="",
                vision_model=vision_model_name,
                used_vision_fallback=True,
                parse_mode="watch_screenshot",
                upload_kind="watch_screenshot",
                toast_message=toast,
                models_unloaded=unloaded,
                source_filename=filename,
                message=toast,
                asset_id=asset_id,
            )

        metrics_raw = vision_data.get("metrics") or []
        if isinstance(metrics_raw, list) and metrics_raw:
            extraction = _parse_extraction(vision_data)
            return self._structure_and_store(
                "",
                user_id=uid,
                filename=filename,
                parse_mode="vision_11b_json",
                used_vision=True,
                vision_model_name=vision_model_name,
                unloaded=unloaded,
                prebuilt_extraction=extraction,
                vision_raw=vision_data,
                source_kind="screenshot",
            )

        raise ValueError(
            "Vision 未能从图片中识别 HRV/化验指标；请上传更清晰的 Apple Watch 截图或体检照片。"
        )

    def _structure_and_store(
        self,
        raw_text: str,
        *,
        user_id: str,
        filename: str,
        parse_mode: str,
        used_vision: bool,
        vision_model_name: str,
        unloaded: List[str],
        prebuilt_extraction: Optional[MedicalReportExtraction] = None,
        vision_raw: Optional[dict[str, Any]] = None,
        source_kind: str = "pdf",
    ) -> MedicalReportUploadResult:
        uid = (user_id or "default").strip() or "default"
        resolution = self._resolve_pdf_llm()
        llm: Optional[OllamaProvider] = None
        extraction_model = "heuristic"
        if prebuilt_extraction is not None:
            extraction = prebuilt_extraction
        elif resolution.mode == "heuristic":
            extraction = heuristic_pdf_text_to_extraction(raw_text)
        else:
            llm = self._medical_llm()
            extraction = self.extract_from_pdf_text(raw_text, llm=llm)
            extraction_model = llm.model
        report_d = _resolve_report_date(extraction.report_date, fallback=date.today())

        rows = []
        for m in extraction.metrics:
            row = normalize_and_enrich_row(
                uid,
                report_d,
                m.metric_name,
                m.value,
                m.unit,
                m.reference_range,
                source_filename=filename,
            )
            if row is not None:
                rows.append(row)

        stored = upsert_medical_metrics(rows) if rows else 0
        abnormal_rows = [r for r in rows if r.is_abnormal]

        parsed_ldl = ldl_value_from_metrics_blob(
            [{"metric_name": m.metric_name, "value": m.value} for m in extraction.metrics],
        )
        db_ldl_rows = query_ldl_metrics_for_calendar_years(uid, [report_d.year], security_inspect=False)
        db_ldl = db_ldl_rows[0].value if db_ldl_rows else None
        record_ingest_ldl_trace(
            uid,
            report_d,
            raw_snippet=extract_ldl_snippet_from_text(raw_text),
            parsed_value=parsed_ldl,
            db_value=sanitize_ldl_value(db_ldl),
            source_filename=filename,
        )

        mode_label = {
            "text": "文字层",
            "vision_ocr": "Vision OCR",
            "tesseract_ocr": "本地 OCR",
        }.get(parse_mode, parse_mode)

        raw_archive = vision_raw if vision_raw is not None else {
            "report_date": report_d.isoformat(),
            "metrics": [
                {
                    "metric_name": m.metric_name,
                    "value": m.value,
                    "unit": m.unit,
                    "reference_range": m.reference_range,
                }
                for m in extraction.metrics
            ],
        }
        asset_id = save_health_report_asset(
            uid,
            report_d,
            source_filename=filename,
            source_kind=source_kind,
            vision_model=vision_model_name or (llm.model if llm else extraction_model),
            vision_raw=raw_archive,
            metrics_preview=_metrics_preview_from_rows(rows),
        )

        toast = (
            f"✅ 解析成功：已从 [{filename}] 中提取 {stored} 项健康指标，并存入数据库。"
        )
        return MedicalReportUploadResult(
            ok=True,
            status="success",
            extracted_count=stored,
            user_id=uid,
            report_date=report_d.isoformat(),
            metrics_stored=stored,
            abnormal_count=len(abnormal_rows),
            extraction_model=extraction_model,
            vision_model=vision_model_name,
            used_vision_fallback=used_vision,
            parse_mode=parse_mode,
            upload_kind="medical_report",
            toast_message=toast,
            models_unloaded=unloaded,
            source_filename=filename,
            asset_id=asset_id,
            message=(
                f"已解析并写入 {stored} 项指标（报告日期 {report_d.isoformat()}），"
                f"其中异常 {len(abnormal_rows)} 项。 [{mode_label}]"
            ),
            abnormal_metrics=[
                {
                    "metric_code": r.metric_code,
                    "metric_name": r.metric_name,
                    "name_en": r.name_en,
                    "name_zh": r.name_zh,
                    "value": r.value,
                    "unit": r.unit,
                    "reference_range": r.reference_range,
                    "report_date": r.report_date.isoformat(),
                }
                for r in abnormal_rows
            ],
        )

    def parse_and_store(
        self,
        pdf_bytes: bytes,
        *,
        user_id: str,
        filename: str = "report.pdf",
    ) -> MedicalReportUploadResult:
        uid = (user_id or "default").strip() or "default"
        used_vision = False
        vision_model_name = ""
        unloaded: List[str] = []

        raw_text = pdf_bytes_to_text(pdf_bytes)
        text_chars = len(raw_text.strip())
        parse_mode = "text"
        needs_vision = text_chars < PDF_OCR_FALLBACK_MIN_CHARS

        if needs_vision:
            logger.info("PDF text sparse (%s chars); llama3.2-vision:11b scan", text_chars)
            vision_data, vision_model_name, unloaded = _vision_parse_pdf_scan(
                pdf_bytes,
                llm=self._llm,
            )
            used_vision = True
            parse_mode = "vision_11b_scan"
            metrics_raw = vision_data.get("metrics") or []
            if isinstance(metrics_raw, list) and metrics_raw:
                extraction = _parse_extraction(vision_data)
                return self._structure_and_store(
                    "",
                    user_id=uid,
                    filename=filename,
                    parse_mode=parse_mode,
                    used_vision=used_vision,
                    vision_model_name=vision_model_name,
                    unloaded=unloaded,
                    prebuilt_extraction=extraction,
                    vision_raw=vision_data,
                    source_kind="scan",
                )
            raise ValueError(
                "Vision 11B 未能从扫描 PDF 提取化验指标；请确认 llama3.2-vision:11b 已加载。"
            )

        if not raw_text.strip():
            raise ValueError("无法从 PDF 提取文本，请确认文件为可搜索的体检报告 PDF")

        return self._structure_and_store(
            raw_text,
            user_id=uid,
            filename=filename,
            parse_mode=parse_mode,
            used_vision=used_vision,
            vision_model_name=vision_model_name,
            unloaded=unloaded,
            source_kind="pdf",
        )
