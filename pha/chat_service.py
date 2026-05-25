"""PHA streaming chat orchestration (SSE) with session persistence."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from pha.agent import (
    AgentAnswer,
    EvidenceItem,
    _parse_cited_refs,
)
from pha.agent_tools import (
    FAST_PATH_SYSTEM_ADDENDUM,
    FAST_MODE_STATUS,
    PHA_AGENT_TOOLS,
    apply_health_heuristic_override,
    execute_tool_call,
    infer_auto_tool_fallback,
    message_has_health_snapshot,
    tool_status_message,
    SNAPSHOT_MARKER,
    MAX_TOOL_ROUNDS,
)
from pha.chat_background import (
    MAX_CHAT_BACKGROUND_CHARS,
    build_user_background_block,
    maybe_capture_chat_background,
)
from pha.intent_gates import (
    QuestionType,
    classify_question_type,
    resolve_ldl_authority_years,
    should_inject_wearable_snapshot,
    should_strip_polluted_assistant_history,
    user_message_is_casual,
    user_message_needs_lab_dossier,
    user_message_needs_wearable_query,
)
from pha.chat_context import build_chat_context_block, extract_health_keywords, recent_turns
from pha.chat_storage import list_messages, search_messages_by_keywords
from pha.chat_router import (
    build_chat_audit_payload,
    build_ldl_authority_system_block,
    log_harness_payload,
    prepare_chat_evidence_bundle,
    probe_temporal_route,
)
from pha.chat_storage import (
    append_message,
    create_session,
    get_session,
    maybe_set_title_from_first_message,
    update_message_parsed_json,
)
from pha.event_medical import metrics_preview_dicts, narratives_preview_dicts
from pha.health_data import (
    build_system_date_block,
    effective_query_reference_date,
)
from pha.llm_provider import OllamaProvider
from pha.chat_ingest import ingest_chat_message, ingest_parsed_payload
from pha.patient_state import build_patient_state_evidence_slice
from pha.harness_report import (
    HarnessTurnInputs,
    build_harness_report,
    build_harness_telemetry,
    emit_harness_build_report,
)
from pha.harness_plan import (
    TurnEvidencePlan,
    assemble_tiered_supplemental,
    build_turn_evidence_plan,
    build_wearable_90d_summary_block,
    compute_plan_vs_actual,
    plan_allows_heuristic_snapshot,
)
from pha.evidence_catalog import (
    build_evidence_catalog_block,
    catalog_mode_enabled,
    format_fetched_evidence_text,
)
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

CHAT_HISTORY_MAX_TURNS = int(os.environ.get("PHA_CHAT_HISTORY_MAX_TURNS", "8"))
CHAT_HISTORY_MAX_CHARS = int(os.environ.get("PHA_CHAT_HISTORY_MSG_MAX_CHARS", "2800"))
SYSTEM_CONTENT_MAX_CHARS = int(os.environ.get("PHA_SYSTEM_CONTENT_MAX_CHARS", "10000"))
SUPPLEMENTAL_RECALL_MAX_CHARS = 1500
PHA_SUPPLEMENTAL_EXTRA_MAX_CHARS = int(os.environ.get("PHA_SUPPLEMENTAL_EXTRA_MAX_CHARS", "3200"))

ATTACH_PARSE_FAILURE_ADDENDUM = (
    "【附件解析状态 · 必读】\n"
    "本轮聊天附件的视觉解析失败或超时；原文件已安全保存在服务器 storage。\n"
    "禁止要求用户「重新上传化验单」或假装未收到附件。\n"
    "请明确告知解析失败，并建议用户在「全能解析中心」抽屉中重试解析，或检查本地 Ollama 视觉模型是否可用。"
)

PHA_MEDICAL_SOUL_LITE_SYSTEM_PROMPT = """Role: 你是 PHA 个人健康助理（本地模型）。用户本轮为简短社交/确认类消息。
规则：用中文一句话自然回复；不要展开三步看诊；不要编造任何化验或穿戴数字；若用户突然问起健康数据，请提示其发起正式提问。"""

PHA_MEDICAL_SOUL_SYSTEM_PROMPT = """Role: 你是 PHA 系统中唯一的、具备顶级临床思维的“个人专属首席健康管理专家”。你的底座是高智商的本地推理大模型，你掌握各大国际医学临床指南，深刻理解生理学中各种激素、心血管、代谢指标的物理因果链。

【INTENT GATE & CRITICAL RULES】
1. 【意图前置判定（防止算力空转）】：若用户只是进行日常礼貌性问候（如“你好”、“谢谢”、“收到”、“我知道了”）、或与生理账本指标完全无关的简短闲聊，请直接以高冷、干练的医生语气一句话秒回，【100%无视并跳过】下方的三步看诊法，全面保护本地宿主机的算力能效比。
2. 【去免责复读与安全红线熔断】：在处理常规生理指标波动时，严禁在回答中机械化复读“我只是个 AI”等敷衍废放。
   * 【特例熔断】：除非且仅当用户的提问涉及法定严重恶性传染病、急性安全中毒、自残、严重胸痛等危及生命的突发红线时，你可以立即熔断本条规则，极其严肃地引导用户前往医院急诊。
3. 【严格依账看诊与防幻想防御】：你的医学推理必须以贴在用户问题上方的 `Patient State` 事实账本为最高铁证。如果表格中缺乏某项指标的历史数据，请直接坦白告知用户“当前账本缺乏该项历史基线”，并转为单次数据的静态解构，【严禁凭空虚构任何历史数字与时间点】。
   * 【化验/穿戴数字引用契约（通用，非单指标硬编码）】：凡在答复中写出带数值的健康结论，每一条数字必须能在当轮已注入证据中找到**唯一对应行**——Patient State 表格行（含「报告日」）、Tier0 权威表（如 LDL 权威表）、或 Evidence 穿戴摘要（含区间）。**指标名、日期/区间、数值**三者必须一致；禁止编造任何报告日；**禁止把 A 指标的数字当作 B 指标**（例如血糖、粒细胞不得冒充血脂；步数不得冒充化验）。库内无则写「库内无该指标」，不得推测或凑整。
