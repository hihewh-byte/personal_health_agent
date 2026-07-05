"""Stage 3A.2.1 — User-visible reply polish (strip harness internal phrases)."""

from __future__ import annotations

import os
import re
from typing import List, Tuple

_STRIP_PHRASES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"【依据】\s*"), ""),
    (re.compile(r"\s*→\s*【推论】\s*"), "："),
    (re.compile(r"【推论】\s*"), ""),
    (re.compile(r"当前账本缺乏该项历史基线[，,]?\s*我们将基于单次数据进行静态解构[。.]?\s*"), ""),
    (re.compile(r"静态解构"), "说明"),
    (re.compile(r"###\s*纵向趋势对账\s*"), "### 与以往化验对比\n"),
    (re.compile(r"###\s*多指标横向联动\s*"), "### 相关指标\n"),
    (re.compile(r"###\s*硬核非药物干预与筛查建议\s*"), "### 建议\n"),
    (re.compile(r"Patient State", re.I), "健康记录"),
    (re.compile(r"Manifest", re.I), "指标清单"),
    # 去 PHA 内部用语，面向用户改为自然专业措辞。
    (re.compile(r"截图定账"), "本次截图"),
    (re.compile(r"定账延伸参考"), "延伸参考"),
    (re.compile(r"定账摘要"), "读数小结"),
    (re.compile(r"定账"), "记录"),
    (re.compile(r"数仓摘要"), "过去约 90 天的记录"),
    (re.compile(r"数仓"), "历史记录"),
    (re.compile(r"化验账本"), "化验记录"),
    (re.compile(r"账本"), "记录"),
]


def presentation_filter_mode() -> str:
    return (os.environ.get("PHA_PRESENTATION_FILTER", "strip") or "strip").strip().lower()


def polish_user_visible_reply(text: str) -> str:
    """Apply phrase substitutions for chat bubbles (mode ``strip`` only)."""
    mode = presentation_filter_mode()
    if mode == "off" or not (text or "").strip():
        return text or ""
    out = text
    if mode == "strip":
        for pat, repl in _STRIP_PHRASES:
            out = pat.sub(repl, out)
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


def polish_final_user_answer(text: str, *, profile: str = "") -> str:
    """Last-mile polish for all user-visible chat answers."""
    prof = (profile or "").strip()
    if "wearable" in prof:
        from pha.wearable_presentation import polish_wearable_user_visible_reply

        return polish_wearable_user_visible_reply(text or "")
    return polish_user_visible_reply(text or "")


__all__ = [
    "polish_user_visible_reply",
    "polish_final_user_answer",
    "presentation_filter_mode",
]
