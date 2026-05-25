"""PHA reasoning entry — prompt assembly and Ollama-backed answers (no silent LLM fallback)."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, Field

from pha.agent_tools import (
    FAST_PATH_SYSTEM_ADDENDUM,
    apply_health_heuristic_override,
    message_has_health_snapshot,
    run_fast_completion,
    run_tool_loop,
)
from pha.health_data import build_system_date_block, effective_query_reference_date
from pha.llm_provider import OllamaProvider
from pha.models import HealthEvent, LongTermMilestone, UserCalibration
from pha.health_analyzer import build_system_historical_layer
from pha.store import store

_CITATION_LINE = re.compile(r"【依据索引】\s*([^\n]+?)\s*\Z", re.MULTILINE)

SYSTEM_PROMPT_TEMPLATE = (
    """Role: 你是一个严谨的个人健康 AI 助手（私人健康助手）。用户的数据存放在本地 PHA 系统中；用户已上传 Apple Health export.zip 后，穿戴与趋势数据即同步写入本地 SQLite（data/pha_storage.db），冷启动会自动载入。

当前日期（参考日）: {reference_date}

数据感知（必须遵守）:
- 当用户询问「最近90天」「看我的睡眠」「步数」「HRV」「静息心率」等需要具体数值的问题时，你必须先调用工具 ``get_health_data`` 查询本地数据库，再基于工具返回的 JSON 作答。
- 禁止回答「我无法看到您的数据」「我没有访问权限」等推脱话术；应回复「正在读取您的健康文件…」并结合查询结果给出均值/趋势。
- 如果你需要分析用户的健康数据，请调用 ``get_health_data`` 函数（参数：start_date, end_date, metrics）。

你必须同时参考下方「证据层」中的校准、里程碑与压缩趋势；工具查询结果优先用于回答具体数值问题。

Evidence Layers（证据层）说明 — 优先级从高到低：
1) 用户核心事实 (Calibration)：最高优先级，代表用户自述的稳定画像。
2) 永久里程碑 (Permanent Milestones)：仅次于 Calibration 的最高优先病史锚点；包含用户标记为里程碑的跨年度重大事件（含本系统实时录入的里程碑），新录入后立即进入本层并在后续对话中生效。
3) 长程趋势 (Long-term Trends)：由系统压缩的穿戴/体征趋势文本，用于识别缓慢变化。
4) 近期事件 (Recent Events)：最近时间线记录，用于感知当下状态。

Reasoning Constraint: 如果用户的健康数据与医学常识冲突，以用户的「核心事实 (Calibration)」与「永久里程碑」为准，并在回答中明确说明冲突点与取舍理由。

输出要求（必须遵守）：
- 优先使用系统提示最上方的「Current Patient State」事实账本与 SQLite 卷宗中的实测数字作答。
- 禁止在没有真实体检/穿戴数字时臆测具体指标值，禁止复读「饮食指导原则、运动路线图、Executive Summary、生活方式总则」等空泛健康模板。
- 有数据时以「指标 | 真实数值 | 参考/穿戴联动」条目或等价表格呈现；无数据时明确写「数据库无该指标记录」。
- 正文结束后，单独起一行，严格使用以下格式列出你在推理中实际引用过的 Evidence ID（来自下文各段方括号内的 ID），多个 ID 用英文逗号分隔，不要添加其它说明文字：
【依据索引】CAL:...,MIL:...,TREND:...,EVT:...
- 若某层证据完全未使用，可省略对应 ID。

--- 以下为当前注入的证据正文 ---

## 1) 用户核心事实 (Calibration)
{calibration_block}

## 2) 永久里程碑 (Permanent Milestones)
{milestones_block}

## 3) 长程趋势 (Long-term Trends)
{long_term_trends_block}

