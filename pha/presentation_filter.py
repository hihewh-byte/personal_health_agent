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


__all__ = ["polish_user_visible_reply", "presentation_filter_mode"]
