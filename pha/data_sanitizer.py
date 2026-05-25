"""Medical metric value/name/unit sanitization — blood counts with 10^n/L notation."""

from __future__ import annotations

import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# e.g. 0.04×10^9/L, 0.04x10^9/L, 0.04*10^9/L, 0.04 10^9/L
_SCIENTIFIC_IN_TEXT = re.compile(
    r"([\d.]+)\s*[×xX*]?\s*10\s*[\^⁰°]?\s*(-?\d+)\s*(?:/\s*([A-Za-zμµ]+))?",
    re.IGNORECASE,
)

# Trailing debris like "×10^9/L" left in metric labels after bad OCR
_SCIENTIFIC_DEBRIS_IN_NAME = re.compile(
    r"[\d.]+\s*[×xX*]?\s*10\s*[\^⁰°]?\s*\d+.*$",
    re.IGNORECASE,
)

# Absolute differential count codes (blood routine)
_BLOOD_ABS_CODES: dict[str, tuple[str, ...]] = {
    "BASO#": ("BASO#", "BASO", "嗜碱性粒细胞", "嗜碱细胞", "嗜碱性粒细胞计数"),
    "EOS#": ("EOS#", "EOS", "嗜酸性粒细胞", "嗜酸细胞", "嗜酸性粒细胞计数"),
    "NEUT#": ("NEUT#", "NEUT", "中性粒细胞", "中性粒细胞计数"),
    "MONO#": ("MONO#", "MONO", "单核细胞", "单核细胞计数"),
    "LYMPH#": ("LYMPH#", "LYMPH", "淋巴细胞", "淋巴细胞计数"),
    "RBC#": ("RBC#",),
    "WBC#": ("WBC#",),
    "PLT#": ("PLT#", "血小板计数"),
}

_BLOOD_ABS_ALIAS_INDEX: dict[str, str] = {}
for code, aliases in _BLOOD_ABS_CODES.items():
    for a in aliases:
        key = re.sub(r"\s+", "", a.upper())
        _BLOOD_ABS_ALIAS_INDEX[key] = code


def _try_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_scientific_mantissa(text: str) -> Optional[Tuple[float, int, str]]:
    """
    Parse ``0.04×10^9/L`` → mantissa ``0.04``, exponent ``9``, unit suffix ``L``.

    Stored convention: ``value=0.04``, ``unit=10^9/L``.
    """
    blob = (text or "").strip()
    if not blob:
        return None
    m = _SCIENTIFIC_IN_TEXT.search(blob)
    if not m:
        return None
    coef = _try_float(m.group(1))
    if coef is None:
        return None
    try:
        exp = int(m.group(2))
    except ValueError:
        return None
    suffix = (m.group(3) or "L").strip() or "L"
    return coef, exp, suffix


def normalize_scientific_unit(exponent: int, suffix: str = "L") -> str:
    suf = (suffix or "L").strip().lstrip("/")
    return f"10^{exponent}/{suf}"


def sanitize_metric_name(raw: str) -> str:
    """Strip scientific notation pollution; map blood absolute counts to canonical codes."""
    original = (raw or "").strip()
    if not original:
        return ""

    cleaned = _SCIENTIFIC_DEBRIS_IN_NAME.sub("", original).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"^[\d.]+\s*", "", cleaned).strip()

    key = re.sub(r"\s+", "", cleaned.upper())
    key = key.replace("＃", "#").replace("№", "#")

    if key in _BLOOD_ABS_ALIAS_INDEX:
        return _BLOOD_ABS_ALIAS_INDEX[key]

    for alias, code in _BLOOD_ABS_ALIAS_INDEX.items():
        if len(alias) >= 3 and alias in key:
            return code

    # Preserve codes like BASO# even if mixed with Chinese
    m_hash = re.match(r"^([A-Z]{2,6}#?)", key)
    if m_hash:
        token = m_hash.group(1)
        if not token.endswith("#") and token in ("BASO", "EOS", "NEUT", "MONO", "LYMPH"):
            return token + "#"
        return token

    return cleaned or original


def sanitize_unit(unit: str, *, exponent_hint: Optional[int] = None, suffix: str = "L") -> str:
    u = (unit or "").strip()
    if exponent_hint is not None:
        return normalize_scientific_unit(exponent_hint, suffix)
    if re.search(r"10\s*[\^⁰°]?\s*9", u, re.I) or u in ("9/L", "9 /L", "/L", "L", "l"):
        return "10^9/L"
    if re.search(r"10\s*[\^⁰°]?\s*12", u, re.I):
        return "10^12/L"
    if re.search(r"10\s*[\^⁰°]?\s*6", u, re.I):
        return "10^6/L"
    return u


def sanitize_metric_fields(
    raw_name: str,
    value: Optional[float],
    unit: str,
    *,
    reference_range: str = "",
) -> Tuple[str, Optional[float], str]:
    """
    Full row sanitization before catalog resolve / SQLite upsert.

    Recovers mantissa from combined name+unit when value was wrongly parsed as ``9``.
    """
    name_blob = raw_name or ""
    unit_blob = unit or ""
    combined = f"{name_blob} {unit_blob} {reference_range or ''}"

    sci = parse_scientific_mantissa(combined)
    clean_name = sanitize_metric_name(name_blob)

    if sci is not None:
        coef, exp, suffix = sci
        fixed_unit = normalize_scientific_unit(exp, suffix)
        return clean_name, coef, fixed_unit

    # Wrong parse: value=9 with broken unit "/L" or "9/L" while name had 10^9
    if value is not None and abs(value - 9.0) < 1e-6 and re.search(
        r"10\s*[\^⁰°]?\s*9",
        combined,
        re.I,
    ):
        m = re.search(r"([\d.]+)\s*[×xX*]?\s*10", combined, re.I)
        if m:
            coef = _try_float(m.group(1))
            if coef is not None:
                return clean_name, coef, "10^9/L"

    if unit_blob and re.fullmatch(r"9\s*/?\s*L", unit_blob.strip(), re.I):
        if parse_scientific_mantissa(name_blob):
            sci2 = parse_scientific_mantissa(name_blob)
            if sci2:
                return clean_name, sci2[0], normalize_scientific_unit(sci2[1], sci2[2])

    # OCR truncated exponent: ``BASO# 0.04×10`` + value wrongly parsed as ``9``
    if value is not None and abs(value - 9.0) < 1e-6:
        m_part = re.search(
            r"([\d.]+)\s*[×xX*]?\s*10(?:\s*[\^⁰°]?\s*9)?",
            combined,
            re.I,
        )
        if m_part:
            coef = _try_float(m_part.group(1))
            if coef is not None:
                return clean_name, coef, "10^9/L"

    fixed_unit = sanitize_unit(unit_blob)
    return clean_name, value, fixed_unit


def parse_numeric_value(raw: str) -> Optional[float]:
    """Parse plain or scientific numeric strings for event drawer / OCR."""
    s = (raw or "").strip().replace(",", "")
    if not s:
        return None
    sci = parse_scientific_mantissa(s)
    if sci is not None:
        return sci[0]
    try:
        return float(s)
    except ValueError:
        m = re.match(r"^([+-]?\d+(?:\.\d+)?)", s)
        if m:
            return _try_float(m.group(1))
    return None
