"""PHA chat agent tool loop and catalog fetch runtime."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from pha.agent_tools import (
    MAX_TOOL_ROUNDS,
    PHA_AGENT_TOOLS,
    SNAPSHOT_MARKER,
    execute_tool_call,
    infer_auto_tool_fallback,
    tool_status_message,
)
from pha.evidence_catalog import format_fetched_evidence_text
from pha.harness_plan import TurnEvidencePlan
from pha.llm_provider import (
    OllamaProvider,
    build_ollama_synthetic_tool_call,
    normalize_ollama_assistant_message,
    parse_ollama_tool_arguments,
)


CATALOG_MAX_FETCH_ROUNDS = max(
    1,
    int((os.environ.get("PHA_CATALOG_MAX_FETCH_ROUNDS") or "3").strip() or "3"),
)

def _model_supports_ollama_tools(model: str) -> bool:
    """DeepSeek-R1 and similar reasoning models reject Ollama tool schemas (HTTP 400)."""
    m = (model or "").lower()
    if "deepseek-r1" in m:
        return False
    if "deepseek" in m and "r1" in m:
        return False
    return True


def _agent_tools_for_plan(plan: TurnEvidencePlan) -> List[Dict[str, Any]]:
    allowed = set(plan.tools_allowed or [])
    if not allowed:
        return []
    return [t for t in PHA_AGENT_TOOLS if (t.get("function") or {}).get("name") in allowed]


def _resolve_runtime_mode(
    model: str,
    plan_tools: List[Dict[str, Any]],
    *,
    fast_path: bool,
    plan: Optional[TurnEvidencePlan] = None,
) -> str:
    if fast_path:
        return "fast_path"
    if plan and "fetch_evidence_by_id" in set(plan.tools_allowed or []):
        if plan_tools and _model_supports_ollama_tools(model):
            return "catalog_tool_loop"
    if plan_tools and _model_supports_ollama_tools(model):
        return "tool_loop"
    if not _model_supports_ollama_tools(model):
        return "model_no_tools"
    return "evidence_preload"


def _runtime_status_message(
    runtime_mode: str,
    *,
    attachment_qa: bool = False,
    attach_status_suffix: str = "",
) -> Optional[str]:
    if runtime_mode == "catalog_tool_loop":
        return "Catalog 模式：请先点单拉取证据（fetch_evidence_by_id），再生成答复"
    if runtime_mode == "evidence_preload":
        if attachment_qa:
            base = "正在依据附件内容作答"
            return f"{base} · {attach_status_suffix}".strip(" ·") if attach_status_suffix else base
        return "本轮由 Harness 预注入证据，不调用工具"
    if runtime_mode == "model_no_tools":
        if attachment_qa:
            base = "正在依据附件内容作答"
            return f"{base} · {attach_status_suffix}".strip(" ·") if attach_status_suffix else base
        return "当前模型不支持工具调用，已切换为单轮证据流式答复…"
    return None


def _run_tool_loop_then_stream(
    provider: OllamaProvider,
    *,
    messages: List[Dict[str, Any]],
    user_id: str,
    user_message: str,
    tools: Optional[List[Dict[str, Any]]] = None,
    plan: Optional[TurnEvidencePlan] = None,
) -> tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Execute tool rounds (non-stream), return messages ready for final streamed completion."""
    status_messages: List[str] = []
    tool_results: List[Dict[str, Any]] = []
    tool_defs = tools if tools is not None else PHA_AGENT_TOOLS

    for round_idx in range(MAX_TOOL_ROUNDS):
        payload = provider.chat_with_tools(messages=messages, tools=tool_defs)
        message = payload.get("message") or {}
        tool_calls = message.get("tool_calls") or []

        if tool_calls:
            messages.append(normalize_ollama_assistant_message(message))
            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                allowed = set((plan.tools_allowed if plan else []) or [])
                if plan is not None and allowed and name not in allowed:
                    status_messages.append(f"工具 {name} 不在本轮计划允许列表，已跳过。")
                    continue
                args = parse_ollama_tool_arguments(fn.get("arguments"))
                if name == "get_health_data":
                    args = {**args, "_user_message": user_message}
                status_messages.append(tool_status_message(name, args))
                result = execute_tool_call(name, args, user_id=user_id)
                tool_results.append({"tool": name, "arguments": args, "result": result})
                messages.append(
                    {"role": "tool", "content": json.dumps(result, ensure_ascii=False)},
                )
            continue

        content = message.get("content") or ""
        if isinstance(content, str) and content.strip():
            messages.append(message)
            return status_messages, tool_results, messages

        if round_idx == 0 and SNAPSHOT_MARKER not in user_message:
            fallback = infer_auto_tool_fallback(user_message, plan=plan)
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
                        "tool_calls": [build_ollama_synthetic_tool_call(tool_name, args)],
                    },
                )
                messages.append(
                    {"role": "tool", "content": json.dumps(result, ensure_ascii=False)},
                )
                continue

        raise RuntimeError(f"Ollama returned empty assistant content: {payload!r}")

    raise RuntimeError(f"Exceeded maximum tool rounds ({MAX_TOOL_ROUNDS})")


