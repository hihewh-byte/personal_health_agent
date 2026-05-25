"""Factory reset — wipe wearable + medical data for a clean re-import."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from pha.import_jobs import clear_jobs_for_user
from pha.medical_storage import clear_user_medical_data
from pha.sqlite_storage import clear_import_sync_state, clear_wearable_storage
from pha.store import store

logger = logging.getLogger(__name__)


class FactoryResetResult(BaseModel):
    ok: bool = True
    user_id: str
    wearable_tables_cleared: bool = True
    medical_reports_deleted: int = 0
    health_assets_deleted: int = 0
    health_narratives_deleted: int = 0
    message: str = ""


def factory_reset_user_data(user_id: str) -> FactoryResetResult:
    """Clear wearable + medical SQLite tables and in-memory ledger for one user."""
    uid = (user_id or "default").strip() or "default"

    clear_wearable_storage(uid)
    reports_n, assets_n, narratives_n = clear_user_medical_data(uid)
    clear_import_sync_state(uid)
    clear_jobs_for_user(uid)
    store.clear_wearable_ledger(uid)

    msg = (
        f"已清空用户 {uid} 的全部健康数据："
        f"可穿戴表已重置，删除体检指标 {reports_n} 条、叙事 {narratives_n} 条、归档资产 {assets_n} 条。"
    )
    logger.warning("Factory reset completed for user_id=%s", uid)
    return FactoryResetResult(
        user_id=uid,
        medical_reports_deleted=reports_n,
        health_assets_deleted=assets_n,
        health_narratives_deleted=narratives_n,
        message=msg,
    )
