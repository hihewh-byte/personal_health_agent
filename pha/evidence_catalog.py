"""Evidence Catalog — v2.2.8-p1 Schema Registry (fetch by id) + Tier0 directory."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Sequence

from pha.universal_catalog_manager import get_catalog_manager

# Back-compat re-exports (dynamic from registry).
def _legacy_meta() -> Dict[str, Dict[str, str]]:
    mgr = get_catalog_manager()
    out: Dict[str, Dict[str, str]] = {}
    for aid in mgr.catalog_asset_ids_for_profile("combined_review"):
        doc = mgr.get_asset(aid) or {}
        disp = doc.get("display") or {}
        out[aid] = {
            "title": disp.get("title_zh") or aid,
            "when": disp.get("when_zh") or "",
            "est_chars": disp.get("est_chars") or "",
        }
    out.setdefault(
        "LDL_TABLE",
        out.get("lab_lipid_panel")
        or {"title": "血脂（legacy）", "when": "", "est_chars": ""},
    )
    out.setdefault(
        "WEARABLE_90D",
        out.get("wearable_bundle")
        or {"title": "穿戴（legacy）", "when": "", "est_chars": ""},
    )
    return out


class _CatalogMetaProxy(dict):
    def __getitem__(self, key: str) -> Dict[str, str]:
        return _legacy_meta()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return _legacy_meta().get(key, default)

    def keys(self):
        return _legacy_meta().keys()

    def __iter__(self):
        return iter(_legacy_meta())

    def __len__(self) -> int:
        return len(_legacy_meta())


CATALOG_ENTRY_META: Dict[str, Dict[str, str]] = _CatalogMetaProxy()  # type: ignore[assignment]


def default_combined_fetch_ids(user_message: str = "") -> List[str]:
    return get_catalog_manager().default_combined_fetch_ids(user_message=user_message)


DEFAULT_COMBINED_FETCH_IDS: List[str] = default_combined_fetch_ids()


def catalog_mode_enabled() -> bool:
    return os.environ.get("PHA_HARNESS_CATALOG_MODE", "1").strip().lower() not in (
        "0",
        "false",
        "off",
        "legacy",
    )


def combined_catalog_task_text(user_message: str = "") -> str:
    ids = default_combined_fetch_ids(user_message)
    id_hint = " + ".join(ids)
    return (
        "【本轮任务 · Catalog 模式】"
        f"你必须先调用 fetch_evidence_by_id 点单拉取证据（至少 {id_hint}），"
        "再基于点单回填块与 Numerics Manifest 作答。"
        "回答血脂与近90日 HRV/活动消耗的关系，并给出补剂调整建议。"
        "【数字引用契约】凡写出化验或穿戴数值，必须逐条对应 Manifest KV 或点单证据中的"
        "「指标名 + 报告日/区间 + 数值」三元组；禁止编造日期；禁止跨指标挪用数字。"
        "必须引用 Manifest 或点单证据中的具体数值，或明确写「库内无该指标」；"
        "禁止向用户索要 HRV/运动消耗/血脂原始数据；禁止输出未点单资产的数值。"
        "【Manifest Tier · T0/T1 · 中英披露协议】"
        "T0 个人数据须来自 Numerics Manifest；T0 主张优先于 T1，禁止将参考值写成您的化验结果。"
        "T1 指南/理想线须用披露块——"
        "中文：「【参考标准】…（来源：xxx，请自行查证，非医疗建议）」；"
        "English: \"[Reference Standard] … (source: xxx, verify by yourself, not medical advice)\"；"
        "禁止在披露块内写您的/your 个人化验措辞。"
        "示例 EN: [Reference Standard] LDL ideal upper limit is often below 3.4 mmol/L "
        "(source: clinical guidelines, verify by yourself, not medical advice)."
    )


def build_evidence_catalog_block(
    *,
    profile: str,
    user_message: str = "",
    user_id: str = "default",
) -> str:
    return get_catalog_manager().build_catalog_block(
        profile=profile,
        user_message=user_message,
        user_id=user_id,
    )


def fetch_evidence_by_id(
    user_id: str,
    ids: Sequence[str],
    user_message: str = "",
    *,
    fallback: bool = False,
) -> Dict[str, Any]:
    """Catalog Reduce: pull evidence blocks by asset id (registry + dual-track)."""
    mgr = get_catalog_manager()
    uid = (user_id or "default").strip() or "default"
    requested = [str(x).strip() for x in ids if str(x).strip()]
    if not requested:
        requested = list(default_combined_fetch_ids(user_message))

    blocks: List[Dict[str, Any]] = []
    resolved: List[str] = []
    for raw_id in requested:
        canonical = mgr.resolve_id(raw_id)
        if not canonical:
            blocks.append(
                {
                    "id": raw_id,
                    "requested_id": raw_id,
                    "text": f"【{raw_id}】未知 Catalog 资产 ID。",
                    "chars": 0,
                },
            )
            continue
        text = mgr.fetch_asset_text(uid, canonical, user_message)
        blocks.append(
            {
                "id": canonical,
                "requested_id": raw_id if raw_id != canonical else None,
                "text": text,
                "chars": len(text),
            },
        )
        if canonical not in resolved:
            resolved.append(canonical)

    combined = "\n\n---\n\n".join(b["text"] for b in blocks if b.get("text"))
    required = set(default_combined_fetch_ids(user_message))
    all_required_ready = bool(required) and required.issubset(set(resolved))
    return {
        "fetched_ids": resolved,
        "requested_ids": requested,
        "blocks": blocks,
        "combined_text": combined,
        "harness_fallback": bool(fallback),
        "all_required_ready": all_required_ready,
        "chars_total": len(combined),
        "schema_registry": True,
    }


def fetched_includes_lipid(fetched_ids: Sequence[str]) -> bool:
    return get_catalog_manager().fetched_includes_manifest_domain(fetched_ids, "lipid")


def fetched_includes_wearable(fetched_ids: Sequence[str]) -> bool:
    return get_catalog_manager().fetched_includes_manifest_domain(fetched_ids, "wearable")


def format_fetched_evidence_text(payload: Dict[str, Any]) -> str:
    return (payload.get("combined_text") or "").strip() or "（点单未返回证据文本）"


__all__ = [
    "CATALOG_ENTRY_META",
    "DEFAULT_COMBINED_FETCH_IDS",
    "build_evidence_catalog_block",
    "catalog_mode_enabled",
    "combined_catalog_task_text",
    "default_combined_fetch_ids",
    "fetch_evidence_by_id",
    "fetched_includes_lipid",
    "fetched_includes_wearable",
    "format_fetched_evidence_text",
]
