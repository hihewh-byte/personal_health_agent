"""Hybrid PDF routing: native text (pdfplumber + fast text LLM) vs scan (Vision)."""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import time
from typing import Any, Literal, Optional

from pha.llm_provider import OllamaProvider, load_dotenv_if_present, smart_resolve_pdf_llm
from pha.vision_engine import (
    LabResultRow,
    NarrativeRow,
    ReportExtraction,
    VISION_EXTRACTION_SYSTEM_PROMPT,
    _coerce_detected_rows,
    _extract_json_object,
    _log_page_alignment_ledger,
    _parse_extraction,
)

logger = logging.getLogger(__name__)

PdfParseMode = Literal["native", "scan"]

PROBE_PAGES = int(os.environ.get("PHA_PDF_PROBE_PAGES", "3"))
NATIVE_MIN_PROBE_CHARS = int(os.environ.get("PHA_PDF_NATIVE_MIN_CHARS", "100"))
TEXT_PAGE_MAX_CHARS = int(os.environ.get("PHA_PDF_TEXT_PAGE_MAX_CHARS", "14000"))
TEXT_PAGE_TIMEOUT_S = float(os.environ.get("PHA_PDF_TEXT_PAGE_TIMEOUT_SECONDS", "12"))
HEURISTIC_MIN_TEXT_LEN = int(os.environ.get("PHA_PDF_HEURISTIC_MIN_TEXT", "40"))

_pdf_mode_cache: dict[str, PdfParseMode] = {}
_pdf_mode_cache_max = 48

_NUM_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)")
_REF_RE = re.compile(
    r"(?:参考[：:]?\s*)?([<>≤≥]?\s*\d+(?:\.\d+)?\s*[-~–—]\s*\d+(?:\.\d+)?|[<>≤≥]\s*\d+(?:\.\d+)?)",
)

_NARRATIVE_CATEGORY_HINTS: tuple[tuple[str, str], ...] = (
    ("超声", "超声影像"),
    ("B超", "超声影像"),
    ("彩超", "超声影像"),
    ("心电图", "心电图结论"),
    ("ECG", "心电图结论"),
    ("心电", "心电图结论"),
    ("总检", "医生总评"),
    ("综述", "医生总评"),
    ("建议", "总检建议"),
    ("结论", "医生总评"),
    ("既往史", "既往病史"),
    ("病史", "既往病史"),
    ("诊断", "诊断意见"),
)


