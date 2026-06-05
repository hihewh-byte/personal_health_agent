"""Stage 3A.2.2 — Supplement label ledger, ecommerce guard, multi-image merge."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

_ECOMMERCE_RE = re.compile(
    r"加入购物车|立即购买|购物车|buy\s+now|add\s+to\s+cart|"
    r"¥\s*\d|￥\s*\d",
    re.I,
)
_LAB_HALLUCINATION_RE = re.compile(
    r"红细胞|白细胞|血小板|血红蛋白|中性粒|淋巴细胞|"
    r"×10\^?12|×10\^?9|血常规|检验结果",
    re.I,
)
_PANEL_HEADER_RE = re.compile(
    r"supplement\s+facts|serving\s+size|amount\s+per\s+serving|"
    r"营养成分表|每份含量",
    re.I,
)
_INGREDIENT_ROW_RE = re.compile(
    r"^(.{2,80}?)\s+(\d+(?:\.\d+)?)\s*(mg|mcg|μg|ug|g|iu)\b",
    re.I,
)
_FRONT_DOSE_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9\s\-]{4,60}?)\s+(\d+(?:\.\d+)?)\s*(mg|mcg|g|iu)\b",
    re.I,
)
_PHOSPHATIDYL_TOKEN_RE = re.compile(r"phosphatid", re.I)
_GARBAGE_INGREDIENT_NAME_RE = re.compile(
    r"^(?:\d+(?:\.\d+)?\s*(?:mg|mcg|g|iu)|100\s*mg|serine\s*-?|\[supplement)",
    re.I,
)
_LECITHIN_ONLY_RE = re.compile(r"卵磷脂|lecithin", re.I)
_MAX_LEDGER = int(os.environ.get("PHA_LABEL_LEDGER_MAX_CHARS", "2200"))


def ecommerce_guard_enabled() -> bool:
    return (os.environ.get("PHA_VISION_ECOMMERCE_GUARD", "1") or "1").strip() not in (
        "0",
        "false",
        "no",
    )


def ocr_required_for_attach() -> bool:
    return (os.environ.get("PHA_VISION_OCR_REQUIRED_FOR_ATTACH", "1") or "1").strip() not in (
        "0",
        "false",
        "no",
    )


def detect_ecommerce_from_ocr(ocr_text: str) -> bool:
    return bool(_ECOMMERCE_RE.search(ocr_text or ""))


def vision_summary_looks_like_lab(summary: str) -> bool:
    hits = len(_LAB_HALLUCINATION_RE.findall(summary or ""))
    return hits >= 3


def classify_label_layout(ocr_text: str) -> str:
    o = ocr_text or ""
    if detect_ecommerce_from_ocr(o):
        if _PANEL_HEADER_RE.search(o):
            return "ecommerce_product_screenshot+facts"
        return "ecommerce_product_screenshot+front"
    if _PANEL_HEADER_RE.search(o):
        return "supplement_facts_panel"
    if _FRONT_DOSE_RE.search(o):
        return "supplement_front"
    return "supplement_label"


def sanitize_ingredient_rows(
    rows: List[Dict[str, str]],
    *,
    ocr_text: str = "",
) -> List[Dict[str, str]]:
    """Drop OCR-split garbage; recover Phosphatidyl Serine when OCR breaks the compound name."""
    ocr = ocr_text or ""
    has_phos = bool(_PHOSPHATIDYL_TOKEN_RE.search(ocr))
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    for row in rows or []:
        name = str(row.get("name") or "").strip()
        amount = str(row.get("amount") or "").strip()
        if not name or not amount:
            continue
        if _GARBAGE_INGREDIENT_NAME_RE.match(name):
            continue
        if has_phos and re.fullmatch(r"serine\s*-?", name, flags=re.I):
            continue
        key = f"{name.lower()}|{amount.lower()}"
        if key in seen:
            continue
        seen.add(key)
        out.append({**row, "name": name, "amount": amount})

    if has_phos and not any(_PHOSPHATIDYL_TOKEN_RE.search(r.get("name") or "") for r in out):
        collapsed = re.sub(r"\s+", " ", ocr.replace("!", " ").replace("?", " "))
        m = re.search(
            r"phosphatidyl?\s*serine[^\d]{0,40}?(\d+(?:\.\d+)?)\s*(mg|mcg|g|iu)\b",
            collapsed,
            re.I,
        )
        if not m:
            m = re.search(
                r"phosphatidyl?[^\d]{0,12}(\d+(?:\.\d+)?)\s*(mg|mcg|g|iu)\b",
                collapsed,
                re.I,
            )
        if m:
            amt = f"{m.group(1)} {m.group(2)}"
            key = f"phosphatidyl serine|{amt.lower()}"
            if key not in seen:
                out.insert(
                    0,
                    {
                        "name": "Phosphatidyl Serine",
                        "amount": amt,
                        "source_line": m.group(0)[:200],
                    },
                )
    return out


def extract_ingredient_rows_from_text(text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen: set[str] = set()
    collapsed = re.sub(r"\s+", " ", (text or "").replace("\n", " "))
    for fm in _FRONT_DOSE_RE.finditer(collapsed):
        name = fm.group(1).strip()
        amount = f"{fm.group(2)} {fm.group(3)}"
        key = f"{name.lower()}|{amount.lower()}"
        if key not in seen and len(name) >= 4:
            seen.add(key)
            rows.append({"name": name, "amount": amount, "source_line": collapsed[:200]})
    for line in (text or "").splitlines():
        ln = line.strip()
        if not ln:
            continue
        m = _INGREDIENT_ROW_RE.match(ln)
        if m:
            name = m.group(1).strip(" .:-•|")
            amount = f"{m.group(2)} {m.group(3)}"
            key = f"{name.lower()}|{amount.lower()}"
            if key not in seen:
                seen.add(key)
                rows.append({"name": name, "amount": amount, "source_line": ln[:200]})
            continue
        for fm in _FRONT_DOSE_RE.finditer(ln):
            name = fm.group(1).strip()
            amount = f"{fm.group(2)} {fm.group(3)}"
            key = f"{name.lower()}|{amount.lower()}"
            if key not in seen and len(name) >= 4:
                seen.add(key)
                rows.append({"name": name, "amount": amount, "source_line": ln[:200]})
    return sanitize_ingredient_rows(rows, ocr_text=text)


def extract_ingredient_rows_from_parsed(parsed: Dict[str, Any]) -> List[Dict[str, str]]:
    parts: List[str] = []
    ocr = (parsed.get("ocr_text") or "").strip()
    if ocr:
        parts.append(ocr)
    for n in parsed.get("narratives") or []:
        if isinstance(n, dict):
            parts.append(str(n.get("content") or ""))
        else:
            parts.append(str(n))
    summary = (parsed.get("vision_summary") or "").strip()
    if summary:
        parts.append(summary)
    return extract_ingredient_rows_from_text("\n".join(parts))


def build_label_ledger_block(
    parsed: Dict[str, Any],
    *,
    ocr_text: str = "",
) -> Tuple[str, str]:
    """
    Returns (ledger_block, parse_confidence) where confidence is high|low.
    """
    ocr = (ocr_text or parsed.get("ocr_text") or "").strip()
    excerpt_lines: List[str] = []
    for line in ocr.splitlines():
        ln = line.strip()
        if not ln or len(ln) < 3:
            continue
        if len(ln) > 160:
            ln = ln[:160] + "…"
        excerpt_lines.append(ln)
        if len(excerpt_lines) >= 40:
            break

    if not excerpt_lines:
        for n in parsed.get("narratives") or []:
            c = (n.get("content") if isinstance(n, dict) else str(n)) or ""
            c = c.strip()
            if c:
                excerpt_lines.append(c[:200])
            if len(excerpt_lines) >= 24:
                break

    ingredients = extract_ingredient_rows_from_parsed({**parsed, "ocr_text": ocr})
    layout = classify_label_layout(ocr) or parsed.get("document_type") or "supplement_label"

    confidence = "high"
    summary = (parsed.get("vision_summary") or "").strip()
    if ecommerce_guard_enabled() and vision_summary_looks_like_lab(summary):
        confidence = "low"
    if not ingredients and not excerpt_lines:
        confidence = "low"

    lines = [
        "【标签摘录 · 系统自动识别 · 请核对】",
    ]
    if excerpt_lines:
        for ln in excerpt_lines[:28]:
            lines.append(f"- {ln}")
    else:
        lines.append("- （未能刮取到可读文字，请依赖模型对图像的描述并标明不确定）")

    if ingredients:
        lines.append("")
        lines.append("【成分定账 · 按标签可见行 · 勿泛称为单一「卵磷脂」】")
        for row in ingredients[:16]:
            lines.append(f"- {row['name']}: {row['amount']}")

    lines.append("")
    lines.append(f"【版式】{layout}")
    if confidence == "low":
        lines.append("【解析置信度】偏低：已优先采用 OCR 摘录；请勿将化验单式指标当作本品成分。")

    block = "\n".join(lines).strip()
    if len(block) > _MAX_LEDGER:
        block = block[: _MAX_LEDGER - 1] + "…"
    return block, confidence


def enrich_parsed_payload(
    parsed: Dict[str, Any],
    *,
    ocr_text: str = "",
    filename: str = "",
) -> Dict[str, Any]:
    """Attach ledger, layout, confidence; fix lab hallucination on supplement uploads."""
    out = dict(parsed)
    ocr = (ocr_text or out.get("ocr_text") or "").strip()
    if ocr:
        out["ocr_text"] = ocr

    layout = classify_label_layout(ocr)
    out["document_type"] = layout.split("+")[0] if layout else out.get("document_type", "supplement_label")
    out["layout_hint"] = layout

    summary = (out.get("vision_summary") or "").strip()
    if ecommerce_guard_enabled() and vision_summary_looks_like_lab(summary):
        out["metrics"] = []
        out["metrics_parsed_count"] = 0

    ledger, conf = build_label_ledger_block(out, ocr_text=ocr)
    out["label_ledger"] = ledger
    out["parse_confidence"] = conf
    out["ingredient_rows"] = extract_ingredient_rows_from_parsed(out)

    if ledger:
        out["vision_summary"] = ledger
    return out


def merge_parsed_payloads(parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge multiple attachment parse results (e.g. front + Supplement Facts)."""
    if not parts:
        return {}
    if len(parts) == 1:
        return dict(parts[0])

    merged: Dict[str, Any] = {
        "metrics": [],
        "narratives": [],
        "source_filename": " + ".join(
            str(p.get("source_filename") or "") for p in parts if p.get("source_filename")
        )[:200],
        "ocr_text": "\n\n---\n\n".join(
            (p.get("ocr_text") or "").strip() for p in parts if (p.get("ocr_text") or "").strip()
        ),
    }

    all_ingredients: List[Dict[str, str]] = []
    seen_ing: set[str] = set()
    for p in parts:
        merged["narratives"].extend(list(p.get("narratives") or []))
        for row in p.get("ingredient_rows") or extract_ingredient_rows_from_parsed(p):
            key = f"{row.get('name','').lower()}|{row.get('amount','').lower()}"
            if key not in seen_ing and row.get("name"):
                seen_ing.add(key)
                all_ingredients.append(row)

    # Facts-heavy part first for ingredient ordering
    def _facts_score(p: Dict[str, Any]) -> int:
        o = p.get("ocr_text") or ""
        return 2 if _PANEL_HEADER_RE.search(o) else 0

    parts_sorted = sorted(parts, key=_facts_score, reverse=True)
    for p in parts_sorted:
        for row in extract_ingredient_rows_from_parsed(p):
            key = f"{row.get('name','').lower()}|{row.get('amount','').lower()}"
            if key not in seen_ing and row.get("name"):
                seen_ing.add(key)
                all_ingredients.append(row)

    merged["ingredient_rows"] = all_ingredients
    merged = enrich_parsed_payload(merged, ocr_text=merged.get("ocr_text") or "")
    merged["attachment_count"] = len(parts)

    per_image: List[str] = []
    for idx, p in enumerate(parts, start=1):
        fn = str(p.get("source_filename") or f"图{idx}")
        blk, _ = build_label_ledger_block(p, ocr_text=str(p.get("ocr_text") or ""))
        if blk:
            per_image.append(f"【图 {idx} · {fn}】\n{blk}")
    if len(per_image) > 1:
        combined = "\n\n".join(per_image)
        if len(combined) <= _MAX_LEDGER:
            merged["vision_summary"] = combined
            merged["label_ledger"] = combined
    return merged


__all__ = [
    "build_label_ledger_block",
    "classify_label_layout",
    "detect_ecommerce_from_ocr",
    "enrich_parsed_payload",
    "ecommerce_guard_enabled",
    "merge_parsed_payloads",
    "ocr_required_for_attach",
    "vision_summary_looks_like_lab",
]