def _catalog_stream_messages(
    messages: List[Dict[str, Any]],
    *,
    fetch_payload: Dict[str, Any],
    manifest_block: str,
) -> List[Dict[str, Any]]:
    """
    Ollama 流式 /api/chat 对 tool / tool_calls 消息支持差 — 第二轮用干净栈。
    保留 system + 会话 history + 原用户问 + 点单证据 user 块。
    """
    system_msg: Optional[Dict[str, Any]] = None
    history: List[Dict[str, Any]] = []
    user_turns: List[str] = []

    for m in messages:
        role = str(m.get("role") or "")
        content = str(m.get("content") or "").strip()
        if role == "system" and system_msg is None:
            system_msg = {"role": "system", "content": content}
            continue
        if role == "user" and content and "Harness · Catalog 第二轮" not in content:
            if "Patient State" in content or "证据切片" in content:
                history.append({"role": "user", "content": content})
            else:
                user_turns.append(content)
            continue
        if role == "assistant" and content and "tool_calls" not in m:
            history.append({"role": "assistant", "content": content})
        elif role == "assistant" and content:
            history.append({"role": "assistant", "content": content})

    evidence_text = format_fetched_evidence_text(fetch_payload)
    round2 = (
        "【Harness · Catalog 第二轮 · 已点单证据】\n"
        f"{evidence_text}\n\n"
        "---\n"
        f"{manifest_block}\n\n"
        "请基于以上点单证据作答；凡写化验/穿戴数值必须引用 Manifest KV 三元组，禁止编造。"
    )
    out: List[Dict[str, Any]] = []
    if system_msg:
        out.append(system_msg)
    out.extend(history)
    for ut in user_turns:
        out.append({"role": "user", "content": ut})
    out.append({"role": "user", "content": round2})
    return out


