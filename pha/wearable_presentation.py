"""User-visible polish for wearable_screenshot_review replies."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from pha.presentation_filter import polish_user_visible_reply
from pha.response_language import normalize_response_locale

_METRIC_ID_TO_LABEL_ZH: Dict[str, str] = {
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

_METRIC_ID_TO_LABEL_EN: Dict[str, str] = {
    "sleep_time_asleep": "sleep duration",
    "sleep_deep": "deep sleep",
    "sleep_rem": "REM sleep",
    "hrv_rmssd_ms": "HRV",
    "resting_heart_rate_bpm": "resting heart rate",
    "spo2_percent": "SpO2",
    "workout_heart_rate_range_bpm": "workout HR range",
    "workout_count_recent": "recent workout days",
    "respiratory_rate": "respiratory rate",
    "heart_rate_range_bpm": "heart rate range",
}

_WEARABLE_STRIP_ZH: List[Tuple[re.Pattern[str], str]] = [
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

_WEARABLE_STRIP_EN: List[Tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"Based on your uploaded Apple Watch screenshots,\s*"
            r"compared with (?:the recent |~)?90 days? of records:",
            re.I,
        ),
        "Based on the uploaded Apple Watch screenshots, compared with ~90 days of records:",
    ),
    (re.compile(r"Wearable Compare Table[^\n]*\n?", re.I), ""),
    (re.compile(r"Tier0[^\n]*\n?", re.I), ""),
    (re.compile(r"metric_id", re.I), ""),
    (re.compile(r"NO_BASELINE", re.I), "no historical baseline"),
    (re.compile(r"verdict_note", re.I), ""),
    (re.compile(r"Patient State", re.I), "health records"),
    (re.compile(r"User Data Snapshot", re.I), "recent ~90-day records"),
    (re.compile(r"###\s*纵向趋势对账\s*"), "### Comparison vs ~90 days\n"),
    (re.compile(r"###\s*多指标横向联动\s*"), "### Related markers\n"),
    (re.compile(r"###\s*硬核非药物干预与筛查建议\s*"), "### Recommendations\n"),
    (re.compile(r"综合结论"), "Summary"),
]


def polish_wearable_user_visible_reply(text: str, *, locale: str | None = None) -> str:
    """Strip harness / metric_id jargon from chat-visible wearable answers."""
    loc = normalize_response_locale(locale) or "zh"
    label_map = _METRIC_ID_TO_LABEL_EN if loc == "en" else _METRIC_ID_TO_LABEL_ZH
    strip_list = _WEARABLE_STRIP_EN if loc == "en" else _WEARABLE_STRIP_ZH
    out = polish_user_visible_reply(text or "", locale=loc)
    for mid, label in label_map.items():
        out = re.sub(rf"\b{re.escape(mid)}\b", label, out, flags=re.I)
        out = re.sub(rf"`{re.escape(mid)}`", label, out, flags=re.I)
    for pat, repl in strip_list:
        out = pat.sub(repl, out)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r" \n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


__all__ = ["polish_wearable_user_visible_reply"]
