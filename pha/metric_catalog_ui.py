"""Metric catalog for UI — golden wearable strip + semantic medical groups (v2.1.3)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pha.metric_customs import is_polluted_metric_name

# Wearable stream ids (automation-first; no manual weigh-in)
GOLDEN_WEARABLE: List[Dict[str, Any]] = [
    {"id": "steps", "label": "每日步数", "source": "wearable", "unit": "步", "default": True},
    {"id": "rhr", "label": "静息心率", "source": "wearable", "unit": "bpm", "default": True},
    {"id": "hrv", "label": "心率变异性", "source": "wearable", "unit": "ms", "default": False},
    {
        "id": "sleep",
        "label": "总睡眠时间",
        "source": "wearable",
        "unit": "h",
        "hint": "睡眠恢复核心",
        "default": False,
    },
    {
        "id": "waso",
        "label": "睡眠清醒时间",
        "source": "wearable",
        "unit": "h",
        "hint": "睡眠碎片化金标准",
        "default": False,
    },
    {
        "id": "activity_kcal",
        "label": "活动消耗",
        "source": "wearable",
        "unit": "kcal",
        "hint": "每日代谢活跃度",
        "default": False,
    },
]

_GOLDEN_IDS = frozenset(g["id"] for g in GOLDEN_WEARABLE)

# Semantic buckets by keyword families (not individual analyte names)
_GROUP_RULES: List[tuple[str, str, re.Pattern[str]]] = [
    ("lipid", "脂质代谢轴", re.compile(r"脂|胆固醇|甘油|lipid|chol|hdl|ldl|tg\b", re.I)),
    ("glucose", "糖代谢轴", re.compile(r"糖|葡萄糖|胰岛|glu|hba|glyco", re.I)),
    ("liver", "肝功能轴", re.compile(r"肝|转氨|胆|alt|ast|ggt|alp", re.I)),
    ("renal", "肾功能轴", re.compile(r"肾|肌酐|尿素|尿酸|crea|bun|ua\b", re.I)),
    ("cbc", "血常规与免疫", re.compile(r"白细胞|红细胞|血红蛋白|血小板|淋巴|中性|嗜|单核|wbc|rbc|hgb|plt|#", re.I)),
    ("thyroid", "甲状腺轴", re.compile(r"甲状腺|tsh|t3|t4", re.I)),
    ("tumor", "肿瘤标志物", re.compile(r"胎|癌|cea|afp|psa|ca\d", re.I)),
    ("vitamin", "维生素与微量元素", re.compile(r"维生素|叶酸|铁|钙|镁|锌|vit", re.I)),
]


def classify_medical_group(metric_id: str, label: str) -> str:
    blob = f"{metric_id} {label}"
    for gid, _title, pat in _GROUP_RULES:
        if pat.search(blob):
            return gid
    return "other"


def build_metrics_catalog_payload(medical_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge golden wearable + clean medical metrics with semantic groups."""
    clean_medical: List[Dict[str, Any]] = []
    for item in medical_items:
        mid = (item.get("id") or "").strip()
        label = (item.get("label") or mid).strip()
        if not mid or mid in _GOLDEN_IDS:
            continue
        if is_polluted_metric_name(mid) or is_polluted_metric_name(label):
            continue
        if len(label) > 12 or len(mid) > 12:
            continue
        if any(tok in label or tok in mid for tok in ("作为乘客", "失眠是指", "中度症状")):
            continue
        clean_medical.append({**item, "group": classify_medical_group(mid, label)})

    groups_map: Dict[str, List[Dict[str, Any]]] = {}
    group_titles = {gid: title for gid, title, _ in _GROUP_RULES}
    group_titles["other"] = "其他检验项"

    for m in clean_medical:
        gid = m.get("group") or "other"
        groups_map.setdefault(gid, []).append(m)

    groups: List[Dict[str, Any]] = []
    for gid, title in group_titles.items():
        items = groups_map.get(gid) or []
        if not items:
            continue
        groups.append({"id": gid, "label": title, "metrics": sorted(items, key=lambda x: x.get("label") or "")})

    all_metrics = list(GOLDEN_WEARABLE) + clean_medical
    return {
        "golden": GOLDEN_WEARABLE,
        "groups": groups,
        "metrics": all_metrics,
        "medical_count": len(clean_medical),
        "golden_count": len(GOLDEN_WEARABLE),
    }