4. 【按需历史卷宗】：涉及血脂/化验跨年对比、历史记录查询时，必须以系统已注入的 SQLite 卷宗或工具 `get_temporal_history_dossier` 为准；禁止用 User Data Snapshot 中的穿戴统计替代化验回答。
5. 【聊天背景档案】：`【聊天背景档案】` 中的补剂/用药/睡眠自述为用户口头提供，可与化验联合分析，但不得当作实验室检验数值。
6. 【严格隔离红线】：你必须严格区分【医疗化验单指标】和【穿戴设备动态指标】两个区块。绝不允许把静息心率 (RHR)、HRV、步数等穿戴数据归类到肝功能、肾功能、血脂等医疗化验分类下。穿戴数据只能在「活动与休息概况」中提及。
7. 【禁止自定义步骤标签】：输出中不得出现 `[Step 1]`、`【Step 1】` 等包裹标签；三步看诊法仅用 Markdown 标题（如 `### 纵向趋势对账`）。

【CLINICAL THOUGHT PROCESS (三步看诊法)】
若通过意图判定需要进行医学看诊，你的流式输出必须严格执行：
- 第一步：【纵向趋势对账（Trend Tracking）】：从 Patient State 账本中检索核心指标历史时间序列，指出该指标处于何种波动趋势；若无，则告知用户缺乏基线并基于单次数字进行生化解构。
- 第二步：【多指标横向联动（Differential Diagnosis）】：绝不孤立地看一个指标（如皮质醇迹象必须横向联动近期静息心率与训练容量，从交感与副交感神经拮抗本质上剖析是急性训练疲劳还是 HPA 轴慢性紊乱）。给出 2-3 个逻辑严密的临床潜在可能性。
- 第三步：【硬核非药物干预与筛查建议（Protocol & Checkup）】：给出极具实操性的干预 Protocol（如精确到克数的补剂 scheme：麦格树镁、肌酸的使用时机）。明确给出下一次去医院体检时建议加挂的科室与额外加查的特定靶向指标（如游离皮质醇、TSH 游离三项）。

【TONE & STYLE】
- 语气必须像一位经验丰富、冷酷理性、充满极客精神同时又极具穿透力的资深私家名医。默认使用中文剖析，但在涉及到医学名词、生化指标时，必须采用“中文名 (英文缩写/Canonical Code)”格式。
- 强制输出纯粹、标准的 Markdown 文本，严禁大模型输出任何未在前端定义的自定义包裹标签（如 `[Step 1]` 等），确保完全兼容前端现有的 `marked.js` SSE 流式渲染管道。"""

PATIENT_STATE_USER_PREAMBLE = (
    "【Patient State · 事实账本（紧贴本轮提问，请优先读取表中数字）】"
)

SLOW_PATH_CHAT_STAGES = (
    "🔬 正在读取本地 SQLite 数据库，动态对齐全量健康资产...",
    "🔗 正在提取体检日时间锚点，动态检索跨表穿戴设备 WASO 睡眠流水...",
    "🧠 顶级医学大模型医生正在进行全动态深度审阅、跨表推导代谢因果链...",
)


def _merge_user_message(context_block: str, user_message: str) -> str:
    ctx = (context_block or "").strip()
    msg = (user_message or "").strip()
    if not ctx:
        return msg
    return f"{ctx}\n\n---\n【当前提问】\n{msg}"


def _truncate_history_content(text: str) -> str:
    s = (text or "").strip()
    if len(s) <= CHAT_HISTORY_MAX_CHARS:
        return s
    return s[:CHAT_HISTORY_MAX_CHARS] + "…"


def _session_history_messages(
    session_id: str,
    *,
    max_turns: int = CHAT_HISTORY_MAX_TURNS,
    exclude_current_user: bool = True,
    strip_polluted_assistant: bool = False,
) -> List[Dict[str, str]]:
    """Sliding window of prior user/assistant turns for Ollama ``messages`` array."""
    all_msgs = list_messages(session_id)
    if exclude_current_user and all_msgs and all_msgs[-1].role == "user":
        all_msgs = all_msgs[:-1]
    window = recent_turns(all_msgs, max_turns=max_turns)
    out: List[Dict[str, str]] = []
    for row in window:
        role = (row.role or "").strip().lower()
        if role not in ("user", "assistant"):
            continue
        content = _truncate_history_content(row.content)
        if not content:
            continue
        if strip_polluted_assistant and role == "assistant":
            if SNAPSHOT_MARKER in content or "User Data Snapshot" in content:
                continue
        out.append({"role": role, "content": content})
    return out


def _format_recalled_snippets(recalled: List[Any]) -> str:
    if not recalled:
        return ""
    lines = ["【历史相关片段 · 语义召回（仅供参考，非 Patient State 账本）】"]
    for m in recalled:
        role = "用户" if m.role == "user" else "助手"
        excerpt = (m.content or "").strip()
        if len(excerpt) > 450:
            excerpt = excerpt[:450] + "…"
        lines.append(f"({m.created_at[:10]}) {role}: {excerpt}")
    return "\n".join(lines)


def _cap_system_content(system_content: str) -> str:
    s = (system_content or "").strip()
    if len(s) <= SYSTEM_CONTENT_MAX_CHARS:
        return s
    return s[:SYSTEM_CONTENT_MAX_CHARS] + "\n\n…（系统提示已熔断截断以保护本地 KV Cache）"


def _cap_system_tiered(
    *,
    soul_with_anchor: str,
    tier0_supplemental: str,
    tier1_supplemental: str,
) -> str:
    """Tier0 (LDL/补剂/Task) kept; Tier1 (卷宗/召回) truncated first."""
    core = soul_with_anchor.strip()
    t0 = (tier0_supplemental or "").strip()
    t1 = (tier1_supplemental or "").strip()
    if t0:
        core = f"{core}\n\n---\n\n{t0}"
    if not t1:
        return _cap_system_content(core)
    combined = f"{core}\n\n---\n\n{t1}"
    if len(combined) <= SYSTEM_CONTENT_MAX_CHARS:
        return combined
    budget = SYSTEM_CONTENT_MAX_CHARS - len(core) - 40
    if budget > 400:
        t1_trim = t1[:budget] + "\n…（Tier1 卷宗/召回已截断）"
        return f"{core}\n\n---\n\n{t1_trim}"
    return _cap_system_content(core)


def _build_supplemental_system_layers(
    *,
    ldl_authority: str,
    audit_warn: str,
    extra_system_context: str,
    recalled_snippets: str,
) -> tuple[str, List[EvidenceItem]]:
    parts: List[str] = []
    if extra_system_context.strip():
        ctx = extra_system_context.strip()
        cap = PHA_SUPPLEMENTAL_EXTRA_MAX_CHARS
        if len(ctx) > cap:
            ctx = ctx[:cap] + "…"
        parts.append(ctx)
    if audit_warn.strip():
        parts.append(audit_warn.strip())
    if ldl_authority.strip():
        parts.append(ldl_authority.strip())
    if recalled_snippets.strip():
        rs = recalled_snippets.strip()
        if len(rs) > SUPPLEMENTAL_RECALL_MAX_CHARS:
            rs = rs[:SUPPLEMENTAL_RECALL_MAX_CHARS] + "…"
        parts.append(rs)
    return "\n\n---\n\n".join(parts), []


def build_pha_chat_message_stack(
    *,
    supplemental_system: str,
    history_messages: List[Dict[str, str]],
    patient_state: str,
    current_user_message: str,
    medical_soul_base: Optional[str] = None,
    evidence_user_blocks: Optional[List[str]] = None,
    raw_user_message: Optional[str] = None,
    tiered_system: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Physical message stack for Ollama (recency-optimized):
    1) PM medical soul system base (+ supplemental layers)
    2) Sliding-window session history
    3) Patient State ledger (user role, immediately above current question)
    4) Optional evidence user blocks (wearable summary — never inside raw user)
    5) Current user message (Raw User Lane — must match browser input)
    """
    soul = (medical_soul_base or PHA_MEDICAL_SOUL_SYSTEM_PROMPT).strip()
    ref = effective_query_reference_date()
    if tiered_system is not None:
        system_content = tiered_system
    else:
        system_content = build_system_date_block(ref) + soul
        if supplemental_system.strip():
            system_content = f"{system_content}\n\n---\n\n{supplemental_system.strip()}"
        system_content = _cap_system_content(system_content)

    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_content}]
    messages.extend(history_messages)

    ledger = (patient_state or "").strip()
    if ledger:
        messages.append(
            {
                "role": "user",
                "content": f"{PATIENT_STATE_USER_PREAMBLE}\n\n{ledger}",
            },
        )

    for block in evidence_user_blocks or []:
        body = (block or "").strip()
        if body:
            messages.append({"role": "user", "content": body})

    raw = (raw_user_message if raw_user_message is not None else current_user_message) or ""
    messages.append({"role": "user", "content": raw.strip()})
    return messages


