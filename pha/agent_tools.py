"""LLM tool definitions and execution for PHA local health data."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from pha.date_parser import safe_parse_date_required
from pha.health_data import ALLOWED_METRICS, HealthDataResult, get_health_data

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
SQLITE_SCAN_STATUS = "🔍 正在扫描本地 SQLite 数据库（参考日见 effective_query_reference_date）..."
ALIGNMENT_STATUS = "⚡ 正在进行跨维度数据对齐（睡眠/HRV/步数/静息/活动消耗/血氧等）..."
SNAPSHOT_MARKER = "User Data Snapshot"
FAST_MODE_STATUS = "⚡ 本地数据已注入，使用快速推理（跳过工具调用）…"
FAST_PATH_SYSTEM_ADDENDUM = """
快速分析模式（已注入 Patient State 账本 / User Data Snapshot）：
- 仅引用上下文中已出现的实测数字；禁止臆造历史时间点或未列出的化验项。
- User Data Snapshot 中 Pearson/HRV/WASO 为统计量，不是 LDL 化验值。
- 若仍需跨年卷宗，可调用 get_temporal_history_dossier；否则不要重复调用 get_health_data。
""".strip()

GET_HEALTH_DATA_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_health_data",
        "description": (
            "从本地 PHA 数据库查询用户已上传的 Apple Health / 穿戴指标。"
            "用户 export.zip 导入后数据即存在本地。"
            "在回答睡眠、步数、HRV、静息心率、活动消耗、血氧、呼吸率、VO2max、手腕体温等数值问题前必须调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "起始日期 YYYY-MM-DD（含）",
                },
                "end_date": {
                    "type": "string",
                    "description": "结束日期 YYYY-MM-DD（含）",
                },
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": sorted(ALLOWED_METRICS),
                    },
                    "description": "要查询的指标列表",
                },
            },
            "required": ["start_date", "end_date", "metrics"],
        },
    },
}

GET_TEMPORAL_HISTORY_DOSSIER_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_temporal_history_dossier",
        "description": (
            "从本地 SQLite 拉取《全景纵向时空对账卷宗》。"
            "仅当 Patient State 账本无法覆盖用户所需的历史纵向对比时调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用户原始问题或需对账的时间范围描述",
                },
            },
            "required": ["query"],
        },
    },
}

FETCH_EVIDENCE_BY_ID_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "fetch_evidence_by_id",
        "description": (
            "从 PHA Evidence Catalog 按资产 ID 拉取化验/穿戴/补剂证据块。"
            "combined 复合问必须先点单 lab_lipid_panel 与 wearable_bundle（或 legacy LDL_TABLE/WEARABLE_90D）再作答。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Catalog 资产 ID，如 lab_lipid_panel, wearable_bundle, SUPPLEMENT_BG（legacy ID 仍可用）",
                },
            },
            "required": ["ids"],
        },
    },
}

PHA_AGENT_TOOLS: List[Dict[str, Any]] = [
    GET_HEALTH_DATA_TOOL,
    GET_TEMPORAL_HISTORY_DOSSIER_TOOL,
    FETCH_EVIDENCE_BY_ID_TOOL,
]

TEMPORAL_DOSSIER_TOOL_MAX_CHARS = 12000


def tool_status_message(name: str, arguments: Dict[str, Any]) -> str:
    if name == "get_temporal_history_dossier":
        q = str(arguments.get("query") or "")[:48]
        return f"正在从 SQLite 勾兑历史时空卷宗… {q}".strip()
    if name == "fetch_evidence_by_id":
        ids = arguments.get("ids") or []
        label = ", ".join(str(x) for x in ids[:4]) or "证据"
        return f"正在从 Catalog 拉取点单证据：{label}…"
    if name != "get_health_data":
        return f"正在调用工具 {name}…"
    metrics = arguments.get("metrics") or []
    metric_labels = {
        "sleep": "睡眠",
        "hrv": "HRV",
        "steps": "步数",
        "rhr": "静息心率",
        "activity_kcal": "活动消耗",
    }
    parts = [metric_labels.get(str(m), str(m)) for m in metrics]
    label = "、".join(parts) if parts else "健康指标"
    start = arguments.get("start_date", "")
    end = arguments.get("end_date", "")
    return (
        f"正在检索本地数据库以获取 {start} 至 {end} 的{label}记录…"
    )


def _parse_iso_date(raw: str) -> date:
    return safe_parse_date_required(raw, field="tool date")


def execute_tool_call(
    name: str,
    arguments: Dict[str, Any],
    *,
    user_id: str,
) -> Dict[str, Any]:
    if name == "get_temporal_history_dossier":
        from pha.chat_router import prepare_chat_evidence_bundle

        query = str(
            arguments.get("query")
            or arguments.get("user_message")
            or arguments.get("_user_message")
            or "",
        ).strip()
        from pha.intent_gates import QuestionType, classify_question_type

        qtype = classify_question_type(query)
        omit_ldl = qtype not in (QuestionType.LAB, QuestionType.COMBINED)
        bundle, intent, status_msg, _, is_dyn, stats = prepare_chat_evidence_bundle(
            user_id,
            query or "历史纵向对账",
            build_dossier=True,
            omit_ldl_fusion_blocks=omit_ldl,
            compact_clinical_only=(qtype == QuestionType.COMBINED),
        )
        dossier = bundle
        if len(dossier) > TEMPORAL_DOSSIER_TOOL_MAX_CHARS:
            dossier = dossier[:TEMPORAL_DOSSIER_TOOL_MAX_CHARS] + "\n…（卷宗已截断）"
        return {
            "dossier": dossier,
            "status": status_msg,
            "is_temporal_dynamic": is_dyn,
            "years": intent.explicit_years,
            "metric_rows": stats.metric_rows,
            "narrative_rows": stats.narrative_rows,
        }
    if name == "fetch_evidence_by_id":
        from pha.evidence_catalog import fetch_evidence_by_id

        ids_raw = arguments.get("ids") or []
        ids = [str(x).strip() for x in ids_raw if str(x).strip()]
        query = str(
            arguments.get("user_message")
            or arguments.get("_user_message")
            or "",
        ).strip()
        return fetch_evidence_by_id(
            user_id,
            ids,
            query,
            fallback=False,
        )
    if name != "get_health_data":
        return {"error": f"unknown tool: {name}"}
    start = _parse_iso_date(arguments["start_date"])
    end = _parse_iso_date(arguments["end_date"])
    query = str(arguments.pop("_user_message", "") or "")
    metrics_raw = arguments.get("metrics")
    if metrics_raw is None or metrics_raw == []:
        from pha.intent_gates import infer_wearable_metrics

        metrics = infer_wearable_metrics(query) if query else []
    else:
        metrics = list(metrics_raw)
    result = get_health_data(
        user_id,
        start,
        end,
        metrics,
        user_message=query,
    )
    return result.as_tool_payload()


def infer_health_tool_args(
    user_message: str,
    *,
    history_text: str = "",
) -> Dict[str, Any]:
    """Heuristic defaults when the model omits tool calls but user asks for wearable metrics."""
    from pha.intent_gates import resolve_wearable_tool_args

    return resolve_wearable_tool_args(user_message, history_text=history_text)


def format_wearable_evidence_contract(payload: Dict[str, Any]) -> str:
    metrics = payload.get("metrics") or []
    return (
        "【证据契约 · get_health_data】\n"
        f"区间: {payload.get('start_date', '')}～{payload.get('end_date', '')}\n"
        f"指标: {', '.join(str(m) for m in metrics)}\n"
        "来源: SQLite wearable_daily（含 active_energy_kcal 日汇总）+ wearable_data 兜底\n"
        f"wearable 有效天数: {payload.get('row_count', 0)}\n"
        f"系统说明: {payload.get('message', '')}"
    )


def _default_range(ref: date, days: int) -> tuple[date, date]:
    end = ref
    start = end - timedelta(days=max(1, days) - 1)
    return start, end


def user_message_needs_health_query(user_message: str) -> bool:
    from pha.intent_gates import user_message_needs_health_query as _gate

    return _gate(user_message)


def infer_auto_tool_fallback(
    user_message: str,
    *,
    plan: Optional[Any] = None,
) -> Optional[tuple[str, Dict[str, Any]]]:
    """v2.2.5: lab/combined → dossier; wearable-only → get_health_data; else no fallback."""
    from pha.harness_plan import TurnEvidencePlan, build_turn_evidence_plan
    from pha.intent_gates import (
        user_message_is_combined_health_review,
        user_message_needs_lab_dossier,
        user_message_needs_wearable_query,
    )

    active = plan or build_turn_evidence_plan(user_message)
    allowed = set(active.tools_allowed or [])
    if "fetch_evidence_by_id" in allowed and active.profile == "combined_review":
        from pha.evidence_catalog import DEFAULT_COMBINED_FETCH_IDS

        return (
            "fetch_evidence_by_id",
            {"ids": list(DEFAULT_COMBINED_FETCH_IDS), "_user_message": (user_message or "").strip()},
        )
    if user_message_needs_lab_dossier(user_message) or user_message_is_combined_health_review(
        user_message,
    ):
        if "get_temporal_history_dossier" in allowed:
            return ("get_temporal_history_dossier", {"query": (user_message or "").strip()})
        return None
    if user_message_needs_wearable_query(user_message):
        if "get_health_data" in allowed:
            return ("get_health_data", infer_health_tool_args(user_message))
        return None
    return None


def message_has_health_snapshot(user_message: str) -> bool:
    return SNAPSHOT_MARKER in user_message


def apply_health_heuristic_override(
    user_message: str,
    user_id: str,
    *,
    history_text: str = "",
) -> tuple[str, List[str], List[Dict[str, Any]]]:
    """
    Spinal reflex: inject wearable snapshot only when the user intent includes wearables.
    Lab / LDL cross-year questions must not pull 90-day wearable aggregates here.
    """
    from pha.intent_gates import (
        user_message_is_combined_health_review,
        user_message_needs_lab_dossier,
        user_message_needs_wearable_query,
    )

    if user_message_needs_lab_dossier(user_message) or user_message_is_combined_health_review(
        user_message,
    ):
        return user_message, [], []
    if not user_message_needs_wearable_query(user_message):
        return user_message, [], []

    from pha.health_data import effective_query_reference_date

    ref = effective_query_reference_date()
    status_messages: List[str] = [
        f"🔍 正在扫描本地 SQLite 数据库（参考日 {ref.isoformat()}）...",
        ALIGNMENT_STATUS,
    ]
    args = infer_health_tool_args(user_message, history_text=history_text)
    args_with_msg = {**args, "_user_message": user_message}
    result_payload = execute_tool_call("get_health_data", args_with_msg, user_id=user_id)
    result = HealthDataResult.model_validate(result_payload)
    if not result.metrics_supported:
        note = (result.message or "").strip() or "请求的穿戴指标不在已接入集合内。"
        return (
            user_message,
            [note],
            [
                {
                    "tool": "get_health_data",
                    "arguments": args,
                    "result": result_payload,
                    "heuristic": True,
                    "blocked": True,
                },
            ],
        )
    snapshot = result.analytics_snapshot or result_payload.get("analytics_snapshot", "")
    contract = format_wearable_evidence_contract(result_payload)
    augmented = (
        f"{user_message.strip()}\n\n---\n{contract}\n\n---\n"
        f"{SNAPSHOT_MARKER}（{result.start_date}～{result.end_date}）\n{snapshot}"
    )
    tool_results: List[Dict[str, Any]] = [
        {
            "tool": "get_health_data",
            "arguments": args,
            "result": result_payload,
            "heuristic": True,
        },
    ]
    return augmented, status_messages, tool_results


def run_fast_completion(
    provider: Any,
    *,
    system_prompt: str,
    user_message: str,
) -> tuple[str, List[str]]:
    """
    Single-turn chat without Ollama tools — used after heuristic snapshot injection
    (much faster on gemma4:e4b and similar small models).
    """
    content = provider.chat_completion(system_prompt=system_prompt, user_message=user_message)
    return content.strip(), [FAST_MODE_STATUS]


def run_tool_loop(
    provider: Any,
    *,
    system_prompt: str,
    user_message: str,
    user_id: str,
) -> tuple[str, List[str], List[Dict[str, Any]]]:
    """
    Run Ollama chat with tools until the model returns final text.

    Returns ``(final_content, tool_status_messages, tool_results)``.
    """
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    status_messages: List[str] = []
    tool_results: List[Dict[str, Any]] = []

    for round_idx in range(MAX_TOOL_ROUNDS):
        payload = provider.chat_with_tools(messages=messages, tools=PHA_AGENT_TOOLS)
        message = payload.get("message") or {}
        tool_calls = message.get("tool_calls") or []

        if tool_calls:
            messages.append(message)
            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                raw_args = fn.get("arguments") or "{}"
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {}
                else:
                    args = dict(raw_args)
                status_messages.append(tool_status_message(name, args))
                result = execute_tool_call(name, args, user_id=user_id)
                tool_results.append({"tool": name, "arguments": args, "result": result})
                messages.append(
                    {
                        "role": "tool",
                        "content": json.dumps(result, ensure_ascii=False),
                    },
                )
            continue

        content = message.get("content") or ""
        if isinstance(content, str) and content.strip():
            return content.strip(), status_messages, tool_results

        if round_idx == 0 and SNAPSHOT_MARKER not in user_message:
            fallback = infer_auto_tool_fallback(user_message)
            if fallback:
                tool_name, args = fallback
                status_messages.append(tool_status_message(tool_name, args))
                result = execute_tool_call(tool_name, args, user_id=user_id)
                tool_results.append(
                    {"tool": tool_name, "arguments": args, "result": result, "auto": True},
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(args, ensure_ascii=False),
                                },
                            },
                        ],
                    },
                )
                messages.append(
                    {"role": "tool", "content": json.dumps(result, ensure_ascii=False)},
                )
                continue

        msg = f"Ollama returned empty assistant content: {payload!r}"
        raise RuntimeError(msg)

    msg = f"Exceeded maximum tool rounds ({MAX_TOOL_ROUNDS})"
    raise RuntimeError(msg)
