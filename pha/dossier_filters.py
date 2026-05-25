"""Drop polluted dossier / metric narrative lines before LLM or tool output (v2.1.5)."""

from __future__ import annotations

import re
from typing import Iterable, List

_DOSSIER_JUNK_SUBSTRINGS = (
    "中度症状",
    "评估者",
    "流水号",
    "作为乘客",
    "失眠是指",
    "仅供参考",
    "病人号",
    "体 检 号",
    "吸烟指数",
    "戒烟",
    "年龄:",
    "总审日期",
    "□",
    "机构:",
)
_ISO_DATE_IN_LINE = re.compile(r"\d{4}-\d{2}-\d{2}")


def is_dossier_junk_line(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return False
    if len(s) > 80:
        return True
    if any(tok in s for tok in _DOSSIER_JUNK_SUBSTRINGS):
        return True
    if "/" in s and not _ISO_DATE_IN_LINE.search(s):
        return True
    return False


def filter_line_list(lines: Iterable[str]) -> List[str]:
    return [line for line in lines if not is_dossier_junk_line(line)]


def filter_evidence_bundle_text(text: str) -> str:
    if not (text or "").strip():
        return ""
    return "\n".join(filter_line_list((text or "").splitlines()))