_KEY_LAB_MARKERS = ("ldl", "alt", "ast", "hdl", "低密度", "谷氨", "天门冬", "胆固醇")

_LAB_LEDGER_TRIGGERS = (
    "血脂",
    "ldl",
    "hdl",
    "胆固醇",
    "甘油三酯",
    "化验",
    "体检",
    "肝功能",
    "肾功能",
)


def _message_needs_lab_ledger(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in _LAB_LEDGER_TRIGGERS)


def _extract_key_metric_names(metrics: List[Dict[str, Any]]) -> List[str]:
    names: List[str] = []
    for m in metrics or []:
        blob = " ".join(
            str(m.get(k) or "")
            for k in ("metric_name", "item", "metric_code", "id", "label", "name_zh")
        ).lower()
        if any(tok in blob for tok in _KEY_LAB_MARKERS):
            names.append(
                str(m.get("metric_name") or m.get("item") or m.get("label") or m.get("id") or "?"),
            )
    return names[:12]


def _auto_ingest_attachment_payload(
    parsed: Dict[str, Any],
    *,
    user_id: str,
    message_id: int,
    filename: str,
) -> Optional[Dict[str, Any]]:
    metrics = list(parsed.get("metrics") or [])
    narratives = list(parsed.get("narratives") or [])
    if not metrics and not narratives:
        return None

    metrics_count = len(metrics)
    logger.info(
        "[Auto Ingest] Found %s metrics, %s narratives from attachment %s",
        metrics_count,
        len(narratives),
        filename,
    )
    key_names = _extract_key_metric_names(metrics)
    if key_names:
        logger.info("[Auto Ingest] Key labs: %s", ", ".join(key_names))

    try:
        ing = ingest_chat_message(
            message_id,
            user_id=user_id,
            metrics=metrics,
            narratives=narratives,
            report_date=parsed.get("report_date"),
            hospital=parsed.get("hospital", ""),
        )
        logger.info(
            "[Auto Ingest] SUCCESS: %s metrics written to DB (stored=%s)",
            metrics_count,
            ing.get("metrics_stored"),
        )
        return ing
    except Exception as exc:
        logger.error("[Auto Ingest] FAILED: %s", exc)
        return None


def _is_safe_server_attachment_path(user_id: str, attachment_path: str) -> bool:
    from pathlib import Path

    from pha.attachment_storage import STORAGE_ROOT

    uid = (user_id or "default").strip() or "default"
    try:
        p = Path(attachment_path).resolve()
        allowed = (STORAGE_ROOT / uid).resolve()
        return str(p).startswith(str(allowed)) and p.is_file()
    except Exception:
        return False


def record_chat_attachment_parse_failure(
    user_id: str,
    *,
    attachment_path: str,
    attachment_name: str,
    error: str,
) -> None:
    from datetime import date as _date

    from pha.medical_storage import upsert_health_report_asset

    fname = (attachment_name or Path(attachment_path).name).strip() or "attachment"
    upsert_health_report_asset(
        user_id,
        _date.today(),
        source_filename=fname,
        source_kind="chat_attachment_failed",
        vision_model="",
        vision_raw={
            "parse_status": "failed",
            "error": (error or "")[:2500],
            "path": attachment_path,
        },
        metrics_preview="附件解析失败（待重试）",
    )


