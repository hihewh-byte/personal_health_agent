"""P0 — Chat turn LLM compose streaming and post-compose audit."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from pha.agent import _parse_cited_refs
from pha.agent_tools import FAST_MODE_STATUS
from pha.chat_agent_runtime import (
    _catalog_stream_messages,
    _run_catalog_fetch_phase,
    _run_tool_loop_then_stream,
    _runtime_status_message,
)
from pha.evidence_catalog import fetched_includes_lipid, fetched_includes_wearable
from pha.grounded_answer_composer import grounded_composer_enabled
from pha.harness_plan import TurnEvidencePlan
from pha.numerics_manifest import (
    NumericsManifest,
    apply_numerics_audit_to_answer,
    audit_response_numerics,
    build_numerics_manifest,
    format_manifest_tier0_block,
    numerics_audit_mode,
    numerics_require_citation,
)
logger = logging.getLogger(__name__)


@dataclass
class TurnComposeContext:
    """Mutable compose-phase context (COMPOSE + POST_AUDIT)."""

    skip_llm: bool
    det_text: str
    fast_path: bool
    use_catalog: bool
    use_tools: bool
    provider: Any
    chat_messages: List[Dict[str, Any]]
    plan_tools: List[Dict[str, Any]]
    plan: TurnEvidencePlan
    uid: str
    msg: str
    raw_user_msg: str
    runtime_mode: str
    attachment_asset_qa: bool
    attach_status_suffix: str
    wearable_screenshot_review: bool
    wearable_compare_table_obj: Any
    numerics_manifest: Optional[NumericsManifest]
    pre_results: List[Dict[str, Any]] = field(default_factory=list)

    full_parts: List[str] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    tool_status: List[str] = field(default_factory=list)
    raw: str = ""
    answer_text: str = ""
    cited: List[str] = field(default_factory=list)
    numerics_audit: Dict[str, Any] = field(default_factory=dict)
    compare_table_audit: Dict[str, Any] = field(default_factory=dict)
    manifest_block: str = ""
    response_locale: str = "en"


def iter_compose_response_phase(ctx: TurnComposeContext) -> Iterator[str]:
    """COMPOSE: skip_llm / fast_path / catalog / tool_loop / plain stream."""

    if ctx.skip_llm:
        _det_text = ctx.det_text
        ctx.full_parts.append(_det_text)
        yield json.dumps({"event": "delta", "delta": _det_text}, ensure_ascii=False)
    elif ctx.fast_path:
        yield json.dumps({"event": "status", "message": FAST_MODE_STATUS}, ensure_ascii=False)
        for delta in ctx.provider.stream_chat_messages(messages=ctx.chat_messages):
            ctx.full_parts.append(delta)
            yield json.dumps({"event": "delta", "delta": delta}, ensure_ascii=False)
    elif ctx.use_catalog:
        fetched_ids: List[str] = []
        fetch_payload: Dict[str, Any] = {}
        ctx.tool_status, ctx.tool_results, ctx.chat_messages, fetched_ids, fetch_payload = (
            _run_catalog_fetch_phase(
                ctx.provider,
                messages=ctx.chat_messages,
                user_id=ctx.uid,
                user_message=ctx.msg,
                tools=ctx.plan_tools,
                plan=ctx.plan,
            )
        )
        for st in ctx.tool_status:
            yield json.dumps({"event": "status", "message": st}, ensure_ascii=False)
        include_lipid = fetched_includes_lipid(fetched_ids)
        include_wearable = fetched_includes_wearable(fetched_ids)
        ctx.numerics_manifest = build_numerics_manifest(
            ctx.uid,
            profile=ctx.plan.profile,
            user_message=ctx.msg,
            include_lipid=include_lipid,
            include_wearable=include_wearable,
        )
        post_manifest_block = format_manifest_tier0_block(
            ctx.numerics_manifest,
            profile=ctx.plan.profile,
        )
        ctx.manifest_block = post_manifest_block
        if grounded_composer_enabled():
            from pha.grounded_answer_composer import build_fact_card_event

            _fc_cat = build_fact_card_event(ctx.numerics_manifest)
            if _fc_cat:
                yield json.dumps(_fc_cat, ensure_ascii=False)
        stream_messages = _catalog_stream_messages(
            ctx.chat_messages,
            fetch_payload=fetch_payload,
            manifest_block=post_manifest_block,
        )
        yield json.dumps(
            {"event": "status", "message": "Catalog 第二轮：基于点单证据流式生成答复…"},
            ensure_ascii=False,
        )
        for delta in ctx.provider.stream_chat_messages(messages=stream_messages):
            ctx.full_parts.append(delta)
            yield json.dumps({"event": "delta", "delta": delta}, ensure_ascii=False)
    elif ctx.use_tools:
        ctx.tool_status, ctx.tool_results, ctx.chat_messages = _run_tool_loop_then_stream(
            ctx.provider,
            messages=ctx.chat_messages,
            user_id=ctx.uid,
            user_message=ctx.msg,
            tools=ctx.plan_tools,
            plan=ctx.plan,
        )
        for st in ctx.tool_status:
            yield json.dumps({"event": "status", "message": st}, ensure_ascii=False)
        yield json.dumps(
            {"event": "status", "message": "模型正在流式生成答复…"},
            ensure_ascii=False,
        )
        last = ctx.chat_messages[-1] if ctx.chat_messages else {}
        if last.get("role") == "assistant" and (last.get("content") or "").strip():
            text = str(last["content"])
            ctx.full_parts.append(text)
            yield json.dumps({"event": "delta", "delta": text}, ensure_ascii=False)
        else:
            for delta in ctx.provider.stream_chat_messages(messages=ctx.chat_messages):
                ctx.full_parts.append(delta)
                yield json.dumps({"event": "delta", "delta": delta}, ensure_ascii=False)
    else:
        status_msg = _runtime_status_message(
            ctx.runtime_mode,
            attachment_qa=ctx.attachment_asset_qa,
            attach_status_suffix=ctx.attach_status_suffix,
        )
        if status_msg:
            yield json.dumps({"event": "status", "message": status_msg}, ensure_ascii=False)
        for delta in ctx.provider.stream_chat_messages(messages=ctx.chat_messages):
            ctx.full_parts.append(delta)
            yield json.dumps({"event": "delta", "delta": delta}, ensure_ascii=False)

    ctx.raw = "".join(ctx.full_parts)
    ctx.answer_text, ctx.cited = _parse_cited_refs(ctx.raw)
    from pha.attachment_asset_qa import (
        is_attachment_grounded_profile,
        is_attachment_qa_profile,
    )

    if is_attachment_qa_profile(ctx.plan.profile) or is_attachment_grounded_profile(
        ctx.plan.profile
    ):
        from pha.presentation_filter import polish_user_visible_reply

        polished = polish_user_visible_reply(
            ctx.answer_text or ctx.raw,
            locale=ctx.response_locale,
        )
        if polished:
            ctx.answer_text = polished


def iter_post_compose_audit_phase(ctx: TurnComposeContext) -> Iterator[str]:
    """POST_AUDIT: CompareTable fallback + numerics audit."""
    if (
        ctx.wearable_screenshot_review
        and ctx.wearable_compare_table_obj is not None
        and not ctx.skip_llm
    ):
        from pha.wearable_compare_table_v1 import apply_compare_table_fallback_if_needed
        from pha.wearable_presentation import polish_wearable_user_visible_reply

        ctx.answer_text, ctx.compare_table_audit = apply_compare_table_fallback_if_needed(
            ctx.answer_text or ctx.raw,
            ctx.wearable_compare_table_obj,
            user_message=ctx.raw_user_msg,
        )
        ctx.answer_text = polish_wearable_user_visible_reply(
            ctx.answer_text or ctx.raw,
            locale=ctx.response_locale,
        )
        if ctx.compare_table_audit.get("fallback_applied"):
            logger.info(
                "[Wearable Compare Audit] fallback violations=%s tier0_chars=%s advisory_chars=%s",
                ctx.compare_table_audit.get("violations"),
                len(ctx.compare_table_audit.get("tier0_markdown") or ""),
                ctx.compare_table_audit.get("advisory_chars"),
            )
            _fb_mode = ctx.compare_table_audit.get("fallback_mode") or "replace"
            _fb_msg = (
                "穿戴对比审计：对比数字已对齐系统表，并保留基于事实的健康建议"
                if int(ctx.compare_table_audit.get("advisory_chars") or 0) > 0
                else "已对齐为系统核对后的读数小结"
            )
            if _fb_mode == "hybrid" and int(ctx.compare_table_audit.get("advisory_chars") or 0) > 0:
                _fb_msg = "穿戴对比审计：对比数字已对齐系统表，并保留模型健康建议"
            yield json.dumps({"event": "status", "message": _fb_msg}, ensure_ascii=False)
    elif ctx.numerics_manifest is not None:
        ctx.numerics_audit = audit_response_numerics(
            ctx.answer_text or ctx.raw,
            ctx.numerics_manifest,
            require_citation=numerics_require_citation(),
        )
        if numerics_audit_mode() == "block" and not ctx.numerics_audit.get("passed"):
            ctx.answer_text = apply_numerics_audit_to_answer(
                ctx.answer_text or ctx.raw,
                ctx.numerics_audit,
            )
        elif numerics_audit_mode() == "warn" and not ctx.numerics_audit.get("passed"):
            yield json.dumps(
                {
                    "event": "status",
                    "message": (
                        "数字合规审计告警："
                        + ",".join(ctx.numerics_audit.get("violations") or [])
                    ),
                },
                ensure_ascii=False,
            )