def _run_catalog_fetch_phase(
    provider: OllamaProvider,
    *,
    messages: List[Dict[str, Any]],
    user_id: str,
    user_message: str,
    tools: List[Dict[str, Any]],
    plan: TurnEvidencePlan,
) -> tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]], List[str], Dict[str, Any]]:
    """Controlled N-step catalog fetch loop; Harness fallback remains final veto."""
    status_messages: List[str] = []
    tool_results: List[Dict[str, Any]] = []
    fetched_ids: List[str] = []
    fetch_payload: Dict[str, Any] = {}
    round_cap = min(MAX_TOOL_ROUNDS, CATALOG_MAX_FETCH_ROUNDS)
    status_messages.append(f"Catalog 点单循环：最多 {round_cap} 轮")

    for round_idx in range(round_cap):
        status_messages.append(f"Catalog 点单第 {round_idx + 1}/{round_cap} 轮")
        payload = provider.chat_with_tools(messages=messages, tools=tools)
        message = payload.get("message") or {}
        tool_calls = message.get("tool_calls") or []

        if tool_calls:
            messages.append(normalize_ollama_assistant_message(message))
            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                if name != "fetch_evidence_by_id":
                    status_messages.append(f"工具 {name} 不在 Catalog 允许列表，已跳过。")
                    continue
                from pha.harness_subagent_protocol import validate_tool_invocation

                _proto = validate_tool_invocation(plan, name, catalog_mode=True)
                if not _proto.ok:
                    status_messages.append(
                        f"协议拦截：{_proto.violations[0].detail}",
                    )
                    continue
                args = {**parse_ollama_tool_arguments(fn.get("arguments")), "_user_message": user_message}
                status_messages.append(tool_status_message(name, args))
                result = execute_tool_call(name, args, user_id=user_id)
                tool_results.append(
                    {
                        "tool": name,
                        "arguments": args,
                        "result": result,
                        "catalog_round": round_idx + 1,
                    },
                )
                messages.append(
                    {"role": "tool", "content": json.dumps(result, ensure_ascii=False)},
                )
                for fid in result.get("fetched_ids") or []:
                    s = str(fid).strip()
                    if s and s not in fetched_ids:
                        fetched_ids.append(s)
                fetch_payload = result
            if fetched_ids and (fetch_payload.get("all_required_ready") is True):
                break
            continue

        if not fetched_ids and round_idx == 0:
            fallback = infer_auto_tool_fallback(user_message, plan=plan)
            if fallback:
                tool_name, args = fallback
                args = {**args, "_user_message": user_message}
                status_messages.append("Harness 代拉 Catalog fallback（模型未点单）…")
                status_messages.append(tool_status_message(tool_name, args))
                result = execute_tool_call(tool_name, args, user_id=user_id)
                tool_results.append(
                    {
                        "tool": tool_name,
                        "arguments": args,
                        "result": result,
                        "harness_fallback": True,
                        "catalog_round": round_idx + 1,
                    },
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            build_ollama_synthetic_tool_call(
                                tool_name,
                                {"ids": args.get("ids")},
                            ),
                        ],
                    },
                )
                messages.append(
                    {"role": "tool", "content": json.dumps(result, ensure_ascii=False)},
                )
                for fid in result.get("fetched_ids") or []:
                    s = str(fid).strip()
                    if s and s not in fetched_ids:
                        fetched_ids.append(s)
                fetch_payload = result
                if fetched_ids:
                    break
        # Model produced no usable tool call this round; stop loop and enforce Harness fallback below.
        break

    if not fetched_ids:
        from pha.evidence_catalog import DEFAULT_COMBINED_FETCH_IDS, fetch_evidence_by_id

        ids = list(DEFAULT_COMBINED_FETCH_IDS)
        status_messages.append(
            "Harness 强制 fallback：拉取 "
            + " + ".join(ids),
        )
        result = fetch_evidence_by_id(user_id, ids, user_message, fallback=True)
        tool_results.append(
            {
                "tool": "fetch_evidence_by_id",
                "arguments": {"ids": ids},
                "result": result,
                "harness_fallback": True,
            },
        )
        fetched_ids = [str(x) for x in (result.get("fetched_ids") or ids)]
        fetch_payload = result
    elif fetch_payload.get("all_required_ready") is not True:
        status_messages.append("Catalog 点单未覆盖全部必需证据，执行 Harness 补齐 fallback…")
        from pha.evidence_catalog import DEFAULT_COMBINED_FETCH_IDS, fetch_evidence_by_id

        ids = list(DEFAULT_COMBINED_FETCH_IDS)
        result = fetch_evidence_by_id(user_id, ids, user_message, fallback=True)
        tool_results.append(
            {
                "tool": "fetch_evidence_by_id",
                "arguments": {"ids": ids},
                "result": result,
                "harness_fallback": True,
                "reason": "catalog_partial_fill",
            },
        )
        fetched_ids = [str(x) for x in (result.get("fetched_ids") or ids)]
        fetch_payload = result

    return status_messages, tool_results, messages, fetched_ids, fetch_payload
