"""Numerics Manifest + C-layer post-check — v2.2.6.2-min (Catalog Reduce 共享底座)."""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, TypedDict

from pha.date_range_parser import default_wearable_window
from pha.health_data import HealthDataResult, effective_query_reference_date, get_health_data
from pha.intent_gates import infer_wearable_metrics
from pha.medical_storage import sanitize_ldl_value

_MANIFEST_MAX_CHARS = int(os.environ.get("PHA_MANIFEST_MAX_CHARS", "600"))

# Known E2E hallucination anchors — always forbidden in model output.
_GLOBAL_FORBIDDEN_DATES: frozenset[str] = frozenset({"2026-04-30", "2025-01-13"})

_WEARABLE_MANIFEST_FORBIDDEN_FOOTER = (
    "FORBIDDEN_90D: sleep_deep_avg, sleep_rem_avg, deep_sleep_90d, rem_sleep_90d "
    "（数仓无睡眠分期历史均值；90 天对比见 WEARABLE_COMPARE_TABLE）"
)

_LIPID_SQL = """
SELECT report_date, metric_name, metric_code, name_zh, value, unit
FROM medical_reports
WHERE user_id = ?
  AND value IS NOT NULL
  AND (
    lower(coalesce(metric_name,'')) LIKE '%胆固醇%'
    OR lower(coalesce(metric_name,'')) LIKE '%ldl%'
    OR lower(coalesce(metric_name,'')) LIKE '%hdl%'
    OR lower(coalesce(metric_name,'')) LIKE '%甘油三酯%'
    OR lower(coalesce(metric_code,'')) IN ('ldl','hdl','tc','tg')
    OR lower(coalesce(name_zh,'')) LIKE '%胆固醇%'
    OR lower(coalesce(name_zh,'')) LIKE '%甘油三酯%'
  )
ORDER BY report_date ASC, metric_name
"""

_DATE_ISO_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
_DATE_CN_RE = re.compile(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日")
# 中文语境无词边界：用前后非数字锚定，避免 \b 失效
_DECIMAL_RE = re.compile(r"(?<!\d)(\d+\.\d{1,2})(?!\d)")
_DOSE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:g|mg|ml|mcg|μg|ug|fu|iu|粒|片|根|次|%)\b",
    re.I,
)

# --- Manifest Tier v1: bilingual disclosure sandbox (extend via LANG_DISCLOSURE_MAP only) ---
# Future: add LANG_DISCLOSURE_MAP entries (e.g. id="ja") + compile in _disclosure_patterns();
# do not scatter locale strings in audit_* call paths.


class _LangDisclosureSpec(TypedDict):
    id: str
    block_open_re: str
    block_full_re: str
    source_re: str
    verify_substrings: Tuple[str, ...]
    disclaimer_substrings: Tuple[str, ...]
    t0_forbidden_in_block_re: str


LANG_DISCLOSURE_MAP: Tuple[_LangDisclosureSpec, ...] = (
    {
        "id": "zh",
        "block_open_re": r"【参考标准[^】]*】",
        "block_full_re": (
            r"【参考标准[^】]*】.*?"
            r"[（(]来源[:：][^）)]{4,}[，,][^）)]*?"
            r"(?:请自行查证|请自行核对)[^）)]*?[）)]"
        ),
        "source_re": r"来源[:：]\s*.{4,}",
        "verify_substrings": ("请自行查证", "请自行核对"),
        "disclaimer_substrings": ("非医疗建议", "不构成医疗建议", "不能替代医嘱"),
        "t0_forbidden_in_block_re": (
            r"您的|你的是|你的|化验日期|报告日期|检验报告|上次化验|个人化验"
        ),
    },
    {
        "id": "en",
        "block_open_re": r"\[(?:Reference Standard|Ref\.?\s*Standard)[^\]]*\]",
        "block_full_re": (
            r"\[(?:Reference Standard|Ref\.?\s*Standard)[^\]]*\].*?"
            r"[\(（]\s*source\s*[:：]\s*[^）)]{4,}\s*[,，]\s*"
            r"(?:verify by yourself|please verify independently|verify independently)"
            r"[^）)]*?[）)]"
        ),
        "source_re": r"source\s*[:：]\s*.{4,}",
        "verify_substrings": (
            "verify by yourself",
            "please verify independently",
            "verify independently",
        ),
        "disclaimer_substrings": (
            "not medical advice",
            "not a substitute for medical advice",
        ),
        "t0_forbidden_in_block_re": (
            r"\byour\b|\byours\b|your lab|your report|report date|test date|"
            r"personal lab|my lab results"
        ),
    },
)