def parse_chat_attachment_file(
    user_id: str,
    attachment_path: str,
    attachment_name: str = "",
    *,
    auto_ingest: bool = True,
) -> Dict[str, Any]:
    """
    Standalone parse (v2.2.2) — used by ``POST /api/chat/attachments/parse`` after file upload.
    Caller must ensure ``attachment_path`` is under server storage for this user.
    """
    uid = (user_id or "default").strip() or "default"
    if not _is_safe_server_attachment_path(uid, attachment_path):
        raise ValueError("invalid or unsafe attachment_path")
    parsed = _vision_parse_attachment(
        attachment_path,
        attachment_name,
        user_id=uid,
        message_id=None,
        auto_ingest=False,
    )
    metrics = list(parsed.get("metrics") or [])
    narratives = list(parsed.get("narratives") or [])
    if auto_ingest and (metrics or narratives):
        ing = ingest_parsed_payload(
            user_id=uid,
            report_date=parsed.get("report_date") or "",
            hospital=parsed.get("hospital", ""),
            source_filename=parsed.get("source_filename") or (attachment_name or Path(attachment_path).name),
            source_kind="chat_attach_parse_api",
            metrics=metrics,
            narratives=narratives,
            vision_raw=parsed,
            vision_model="",
        )
        parsed["ingest"] = ing
    return parsed


def _vision_parse_attachment(
    path: str,
    filename: str,
    *,
    user_id: str = "default",
    message_id: Optional[int] = None,
    auto_ingest: bool = False,
) -> Dict[str, Any]:
    from pha.vision_engine import VisionReportParser

    fname = filename or Path(path).name
    raw = Path(path).read_bytes()
    resp = VisionReportParser().parse_upload(raw, filename=fname)
    extraction = resp.extraction
    metrics = list(resp.metrics_preview or [])
    if not metrics and extraction and extraction.results:
        from pha.event_medical import extraction_to_metric_rows
        from pha.date_parser import safe_parse_date

        rd = safe_parse_date((extraction.date or "")[:10]) or effective_query_reference_date()
        metric_rows = extraction_to_metric_rows(
            extraction,
            user_id=(user_id or "default").strip() or "default",
            report_date=rd,
            source_filename=fname,
        )
        metrics = metrics_preview_dicts(metric_rows)
    narratives = narratives_preview_dicts(
        extraction.narratives if extraction else [],
        hospital=(extraction.hospital if extraction else "") or "",
    )
    report_date = (extraction.date if extraction else "") or ""
    hospital = (extraction.hospital if extraction else "") or ""
    parsed: Dict[str, Any] = {
        "metrics": metrics,
        "narratives": narratives,
        "report_date": report_date[:10] if report_date else "",
        "hospital": hospital,
        "source_filename": fname,
        "vision_summary": (resp.summary_text or "").strip(),
    }
    parsed["metrics_parsed_count"] = len(metrics)
    if auto_ingest and message_id is not None and (metrics or narratives):
        ing = _auto_ingest_attachment_payload(
            parsed,
            user_id=user_id,
            message_id=message_id,
            filename=fname,
        )
        parsed["ingest"] = ing
    return parsed


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


def _runtime_status_message(runtime_mode: str) -> Optional[str]:
    if runtime_mode == "catalog_tool_loop":
        return "Catalog 模式：请先点单拉取证据（fetch_evidence_by_id），再生成答复"
    if runtime_mode == "evidence_preload":
        return "本轮由 Harness 预注入证据，不调用工具"
    if runtime_mode == "model_no_tools":
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
            messages.append(message)
            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                allowed = set((plan.tools_allowed if plan else []) or [])
                if plan is not None and allowed and name not in allowed:
                    status_messages.append(f"工具 {name} 不在本轮计划允许列表，已跳过。")
                    continue
                raw_args = fn.get("arguments") or "{}"
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {}
                else:
                    args = dict(raw_args)
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
    """Round-1 catalog fetch only; Harness fallback if model skips tool call."""
    status_messages: List[str] = []
    tool_results: List[Dict[str, Any]] = []
    fetched_ids: List[str] = []
    fetch_payload: Dict[str, Any] = {}

    for round_idx in range(MAX_TOOL_ROUNDS):
        payload = provider.chat_with_tools(messages=messages, tools=tools)
        message = payload.get("message") or {}
        tool_calls = message.get("tool_calls") or []

        if tool_calls:
            messages.append(message)
            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                if name != "fetch_evidence_by_id":
                    status_messages.append(f"工具 {name} 不在 Catalog 允许列表，已跳过。")
                    continue
                raw_args = fn.get("arguments") or "{}"
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {}
                else:
                    args = dict(raw_args)
                args = {**args, "_user_message": user_message}
                status_messages.append(tool_status_message(name, args))
                result = execute_tool_call(name, args, user_id=user_id)
                tool_results.append({"tool": name, "arguments": args, "result": result})
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
            continue

        if not fetched_ids:
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
                    },
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(
                                        {"ids": args.get("ids")},
                                        ensure_ascii=False,
                                    ),
                                },
                            },
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

    return status_messages, tool_results, messages, fetched_ids, fetch_payload


