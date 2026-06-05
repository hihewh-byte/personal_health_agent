"""Registry-driven wearable metric intent → warehouse readiness probe (Wave 3d C-20)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from pha.intent_gates import infer_wearable_metrics, user_message_needs_wearable_query
from pha.sqlite_storage import _connect, get_wearable_record_counts, init_schema
from pha.wearable_metric_registry import (
    ingest_module,
    list_metric_entries,
    metric_entry,
    metric_labels_zh,
    metric_mention_hints,
)

_CATALOG_TO_REGISTRY: Dict[str, Tuple[str, ...]] = {
    "sleep": ("sleep_time_asleep", "sleep_deep", "sleep_rem"),
    "hrv": ("hrv_rmssd_ms",),
    "rhr": ("resting_heart_rate_bpm",),
    "spo2": ("spo2_percent",),
    "respiratory_rate": ("respiratory_rate",),
    "steps": (),
    "activity_kcal": (),
}

_BROAD_COMPARE_RE = re.compile(
    r"指标|是否正常|对比|相比|是不是都|整体|90\s*天|过去\s*90",
    re.I,
)
_STAGE_HINT_RE = re.compile(r"深睡|REM|快速眼动|睡眠分期|分期", re.I)
_WORKOUT_HINT_RE = re.compile(r"workout|work\s*out|锻炼|跑步|训练|运动", re.I)

_MIN_DAILY_ROWS = 14


def _hint_match_metric_ids(user_message: str) -> Set[str]:
    msg = user_message or ""
    blob = msg.lower()
    out: Set[str] = set()
    for mid, hints in metric_mention_hints().items():
        for h in hints:
            if h and h.lower() in blob:
                out.add(mid)
    if _STAGE_HINT_RE.search(msg):
        out.update({"sleep_deep", "sleep_rem"})
    if _WORKOUT_HINT_RE.search(msg):
        out.update({"workout_heart_rate_range_bpm", "workout_count_recent"})
    return out


def infer_requested_compare_metric_ids(user_message: str) -> List[str]:
    """Map user message → Registry metric_id set (deterministic, no LLM)."""
    msg = (user_message or "").strip()
    ids: Set[str] = set(_hint_match_metric_ids(msg))
    for cat_id in infer_wearable_metrics(msg):
        for reg_id in _CATALOG_TO_REGISTRY.get(cat_id, ()):
            ids.add(reg_id)
    if _BROAD_COMPARE_RE.search(msg) or user_message_needs_wearable_query(msg):
        for m in list_metric_entries():
            compare = m.get("compare") or {}
            if compare.get("comparable_90d") and not compare.get("conditional_row"):
                ids.add(str(m.get("metric_id")))
        if _WORKOUT_HINT_RE.search(msg) or any(
            m in ids for m in ("workout_heart_rate_range_bpm", "workout_count_recent")
        ):
            ids.update({"workout_heart_rate_range_bpm", "workout_count_recent"})
    # stable order: registry file order
    order = [str(m.get("metric_id")) for m in list_metric_entries()]
    return [mid for mid in order if mid in ids]


def _allowed_daily_fields() -> frozenset[str]:
    fields: Set[str] = set()
    for m in list_metric_entries():
        l1 = m.get("l1") or {}
        if str(l1.get("kind") or "") != "wearable_daily":
            continue
        field = str(l1.get("field") or "").strip()
        if field:
            fields.add(field)
    return frozenset(fields)


def _daily_field_ready(user_id: str, field: str) -> bool:
    if field not in _allowed_daily_fields():
        return False
    init_schema()
    uid = (user_id or "default").strip() or "default"
    conn = _connect()
    try:
        row = conn.execute(
            f"""
            SELECT COUNT(*) FROM wearable_daily
            WHERE user_id = ? AND {field} IS NOT NULL
            """,
            (uid,),
        ).fetchone()
        return int(row[0] or 0) >= _MIN_DAILY_ROWS
    except Exception:
        return False
    finally:
        conn.close()


def warehouse_ready_for_metric(user_id: str, metric_id: str) -> Tuple[bool, str]:
    """Return (ready, reason_code)."""
    entry = metric_entry(metric_id)
    if not entry:
        return False, "not_registered"
    l1 = entry.get("l1") or {}
    kind = str(l1.get("kind") or "")
    if kind == "wearable_daily":
        field = str(l1.get("field") or "").strip()
        if not field:
            return False, "warehouse_not_implemented"
        if _daily_field_ready(user_id, field):
            return True, "ready"
        counts = get_wearable_record_counts((user_id or "default").strip() or "default")
        if int(counts.get("daily_days") or 0) == 0:
            return False, "no_daily_warehouse"
        return False, "insufficient_days"
    if kind == "workout_sessions":
        n = int(get_wearable_record_counts((user_id or "default").strip() or "default").get("workout_sessions") or 0)
        if n > 0:
            return True, "ready"
        if int(get_wearable_record_counts((user_id or "default").strip() or "default").get("daily_days") or 0) > 0:
            return False, "workout_module_needed"
        return False, "no_daily_warehouse"
    return False, "warehouse_not_implemented"


def ingest_modules_for_gaps(metric_ids: List[str], *, not_ready: List[str]) -> List[Dict[str, Any]]:
    modules: Dict[str, Dict[str, Any]] = {}
    for mid in not_ready:
        entry = metric_entry(mid)
        if not entry:
            continue
        ing = entry.get("ingest") or {}
        mod_id = str(ing.get("module") or "").strip()
        if not mod_id:
            continue
        spec = ingest_module(mod_id)
        if not spec:
            continue
        modules[mod_id] = {
            "module_id": mod_id,
            "display_zh": str(spec.get("display_zh") or mod_id),
            "requires_zip": bool(spec.get("requires_zip")),
            "legacy_endpoint": str(spec.get("legacy_endpoint") or f"/data/sync-module/{mod_id}"),
            "metrics": sorted(
                set(modules.get(mod_id, {}).get("metrics") or []) | {mid},
            ),
        }
    return list(modules.values())


def build_user_probe_message(
    *,
    ready_ids: List[str],
    not_ready_ids: List[str],
    ingest_modules: List[Dict[str, Any]],
) -> str:
    labels = metric_labels_zh()
    parts: List[str] = []
    if ready_ids:
        names = "、".join(labels.get(m, m) for m in ready_ids[:8])
        parts.append(f"数仓已就绪：{names}")
    if not_ready_ids:
        names = "、".join(labels.get(m, m) for m in not_ready_ids[:6])
        parts.append(f"尚缺 90 天基线：{names}")
    if ingest_modules:
        mods = "、".join(str(m.get("display_zh") or m.get("module_id")) for m in ingest_modules)
        parts.append(f"请在「数据导入」选择 export.zip 后增量同步：{mods}")
    return "；".join(parts)


def probe_wearable_metric_needs(
    user_id: str,
    user_message: str,
) -> Dict[str, Any]:
    """
    Dialogue / API probe: user intent → Registry metrics → warehouse readiness.

    Does **not** generate SQL or new L1 pipelines; only reports gaps and ingest actions.
    """
    uid = (user_id or "default").strip() or "default"
    requested = infer_requested_compare_metric_ids(user_message)
    if not requested:
        return {
            "user_id": uid,
            "requested_metric_ids": [],
            "ready_metric_ids": [],
            "not_ready_metric_ids": [],
            "ingest_modules": [],
            "user_message_zh": "",
            "all_ready": True,
        }

    ready: List[str] = []
    not_ready: List[str] = []
    details: List[Dict[str, Any]] = []
    for mid in requested:
        ok, reason = warehouse_ready_for_metric(uid, mid)
        details.append({"metric_id": mid, "ready": ok, "reason_code": reason})
        if ok:
            ready.append(mid)
        else:
            not_ready.append(mid)

    modules = ingest_modules_for_gaps(requested, not_ready=not_ready)
    msg_zh = build_user_probe_message(
        ready_ids=ready,
        not_ready_ids=not_ready,
        ingest_modules=modules,
    )
    return {
        "user_id": uid,
        "requested_metric_ids": requested,
        "ready_metric_ids": ready,
        "not_ready_metric_ids": not_ready,
        "metric_details": details,
        "ingest_modules": modules,
        "user_message_zh": msg_zh,
        "all_ready": len(not_ready) == 0,
    }


__all__ = [
    "build_user_probe_message",
    "infer_requested_compare_metric_ids",
    "ingest_modules_for_gaps",
    "probe_wearable_metric_needs",
    "warehouse_ready_for_metric",
]