# T0 claim cues — evaluated on masked text; T0 always wins over T1 (see audit priority).
LANG_T0_CLAIM_MAP: Dict[str, Tuple[str, ...]] = {
    "owner_cues": (
        "您的",
        "你的",
        "你的是",
        "your",
        "yours",
        "your lab",
        "your ldl",
    ),
    "report_cues": (
        "报告",
        "化验",
        "检验",
        "report",
        "lab result",
        "test result",
    ),
    "metric_cues": (
        "LDL",
        "HDL",
        "TC",
        "TG",
        "血脂",
        "胆固醇",
        "HRV",
        "spo2",
        "blood oxygen",
    ),
    "lab_citation_cues": (
        "报告",
        "化验",
        "检验",
        "LDL",
        "HDL",
        "TC",
        "TG",
        "血脂",
        "胆固醇",
        "mmol",
        "mg/dL",
        "report",
        "lab",
    ),
}

_DISCLOSURE_COMPILED: Optional[List[Dict[str, Any]]] = None

_LAB_RANGE_MIN = 0.5
_LAB_RANGE_MAX = 15.0

_METRIC_CANON: List[tuple[str, str]] = [
    ("tc", "TC"),
    ("总胆固醇", "TC"),
    ("ldl", "LDL"),
    ("低密度", "LDL"),
    ("hdl", "HDL"),
    ("高密度", "HDL"),
    ("tg", "TG"),
    ("甘油三酯", "TG"),
]


def _db_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "pha_storage.db"


def _canonical_lipid_metric(name: str, code: str, zh: str) -> Optional[str]:
    blob = f"{name}|{code}|{zh}".lower()
    for needle, canon in _METRIC_CANON:
        if needle in blob:
            return canon
    return None


def _fmt_value(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _value_variants(v: float) -> Set[str]:
    out = {_fmt_value(v), f"{v:.1f}", f"{v:.2f}"}
    if abs(v - round(v)) < 1e-6:
        out.add(str(int(round(v))))
    return {x for x in out if x}


@dataclass(frozen=True)
class ManifestEntry:
    domain: str
    metric: str
    value: float
    unit: str
    anchor: str
    source: str

    def kv_line(self) -> str:
        return f"{self.domain}|{self.anchor}|{self.metric}|{_fmt_value(self.value)}|{self.unit or '-'}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "anchor": self.anchor,
            "source": self.source,
        }


@dataclass
class NumericsManifest:
    profile: str
    user_id: str
    entries: List[ManifestEntry] = field(default_factory=list)
    reference_date: str = ""
    forbidden_dates: Set[str] = field(default_factory=set)

    @property
    def allowed_dates(self) -> Set[str]:
        dates: Set[str] = set()
        for e in self.entries:
            if e.domain == "lipid" and len(e.anchor) == 10:
                dates.add(e.anchor)
        return dates

    @property
    def allowed_values(self) -> Set[str]:
        vals: Set[str] = set()
        for e in self.entries:
            vals.update(_value_variants(e.value))
        return vals

    @property
    def lipid_values(self) -> Set[str]:
        vals: Set[str] = set()
        for e in self.entries:
            if e.domain == "lipid":
                vals.update(_value_variants(e.value))
        return vals

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile,
            "user_id": self.user_id,
            "reference_date": self.reference_date,
            "entry_count": len(self.entries),
            "allowed_dates": sorted(self.allowed_dates),
            "entries": [e.to_dict() for e in self.entries],
            "forbidden_dates": sorted(self.forbidden_dates),
        }