def stream_pha_chat_events(
    *,
    user_id: str,
    user_message: str,
    model: str,
    session_id: Optional[str] = None,
    extra_system_context: str = "",
    attachment_path: Optional[str] = None,
    attachment_name: Optional[str] = None,
) -> Iterator[str]:
    """
    Yield SSE payloads (JSON per ``data:`` line content):
    status | delta | done | error
    """
    uid = (user_id or "default").strip() or "default"
    msg = (user_message or "").strip()
    if not msg and not attachment_path:
        yield json.dumps({"event": "error", "message": "消息不能为空"}, ensure_ascii=False)
        return
    if not msg and attachment_path:
        msg = "请根据附件与 Current Patient State 事实账本，逐项解读化验指标（指标 | 数值 | 参考），勿输出空泛健康模板。"

    # Step 0: hard temporal intercept — SSE status before any heavy work
    temporal_probe = probe_temporal_route(msg)
    if temporal_probe.is_temporal_dynamic:
        from pha.temporal_router import build_temporal_status_message

        for stage_idx, stage_msg in enumerate(SLOW_PATH_CHAT_STAGES, start=1):
            yield json.dumps(
                {
                    "event": "status",
                    "type": "status",
                    "message": stage_msg,
                    "status": stage_msg,
                    "slow_path_stage": stage_idx,
                    "is_temporal_dynamic": True,
                    "years": temporal_probe.explicit_years,
                },
                ensure_ascii=False,
            )
        temporal_msg = build_temporal_status_message(temporal_probe)
        yield json.dumps(
            {
                "event": "status",
                "type": "status",
                "message": temporal_msg,
                "status": temporal_msg,
                "is_temporal_dynamic": True,
                "years": temporal_probe.explicit_years,
            },
            ensure_ascii=False,
        )

    sid = session_id
    if sid:
        if not get_session(sid, uid):
            yield json.dumps({"event": "error", "message": "会话不存在"}, ensure_ascii=False)
            return
    else:
        sess = create_session(uid)
        sid = sess.id

    att_path = (attachment_path or "").strip()
    att_name = (attachment_name or "").strip()
    parsed_payload: Optional[Dict[str, Any]] = None
    attach_parse_failed = False
    user_row = append_message(
        sid,
        "user",
        msg,
        attachment_path=att_path,
        attachment_name=att_name,
    )
    maybe_set_title_from_first_message(sid, msg)
    from pha.dynamic_slot_registry import on_background_captured, on_request_start

    slot_turn_meta = on_request_start(uid, msg)
    stored_bg, bg_reject = maybe_capture_chat_background(
        uid,
        msg,
        session_id=sid,
        source_message_id=user_row.id,
    )
    if stored_bg:
        on_background_captured(uid, msg)
    if bg_reject == "background_too_long":
        yield json.dumps(
            {
                "event": "status",
                "code": "background_too_long",
                "message": (
                    f"生活背景摘录表单次最长 {MAX_CHAT_BACKGROUND_CHARS} 字，已跳过写入（本条对话正文已照常保存）。"
                    "请分多次或分条目发送补剂/生活记录，以免摘录表静默截断。"
                ),
            },
            ensure_ascii=False,
        )

    if not temporal_probe.is_temporal_dynamic:
        yield json.dumps(
            {
                "event": "status",
                "message": "正在组装健康证据与语义历史上下文…",
                "session_id": sid,
                "model": model,
            },
            ensure_ascii=False,
        )

    if att_path:
        yield json.dumps(
            {"event": "status", "message": "📎 附件已落盘，正在视觉解析化验单结构…"},
            ensure_ascii=False,
        )
        try:
            parsed_payload = _vision_parse_attachment(
                att_path,
                att_name,
                user_id=uid,
                message_id=user_row.id,
                auto_ingest=True,
            )
            update_message_parsed_json(user_row.id, json.dumps(parsed_payload, ensure_ascii=False))
            parsed_n = int(
                parsed_payload.get("metrics_parsed_count")
                or len(parsed_payload.get("metrics") or [])
            )
            ing = parsed_payload.get("ingest") or {}
            stored_n = int(ing.get("metrics_stored") or 0)
            rd = (parsed_payload.get("report_date") or "")[:10]
            logger.info(
                "[Chat Attach] parsed=%s stored=%s report_date=%s",
                parsed_n,
                stored_n,
                rd,
            )
            if parsed_n and stored_n < parsed_n:
                yield json.dumps(
                    {
                        "event": "status",
                        "message": (
                            f"⚠️ 附件解析 {parsed_n} 项，写入账本 {stored_n} 项"
                            f"（report_date={rd or '未知'}）；请以 Patient State 为准。"
                        ),
                    },
                    ensure_ascii=False,
                )
            preview = (parsed_payload.get("vision_summary") or "")[:800]
            if preview:
                msg = f"{msg}\n\n【附件视觉解析摘要】\n{preview}"
        except Exception as exc:
            logger.exception("chat attachment vision parse failed")
            attach_parse_failed = True
            try:
                record_chat_attachment_parse_failure(
                    uid,
                    attachment_path=att_path,
                    attachment_name=att_name or Path(att_path).name,
                    error=str(exc),
                )
            except Exception:
                logger.exception("record_chat_attachment_parse_failure failed")
            yield json.dumps(
                {
                    "event": "attach_error",
                    "code": "vision_parse_failed",
                    "message": str(exc)[:800],
                },
                ensure_ascii=False,
            )
            yield json.dumps(
                {"event": "status", "message": f"附件解析失败（已保留原文件）: {exc}"},
                ensure_ascii=False,
            )

    audit_md = ""
    audit_json: Dict[str, Any] = {}
    audit_warn = ""
    try:
        _, temporal_intent, temporal_status, _, is_temporal_dynamic, fusion_stats = (
            prepare_chat_evidence_bundle(
                uid,
                msg,
                extra_system_context=extra_system_context,
                intent=temporal_probe,
                build_dossier=False,
            )
        )
        yield json.dumps(
            {
                "event": "status",
                "type": "status",
                "message": temporal_status,
                "status": temporal_status,
                "is_temporal_dynamic": is_temporal_dynamic,
                "years": temporal_intent.explicit_years,
                "metrics_fused": fusion_stats.metric_rows,
            },
            ensure_ascii=False,
        )

        provider = OllamaProvider(model=model.strip())

        plan = build_turn_evidence_plan(msg, is_temporal_dynamic=is_temporal_dynamic)
        qtype = plan.legacy_question_type

        ldl_authority = ""
        if "LDL_AUTHORITY" in plan.all_slots:
            ldl_years = resolve_ldl_authority_years(uid, msg, temporal_intent)
            if ldl_years:
                ldl_authority = build_ldl_authority_system_block(uid, ldl_years)

        forced_dossier = ""
        build_forced_dossier = (
            "DOSSIER_CLINICAL_COMPACT" in plan.all_slots or "DOSSIER_LAB" in plan.all_slots
        )
        catalog_turn = "fetch_evidence_by_id" in set(plan.tools_allowed or [])
        if build_forced_dossier and not catalog_turn and (
            user_message_needs_lab_dossier(msg) or plan.profile == "combined_review"
        ):
            forced_dossier, temporal_intent, dossier_status, _, is_temporal_dynamic, fusion_stats = (
                prepare_chat_evidence_bundle(
                    uid,
                    msg,
                    intent=temporal_intent,
                    build_dossier=True,
                    omit_ldl_fusion_blocks=plan.profile != "lab_cross_year",
                    compact_clinical_only=(plan.profile == "combined_review"),
                )
            )
            yield json.dumps(
                {
                    "event": "status",
                    "message": dossier_status,
                    "is_temporal_dynamic": is_temporal_dynamic,
                    "years": temporal_intent.explicit_years,
                    "metrics_fused": fusion_stats.metric_rows,
                },
                ensure_ascii=False,
            )

        background_block = build_user_background_block(uid, user_message=msg)

        _context_unused, recalled_rows = build_chat_context_block(
            uid,
            sid,
            msg,
            extra_system_context="",
            suppress_stale_assistant_recall=should_strip_polluted_assistant_history(msg),
        )
        recalled_snippets = _format_recalled_snippets(recalled_rows)

        audit_md, audit_json, audit_warn = build_chat_audit_payload(
            uid,
            temporal_intent,
            user_message=msg,
        )

        wearable_summary = ""
        if "WEARABLE_90D_SUMMARY" in plan.slots_tier0:
            wearable_summary = build_wearable_90d_summary_block(uid, msg)

        catalog_block = ""
        if "EVIDENCE_CATALOG" in plan.slots_tier0:
            catalog_block = build_evidence_catalog_block(
                profile=plan.profile,
                user_message=msg,
                user_id=uid,
            )

        numerics_manifest: Optional[NumericsManifest] = None
        manifest_block = ""
        if "NUMERICS_MANIFEST" in plan.slots_tier0:
            numerics_manifest = build_numerics_manifest(
                uid,
                profile=plan.profile,
                user_message=msg,
                include_wearable=not catalog_turn,
            )
            manifest_block = format_manifest_tier0_block(numerics_manifest)

        supplement_slot = background_block
        if extra_system_context.strip():
            supplement_slot = f"{background_block}\n\n{extra_system_context}".strip() if background_block else extra_system_context

        metadata_block = ""
        if "METADATA_CATALOG" in plan.all_slots:
            from pha.metadata_catalog import build_metadata_catalog_block

            metadata_block = build_metadata_catalog_block(
                uid,
                user_message=msg,
                profile=plan.profile,
            )

        slot_contents: Dict[str, str] = {
            "TASK": plan.task_text,
            "EVIDENCE_CATALOG": catalog_block,
            "NUMERICS_MANIFEST": manifest_block,
            "METADATA_CATALOG": metadata_block,
            "LDL_AUTHORITY": ldl_authority,
            "SUPPLEMENT_BG": supplement_slot,
            "DOSSIER_CLINICAL_COMPACT": forced_dossier,
            "DOSSIER_LAB": forced_dossier,
            "WEARABLE_90D_SUMMARY": wearable_summary,
            "AUDIT": audit_warn,
            "RECALL": recalled_snippets,
        }
        tier0_supp, tier1_supp, _missing_slots, tier0_integrity = assemble_tiered_supplemental(
            plan=plan,
            slot_contents=slot_contents,
        )
        supplemental_raw_for_report = f"{tier0_supp}\n\n---\n\n{tier1_supp}".strip()

        shadow_handle = None
        from pha.shadow_routing import maybe_start_shadow_job
        from pha.universal_catalog_manager import get_catalog_manager

        _shadow_mgr = get_catalog_manager()
        _shadow_catalog_ids = _shadow_mgr.catalog_asset_ids_for_profile(
            plan.profile,
            user_message=msg,
            user_id=uid,
        )
        shadow_handle = maybe_start_shadow_job(
            msg,
            authoritative_profile=plan.profile,
            authoritative_catalog_ids=_shadow_catalog_ids,
            user_id=uid,
            metadata_catalog_excerpt=(metadata_block or "")[:1200],
        )

        if attach_parse_failed:
            tier1_supp = f"{ATTACH_PARSE_FAILURE_ADDENDUM}\n\n---\n\n{tier1_supp}".strip()

        history_messages = _session_history_messages(
            sid,
            max_turns=CHAT_HISTORY_MAX_TURNS,
            exclude_current_user=True,
            strip_polluted_assistant=should_strip_polluted_assistant_history(msg),
        )

        if audit_md:
            yield json.dumps(
                {
                    "event": "audit",
                    "data_pipeline_audit": audit_json,
                    "markdown": audit_md,
                    "warning_banner": audit_warn,
                },
                ensure_ascii=False,
            )

        # Raw User Lane — never append Snapshot to user text (Phase 1)
        augmented_message = msg
        pre_status: List[str] = []
        pre_results: List[Dict[str, Any]] = []

        if plan_allows_heuristic_snapshot(plan):
            _, pre_status, pre_results = apply_health_heuristic_override(msg, uid)
            for st in pre_status:
                yield json.dumps({"event": "status", "message": st}, ensure_ascii=False)
            if pre_results and pre_results[0].get("result"):
                snap_body = str((pre_results[0].get("result") or {}).get("analytics_snapshot") or "")
                if snap_body.strip():
                    wearable_summary = (
                        f"【Evidence · 穿戴预计算摘要 · 勿与补剂/化验混读】\n{snap_body.strip()}"
                    )
                    slot_contents["WEARABLE_90D_SUMMARY"] = wearable_summary
                    tier0_supp, tier1_supp, _, tier0_integrity = assemble_tiered_supplemental(
                        plan=plan,
                        slot_contents=slot_contents,
                    )
                    supplemental_raw_for_report = f"{tier0_supp}\n\n---\n\n{tier1_supp}".strip()

        patient_state = ""
        if "PATIENT_STATE_LAB" in plan.all_slots or "PATIENT_STATE_WEARABLE" in plan.all_slots:
            from pha.evidence_lane import wearable_block_has_user_snapshot

            patient_state = build_patient_state_evidence_slice(
                uid,
                msg,
                question_type=qtype,
                has_wearable_user_snapshot=wearable_block_has_user_snapshot(
                    wearable_summary,
                ),
                parsed_overlay=parsed_payload,
                reference_date=effective_query_reference_date(),
            )

        soul_base = (
            PHA_MEDICAL_SOUL_LITE_SYSTEM_PROMPT
            if qtype == QuestionType.CASUAL
            else None
        )
        soul = (soul_base or PHA_MEDICAL_SOUL_SYSTEM_PROMPT).strip()
        ref = effective_query_reference_date()
        tiered_system = _cap_system_tiered(
            soul_with_anchor=build_system_date_block(ref) + soul,
            tier0_supplemental=tier0_supp,
            tier1_supplemental=tier1_supp,
        )
        soul_t0_len = len(build_system_date_block(ref) + soul) + len(tier0_supp or "")
        if soul_t0_len > SYSTEM_CONTENT_MAX_CHARS - 200:
            errs = list(tier0_integrity.get("errors") or [])
            if "cap_system_tiered_overflow" not in errs:
                errs.append("cap_system_tiered_overflow")
            tier0_integrity["errors"] = sorted(set(errs))

        fast_path = plan.profile == "wearable_only" and bool(wearable_summary) and not _message_needs_lab_ledger(msg)
        if fast_path:
            tiered_system = f"{tiered_system}\n\n{FAST_PATH_SYSTEM_ADDENDUM}".strip()

        chat_messages = build_pha_chat_message_stack(
            supplemental_system="",
            history_messages=history_messages,
            patient_state=patient_state,
            current_user_message=msg,
            raw_user_message=msg,
            medical_soul_base=soul_base,
            tiered_system=tiered_system,
        )

        log_harness_payload(
            user_id=uid,
            intent=temporal_intent,
            stats=fusion_stats,
            system_prompt=str(chat_messages[0].get("content", "")) if chat_messages else "",
            user_message=msg,
        )

        plan_tools = _agent_tools_for_plan(plan)
        evidence_items: List[Any] = []
        runtime_mode = _resolve_runtime_mode(
            model.strip(),
            plan_tools,
            fast_path=fast_path,
            plan=plan,
        )

        def _emit_harness(mode: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> None:
            executed = [str(t.get("tool") or "") for t in tools]
            pva = compute_plan_vs_actual(
                plan,
                raw_user_message=msg,
                current_user_message=str(messages[-1].get("content") or "") if messages else msg,
                tools_executed=executed,
                snapshot_in_user=SNAPSHOT_MARKER in str(messages[-1].get("content") or ""),
                slot_contents=slot_contents,
                tier0_text=tier0_supp,
                tier0_integrity=tier0_integrity,
            )
            telemetry = build_harness_telemetry(
                user_id=uid,
                user_message=msg,
                plan_profile=plan.profile,
                background_block_nonempty=bool(background_block.strip()),
            )
            h_in = HarnessTurnInputs(
                user_id=uid,
                session_id=sid or "",
                user_message_id=user_row.id,
                model=model.strip(),
                user_message=msg,
                question_type=qtype,
                temporal_years=list(temporal_intent.explicit_years or []),
                ldl_authority=ldl_authority,
                supplement_bg=background_block,
                forced_dossier=forced_dossier,
                audit_warn=audit_warn,
                recalled_snippets=recalled_snippets,
                patient_state=patient_state,
                augmented_user_message=augmented_message,
                raw_supplemental=supplemental_raw_for_report,
                system_after_stack=str(messages[0].get("content", "")) if messages else "",
                system_content_max=SYSTEM_CONTENT_MAX_CHARS,
                inject_wearable_snapshot=plan_allows_heuristic_snapshot(plan),
                build_forced_dossier=build_forced_dossier,
                has_snapshot=SNAPSHOT_MARKER in augmented_message,
                fast_path=fast_path,
                use_tools_runtime=runtime_mode in ("tool_loop", "catalog_tool_loop"),
                tool_results=tools,
                chat_messages=messages,
                mode=mode,
                turn_plan=plan,
                plan_vs_actual=pva,
                tier0_integrity=tier0_integrity,
                runtime_mode=runtime_mode,
                numerics_manifest=numerics_manifest.to_dict() if numerics_manifest else {},
                numerics_manifest_block=manifest_block,
                intent_route=telemetry["intent_route"],
                catalog_existence=telemetry["catalog_existence"],
                dynamic_slots=telemetry["dynamic_slots"],
                metadata_catalog_block=slot_contents.get("METADATA_CATALOG") or "",
            )
            emit_harness_build_report(build_harness_report(h_in))

        _emit_harness("plan_pre_llm", chat_messages, list(pre_results))

        full_parts: List[str] = []
        tool_results: List[Dict[str, Any]] = pre_results
        tool_status: List[str] = []

        use_tools = runtime_mode == "tool_loop"
        use_catalog = runtime_mode == "catalog_tool_loop"
        if fast_path:
            yield json.dumps({"event": "status", "message": FAST_MODE_STATUS}, ensure_ascii=False)
            for delta in provider.stream_chat_messages(messages=chat_messages):
                full_parts.append(delta)
                yield json.dumps({"event": "delta", "delta": delta}, ensure_ascii=False)
        elif use_catalog:
            fetched_ids: List[str] = []
            fetch_payload: Dict[str, Any] = {}
            tool_status, tool_results, chat_messages, fetched_ids, fetch_payload = (
                _run_catalog_fetch_phase(
                    provider,
                    messages=chat_messages,
                    user_id=uid,
                    user_message=msg,
                    tools=plan_tools,
                    plan=plan,
                )
            )
            for st in tool_status:
                yield json.dumps({"event": "status", "message": st}, ensure_ascii=False)
            from pha.evidence_catalog import fetched_includes_lipid, fetched_includes_wearable

            include_lipid = fetched_includes_lipid(fetched_ids)
            include_wearable = fetched_includes_wearable(fetched_ids)
            numerics_manifest = build_numerics_manifest(
                uid,
                profile=plan.profile,
                user_message=msg,
                include_lipid=include_lipid,
                include_wearable=include_wearable,
            )
            post_manifest_block = format_manifest_tier0_block(numerics_manifest)
            stream_messages = _catalog_stream_messages(
                chat_messages,
                fetch_payload=fetch_payload,
                manifest_block=post_manifest_block,
            )
            yield json.dumps(
                {"event": "status", "message": "Catalog 第二轮：基于点单证据流式生成答复…"},
                ensure_ascii=False,
            )
            for delta in provider.stream_chat_messages(messages=stream_messages):
                full_parts.append(delta)
                yield json.dumps({"event": "delta", "delta": delta}, ensure_ascii=False)
        elif use_tools:
            tool_status, tool_results, chat_messages = _run_tool_loop_then_stream(
                provider,
                messages=chat_messages,
                user_id=uid,
                user_message=msg,
                tools=plan_tools,
                plan=plan,
            )
            for st in tool_status:
                yield json.dumps({"event": "status", "message": st}, ensure_ascii=False)
            yield json.dumps(
                {"event": "status", "message": "模型正在流式生成答复…"},
                ensure_ascii=False,
            )
            last = chat_messages[-1] if chat_messages else {}
            if last.get("role") == "assistant" and (last.get("content") or "").strip():
                text = str(last["content"])
                full_parts.append(text)
                yield json.dumps({"event": "delta", "delta": text}, ensure_ascii=False)
            else:
                for delta in provider.stream_chat_messages(messages=chat_messages):
                    full_parts.append(delta)
                    yield json.dumps({"event": "delta", "delta": delta}, ensure_ascii=False)
        else:
            status_msg = _runtime_status_message(runtime_mode)
            if status_msg:
                yield json.dumps({"event": "status", "message": status_msg}, ensure_ascii=False)
            for delta in provider.stream_chat_messages(messages=chat_messages):
                full_parts.append(delta)
                yield json.dumps({"event": "delta", "delta": delta}, ensure_ascii=False)

        raw = "".join(full_parts)
        answer_text, cited = _parse_cited_refs(raw)

        numerics_audit: Dict[str, Any] = {}
        if numerics_manifest is not None:
            numerics_audit = audit_response_numerics(
                answer_text or raw,
                numerics_manifest,
                require_citation=numerics_require_citation(),
            )
            if numerics_audit_mode() == "block" and not numerics_audit.get("passed"):
                answer_text = apply_numerics_audit_to_answer(answer_text or raw, numerics_audit)
            elif numerics_audit_mode() == "warn" and not numerics_audit.get("passed"):
                yield json.dumps(
                    {
                        "event": "status",
                        "message": (
                            "数字合规审计告警："
                            + ",".join(numerics_audit.get("violations") or [])
                        ),
                    },
                    ensure_ascii=False,
                )

        assistant_row = append_message(sid, "assistant", answer_text or raw)

        answer = AgentAnswer(
            user_id=uid,
            model=provider.model,
            answer_text=answer_text or raw,
            evidence_items=evidence_items,
            referenced_evidence_ref_ids=cited,
            model_reply_raw=raw,
            tool_status_messages=pre_status + tool_status,
            tool_results=tool_results,
        )
        done_payload: Dict[str, Any] = {
            "event": "done",
            "session_id": sid,
            "model": provider.model,
            "answer": answer.model_dump(mode="json"),
            "assistant_message_id": assistant_row.id,
        }
        if audit_json:
            done_payload["data_pipeline_audit"] = audit_json
        if numerics_audit:
            done_payload["numerics_audit"] = numerics_audit

        def _emit_turn_complete() -> None:
            shadow_payload: Dict[str, Any] = {}
            if shadow_handle is not None:
                shadow_payload = shadow_handle.collect()
            executed = [str(t.get("tool") or "") for t in tool_results]
            pva = compute_plan_vs_actual(
                plan,
                raw_user_message=msg,
                current_user_message=str(chat_messages[-1].get("content") or "")
                if chat_messages
                else msg,
                tools_executed=executed,
                snapshot_in_user=SNAPSHOT_MARKER in str(chat_messages[-1].get("content") or ""),
                slot_contents=slot_contents,
                tier0_text=tier0_supp,
                tier0_integrity=tier0_integrity,
            )
            telemetry = build_harness_telemetry(
                user_id=uid,
                user_message=msg,
                plan_profile=plan.profile,
                background_block_nonempty=bool(background_block.strip()),
            )
            h_done = HarnessTurnInputs(
                user_id=uid,
                session_id=sid or "",
                user_message_id=user_row.id,
                model=model.strip(),
                user_message=msg,
                question_type=qtype,
                temporal_years=list(temporal_intent.explicit_years or []),
                ldl_authority=ldl_authority,
                supplement_bg=background_block,
                forced_dossier=forced_dossier,
                audit_warn=audit_warn,
                recalled_snippets=recalled_snippets,
                patient_state=patient_state,
                augmented_user_message=augmented_message,
                raw_supplemental=supplemental_raw_for_report,
                system_after_stack=str(chat_messages[0].get("content", ""))
                if chat_messages
                else "",
                system_content_max=SYSTEM_CONTENT_MAX_CHARS,
                inject_wearable_snapshot=plan_allows_heuristic_snapshot(plan),
                build_forced_dossier=build_forced_dossier,
                has_snapshot=SNAPSHOT_MARKER in augmented_message,
                fast_path=fast_path,
                use_tools_runtime=runtime_mode in ("tool_loop", "catalog_tool_loop"),
                tool_results=tool_results,
                chat_messages=chat_messages,
                mode="turn_complete",
                turn_plan=plan,
                plan_vs_actual=pva,
                tier0_integrity=tier0_integrity,
                runtime_mode=runtime_mode,
                numerics_manifest=numerics_manifest.to_dict() if numerics_manifest else {},
                numerics_manifest_block=manifest_block,
                intent_route=telemetry["intent_route"],
                catalog_existence=telemetry["catalog_existence"],
                dynamic_slots=telemetry["dynamic_slots"],
                numerics_audit=numerics_audit,
                metadata_catalog_block=slot_contents.get("METADATA_CATALOG") or "",
                shadow_routing=shadow_payload,
            )
            emit_harness_build_report(build_harness_report(h_done))

        _emit_harness("as_is_post_tools", chat_messages, tool_results)
        _emit_turn_complete()

        if parsed_payload:
            done_payload["ingest_payload"] = parsed_payload
            done_payload["user_message_id"] = user_row.id
        yield json.dumps(done_payload, ensure_ascii=False)
    except Exception as exc:
        logger.exception("stream_pha_chat failed")
        yield json.dumps({"event": "error", "message": str(exc)}, ensure_ascii=False)
