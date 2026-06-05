"""Stage 3B — LabelLedgerV1 schema, confidence law (P-layer G1–G6), and merge."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from pha.perception_merge import (
    brand_weight_for_hints,
    has_authoritative_ingredient_panel,
    ingredient_weight_for_hints,
    merge_ingredient_rows_weighted,
    pick_string_by_weight,
)
from pha.vision_label_ledger import (
    _GARBAGE_INGREDIENT_NAME_RE,
    _PANEL_HEADER_RE,
    _PHOSPHATIDYL_TOKEN_RE,
    build_label_ledger_block,
    classify_label_layout,
    detect_ecommerce_from_ocr,
    enrich_parsed_payload,
    extract_ingredient_rows_from_text,
)

ParseConfidence = Literal["high", "low"]
PerceptionChannel = Literal["ocr_only", "ocr_plus_vision_validate", "vision_structured"]

_BRAND_LINE_RE = re.compile(r"^[A-Z][A-Z0-9\-]{2,15}$")
_PACKAGE_RE = re.compile(
    r"(\d+)\s*(?:veg\s*)?(?:capsules?|caps|softgels?|tablets?|粒|片)",
    re.I,
)
_MISREAD_BRAND_RE = re.compile(r"\bZENS(?:ESSE)?\b", re.I)
_PHOSPHATIDYL_RE = re.compile(r"phosphatidyl\s*serine|磷脂酰丝氨酸", re.I)

_MIN_OCR = int(os.environ.get("PHA_PERCEPTION_MIN_OCR_CHARS", "80") or "80")


class IngredientRowV1(BaseModel):
    name: str
    amount: str = ""
    unit: str = ""
    source_image_index: int = 0
    source_line: str = ""

    @property
    def amount_display(self) -> str:
        if self.amount and self.unit:
            return f"{self.amount} {self.unit}"
        return (self.amount or "").strip()


class LabelLedgerV1(BaseModel):
    schema_version: str = "label_ledger_v1"
    attachment_count: int = 1
    brand: str = ""
    product_title: str = ""
    package_size: str = ""
    layout_hints: List[str] = Field(default_factory=list)
    layout_hints_per_image: List[Dict[str, Any]] = Field(default_factory=list)
    ingredient_rows: List[IngredientRowV1] = Field(default_factory=list)
    parse_confidence: ParseConfidence = "high"
    reject_reasons: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    perception_channel: PerceptionChannel = "ocr_only"
    ocr_char_count: int = 0
    merge_trace: List[Dict[str, Any]] = Field(default_factory=list)
    ledger_markdown: str = ""

    def to_parsed_dict(self) -> Dict[str, Any]:
        return {
            "label_ledger_v1": self.model_dump(mode="python"),
            "schema_version": self.schema_version,
            "attachment_count": self.attachment_count,
            "brand": self.brand,
            "product_title": self.product_title,
            "package_size": self.package_size,
            "layout_hints": list(self.layout_hints),
            "layout_hints_per_image": list(self.layout_hints_per_image),
            "ingredient_rows": [
                {
                    "name": r.name,
                    "amount": r.amount_display or r.amount,
                    "source_line": r.source_line,
                    "source_image_index": r.source_image_index,
                }
                for r in self.ingredient_rows
            ],
            "parse_confidence": self.parse_confidence,
            "reject_reasons": list(self.reject_reasons),
            "warnings": list(self.warnings),
            "perception_channel": self.perception_channel,
            "ocr_char_count": self.ocr_char_count,
            "merge_trace": list(self.merge_trace),
            "label_ledger": self.ledger_markdown,
            "vision_summary": self.ledger_markdown,
        }


def _split_amount_unit(amount_str: str) -> Tuple[str, str]:
    raw = (amount_str or "").strip()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(mg|mcg|μg|ug|g|iu)\b", raw, re.I)
    if m:
        return m.group(1), m.group(2).lower().replace("ug", "mcg")
    return raw, ""


def row_has_parseable_dose(row: IngredientRowV1) -> bool:
    if row.amount and row.unit:
        return True
    return bool(re.match(r"^\d+(?:\.\d+)?\s*(mg|mcg|g|iu)\b", row.amount or "", re.I))


def rows_from_legacy(legacy_rows: List[Dict[str, Any]], *, source_image_index: int = 0) -> List[IngredientRowV1]:
    out: List[IngredientRowV1] = []
    for row in legacy_rows or []:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        amt_s = str(row.get("amount") or "").strip()
        amount, unit = _split_amount_unit(amt_s)
        out.append(
            IngredientRowV1(
                name=name,
                amount=amount,
                unit=unit,
                source_image_index=int(row.get("source_image_index") or source_image_index),
                source_line=str(row.get("source_line") or "")[:200],
            ),
        )
    return out


def rows_from_ocr_text(ocr_text: str, *, source_image_index: int = 0) -> List[IngredientRowV1]:
    legacy = extract_ingredient_rows_from_text(ocr_text or "")
    return rows_from_legacy(legacy, source_image_index=source_image_index)


def layout_hints_from_ocr(ocr_text: str) -> List[str]:
    layout = classify_label_layout(ocr_text or "")
    hints: List[str] = []
    if not layout:
        return hints
    if "+" in layout:
        hints.extend(layout.split("+"))
    else:
        hints.append(layout)
    o = ocr_text or ""
    if _PANEL_HEADER_RE.search(o):
        if "supplement_facts_panel" not in hints:
            hints.append("supplement_facts_panel")
    rows = rows_from_ocr_text(o)
    if len(rows) == 1 and not _PANEL_HEADER_RE.search(o):
        hints.append("single_ingredient_product")
    if not hints:
        hints.append("unknown")
    return list(dict.fromkeys(hints))


def extract_brand_from_ocr(ocr_text: str, *, combined_ocr: str = "") -> str:
    for line in (ocr_text or "").splitlines():
        ln = line.strip()
        if not ln or len(ln) > 20:
            continue
        if _BRAND_LINE_RE.match(ln) and "mg" not in ln.lower():
            if _MISREAD_BRAND_RE.match(ln):
                continue
            return ln
    return ""


def extract_product_title(ocr_text: str) -> str:
    for line in (ocr_text or "").splitlines():
        ln = line.strip()
        if _PHOSPHATIDYL_RE.search(ln) and len(ln) < 120:
            return ln[:120]
    m = _PHOSPHATIDYL_RE.search(ocr_text or "")
    if m:
        return m.group(0)
    for line in (ocr_text or "").splitlines():
        ln = line.strip()
        if 4 <= len(ln) <= 80 and not re.search(r"\d+\s*mg", ln, re.I):
            if not detect_ecommerce_from_ocr(ln):
                return ln[:120]
    return ""


def extract_package_size(ocr_text: str) -> str:
    for line in (ocr_text or "").splitlines():
        m = _PACKAGE_RE.search(line)
        if m:
            return line.strip()[:120]
    m = _PACKAGE_RE.search(ocr_text or "")
    if m:
        return m.group(0)
    return ""


def is_single_ingredient_product(hints: List[str], rows: List[IngredientRowV1]) -> bool:
    if "single_ingredient_product" in hints:
        return True
    if len(rows) == 1 and rows[0].amount and rows[0].unit:
        if not has_authoritative_ingredient_panel(hints):
            return True
    return False


def assess_confidence(
    ledger: LabelLedgerV1,
    *,
    attachment_count: int,
) -> Tuple[ParseConfidence, List[str], List[str]]:
    """
    P-layer gates G1–G6 (stage3b-beta-vision-worker-spec.md §4).
    Returns (confidence, reject_reasons, warnings). G6 panel hint alone → warnings only.
    """
    reasons: List[str] = []
    warnings: List[str] = []
    hints = list(ledger.layout_hints or [])
    rows = ledger.ingredient_rows
    ocr_n = ledger.ocr_char_count
    single_ok = is_single_ingredient_product(hints, rows)
    per_image = ledger.layout_hints_per_image or []

    # G1
    if not rows:
        reasons.append("no_ingredient_rows")

    # G2
    if rows and not any(row_has_parseable_dose(r) for r in rows):
        reasons.append("no_parseable_dose")

    # G4
    channel = str(ledger.perception_channel or "ocr_only")
    if channel == "ocr_only" and ocr_n < _MIN_OCR and not has_authoritative_ingredient_panel(hints):
        reasons.append("ocr_too_short")

    # G5
    for row in rows:
        nm = (row.name or "").strip()
        if _GARBAGE_INGREDIENT_NAME_RE.match(nm):
            reasons.append("polluted_ingredient_rows")
            break

    ocr_blob = ledger.ledger_markdown or ""
    if _PHOSPHATIDYL_TOKEN_RE.search(ocr_blob) and any(
        re.fullmatch(r"serine\s*-?", (r.name or "").strip(), flags=re.I) for r in rows
    ):
        reasons.append("polluted_ingredient_rows")

    # G6 — panel hint missing alone must not block high (Spec v0.3 §4.1)
    panel_hint_missing = False
    if attachment_count >= 2:
        any_auth = False
        if per_image:
            any_auth = any(
                has_authoritative_ingredient_panel(entry.get("hints") or [])
                for entry in per_image
                if isinstance(entry, dict)
            )
        if not any_auth:
            any_auth = has_authoritative_ingredient_panel(hints)
        if not any_auth:
            panel_hint_missing = True

    # merge_incomplete (G3 style: multi-image but too few rows)
    if attachment_count >= 2 and len(rows) < 2 and not single_ok:
        reasons.append("merge_incomplete")

    if detect_ecommerce_from_ocr(ledger.ledger_markdown) and not rows:
        reasons.append("ecommerce_only_no_dose")

    if has_authoritative_ingredient_panel(hints) and not rows:
        reasons.append("facts_panel_unreadable")

    if attachment_count == 1:
        if detect_ecommerce_from_ocr(ocr_blob) and not has_authoritative_ingredient_panel(hints):
            if len(rows) <= 1 and not single_ok:
                panel_hint_missing = True

    has_parseable = bool(rows) and any(row_has_parseable_dose(r) for r in rows)
    if panel_hint_missing:
        if ("no_ingredient_rows" in reasons) or ("no_parseable_dose" in reasons) or not has_parseable:
            if "missing_authoritative_panel" not in reasons:
                reasons.append("missing_authoritative_panel")
        else:
            warnings.append("layout_panel_hint_missing")

    if ledger.brand and _MISREAD_BRAND_RE.search(ledger.brand):
        reasons.append("brand_ocr_uncertain")

    if any(t.get("rule") == "ingredient_conflict" for t in (ledger.merge_trace or [])):
        reasons.append("ingredient_conflict")

    conf: ParseConfidence = "low" if reasons else "high"
    return conf, list(dict.fromkeys(reasons)), list(dict.fromkeys(warnings))


def build_ledger_from_parsed_part(
    parsed: Dict[str, Any],
    *,
    source_image_index: int = 0,
    combined_ocr: str = "",
) -> LabelLedgerV1:
    ocr = str(parsed.get("ocr_text") or "").strip()
    legacy_rows = parsed.get("ingredient_rows") or []
    rows = rows_from_legacy(legacy_rows, source_image_index=source_image_index)
    if not rows and ocr:
        rows = rows_from_ocr_text(ocr, source_image_index=source_image_index)

    hints = layout_hints_from_ocr(ocr)
    brand = extract_brand_from_ocr(ocr, combined_ocr=combined_ocr)
    if not brand:
        brand = str(parsed.get("brand") or "").strip()

    product = extract_product_title(ocr) or str(parsed.get("product_title") or "").strip()
    package = extract_package_size(ocr) or str(parsed.get("package_size") or "").strip()

    block, _ = build_label_ledger_block({**parsed, "ocr_text": ocr, "ingredient_rows": legacy_rows})

    channel = str(parsed.get("perception_channel") or "ocr_only")
    if channel not in ("ocr_only", "ocr_plus_vision_validate", "vision_structured"):
        channel = "ocr_only"

    return LabelLedgerV1(
        attachment_count=1,
        brand=brand,
        product_title=product,
        package_size=package,
        layout_hints=hints,
        layout_hints_per_image=[{"index": source_image_index, "hints": hints}],
        ingredient_rows=rows,
        perception_channel=channel,  # type: ignore[arg-type]
        ocr_char_count=len(ocr),
        ledger_markdown=block,
    )


def merge_parts_to_ledger(
    parts: List[Dict[str, Any]],
    *,
    perception_channel: PerceptionChannel = "ocr_only",
    client_parse_reuse: bool = False,
) -> LabelLedgerV1:
    combined_ocr = "\n\n---\n\n".join(
        (str(p.get("ocr_text") or "").strip()) for p in parts if (p.get("ocr_text") or "").strip()
    )
    merge_trace: List[Dict[str, Any]] = []
    layout_hints_per_image: List[Dict[str, Any]] = []
    part_legs: List[LabelLedgerV1] = []

    for idx, part in enumerate(parts):
        leg = build_ledger_from_parsed_part(
            part,
            source_image_index=idx,
            combined_ocr=combined_ocr,
        )
        part_legs.append(leg)
        layout_hints_per_image.append({"index": idx, "hints": list(leg.layout_hints)})

    brand_candidates: List[Tuple[str, float, int]] = []
    product_candidates: List[Tuple[str, float, int]] = []
    package_candidates: List[Tuple[str, float, int]] = []
    row_batches: List[Tuple[List[IngredientRowV1], float, int, List[str]]] = []
    all_hints: List[str] = []

    for idx, leg in enumerate(part_legs):
        hints = list(leg.layout_hints)
        for h in hints:
            if h not in all_hints:
                all_hints.append(h)
        bw = brand_weight_for_hints(hints)
        iw = ingredient_weight_for_hints(hints)
        brand_candidates.append((leg.brand, bw, idx))
        product_candidates.append((leg.product_title, bw, idx))
        package_candidates.append((leg.package_size, bw, idx))
        row_batches.append((list(leg.ingredient_rows), iw, idx, hints))

    brand, brand_trace = pick_string_by_weight(brand_candidates)
    for t in brand_trace:
        merge_trace.append({"field": "brand", **t})

    product, product_trace = pick_string_by_weight(product_candidates)
    for t in product_trace:
        merge_trace.append({"field": "product_title", **t})

    package, package_trace = pick_string_by_weight(package_candidates)
    for t in package_trace:
        merge_trace.append({"field": "package_size", **t})

    if not brand:
        brand = extract_brand_from_ocr(combined_ocr)
    if not product:
        product = extract_product_title(combined_ocr)
    if not package:
        package = extract_package_size(combined_ocr)

    all_rows, row_trace = merge_ingredient_rows_weighted(row_batches)
    merge_trace.extend(row_trace)

    merged_stub: Dict[str, Any] = {
        "ocr_text": combined_ocr,
        "ingredient_rows": [
            {"name": r.name, "amount": r.amount_display, "source_line": r.source_line}
            for r in all_rows
        ],
    }
    block, _ = build_label_ledger_block(merged_stub, ocr_text=combined_ocr)

    per_image: List[str] = []
    for idx, part in enumerate(parts, start=1):
        fn = str(part.get("source_filename") or f"图{idx}")
        blk, _ = build_label_ledger_block(part, ocr_text=str(part.get("ocr_text") or ""))
        if blk:
            per_image.append(f"【图 {idx} · {fn}】\n{blk}")
    if len(per_image) > 1:
        combined_block = "\n\n".join(per_image)
        if len(combined_block) <= int(os.environ.get("PHA_LABEL_LEDGER_MAX_CHARS", "2200")):
            block = combined_block

    ledger = LabelLedgerV1(
        attachment_count=len(parts),
        brand=brand,
        product_title=product,
        package_size=package,
        layout_hints=all_hints,
        layout_hints_per_image=layout_hints_per_image,
        ingredient_rows=all_rows,
        perception_channel=perception_channel,
        ocr_char_count=len(combined_ocr),
        merge_trace=merge_trace,
        ledger_markdown=block,
    )
    conf, reasons, warns = assess_confidence(ledger, attachment_count=len(parts))
    ledger.parse_confidence = conf
    ledger.reject_reasons = reasons
    ledger.warnings = warns

    if conf == "low" and block:
        ledger.ledger_markdown = (
            block
            + "\n\n【解析置信度】偏低：定账可能不完整；回答时不得编造未出现的剂量，"
            "须建议用户补拍成分表或核对品牌。"
        )

    _ = client_parse_reuse
    return ledger


def finalize_parsed_payload(
    parsed: Dict[str, Any],
    *,
    attachment_count: int = 1,
    parts: Optional[List[Dict[str, Any]]] = None,
    perception_channel: PerceptionChannel = "ocr_only",
    client_parse_reuse: bool = False,
) -> Dict[str, Any]:
    """Upgrade enrich_parsed output to LabelLedgerV1 contract."""
    if parts and len(parts) > 1:
        ledger = merge_parts_to_ledger(
            parts,
            perception_channel=perception_channel,
            client_parse_reuse=client_parse_reuse,
        )
    else:
        single = parts[0] if parts else parsed
        leg = build_ledger_from_parsed_part(single, combined_ocr=str(single.get("ocr_text") or ""))
        leg.attachment_count = max(1, attachment_count)
        conf, reasons, warns = assess_confidence(leg, attachment_count=leg.attachment_count)
        leg.parse_confidence = conf
        leg.reject_reasons = reasons
        leg.warnings = warns
        if conf == "low":
            leg.ledger_markdown = (
                (leg.ledger_markdown or "")
                + "\n\n【解析置信度】偏低：定账可能不完整；回答时不得编造未出现的剂量。"
            )
        ledger = leg

    out = dict(parsed)
    out.update(ledger.to_parsed_dict())
    out["attachment_count"] = ledger.attachment_count
    out["client_parse_reuse"] = client_parse_reuse
    out["label_ledger"] = ledger.ledger_markdown
    out["vision_summary"] = ledger.ledger_markdown
    out["parse_confidence"] = ledger.parse_confidence
    out["reject_reasons"] = list(ledger.reject_reasons)
    out["warnings"] = list(ledger.warnings)
    out["document_type"] = (
        ledger.layout_hints[0] if ledger.layout_hints else out.get("document_type", "supplement_label")
    )
    return out


__all__ = [
    "IngredientRowV1",
    "LabelLedgerV1",
    "assess_confidence",
    "build_ledger_from_parsed_part",
    "finalize_parsed_payload",
    "merge_parts_to_ledger",
    "row_has_parseable_dose",
]
