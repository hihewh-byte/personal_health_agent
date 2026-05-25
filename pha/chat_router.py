"""PHA chat routing — temporal dossier injection (v1.8.8 harness)."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pha.data_audit import build_ldl_pipeline_audit
from pha.dossier_filters import filter_evidence_bundle_text
from pha.medical_storage import format_ldl_crossyear_markdown_table
from pha.temporal_router import (
    DOSSIER_TITLE,
    TemporalFusionStats,
    TemporalIntent,
    build_panoramic_temporal_dossier,
    build_temporal_status_message,
    infer_dynamic_health_tool_range,
    parse_temporal_intent,
)

logger = logging.getLogger(__name__)


def build_ldl_authority_system_block(user_id: str, years: list[int]) -> str:
    """Authoritative LDL numbers from SQLite only — injected into system prompt."""
    if not years:
        return ""
    table = format_ldl_crossyear_markdown_table(
        user_id,
        years,
        security_inspect=False,
    )
    return (
        "【SQLite LDL 权威表 · 回答指定年份对比时仅可使用下表数值】\n"
        f"{table}\n"
        "禁止引用历史会话、Historical Baseline 其他日期、或未入库的 harness 测试残留数值。"
    )


__all__ = [
    "TemporalIntent",
    "TemporalFusionStats",
    "build_ldl_authority_system_block",
    "build_panoramic_temporal_dossier",
    "infer_dynamic_health_tool_range",
    "parse_temporal_intent",
    "prepare_chat_evidence_bundle",
    "probe_temporal_route",
    "log_harness_payload",
]

_USER_CONTEXT_PREFIX = (
    "【System Context: 全景纵向时空对账卷宗 — 以下为 SQLite 真实查询结果，必须据此作答】\n"
)


def probe_temporal_route(user_message: str) -> TemporalIntent:
    """First-step intercept on raw user message (before DB/session work)."""
    return parse_temporal_intent(user_message)


def prepare_chat_evidence_bundle(
    user_id: str,
    user_message: str,
    *,
    extra_system_context: str = "",
    intent: Optional[TemporalIntent] = None,
    build_dossier: bool = True,
    omit_ldl_fusion_blocks: bool = False,
    compact_clinical_only: bool = False,
) -> Tuple[str, TemporalIntent, str, str, bool, TemporalFusionStats]:
    """Temporal routing; dossier only when ``build_dossier=True`` (on-demand tool)."""
    intent = intent or parse_temporal_intent(user_message)
    status_msg = build_temporal_status_message(intent)
    extra = (extra_system_context or "").strip()
    if not build_dossier:
        stats = TemporalFusionStats(years_queried=list(intent.explicit_years))
        return "", intent, status_msg, extra, intent.is_temporal_dynamic, stats

    dossier, intent, status_msg, stats = build_panoramic_temporal_dossier(
        user_id,
        user_message,
        intent=intent,
        omit_ldl_fusion_blocks=omit_ldl_fusion_blocks,
        compact_clinical_only=compact_clinical_only,
    )
    parts: List[str] = []
    if extra:
        parts.append(extra)
    parts.append(dossier)
    bundle = filter_evidence_bundle_text("\n\n".join(parts))
    return (
        bundle,
        intent,
        status_msg,
        extra,
        intent.is_temporal_dynamic,
        stats,
    )


def format_user_fusion_block(
    dossier: str,
    *,
    user_id: str = "default",
    intent: Optional[TemporalIntent] = None,
    user_message: str = "",
) -> str:
    """Duplicate ledger (+ optional LDL table) into user turn — LDL gated like SSE audit."""
    from pha.intent_gates import should_show_lab_pipeline_audit

    body = (dossier or "").strip()
    if not body or DOSSIER_TITLE not in body:
        return ""
    parts = [f"{_USER_CONTEXT_PREFIX}\n{body}"]
    if (
        intent
        and intent.explicit_years
        and should_show_lab_pipeline_audit(user_message or "", intent)
    ):
        parts.append(
            "\n---\n"
            + format_ldl_crossyear_markdown_table(
                user_id,
                intent.explicit_years,
                security_inspect=True,
            ),
        )
    return "\n".join(parts)


def build_chat_audit_payload(
    user_id: str,
    intent: Optional[TemporalIntent],
    *,
    user_message: str = "",
) -> tuple[str, dict, str]:
    """Audit markdown + JSON for SSE / done payload — lab cross-year only (v2.2.1)."""
    from pha.intent_gates import should_show_lab_pipeline_audit

    if not intent or not intent.explicit_years:
        return "", {}, ""
    if not should_show_lab_pipeline_audit(user_message, intent):
        return "", {}, ""
    return build_ldl_pipeline_audit(user_id, intent.explicit_years)


def log_harness_payload(
    *,
    user_id: str,
    intent: TemporalIntent,
    stats: TemporalFusionStats,
    system_prompt: str,
    user_message: str,
) -> None:
    """Print final Ollama-bound payload stats to console (harness audit)."""
    years_snip = (
        "/".join(str(y) for y in intent.explicit_years)
        if intent.explicit_years
        else "default-fallback"
    )
    dossier_in_sys = DOSSIER_TITLE in (system_prompt or "")
    dossier_in_user = DOSSIER_TITLE in (user_message or "")
    year_hits = []
    for y in intent.explicit_years or []:
        if re.search(rf"\b{y}\b|{y}年", system_prompt + user_message):
            year_hits.append(str(y))
    print(
        f"[PHA Harness v1.9.9] user={user_id} temporal_dynamic={intent.is_temporal_dynamic} "
        f"sniff={intent.sniff_source} years={years_snip} "
        f"metrics={stats.metric_rows} narratives={stats.narrative_rows} "
        f"wearable_windows={stats.wearable_windows} "
        f"system_chars={len(system_prompt)} user_chars={len(user_message)} "
        f"dossier_in_system={dossier_in_sys} dossier_in_user={dossier_in_user} "
        f"year_fragments_in_payload={','.join(year_hits) or 'none'}",
        flush=True,
    )
    if stats.metric_rows == 0 and intent.is_temporal_dynamic:
        print(
            "[PHA Harness WARNING] temporal_dynamic=True but metric_rows=0 — check user_id / 归仓",
            flush=True,
        )
    preview = system_prompt
    if DOSSIER_TITLE in preview:
        idx = preview.index(DOSSIER_TITLE)
        preview = preview[idx : idx + 600]
    print(f"[PHA Harness payload excerpt]\n{preview}\n---", flush=True)
