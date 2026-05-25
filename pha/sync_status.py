"""Apple Health import sync status for console dashboard."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pha.import_jobs import get_active_job_for_user, get_latest_job_for_user
from pha.sqlite_storage import (
    get_import_sync_state,
    get_max_wearable_timestamp,
    get_wearable_record_counts,
)


def build_sync_status_payload(user_id: str) -> Dict[str, Any]:
    uid = (user_id or "default").strip() or "default"
    counts = get_wearable_record_counts(uid)
    persisted = get_import_sync_state(uid)
    active = get_active_job_for_user(uid)
    latest_job = get_latest_job_for_user(uid)
    db_max = get_max_wearable_timestamp(uid)

    status_key = "never"
    status_label = "未同步"
    message = ""
    percent = 0.0
    last_record_time: Optional[str] = None
    last_sync_at: Optional[str] = None
    records_seen = 0
    days_written = counts["daily_days"]

    if active:
        status_key = "parsing"
        status_label = "正在解析"
        message = active.message or "正在导入 Apple Health export.zip…"
        percent = active.percent
        records_seen = active.rows_processed
        days_written = active.days_written or days_written
        last_sync_at = active.updated_at
    elif persisted:
        status_key = str(persisted.get("status") or "never")
        if status_key == "complete":
            status_label = "同步完成"
        elif status_key == "failed":
            status_label = "同步失败"
        elif status_key == "running":
            status_key = "parsing"
            status_label = "正在解析"
        else:
            status_label = "未同步"
        message = str(persisted.get("message") or "")
        last_record_time = persisted.get("last_record_time")
        last_sync_at = persisted.get("last_sync_at")
        records_seen = int(persisted.get("records_seen") or 0)
        days_written = int(persisted.get("days_written") or days_written)
    elif counts["daily_days"] > 0 or counts["sleep_segments"] > 0 or counts["steps_samples"] > 0:
        if status_key in ("never", ""):
            status_key = "complete"
            status_label = "同步完成"
            message = message or "数据库中已有可穿戴样本记录"
        if db_max:
            last_record_time = last_record_time or db_max.isoformat()

    if not last_record_time and db_max:
        last_record_time = db_max.isoformat()

    return {
        "user_id": uid,
        "status": status_key,
        "status_label": status_label,
        "message": message,
        "percent": percent,
        "last_sync_at": last_sync_at,
        "last_record_time": last_record_time,
        "records_seen": records_seen,
        "days_written": days_written,
        "counts": {
            "sleep_segments": counts["sleep_segments"],
            "steps_samples": counts["steps_samples"],
            "heart_rate_samples": counts["heart_rate_samples"],
            "daily_days": counts["daily_days"],
        },
        "active_job_id": active.job_id if active else None,
        "latest_job": latest_job.to_dict() if latest_job else None,
    }
