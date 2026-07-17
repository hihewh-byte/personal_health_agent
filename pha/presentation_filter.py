"""Stage 3A.2.1 — User-visible reply polish (strip harness internal phrases)."""

from __future__ import annotations

import os
import re
from typing import List, Tuple

from pha.response_language import normalize_response_locale

_STRIP_PHRASES_ZH: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"【依据】\s*"), ""),
    (re.compile(r"\s*→\s*【推论】\s*"), "："),
    (re.compile(r"【推论】\s*"), ""),
    (re.compile(r"当前账本缺乏该项历史基线[，,]?\s*我们将基于单次数据进行静态解构[。.]?\s*"), ""),
    (re.compile(r"静态解构"), "说明"),
    (re.compile(r"###\s*纵向趋势对账\s*"), "### 与以往化验对比\n"),
    (re.compile(r"###\s*多指标横向联动\s*"), "### 相关指标\n"),
    (re.compile(r"###\s*相关指标对照\s*"), "### 相关指标\n"),
    (
        re.compile(
            r"###\s*(?:Differential\s+Diagnos[ie]s|鉴别诊断|临床鉴别|Differential)\s*",
            re.I,
        ),
        "### 相关指标\n",
    ),
    (re.compile(r"###\s*硬核非药物干预与筛查建议\s*"), "### 建议\n"),
    (re.compile(r"###\s*生活方式建议与体检提示\s*"), "### 建议\n"),
    (re.compile(r"Patient State", re.I), "健康记录"),
    (re.compile(r"Manifest", re.I), "指标清单"),
    (re.compile(r"截图定账"), "本次截图"),
    (re.compile(r"定账延伸参考"), "延伸参考"),
    (re.compile(r"定账摘要"), "读数小结"),
    (re.compile(r"定账"), "记录"),
    (re.compile(r"数仓摘要"), "过去约 90 天的记录"),
    (re.compile(r"数仓"), "历史记录"),
    (re.compile(r"化验账本"), "化验记录"),
    (re.compile(r"账本"), "记录"),
]

_STRIP_PHRASES_EN: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"Patient State", re.I), "health records"),
    (re.compile(r"Manifest", re.I), "included metrics"),
    (re.compile(r"User Data Snapshot", re.I), "recent ~90-day records"),
    (re.compile(r"WEARABLE_COMPARE_TABLE", re.I), "wearable comparison table"),
    (re.compile(r"Tier0[^\n]*\n?", re.I), ""),
    (re.compile(r"metric_id", re.I), ""),
    (re.compile(r"NO_BASELINE", re.I), "no historical baseline"),
    (re.compile(r"verdict_note", re.I), ""),
    (re.compile(r"###\s*纵向趋势对账\s*"), "### Trend review\n"),
    (re.compile(r"###\s*多指标横向联动\s*"), "### Related markers\n"),
    (re.compile(r"###\s*相关指标对照\s*"), "### Related markers\n"),
    (
        re.compile(
            r"###\s*(?:Differential\s+Diagnos[ie]s|鉴别诊断|临床鉴别|Differential)\s*",
            re.I,
        ),
        "### Related markers\n",
    ),
    (re.compile(r"###\s*硬核非药物干预与筛查建议\s*"), "### Recommendations\n"),
    (re.compile(r"###\s*生活方式建议与体检提示\s*"), "### Recommendations\n"),
    (
        re.compile(
            r"当前(?:账本|记录)缺乏该项历史基线[，,]?\s*我们将基于单次数据进行静态解构[。.]?\s*",
        ),
        "No historical baseline for this metric is stored; interpreting the latest reading only. ",
    ),
    (
        re.compile(r"当前记录缺乏[^。.\n]{0,80}[。.]?\s*"),
        "",
    ),
    (re.compile(r"静态解构"), "interpretation"),
    (re.compile(r"健康记录"), "health records"),
    (re.compile(r"指标清单"), "included metrics"),
    (re.compile(r"历史记录"), "stored records"),
    (re.compile(r"低密度脂蛋白(?:胆固醇)?(?:\s*\(LDL(?:-C)?\))?"), "LDL cholesterol"),
    (re.compile(r"高密度脂蛋白(?:胆固醇)?"), "HDL cholesterol"),
    (re.compile(r"总胆固醇"), "total cholesterol"),
    (re.compile(r"甘油三酯"), "triglycerides"),
]


def _resolve_polish_locale(locale: str | None) -> str:
    return normalize_response_locale(locale) or "zh"


def presentation_filter_mode() -> str:
    return (os.environ.get("PHA_PRESENTATION_FILTER", "strip") or "strip").strip().lower()


def polish_user_visible_reply(text: str, *, locale: str | None = None) -> str:
    """Apply phrase substitutions for chat bubbles (mode ``strip`` only)."""
    mode = presentation_filter_mode()
    if mode == "off" or not (text or "").strip():
        return text or ""
    loc = _resolve_polish_locale(locale)
    phrases = _STRIP_PHRASES_EN if loc == "en" else _STRIP_PHRASES_ZH
    out = text
    if mode == "strip":
        for pat, repl in phrases:
            out = pat.sub(repl, out)
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


def polish_final_user_answer(
    text: str,
    *,
    profile: str = "",
    locale: str | None = None,
) -> str:
    """Last-mile polish for all user-visible chat answers."""
    prof = (profile or "").strip()
    if "wearable" in prof:
        from pha.wearable_presentation import polish_wearable_user_visible_reply

        return polish_wearable_user_visible_reply(text or "", locale=locale)
    return polish_user_visible_reply(text or "", locale=locale)


__all__ = [
    "polish_user_visible_reply",
    "polish_final_user_answer",
    "presentation_filter_mode",
]
