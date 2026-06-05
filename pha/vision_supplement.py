"""Supplement / product label vision prompts and OCR-only fallbacks (Stage 3A).

Line heuristics use **layout and dose units only** — no hardcoded brands or ingredients.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from pha.vision_engine import NarrativeRow, ReportExtraction
from pha.vision_ocr import asset_whitelist_hint, format_ocr_context_block

# Dose / panel structure only (shared with vision_ocr scoring).
_DOSE_LINE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:mg|mcg|μg|ug|g|iu|ml)\b|\d+\s*%",
    re.I,
)
_PANEL_HEADER_RE = re.compile(
    r"supplement\s+facts|serving\s+size|daily\s+value|amount\s+per\s+serving|"
    r"营养成分表|每份|每日参考值",
    re.I,
)
_DISTRIBUTOR_RE = re.compile(
    r"distributed\s+by|manufactured\s+for|manufactured\s+by|经销商|生产商",
    re.I,
)

SUPPLEMENT_LABEL_VISION_SYSTEM = """你是营养补剂/保健品标签结构化助手。输入包含 OCR 刮取的印刷文字 + 图像。

必须只输出一个 JSON 对象（无 Markdown、无前后说明）。格式：
{
  "document_type": "supplement_label",
  "date": "",
  "title": "品牌与产品名简述（来自图中文字，勿臆测）",
  "hospital": "",
  "total_detected_rows_in_page": 0,
  "results": [],
  "narratives": [
    {"category": "supplement_facts", "content": "成分/剂量一行（照抄 OCR）"},
    {"category": "brand", "content": "品牌或经销商一行"},
    {"category": "usage_hint", "content": "服用说明或警示（若有）"}
  ]
}

规则：
- results 必须为空数组（补剂标签不是化验数字表）。
- 仅照抄图中可见文字填入 narratives；禁止编造未出现的成分名或剂量。
- 看不清的字段用 ""。
""" + "\n" + asset_whitelist_hint()


def build_supplement_vision_user_message(
    *,
    ocr_text: str,
    page_index: int = 0,
    page_total: int = 1,
) -> str:
    ocr_block = format_ocr_context_block(ocr_text)
    base = (
        "请根据 OCR 死字与图像，将本图识别为营养补剂/保健品标签，按系统 JSON 输出。"
        "将 OCR 中的成分/剂量行写入 narratives；不要输出化验 results。"
    )
    if page_total > 1:
        base = f"这是共 {page_total} 页的第 {page_index + 1} 页。{base}"
    if ocr_block:
        return f"{ocr_block}\n\n{base}"
    return base


def _is_brand_or_distributor_line(line: str, *, in_facts_panel: bool) -> bool:
    ln = (line or "").strip()
    if not ln or len(ln) > 120:
        return False
    if _DISTRIBUTOR_RE.search(ln):
        return True
    if in_facts_panel:
        return False
    if _DOSE_LINE_RE.search(ln) or _PANEL_HEADER_RE.search(ln):
        return False
    # Short header-like line before facts panel (brand block).
    if len(ln) <= 64 and not re.search(r"\d{2,}", ln):
        return True
    return False


def extraction_from_ocr_fallback(ocr_text: str, *, raw_model_snippet: str = "") -> ReportExtraction:
    """Deterministic fallback when vision JSON parsing fails — never poisons lab metrics."""
    text = (ocr_text or "").strip()
    narratives: List[NarrativeRow] = []
    brand_line = ""
    in_panel = False

    for line in text.splitlines():
        ln = line.strip()
        if not ln:
            continue
        if _PANEL_HEADER_RE.search(ln):
            in_panel = True
            narratives.append(NarrativeRow(category="panel_header", content=ln, summary=ln[:48]))
            continue
        if _DISTRIBUTOR_RE.search(ln):
            if not brand_line:
                brand_line = ln
            narratives.append(NarrativeRow(category="brand", content=ln, summary=ln[:48]))
            continue
        if _is_brand_or_distributor_line(ln, in_facts_panel=in_panel) and not brand_line:
            brand_line = ln
            narratives.append(NarrativeRow(category="brand", content=ln, summary=ln[:48]))
            continue
        if _DOSE_LINE_RE.search(ln) or (in_panel and len(ln) > 8):
            narratives.append(
                NarrativeRow(category="supplement_facts", content=ln, summary=ln[:48]),
            )

    if raw_model_snippet.strip():
        narratives.append(
            NarrativeRow(
                category="vision_raw_snippet",
                content=raw_model_snippet.strip()[:2000],
                summary="模型原文片段",
            ),
        )

    if not narratives and text:
        narratives.append(
            NarrativeRow(
                category="unstructured_vision",
                content=text[:4000],
                summary="OCR 原文兜底",
            ),
        )

    title = "营养补剂/成分标签"
    if brand_line:
        title = f"{title} · {brand_line[:80]}"

    return ReportExtraction(
        date="",
        title=title,
        hospital="",
        total_detected_rows_in_page=len(narratives),
        results=[],
        narratives=narratives,
    )


def parsed_payload_from_extraction(
    extraction: ReportExtraction,
    *,
    filename: str,
    parse_channel: str,
    vision_summary: str = "",
) -> Dict[str, Any]:
    from pha.event_medical import narratives_preview_dicts

    narratives = narratives_preview_dicts(
        extraction.narratives,
        hospital=extraction.hospital or "",
    )
    summary = vision_summary.strip() or _format_summary(extraction)
    return {
        "metrics": [],
        "narratives": narratives,
        "report_date": (extraction.date or "")[:10],
        "hospital": extraction.hospital or "",
        "source_filename": filename,
        "vision_summary": summary,
        "metrics_parsed_count": 0,
        "document_type": "supplement_label",
        "parse_channel": parse_channel,
    }


def _format_summary(extraction: ReportExtraction) -> str:
    parts: List[str] = []
    if extraction.title:
        parts.append(extraction.title)
    for n in extraction.narratives[:24]:
        if n.content:
            parts.append(f"- [{n.category}] {n.content}")
    return "\n".join(parts).strip()