## 4) 近期事件 (Recent Events，最多 30 条，按时间从新到旧)
{recent_events_block}
"""
)


class EvidenceLayer(str, Enum):
    CALIBRATION = "calibration"
    MILESTONE = "milestone"
    LONG_TERM_TREND = "long_term_trend"
    RECENT_EVENT = "recent_event"


class EvidenceItem(BaseModel):
    """Structured provenance row — what context was supplied to the model."""

    ref_id: str = Field(description="Stable ID matching prompt brackets, e.g. MIL:<uuid>.")
    layer: EvidenceLayer
    title: str
    excerpt: str


class AgentAnswer(BaseModel):
    """Structured agent response with explicit evidence inventory and optional citation parse."""

    user_id: str
    model: str
    answer_text: str
    evidence_items: List[EvidenceItem] = Field(
        default_factory=list,
        description="Full catalog of evidence blocks supplied in the system prompt.",
    )
    referenced_evidence_ref_ids: List[str] = Field(
        default_factory=list,
        description="Subset parsed from the model's trailing 【依据索引】 line, if present.",
    )
    model_reply_raw: str = Field(
        default="",
        description="Verbatim model output (UI may parse 【依据索引】 client-side).",
    )
    tool_status_messages: List[str] = Field(
        default_factory=list,
        description="Human-readable status lines while tools run (for UI).",
    )
    tool_results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Structured tool execution log returned to the client.",
    )


def _excerpt(text: str, max_len: int = 400) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= max_len:
        return one_line
    return one_line[: max_len - 3] + "..."


def _split_trend_sections(compressed_trends: str) -> List[Tuple[str, str]]:
    """Split compressed wearable text into coarse sections for evidence refs."""
    text = compressed_trends.strip()
    if not text:
        return [("empty", "(无长程趋势文本)")]

    chunks = re.split(r"\n(?=---)", text)
    out: List[Tuple[str, str]] = []
    for idx, chunk in enumerate(chunks):
        chunk = chunk.strip()
        if not chunk:
            continue
        first = chunk.split("\n", 1)[0].strip()
        slug = re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", first)[:48] or f"sec-{idx}"
        out.append((f"{idx}-{slug}", chunk))
    return out or [("full", text)]


def assemble_system_prompt_and_evidence(
    *,
    user_id: str,
    calibration: UserCalibration,
    compressed_trends: str,
    milestones: List[LongTermMilestone],
    recent_events: List[HealthEvent],
) -> Tuple[str, List[EvidenceItem]]:
    """
    Build the final system prompt and parallel evidence catalog.

    This is the single source of truth for context ordering (Calibration > Milestones > Trends > Recent).
    """
    evidence: List[EvidenceItem] = []

    cal_ref = f"CAL:{user_id}"
    cal_lines = [
        f"[{cal_ref}]",
        f"姓名: {calibration.display_name or '—'}",
        f"性别: {calibration.gender or '—'}",
        f"年龄: {calibration.age_years if calibration.age_years is not None else '—'}",
        f"过敏史: {calibration.allergies or '—'}",
        f"核心疾病: {calibration.core_conditions or '—'}",
    ]
    calibration_block = "\n".join(cal_lines)
    evidence.append(
        EvidenceItem(
            ref_id=cal_ref,
            layer=EvidenceLayer.CALIBRATION,
            title="User calibration",
            excerpt=_excerpt(calibration_block, 500),
        ),
    )

    milestone_lines: List[str] = []
    for m in sorted(milestones, key=lambda x: x.occurred_at):
        ref = f"MIL:{m.source_event_id}"
        line = (
            f"[{ref}] {m.occurred_at.date().isoformat()} | {m.event_type.value} | {m.title} | {m.summary}"
        )
        milestone_lines.append(line)
        evidence.append(
            EvidenceItem(
                ref_id=ref,
                layer=EvidenceLayer.MILESTONE,
                title=m.title,
                excerpt=_excerpt(m.summary),
            ),
        )
    milestones_block = (
        "\n".join(milestone_lines) if milestone_lines else "(当前无永久里程碑记录)"
    )

    trend_sections = _split_trend_sections(compressed_trends)
    trend_blocks: List[str] = []
    for idx, (slug, body) in enumerate(trend_sections):
        ref = f"TREND:{idx}"
        trend_blocks.append(f"[{ref}] section={slug}\n{body}")
        evidence.append(
            EvidenceItem(
                ref_id=ref,
                layer=EvidenceLayer.LONG_TERM_TREND,
                title=f"Trend section {idx}",
                excerpt=_excerpt(body, 500),
            ),
        )
    long_term_trends_block = "\n\n".join(trend_blocks) if trend_blocks else "(无趋势文本)"

    recent_lines: List[str] = []
    for e in recent_events:
        ref = f"EVT:{e.id}"
        line = (
            f"[{ref}] {e.occurred_at.isoformat()} | {e.event_type.value} | {e.title} | {e.summary}"
        )
        recent_lines.append(line)
        evidence.append(
            EvidenceItem(
                ref_id=ref,
                layer=EvidenceLayer.RECENT_EVENT,
                title=e.title,
                excerpt=_excerpt(e.summary),
            ),
        )
    recent_events_block = "\n".join(recent_lines) if recent_lines else "(当前无近期事件)"

    historical_top = build_system_historical_layer(user_id, effective_query_reference_date())

    ref = effective_query_reference_date()
    core_prompt = (build_system_date_block(ref) + SYSTEM_PROMPT_TEMPLATE).format(
        reference_date=ref.isoformat(),
        calibration_block=calibration_block,
        milestones_block=milestones_block,
        long_term_trends_block=long_term_trends_block,
        recent_events_block=recent_events_block,
    )
    system_prompt = f"{historical_top}\n\n---\n\n{core_prompt}"
    return system_prompt, evidence


def _parse_cited_refs(raw_reply: str) -> Tuple[str, List[str]]:
    stripped = raw_reply.strip()
    match = _CITATION_LINE.search(stripped)
    if not match:
        return stripped, []
    cited_part = match.group(1).strip()
    refs = [token.strip() for token in cited_part.split(",") if token.strip()]
    answer_core = stripped[: match.start()].rstrip()
    return answer_core, refs


def ask_pha_agent(
    user_id: str,
    user_message: str,
    *,
    llm: OllamaProvider | None = None,
) -> AgentAnswer:
    """
    Run one PHA reasoning turn. LLM / transport failures propagate (no rule-engine fallback).
    """
    ctx = store.get_user_context(user_id)
    compressed = str(ctx.get("compressed_wearable_trends") or "")
    milestones_raw = ctx.get("permanent_milestones") or []
    milestones = [LongTermMilestone.model_validate(m) for m in milestones_raw]

    calibration = store.get_user_calibration(user_id)
    recent_events = store.list_recent_health_events(user_id, limit=30)

    system_prompt, evidence_items = assemble_system_prompt_and_evidence(
        user_id=user_id,
        calibration=calibration,
        compressed_trends=compressed,
        milestones=milestones,
        recent_events=recent_events,
    )

    provider = llm or OllamaProvider()
    augmented_message, pre_status, pre_results = apply_health_heuristic_override(
        user_message,
        user_id,
    )
    if message_has_health_snapshot(augmented_message):
        system_prompt = f"{system_prompt}\n\n{FAST_PATH_SYSTEM_ADDENDUM}"
        raw, fast_status = run_fast_completion(
            provider,
            system_prompt=system_prompt,
            user_message=augmented_message,
        )
        tool_status = pre_status + fast_status
        tool_results = pre_results
    else:
        raw, tool_status, tool_results = run_tool_loop(
            provider,
            system_prompt=system_prompt,
            user_message=augmented_message,
            user_id=user_id,
        )
        tool_status = pre_status + tool_status
        tool_results = pre_results + tool_results
    answer_text, cited = _parse_cited_refs(raw)

    return AgentAnswer(
        user_id=user_id,
        model=provider.model,
        answer_text=answer_text,
        evidence_items=evidence_items,
        referenced_evidence_ref_ids=cited,
        model_reply_raw=raw,
        tool_status_messages=tool_status,
        tool_results=tool_results,
    )
