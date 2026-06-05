"""User-visible polish for wearable_screenshot_review replies."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from pha.presentation_filter import polish_user_visible_reply

_METRIC_ID_TO_LABEL: Dict[str, str] = {
    "sleep_time_asleep": "睡眠总时长",
    "sleep_deep": "深睡",
    "sleep_rem": "REM 睡眠",
    "hrv_rmssd_ms": "HRV",
    "resting_heart_rate_bpm": "静息心率",
    "spo2_percent": "血氧",
    "workout_heart_rate_range_bpm": "锻炼心率范围",
    "workout_count_recent": "近期锻炼次数",
    "respiratory_rate": "呼吸率",
    "heart_rate_range_bpm": "心率范围",
}

_WEARABLE_STRIP: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"截图定账"), "截图"),
    (re.compile(r"定账"), ""),
    (re.compile(r"数仓"), "过去约 90 天的记录"),
    (re.compile(r"Wearable Compare Table[^\n]*\n?", re.I), ""),
    (re.compile(r"Tier0[^\n]*\n?", re.I), ""),
    (re.compile(r"metric_id", re.I), ""),
    (re.compile(r"NO_BASELINE"), ""),
    (re.compile(r"verdict_note", re.I), ""),
    (re.compile(r"Patient State", re.I), "健康记录"),
    (re.compile(r"User Data Snapshot", re.I), "过去约 90 天的记录"),
    (re.compile(r"###\s*纵向趋势对账\s*"), "### 与过去约 90 天对比\n"),
    (re.compile(r"###\s*多指标横向联动\s*"), "### 其他相关指标\n"),
    (re.compile(r"###\s*硬核非药物干预与筛查建议\s*"), "### 建议\n"),
    (re.compile(r"综合结论"), "小结"),
]


def polish_wearable_user_visible_reply(text: str) -> str:
    """Strip harness / metric_id jargon from chat-visible wearable answers."""
    out = polish_user_visible_reply(text or "")
    for mid, label in _METRIC_ID_TO_LABEL.items():
        out = re.sub(rf"\b{re.escape(mid)}\b", label, out, flags=re.I)
        out = re.sub(rf"`{re.escape(mid)}`", label, out, flags=re.I)
    for pat, repl in _WEARABLE_STRIP:
        out = pat.sub(repl, out)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r" \n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


__all__ = ["polish_wearable_user_visible_reply"]