def _pdf_cache_key(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


def _pdfplumber_available() -> bool:
    try:
        import pdfplumber  # noqa: F401
        return True
    except ImportError:
        return False


def _open_pdfplumber(pdf_bytes: bytes):
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber is required; pip install pdfplumber") from exc
    return pdfplumber.open(io.BytesIO(pdf_bytes))


def _extract_page_text_pymupdf(pdf_bytes: bytes, page_index: int) -> str:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required") from exc

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if page_index < 0 or page_index >= doc.page_count:
            return ""
        return (doc.load_page(page_index).get_text("text") or "").strip()
    finally:
        doc.close()


def _probe_chars_pymupdf(pdf_bytes: bytes, n_probe: int) -> int:
    try:
        import fitz
    except ImportError:
        return 0
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        total = 0
        for i in range(min(n_probe, doc.page_count)):
            total += len((doc.load_page(i).get_text("text") or "").strip())
        return total
    finally:
        doc.close()


def _page_plain_text(page: Any) -> str:
    parts: list[str] = []
    try:
        t = page.extract_text() or ""
        if t.strip():
            parts.append(t)
    except Exception as exc:
        logger.debug("extract_text failed: %s", exc)
    try:
        for table in page.extract_tables() or []:
            for row in table:
                if not row:
                    continue
                cells = [str(c or "").strip() for c in row if c is not None]
                line = "\t".join(c for c in cells if c)
                if line:
                    parts.append(line)
    except Exception as exc:
        logger.debug("extract_tables failed: %s", exc)
    return "\n".join(parts).strip()


def classify_pdf_mode(pdf_bytes: bytes) -> PdfParseMode:
    """Return ``native`` when first probe pages have enough extractable text."""
    try:
        if _pdfplumber_available():
            with _open_pdfplumber(pdf_bytes) as pdf:
                n_probe = min(PROBE_PAGES, len(pdf.pages))
                if n_probe == 0:
                    return "scan"
                total_chars = sum(len(_page_plain_text(pdf.pages[i])) for i in range(n_probe))
        else:
            logger.warning("pdfplumber not installed; probing with PyMuPDF text layer")
            total_chars = _probe_chars_pymupdf(pdf_bytes, PROBE_PAGES)
            n_probe = PROBE_PAGES
        mode: PdfParseMode = "native" if total_chars >= NATIVE_MIN_PROBE_CHARS else "scan"
        logger.info(
            "PDF hybrid probe: pages=%s chars=%s -> %s",
            n_probe,
            total_chars,
            mode,
        )
        return mode
    except Exception as exc:
        logger.warning("PDF probe failed, defaulting to scan/Vision: %s", exc)
        return "scan"


def get_pdf_parse_mode(pdf_bytes: bytes) -> PdfParseMode:
    key = _pdf_cache_key(pdf_bytes)
    cached = _pdf_mode_cache.get(key)
    if cached:
        return cached
    mode = classify_pdf_mode(pdf_bytes)
    if len(_pdf_mode_cache) >= _pdf_mode_cache_max:
        _pdf_mode_cache.pop(next(iter(_pdf_mode_cache)))
    _pdf_mode_cache[key] = mode
    return mode


def extract_pdf_page_text(pdf_bytes: bytes, page_index: int) -> str:
    if _pdfplumber_available():
        with _open_pdfplumber(pdf_bytes) as pdf:
            if page_index < 0 or page_index >= len(pdf.pages):
                return ""
            return _page_plain_text(pdf.pages[page_index])[:TEXT_PAGE_MAX_CHARS]
    return _extract_page_text_pymupdf(pdf_bytes, page_index)[:TEXT_PAGE_MAX_CHARS]


def _guess_narrative_category(text: str) -> str:
    for hint, cat in _NARRATIVE_CATEGORY_HINTS:
        if hint in text:
            return cat
    return "报告原文"


def _line_is_narrative(line: str) -> bool:
    s = line.strip()
    if len(s) < 8:
        return False
    if len(s) >= 28 and not _REF_RE.search(s):
        for hint, _ in _NARRATIVE_CATEGORY_HINTS:
            if hint in s:
                return True
    if len(s) >= 36 and not re.search(r"[a-zA-Zμ%/]{1,12}", s):
        return True
    return False


def _line_looks_like_lab(line: str) -> bool:
    s = line.strip()
    if len(s) < 4 or len(s) > 80:
        return False
    if _line_is_narrative(s):
        return False
    if not _NUM_RE.search(s):
        return False
    alpha = re.sub(r"[\d\s\.\-+<>≤≥%/\\|，,;:：·\t]", "", s)
    if len(alpha) < 2:
        return False
    if len(alpha) > 24 and not _REF_RE.search(s) and not re.search(
        r"\b(mmol|mmol/L|mg|g/L|U/L|IU|μmol|pmol|ng|mL|%|次/分|bpm)\b",
        s,
        re.I,
    ):
        return False
    return True


def _is_valid_lab_row(row: LabResultRow) -> bool:
    item = (row.item or "").strip()
    val = (row.value or "").strip()
    unit = (row.unit or "").strip()
    ref = (row.ref or "").strip()
    if not item or not val:
        return False
    if _line_is_narrative(" ".join(x for x in [item, val, unit, ref] if x)):
        return False
    try:
        num = float(val.replace(",", ""))
        if 1900 <= num <= 2100 and not unit and not ref:
            return False
    except ValueError:
        if len(val) > 12 and not unit and not ref:
            return False
    if len(item) > 32 and not unit and not ref:
        return False
    return True


def _parse_lab_line(line: str) -> Optional[LabResultRow]:
    s = re.sub(r"\s+", " ", line.strip())
    if not _line_looks_like_lab(s):
        return None
    ref_m = _REF_RE.search(s)
    ref = ref_m.group(1).strip() if ref_m else ""
    if ref:
        s = s[: ref_m.start()].strip() + " " + s[ref_m.end() :].strip()
        s = re.sub(r"\s+", " ", s).strip()
    nums = list(_NUM_RE.finditer(s))
    if not nums:
        return None
    val_m = nums[-1]
    value = val_m.group(1)
    before = s[: val_m.start()].strip()
    after = s[val_m.end() :].strip()
    item = before
    unit = ""
    if after:
        unit_m = re.match(r"^([a-zA-Zμ%/°]{1,16})\b", after)
        if unit_m:
            unit = unit_m.group(1)
    if not item or len(item) < 2:
        return None
    return LabResultRow(item=item, value=value, unit=unit, ref=ref)


def _extract_date_hospital(lines: list[str]) -> tuple[str, str]:
    date_s = ""
    hospital = ""
    date_pat = re.compile(r"(20\d{2})[年\-/](\d{1,2})[月\-/](\d{1,2})")
    hosp_pat = re.compile(r"([\u4e00-\u9fff]{2,20}(?:医院|体检中心|医学中心|卫生院))")
    for line in lines[:12]:
        if not date_s:
            m = date_pat.search(line)
            if m:
                y, mo, d = m.groups()
                date_s = f"{y}-{int(mo):02d}-{int(d):02d}"
        if not hospital:
            m = hosp_pat.search(line)
            if m:
                hospital = m.group(1)
    return date_s, hospital


def heuristic_text_to_extraction(page_text: str) -> ReportExtraction:
    """Rule-based fast path — target sub-second per page on native PDFs."""
    lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
    results: list[LabResultRow] = []
    narratives: list[NarrativeRow] = []
    narrative_buf: list[str] = []

    def flush_narrative() -> None:
        nonlocal narrative_buf
        if not narrative_buf:
            return
        body = "\n".join(narrative_buf).strip()
        narrative_buf = []
        if len(body) < 6:
            return
        cat = _guess_narrative_category(body)
        summary = body[:50] + ("…" if len(body) > 50 else "")
        narratives.append(NarrativeRow(category=cat, content=body, summary=summary))

    for line in lines:
        if _line_is_narrative(line):
            flush_narrative()
            narrative_buf.append(line)
            continue
        row = _parse_lab_line(line)
        if row and _is_valid_lab_row(row):
            flush_narrative()
            results.append(row)
        elif len(line) >= 8:
            flush_narrative()
            narrative_buf.append(line)
        elif "\t" in line:
            for cell_line in line.split("\t"):
                if _line_is_narrative(cell_line):
                    flush_narrative()
                    narrative_buf.append(cell_line)
                    continue
                sub = _parse_lab_line(cell_line)
                if sub and _is_valid_lab_row(sub):
                    flush_narrative()
                    results.append(sub)
                elif len(cell_line) >= 8:
                    flush_narrative()
                    narrative_buf.append(cell_line)

    flush_narrative()
    date_s, hospital = _extract_date_hospital(lines)
    captured = len(results) + len(narratives)
    detected = captured if captured else 0
    ext = ReportExtraction(
        date=date_s,
        title="",
        hospital=hospital,
        total_detected_rows_in_page=detected,
        results=results,
        narratives=narratives,
    )
    return sanitize_extraction(ext)


def sanitize_extraction(ext: ReportExtraction) -> ReportExtraction:
    """Move narrative-like rows out of ``results``; align detected count with captured items."""
    clean_results: list[LabResultRow] = []
    extra_narratives: list[NarrativeRow] = list(ext.narratives)

    for row in ext.results:
        if _is_valid_lab_row(row):
            clean_results.append(row)
            continue
        content = " ".join(x for x in [row.item, row.value, row.unit, row.ref] if x).strip()
        if not content:
            continue
        cat = _guess_narrative_category(content)
        summary = content[:50] + ("…" if len(content) > 50 else "")
        extra_narratives.append(NarrativeRow(category=cat, content=content, summary=summary))

    captured = len(clean_results) + len(extra_narratives)
    detected = ext.total_detected_rows_in_page
    if detected < captured:
        detected = captured
    return ReportExtraction(
        date=ext.date,
        title=ext.title,
        hospital=ext.hospital,
        total_detected_rows_in_page=detected,
        results=clean_results,
        narratives=extra_narratives,
    )


def _heuristic_sufficient(ext: ReportExtraction, page_text: str) -> bool:
    if ext.results or ext.narratives:
        return True
    if len(page_text.strip()) < HEURISTIC_MIN_TEXT_LEN:
        return True
    return False


def _acquire_text_llm(*, pdf_model_override: str = "") -> Optional[OllamaProvider]:
    load_dotenv_if_present()
    base = (
        os.environ.get("OLLAMA_BASE_URL")
        or os.environ.get("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).rstrip("/")
    probe = float(os.environ.get("LLM_PROBE_TIMEOUT_SECONDS", "10"))
    resolution = smart_resolve_pdf_llm(
        override=pdf_model_override,
        base_url=base,
        timeout_seconds=probe,
    )
    if resolution.mode != "llm" or not resolution.model:
        return None
    return OllamaProvider(
        base_url=base,
        model=resolution.model,
        timeout_seconds=TEXT_PAGE_TIMEOUT_S,
    )


def text_llm_to_extraction(
    page_text: str,
    *,
    page_index: int,
    page_total: int,
    pdf_model_override: str = "",
) -> tuple[ReportExtraction, str]:
    llm = _acquire_text_llm(pdf_model_override=pdf_model_override)
    if llm is None:
        raise RuntimeError("text_llm_unavailable")
    user_msg = (
        f"这是共 {page_total} 页体检/检验报告 PDF 的第 {page_index + 1} 页纯文本（pdfplumber 提取，含表格）。"
        "请严格按系统 JSON 格式输出，数字指标放 results，超声/心电图/总评等放 narratives。\n\n"
        f"{page_text[:TEXT_PAGE_MAX_CHARS]}"
    )
    raw = llm.chat_completion(system_prompt=VISION_EXTRACTION_SYSTEM_PROMPT, user_message=user_msg)
    data = _extract_json_object(raw)
    return _parse_extraction(data), llm.model


def _force_heuristic_only(pdf_model_override: str) -> bool:
    from pha.llm_provider import FALLBACK_TO_HEURISTIC

    token = (pdf_model_override or "").strip().lower()
    return token in {
        FALLBACK_TO_HEURISTIC.lower(),
        "heuristic",
        "__heuristic__",
    }


def native_page_to_extraction(
    page_text: str,
    *,
    page_index: int,
    page_total: int,
    pdf_model_override: str = "",
) -> tuple[ReportExtraction, str, str]:
    """
    Fast native PDF page parse.

    Returns (extraction, model_label, channel) where channel is ``heuristic`` or ``text_llm``.
    """
    t0 = time.perf_counter()
    ext = heuristic_text_to_extraction(page_text)
    elapsed = time.perf_counter() - t0
    if _force_heuristic_only(pdf_model_override):
        logger.info(
            "PDF native page %s heuristic-only %.3fs (override)",
            page_index + 1,
            elapsed,
        )
        return ext, "pdfplumber-heuristic", "heuristic"
    if _heuristic_sufficient(ext, page_text):
        logger.info("PDF native page %s heuristic %.3fs (metrics=%s narr=%s)", page_index + 1, elapsed, len(ext.results), len(ext.narratives))
        return ext, "pdfplumber-heuristic", "heuristic"

    try:
        ext, model = text_llm_to_extraction(
            page_text,
            page_index=page_index,
            page_total=page_total,
            pdf_model_override=pdf_model_override,
        )
        elapsed = time.perf_counter() - t0
        logger.info("PDF native page %s text_llm %.3fs model=%s", page_index + 1, elapsed, model)
        return ext, model, "text_llm"
    except Exception as exc:
        logger.warning("Text LLM page %s failed (%s), using heuristic partial", page_index + 1, exc)
        return ext, "pdfplumber-heuristic", "heuristic"