def _query_lipid_rows(user_id: str) -> List[Dict[str, Any]]:
    db = _db_path()
    if not db.exists():
        return []
    uid = (user_id or "default").strip() or "default"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(_LIPID_SQL, (uid,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _lipid_entries(user_id: str) -> List[ManifestEntry]:
    rows = _query_lipid_rows(user_id)
    out: List[ManifestEntry] = []
    seen: Set[tuple[str, str, str]] = set()
    for r in rows:
        canon = _canonical_lipid_metric(
            str(r.get("metric_name") or ""),
            str(r.get("metric_code") or ""),
            str(r.get("name_zh") or ""),
        )
        if not canon:
            continue
        raw_val = r.get("value")
        try:
            val = float(raw_val)
        except (TypeError, ValueError):
            continue
        if canon == "LDL":
            sv = sanitize_ldl_value(val)
            if sv is None:
                continue
            val = sv
        anchor = str(r.get("report_date") or "")[:10]
        if not anchor or len(anchor) != 10:
            continue
        key = (anchor, canon, _fmt_value(val))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            ManifestEntry(
                domain="lipid",
                metric=canon,
                value=val,
                unit=str(r.get("unit") or "mmol/L").strip() or "mmol/L",
                anchor=anchor,
                source="sqlite.medical_reports",
            ),
        )
    return out


def _wearable_entries(
    user_id: str,
    user_message: str,
    *,
    wearable_result: Optional[HealthDataResult] = None,
) -> List[ManifestEntry]:
    uid = (user_id or "default").strip() or "default"
    ref = effective_query_reference_date()
    window = default_wearable_window(user_message, reference=ref)
    anchor = f"{window.start.isoformat()}~{window.end.isoformat()}"

    if wearable_result is None:
        metrics = infer_wearable_metrics(user_message) or ["hrv", "activity_kcal"]
        wearable_result = get_health_data(
            uid,
            window.start,
            window.end,
            metrics,
            user_message=user_message,
        )

    out: List[ManifestEntry] = []
    label_map = {
        "hrv": ("HRV均值", "ms"),
        "activity_kcal": ("活动消耗日均", "kcal"),
        "steps": ("步数均值", "步"),
        "sleep": ("睡眠均值", "h"),
        "rhr": ("静息心率均值", "bpm"),
        "spo2": ("血氧均值", "%"),
        "respiratory_rate": ("呼吸率均值", "breaths/min"),
        "vo2max": ("VO2max均值", "mL/kg/min"),
        "wrist_temp": ("手腕体温均值", "°C"),
    }
    for key, summary in (wearable_result.summaries or {}).items():
        avg = summary.average
        if avg is None:
            continue
        metric_key = str(key).strip().lower()
        label, unit = label_map.get(metric_key, (metric_key, summary.unit or ""))
        out.append(
            ManifestEntry(
                domain="wearable",
                metric=label,
                value=round(float(avg), 2),
                unit=unit or str(summary.unit or ""),
                anchor=anchor,
                source="wearable.summary",
            ),
        )
    return out


def build_numerics_manifest(
    user_id: str,
    *,
    profile: str,
    user_message: str = "",
    wearable_result: Optional[HealthDataResult] = None,
    include_lipid: bool = True,
    include_wearable: bool = True,
) -> NumericsManifest:
    """Build machine-verifiable numerics whitelist for the current turn."""
    ref = effective_query_reference_date()
    forbidden = set(_GLOBAL_FORBIDDEN_DATES)
    entries: List[ManifestEntry] = []

    if include_lipid and profile in ("combined_review", "lab_cross_year", "lifestyle"):
        entries.extend(_lipid_entries(user_id))

    if include_wearable and profile in (
        "combined_review",
        "wearable_only",
        "wearable_screenshot_review",
    ):
        entries.extend(
            _wearable_entries(user_id, user_message, wearable_result=wearable_result),
        )

    return NumericsManifest(
        profile=profile,
        user_id=(user_id or "default").strip() or "default",
        entries=entries,
        reference_date=ref.isoformat(),
        forbidden_dates=forbidden,
    )


def format_manifest_tier0_block(
    manifest: NumericsManifest,
    *,
    max_chars: Optional[int] = None,
    profile: str = "",
) -> str:
    cap = max_chars if max_chars is not None else _MANIFEST_MAX_CHARS
    if not manifest.entries:
        empty = (
            "【Numerics Manifest · T0 · 机器白名单】\n"
            "Numerics Manifest (T0): no verifiable lipid/wearable values in DB this turn.\n"
            "（本轮库内无血脂/穿戴可校验数值；禁止编造化验或 HRV/千卡数字。）\n"
            "T1 guide values: use 【参考标准】 or [Reference Standard] disclosure; not whitelisted here."
        )
        if (profile or manifest.profile or "").strip() == "wearable_screenshot_review":
            empty = f"{empty}\n{_WEARABLE_MANIFEST_FORBIDDEN_FOOTER}"
        return empty
    header = (
        "【T0 · 您的个人化验/穿戴实测值 · Personal lab/wearable values】\n"
        "Numerics Manifest (T0): reply citations must match KV below.\n"
        "格式 / format: domain|anchor|metric|value|unit\n"
        "T1 指南/理想线: 【参考标准】…（来源：…，请自行查证，非医疗建议） or "
        "[Reference Standard] … (source: …, verify by yourself, not medical advice).\n"
        "T0 主张优先于 T1：个人数据仅可引用下列 KV；参考值不得伪装成您的化验结果。"
    )
    lines = [header.strip()]
    for e in manifest.entries:
        lines.append(e.kv_line())
    body = "\n".join(lines)
    if len(body) <= cap:
        if (profile or manifest.profile or "").strip() == "wearable_screenshot_review":
            body = f"{body}\n{_WEARABLE_MANIFEST_FORBIDDEN_FOOTER}"
        return body
    trimmed = [header.strip()]
    for e in manifest.entries:
        line = e.kv_line()
        candidate = "\n".join(trimmed + [line])
        if len(candidate) > cap - 20:
            break
        trimmed.append(line)
    trimmed.append("…（Manifest 已按 Tier0 上限截断，仍以已列 KV 为唯一合法数字源）")
    body = "\n".join(trimmed)[:cap]
    if (profile or manifest.profile or "").strip() == "wearable_screenshot_review":
        body = f"{body}\n{_WEARABLE_MANIFEST_FORBIDDEN_FOOTER}"
    return body


def _normalize_cn_date(y: str, m: str, d: str) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _extract_normalized_dates(text: str) -> List[str]:
    """Extract ISO + 中文日期并统一为 YYYY-MM-DD。"""
    found: List[str] = []
    for iso in _DATE_ISO_RE.findall(text or ""):
        found.append(iso)
    for y, m, d in _DATE_CN_RE.findall(text or ""):
        found.append(_normalize_cn_date(y, m, d))
    return found


def _extract_decimal_tokens(text: str) -> List[str]:
    return _DECIMAL_RE.findall(text or "")


def _values_cited_in_text(text: str, value_set: Set[str]) -> List[str]:
    """子串匹配白名单数值（适配「日的4.05」等无空格中文语境）。"""
    cited: List[str] = []
    for v in sorted(value_set, key=len, reverse=True):
        if v and v in text:
            cited.append(v)
    return cited


def _in_dose_context(text: str, token: str) -> bool:
    for m in _DOSE_RE.finditer(text):
        if token in m.group(0):
            return True
    return False


def _looks_like_lab_citation(text: str, date_str: str) -> bool:
    idx = text.find(date_str)
    if idx < 0:
        for y, m, d in _DATE_CN_RE.findall(text):
            if _normalize_cn_date(y, m, d) == date_str:
                cn = f"{y}年{int(m)}月{int(d)}日"
                idx = text.find(cn)
                if idx < 0:
                    cn2 = f"{y}年{m}月{d}日"
                    idx = text.find(cn2)
                break
    if idx < 0:
        return False
    window = text[max(0, idx - 40) : idx + len(date_str) + 40]
    cues = LANG_T0_CLAIM_MAP["lab_citation_cues"]
    return any(c in window for c in cues)


def _disclosure_patterns() -> List[Dict[str, Any]]:
    global _DISCLOSURE_COMPILED
    if _DISCLOSURE_COMPILED is not None:
        return _DISCLOSURE_COMPILED
    compiled: List[Dict[str, Any]] = []
    flags = re.I | re.S
    for spec in LANG_DISCLOSURE_MAP:
        compiled.append(
            {
                "id": spec["id"],
                "block_open": re.compile(spec["block_open_re"], flags),
                "block_full": re.compile(spec["block_full_re"], flags),
                "source": re.compile(spec["source_re"], flags),
                "t0_forbidden": re.compile(spec["t0_forbidden_in_block_re"], flags),
                "verify": spec["verify_substrings"],
                "disclaimer": spec["disclaimer_substrings"],
            },
        )
    _DISCLOSURE_COMPILED = compiled
    return compiled


def _merge_intervals(intervals: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    if not intervals:
        return []
    sorted_iv = sorted(intervals)
    merged: List[Tuple[int, int]] = [sorted_iv[0]]
    for start, end in sorted_iv[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def extract_disclosure_blocks(text: str) -> List[Tuple[int, int, str, str]]:
    """Return [(start, end, block_text, lang_id), ...] non-overlapping."""
    raw = text or ""
    found: List[Tuple[int, int, str, str]] = []
    for pat in _disclosure_patterns():
        for m in pat["block_full"].finditer(raw):
            found.append((m.start(), m.end(), m.group(0), pat["id"]))
        for m in pat["block_open"].finditer(raw):
            start = m.start()
            if any(start >= s and start < e for s, e, _, _ in found):
                continue
            end_line = raw.find("\n", start)
            if end_line < 0:
                end_line = len(raw)
            close_cn = raw.find("）", start, min(len(raw), start + 500))
            close_en = raw.find(")", start, min(len(raw), start + 500))
            end = end_line
            for close in (close_cn, close_en):
                if close >= start:
                    end = max(end, close + 1)
            segment = raw[start:end]
            if len(segment) >= 8:
                found.append((start, end, segment, pat["id"]))
    if not found:
        return []
    found.sort(key=lambda x: x[0])
    merged = _merge_intervals([(s, e) for s, e, _, _ in found])
    out: List[Tuple[int, int, str, str]] = []
    for ms, me in merged:
        block_text = raw[ms:me]
        lang_id = "zh"
        for pat in _disclosure_patterns():
            if pat["block_open"].search(block_text):
                lang_id = pat["id"]
                break
        out.append((ms, me, block_text, lang_id))
    return out


def mask_disclosure_blocks(text: str, blocks: Sequence[Tuple[int, int, str, str]]) -> str:
    if not blocks:
        return text or ""
    chars = list(text or "")
    for start, end, _, _ in blocks:
        for i in range(max(0, start), min(len(chars), end)):
            chars[i] = " "
    return "".join(chars)


def _disclosure_spec_for_lang(lang_id: str) -> Dict[str, Any]:
    for pat in _disclosure_patterns():
        if pat["id"] == lang_id:
            return pat
    return _disclosure_patterns()[0]


def audit_disclosure_block(
    block: str,
    lang_id: str,
    *,
    m4_mode: str,
) -> Tuple[List[str], List[str]]:
    violations: List[str] = []
    warnings: List[str] = []
    pat = _disclosure_spec_for_lang(lang_id)
    if pat["t0_forbidden"].search(block):
        violations.append("t0_forgery_in_t1_block")
        return violations, warnings
    has_open = bool(pat["block_open"].search(block))
    has_source = bool(pat["source"].search(block))
    has_verify = any(v in block for v in pat["verify"])
    has_m4 = any(d in block.lower() if lang_id == "en" else d in block for d in pat["disclaimer"])
    if not (has_open and has_source and has_verify):
        for token in set(_extract_decimal_tokens(block)):
            violations.append(f"t1_disclosure_incomplete:{token}")
        if not violations:
            violations.append("t1_disclosure_incomplete")
        return violations, warnings
    if not has_m4:
        if m4_mode == "strict":
            for token in set(_extract_decimal_tokens(block)):
                violations.append(f"t1_disclosure_incomplete:{token}")
        elif m4_mode == "warn":
            for token in set(_extract_decimal_tokens(block)):
                warnings.append(f"t1_missing_disclaimer:{token}")
    for token in set(_extract_decimal_tokens(block)):
        try:
            fv = float(token)
        except ValueError:
            continue
        if _LAB_RANGE_MIN <= fv <= _LAB_RANGE_MAX:
            warnings.append(f"t1_unverified_reference:{token}")
    return violations, warnings


def block_contains_t0_forgery(
    block: str,
    lang_id: str,
    manifest: NumericsManifest,
) -> bool:
    pat = _disclosure_spec_for_lang(lang_id)
    if pat["t0_forbidden"].search(block):
        return True
    for d in manifest.allowed_dates:
        if d in block:
            for token in _extract_decimal_tokens(block):
                if token not in manifest.allowed_values:
                    try:
                        fv = float(token)
                    except ValueError:
                        continue
                    if _LAB_RANGE_MIN <= fv <= _LAB_RANGE_MAX:
                        return True
    return False


def _token_in_t0_claim_context(text: str, token: str, *, window: int = 48) -> bool:
    if not text or not token:
        return False
    start = 0
    while True:
        idx = text.find(token, start)
        if idx < 0:
            return False
        win = text[max(0, idx - window) : idx + len(token) + window]
        win_lower = win.lower()
        owner = any(c in win for c in LANG_T0_CLAIM_MAP["owner_cues"]) or any(
            c in win_lower for c in LANG_T0_CLAIM_MAP["owner_cues"]
        )
        report = any(c in win for c in LANG_T0_CLAIM_MAP["report_cues"]) or any(
            c in win_lower for c in LANG_T0_CLAIM_MAP["report_cues"]
        )
        metric = any(c in win for c in LANG_T0_CLAIM_MAP["metric_cues"]) or any(
            c in win_lower for c in LANG_T0_CLAIM_MAP["metric_cues"]
        )
        if owner or report or metric:
            return True
        start = idx + 1


def numerics_audit_scope() -> str:
    raw = os.environ.get("PHA_NUMERICS_AUDIT_SCOPE", "t0_plus_disclosure").strip().lower()
    if raw in ("t0_strict", "strict", "legacy"):
        return "t0_strict"
    if raw in ("t0_plus_disclosure", "disclosure", "tier_v1"):
        return "t0_plus_disclosure"
    return "t0_plus_disclosure"


def numerics_t1_m4_mode() -> str:
    raw = os.environ.get("PHA_NUMERICS_T1_M4_MODE", "warn").strip().lower()
    if raw in ("strict", "warn", "off"):
        return raw
    return "warn"


def _audit_dates_and_citation(
    text: str,
    manifest: NumericsManifest,
    *,
    require_citation: bool,
) -> Tuple[List[str], List[str], List[str], List[str], List[str]]:
    """Shared date audit + citation extraction (strict & plus)."""
    violations: List[str] = []
    allowed_dates = manifest.allowed_dates
    allowed_values = manifest.allowed_values
    lipid_values = manifest.lipid_values
    normalized_dates = _extract_normalized_dates(text)

    cited_dates = sorted({d for d in normalized_dates if d in allowed_dates})
    cited_values = _values_cited_in_text(text, allowed_values)
    cited_lipid_values = _values_cited_in_text(text, lipid_values)

    forbidden = set(manifest.forbidden_dates)
    for d in normalized_dates:
        if d in forbidden:
            violations.append(f"forbidden_date:{d}")
    for d in forbidden:
        if d in text:
            violations.append(f"forbidden_date:{d}")

    ref = manifest.reference_date
    if ref:
        try:
            ref_d = date.fromisoformat(ref[:10])
            for d in set(normalized_dates):
                try:
                    dd = date.fromisoformat(d)
                except ValueError:
                    continue
                if dd > ref_d and d not in allowed_dates:
                    violations.append(f"future_date:{d}")
        except ValueError:
            pass

    for d in set(normalized_dates):
        if d in allowed_dates or d in forbidden:
            continue
        if _looks_like_lab_citation(text, d):
            violations.append(f"unauthorized_date:{d}")

    if require_citation and manifest.profile == "combined_review":
        if not cited_dates and not cited_lipid_values:
            violations.append("missing_ground_truth_citation")

    return violations, cited_dates, cited_values, cited_lipid_values, sorted(allowed_dates)


def _audit_response_numerics_strict(
    answer_text: str,
    manifest: NumericsManifest,
    *,
    require_citation: bool = False,
) -> Dict[str, Any]:
    """Legacy C-layer audit — unchanged behavior for t0_strict."""
    text = answer_text or ""
    warnings: List[str] = []
    allowed_values = manifest.allowed_values

    violations, cited_dates, cited_values, cited_lipid_values, allowed_dates = _audit_dates_and_citation(
        text,
        manifest,
        require_citation=require_citation,
    )

    for token in set(_extract_decimal_tokens(text)):
        if token in allowed_values:
            continue
        if _in_dose_context(text, token):
            continue
        try:
            fv = float(token)
        except ValueError:
            continue
        if _LAB_RANGE_MIN <= fv <= _LAB_RANGE_MAX:
            violations.append(f"unauthorized_value:{token}")

    passed = len(violations) == 0
    return {
        "passed": passed,
        "violations": sorted(set(violations)),
        "warnings": sorted(set(warnings)),
        "cited_dates": cited_dates,
        "cited_values": sorted(set(cited_values)),
        "cited_lipid_values": sorted(set(cited_lipid_values)),
        "manifest_entry_count": len(manifest.entries),
        "allowed_dates": allowed_dates,
        "audit_scope": "t0_strict",
    }


def _audit_response_numerics_t0_plus_disclosure(
    answer_text: str,
    manifest: NumericsManifest,
    *,
    require_citation: bool = False,
) -> Dict[str, Any]:
    """T0 strict on masked text; T1 format-only inside disclosure blocks."""
    text = answer_text or ""
    violations: List[str] = []
    warnings: List[str] = []
    allowed_values = manifest.allowed_values
    m4_mode = numerics_t1_m4_mode()

    blocks = extract_disclosure_blocks(text)
    masked = mask_disclosure_blocks(text, blocks)

    violations, cited_dates, cited_values, cited_lipid_values, allowed_dates = _audit_dates_and_citation(
        masked,
        manifest,
        require_citation=require_citation,
    )

    # T1 block audit (format + t0 forgery in shell)
    for _, _, block_text, lang_id in blocks:
        if block_contains_t0_forgery(block_text, lang_id, manifest):
            violations.append("t0_forgery_in_t1_block")
        b_v, b_w = audit_disclosure_block(block_text, lang_id, m4_mode=m4_mode)
        violations.extend(b_v)
        warnings.extend(b_w)

    # T0 priority: decimals outside disclosure blocks — strict on masked text
    for token in set(_extract_decimal_tokens(masked)):
        if token in allowed_values:
            continue
        if _in_dose_context(masked, token):
            continue
        try:
            fv = float(token)
        except ValueError:
            continue
        if _LAB_RANGE_MIN <= fv <= _LAB_RANGE_MAX:
            violations.append(f"unauthorized_value:{token}")

    passed = len(violations) == 0
    return {
        "passed": passed,
        "violations": sorted(set(violations)),
        "warnings": sorted(set(warnings)),
        "cited_dates": cited_dates,
        "cited_values": sorted(set(cited_values)),
        "cited_lipid_values": sorted(set(cited_lipid_values)),
        "manifest_entry_count": len(manifest.entries),
        "allowed_dates": allowed_dates,
        "audit_scope": "t0_plus_disclosure",
        "disclosure_block_count": len(blocks),
    }


def audit_response_numerics(
    answer_text: str,
    manifest: NumericsManifest,
    *,
    require_citation: bool = False,
) -> Dict[str, Any]:
    """C-layer post-check: response numerics/dates must stay within manifest."""
    if numerics_audit_scope() == "t0_plus_disclosure":
        return _audit_response_numerics_t0_plus_disclosure(
            answer_text,
            manifest,
            require_citation=require_citation,
        )
    return _audit_response_numerics_strict(
        answer_text,
        manifest,
        require_citation=require_citation,
    )


def numerics_audit_mode() -> str:
    return os.environ.get("PHA_NUMERICS_AUDIT", "warn").strip().lower()


def numerics_require_citation() -> bool:
    return os.environ.get("PHA_NUMERICS_REQUIRE_CITATION", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def apply_numerics_audit_to_answer(
    answer_text: str,
    audit: Dict[str, Any],
) -> str:
    """When block mode is on, replace answer with audit failure notice."""
    if audit.get("passed"):
        return answer_text
    vlist = ", ".join(audit.get("violations") or [])
    scope = audit.get("audit_scope") or numerics_audit_scope()
    t1_hint = ""
    if scope == "t0_plus_disclosure":
        t1_hint = (
            "\n· T1 参考标准: 【参考标准】…（来源：…，请自行查证，非医疗建议） or "
            "[Reference Standard] … (source: …, verify by yourself, not medical advice)."
        )
    return (
        "【PHA 数字合规审计未通过，本轮答复已拦截】\n"
        f"违规项：{vlist or 'unknown'}\n"
        "请仅引用 Numerics Manifest 白名单中的报告日/数值（T0）；"
        "若库内无该指标，应明确写「库内无该指标」。"
        f"{t1_hint}"
    )


__all__ = [
    "LANG_DISCLOSURE_MAP",
    "LANG_T0_CLAIM_MAP",
    "ManifestEntry",
    "NumericsManifest",
    "apply_numerics_audit_to_answer",
    "audit_disclosure_block",
    "audit_response_numerics",
    "build_numerics_manifest",
    "extract_disclosure_blocks",
    "format_manifest_tier0_block",
    "mask_disclosure_blocks",
    "numerics_audit_mode",
    "numerics_audit_scope",
    "numerics_require_citation",
    "numerics_t1_m4_mode",
]
