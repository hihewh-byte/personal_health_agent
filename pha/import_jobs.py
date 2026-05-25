"""In-memory import job progress (process-local) for long Apple Health uploads."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

_lock = threading.Lock()
_jobs: Dict[str, "ImportJobState"] = {}


@dataclass
class ImportJobState:
    job_id: str
    user_id: str = "default"
    status: str = "pending"  # pending | running | complete | failed
    rows_processed: int = 0
    rows_total: int = 0
    percent: float = 0.0
    message: str = ""
    xml_max_date: str = ""
    db_max_timestamp: str = ""
    days_written: int = 0
    wearable_samples_written: int = 0
    import_complete: bool = False
    error: str = ""
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "user_id": self.user_id,
            "status": self.status,
            "rows_processed": self.rows_processed,
            "rows_total": self.rows_total,
            "percent": round(self.percent, 1),
            "message": self.message,
            "xml_max_date": self.xml_max_date,
            "db_max_timestamp": self.db_max_timestamp,
            "days_written": self.days_written,
            "wearable_samples_written": self.wearable_samples_written,
            "import_complete": self.import_complete,
            "error": self.error,
            "updated_at": self.updated_at,
        }


def create_job(*, user_id: str) -> ImportJobState:
    job_id = uuid.uuid4().hex[:12]
    state = ImportJobState(job_id=job_id, user_id=user_id.strip() or "default")
    with _lock:
        _jobs[job_id] = state
    return state


def get_job(job_id: str) -> Optional[ImportJobState]:
    with _lock:
        return _jobs.get(job_id)


def update_job(job_id: str, **kwargs: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        for key, val in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, val)
        job.updated_at = datetime.utcnow().isoformat()


def list_jobs_for_user(user_id: str) -> list[ImportJobState]:
    uid = (user_id or "default").strip() or "default"
    with _lock:
        return [j for j in _jobs.values() if j.user_id == uid]


def get_active_job_for_user(user_id: str) -> Optional[ImportJobState]:
    for job in list_jobs_for_user(user_id):
        if job.status in ("pending", "running"):
            return job
    return None


def get_latest_job_for_user(user_id: str) -> Optional[ImportJobState]:
    jobs = list_jobs_for_user(user_id)
    if not jobs:
        return None
    return max(jobs, key=lambda j: j.updated_at)


def clear_jobs_for_user(user_id: str) -> None:
    uid = (user_id or "default").strip() or "default"
    with _lock:
        for jid in [j.job_id for j in _jobs.values() if j.user_id == uid]:
            _jobs.pop(jid, None)
