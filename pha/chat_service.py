"""PHA streaming chat orchestration (SSE) with session persistence."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

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
    user_message_needs_attachment_recall,
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
    recall_focus_user_block: str = "",
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

    recall_block = (recall_focus_user_block or "").strip()
    if recall_block:
        messages.append({"role": "user", "content": recall_block})

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
    from pha.vision_label_ledger import enrich_parsed_payload

    ocr_pre = (parsed.get("ocr_text") or "").strip()
    parsed = enrich_parsed_payload(
        parsed,
        ocr_text=ocr_pre,
        filename=attachment_name or Path(attachment_path).name,
    )
    metrics = list(parsed.get("metrics") or [])
    narratives = list(parsed.get("narratives") or [])
    if metrics:
        parsed["ingest_status"] = "manual_required"
    elif auto_ingest and narratives:
        ing = ingest_parsed_payload(
            user_id=uid,
            report_date=parsed.get("report_date") or "",
            hospital=parsed.get("hospital", ""),
            source_filename=parsed.get("source_filename") or (attachment_name or Path(attachment_path).name),
            source_kind="chat_attach_parse_api",
            metrics=[],
            narratives=narratives,
            vision_raw=parsed,
            vision_model="",
        )
        parsed["ingest"] = ing
        parsed["ingest_status"] = "auto_ok"
    else:
        parsed["ingest_status"] = "auto_skipped"
    from pha.perception_worker import finalize_attachment_parse

    return finalize_attachment_parse(
        parsed,
        attachment_path_count=1,
        parts=[parsed],
        client_parse_reuse=False,
    )


def compute_attachment_ingest_status(parsed: Optional[Dict[str, Any]]) -> str:
    """SSE/UI: manual_required when lab metrics present and not yet ingested."""
    if not parsed:
        return "auto_skipped"
    if parsed.get("ingest_status"):
        return str(parsed["ingest_status"])
    metrics = list(parsed.get("metrics") or [])
    if not metrics:
        return "auto_skipped"
    ing = parsed.get("ingest") or {}
    stored = int(ing.get("metrics_stored") or 0)
    if stored >= len(metrics) and stored > 0:
        return "auto_ok"
    if stored > 0:
        return "auto_partial"
    return "manual_required"


def _ocr_text_from_attachment_bytes(raw: bytes, filename: str) -> str:
    try:
        from pha.vision_engine import image_file_to_png_list
        from pha.vision_ocr import tesseract_ocr_png

        pages = image_file_to_png_list(raw, filename=filename)
        ocr_chunks = [tesseract_ocr_png(p) for p in pages]
        return "\n\n".join(c for c in ocr_chunks if c).strip()
    except Exception:
        logger.debug("attachment ocr read skipped", exc_info=True)
        return ""


def _ocr_with_layout_regions(
    raw: bytes,
    filename: str,
) -> Tuple[str, List[Any], Dict[str, Any]]:
    """L0.2 layout_region crop + OCR arbitration (Wave 3). Falls back to full-page OCR."""
    try:
        from pha.layout_region import (
            layout_hints_from_regions,
            ocr_with_layout_regions,
        )
        from pha.vision_engine import image_file_to_png_list

        pages = image_file_to_png_list(raw, filename=filename)
        if not pages:
            return "", [], {}
        merged_parts: List[str] = []
        all_regions: List[Any] = []
        telem: Dict[str, Any] = {"layout_region_count": 0, "regions": []}
        for idx, page in enumerate(pages):
            text, regions, t = ocr_with_layout_regions(page, source_page_index=idx)
            if text:
                merged_parts.append(text)
            all_regions.extend(regions)
            telem["layout_region_count"] = int(telem.get("layout_region_count", 0)) + t.get(
                "layout_region_count",
                0,
            )
            telem.setdefault("regions", []).extend(t.get("regions") or [])
        telem["layout_hints"] = layout_hints_from_regions(all_regions)
        return "\n\n".join(merged_parts).strip(), all_regions, telem
    except Exception:
        logger.debug("layout_region ocr failed; full-page fallback", exc_info=True)
        return _ocr_text_from_attachment_bytes(raw, filename), [], {}


def _vision_model_available() -> bool:
    """Return True if at least one supported Ollama vision model is installed.

    Uses the same base URL resolution as other llm_provider helpers
    (OLLAMA_BASE_URL / OLLAMA_HOST / http://127.0.0.1:11434).
    """
    import os

    try:
        from pha.llm_provider import find_vision_model, list_ollama_installed_models

        base_url = (
            os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_HOST")
            or "http://127.0.0.1:11434"
        )
        installed = list_ollama_installed_models(base_url, timeout_seconds=5.0)
        return bool(find_vision_model(installed))
    except Exception:
        return False


def _extraction_looks_like_ocr_fallback(extraction: Any) -> bool:
    """True when vision page parse fell back to OCR-only supplement extraction."""
    if extraction is None:
        return True
    narratives = getattr(extraction, "narratives", None) or []
    cats = {str(getattr(n, "category", "") or "") for n in narratives}
    if "vision_raw_snippet" in cats:
        return True
    if not getattr(extraction, "results", None) and "unstructured_vision" in cats:
        return True
    return False


def _wearable_ocr_only_parse(
    *,
    ocr_text: str,
    filename: str,
    raw: bytes = b"",
    parse_channel: str = "ocr_only_no_vlm",
    perception_channel: str = "ocr_only",
    layout_telemetry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {
        "ocr_text": ocr_text,
        "vision_summary": "",
        "perception_channel": perception_channel,
        "parse_channel": parse_channel,
        "ingredient_rows": [],
        "metrics_parsed_count": 0,
        "ingest_status": "auto_skipped",
        "document_family": "wearable",
        "document_type": "apple_watch",
    }
    if layout_telemetry:
        parsed["layout_region_meta"] = layout_telemetry
    return _annotate_attachment_routing(
        parsed,
        raw=raw,
        filename=filename,
        ocr_text=ocr_text,
        layout_telemetry=layout_telemetry,
    )


def _supplement_ocr_only_parse(
    *,
    ocr_text: str,
    filename: str,
    user_id: str,
    message_id: Optional[int],
    auto_ingest: bool,
    raw: bytes = b"",
    parse_channel: str = "ocr_fallback",
    perception_channel: str = "ocr_only",
    layout_telemetry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from pha.vision_label_ledger import enrich_parsed_payload
    from pha.vision_supplement import (
        extraction_from_ocr_fallback,
        parsed_payload_from_extraction,
    )

    fname = filename or "attachment"
    ext = extraction_from_ocr_fallback(ocr_text)
    parsed = parsed_payload_from_extraction(
        ext,
        filename=fname,
        parse_channel=parse_channel,
    )
    parsed["ocr_text"] = ocr_text
    parsed["perception_channel"] = perception_channel
    parsed = enrich_parsed_payload(parsed, ocr_text=ocr_text, filename=fname)
    parsed["metrics_parsed_count"] = 0
    parsed["ingest_status"] = "auto_skipped"
    if auto_ingest and message_id is not None and parsed.get("narratives"):
        ing = _auto_ingest_attachment_payload(
            parsed,
            user_id=user_id,
            message_id=message_id,
            filename=fname,
        )
        parsed["ingest"] = ing
        parsed["ingest_status"] = "auto_ok" if ing else "auto_skipped"
    if layout_telemetry:
        parsed["layout_region_meta"] = layout_telemetry
    return _annotate_attachment_routing(
        parsed,
        raw=raw,
        filename=fname,
        ocr_text=ocr_text,
        layout_telemetry=layout_telemetry,
    )


def _annotate_attachment_routing(
    parsed: Dict[str, Any],
    *,
    raw: bytes,
    filename: str,
    ocr_text: str = "",
    layout_telemetry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from pha.perception_media import attach_perception_routing_metadata

    out = attach_perception_routing_metadata(
        parsed,
        raw=raw,
        filename=filename,
        ocr_text=ocr_text or str(parsed.get("ocr_text") or ""),
    )
    out["media_route"] = out.get("media_route") or "unknown"
    if layout_telemetry:
        out["layout_region_meta"] = layout_telemetry
        hints = layout_telemetry.get("layout_hints") or []
        if hints:
            existing = list(out.get("layout_hints") or [])
            for h in hints:
                if h not in existing:
                    existing.append(h)
            out["layout_hints"] = existing
    return out


def _vision_parse_attachment(
    path: str,
    filename: str,
    *,
    user_id: str = "default",
    message_id: Optional[int] = None,
    auto_ingest: bool = False,
) -> Dict[str, Any]:
    """
    Per-image perception: OCR classifies layout; wearable Lane-O skips VLM when OCR is actionable.
    """
    from pha.vision_engine import VisionReportParser
    from pha.vision_supplement import parsed_payload_from_extraction

    fname = filename or Path(path).name
    raw = Path(path).read_bytes()
    from pha.perception_media import (
        classify_document_family,
        detect_media_route,
        legacy_doc_kind_from_family,
    )

    media_route, _media_meta = detect_media_route(raw, fname)
    ocr_text, _layout_regions, _layout_telem = _ocr_with_layout_regions(raw, fname)
    doc_family = "unknown"
    if ocr_text:
        doc_family, _, _ = classify_document_family(ocr_text)
        doc_kind = legacy_doc_kind_from_family(doc_family)
    else:
        doc_kind = "other"

    from pha.perception_family import should_skip_vlm_for_wearable

    if should_skip_vlm_for_wearable(
        doc_kind=doc_kind,
        document_family=doc_family,
        ocr_text=ocr_text,
    ):
        logger.info("Wearable Lane-O: skip VLM for %s (doc_kind=%s)", fname, doc_kind)
        return _wearable_ocr_only_parse(
            ocr_text=ocr_text,
            filename=fname,
            raw=raw,
            parse_channel="wearable_lane_o",
            perception_channel="ocr_only",
            layout_telemetry=_layout_telem,
        )

    if not _vision_model_available():
        logger.warning(
            "No Ollama vision model; degraded OCR-only parse for %s (doc_kind=%s)",
            fname,
            doc_kind,
        )
        if doc_kind == "supplement_label":
            return _supplement_ocr_only_parse(
                ocr_text=ocr_text,
                filename=fname,
                user_id=user_id,
                message_id=message_id,
                auto_ingest=auto_ingest,
                raw=raw,
                parse_channel="ocr_only_no_vlm",
                layout_telemetry=_layout_telem,
            )
        if doc_kind == "apple_watch":
            return _wearable_ocr_only_parse(
                ocr_text=ocr_text,
                filename=fname,
                raw=raw,
                parse_channel="ocr_only_no_vlm",
                layout_telemetry=_layout_telem,
            )
        raise ValueError(
            "未检测到可用的 Ollama 视觉模型（需 llama3.2-vision 或 llava）。"
            "化验/报告解析无法仅依赖 OCR。",
        )

    try:
        resp = VisionReportParser().parse_upload(raw, filename=fname)
    except Exception as exc:
        logger.exception("VisionReportParser.parse_upload failed for %s", fname)
        if doc_kind == "supplement_label":
            return _supplement_ocr_only_parse(
                ocr_text=ocr_text,
                filename=fname,
                user_id=user_id,
                message_id=message_id,
                auto_ingest=auto_ingest,
                raw=raw,
                parse_channel="vision_failed_ocr_fallback",
                layout_telemetry=_layout_telem,
            )
        if doc_kind == "apple_watch":
            return _wearable_ocr_only_parse(
                ocr_text=ocr_text,
                filename=fname,
                raw=raw,
                parse_channel="vision_failed_ocr_fallback",
                layout_telemetry=_layout_telem,
            )
        raise

    extraction = resp.extraction
    vision_fallback = _extraction_looks_like_ocr_fallback(extraction)
    perception_channel: str = "ocr_only" if vision_fallback else "vision_structured"
    parse_channel = (
        "vision_failed_ocr_fallback"
        if vision_fallback
        else ("vision_supplement" if doc_kind == "supplement_label" else "vision_lab")
    )

    if doc_kind == "apple_watch":
        parsed = {
            "ocr_text": ocr_text,
            "vision_summary": (resp.summary_text or "").strip(),
            "perception_channel": perception_channel,
            "parse_channel": "vision_wearable",
            "vision_model": resp.vision_model,
            "ingredient_rows": [],
            "metrics_parsed_count": 0,
            "ingest_status": "auto_skipped",
        }
        return _annotate_attachment_routing(
            parsed,
            raw=raw,
            filename=fname,
            ocr_text=ocr_text,
            layout_telemetry=_layout_telem,
        )

    if doc_kind == "supplement_label":
        parsed = parsed_payload_from_extraction(
            extraction,
            filename=fname,
            parse_channel=parse_channel,
            vision_summary=(resp.summary_text or "").strip(),
        )
        parsed["ocr_text"] = ocr_text
        parsed["perception_channel"] = perception_channel
        parsed["vision_model"] = resp.vision_model
        from pha.vision_label_ledger import enrich_parsed_payload

        parsed = enrich_parsed_payload(parsed, ocr_text=ocr_text, filename=fname)
        parsed["metrics_parsed_count"] = 0
        parsed["ingest_status"] = "auto_skipped"
        if auto_ingest and message_id is not None and parsed.get("narratives"):
            ing = _auto_ingest_attachment_payload(
                parsed,
                user_id=user_id,
                message_id=message_id,
                filename=fname,
            )
            parsed["ingest"] = ing
            parsed["ingest_status"] = "auto_ok" if ing else "auto_skipped"
        return _annotate_attachment_routing(
            parsed,
            raw=raw,
            filename=fname,
            ocr_text=ocr_text,
            layout_telemetry=_layout_telem,
        )

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
    if ocr_text and doc_kind == "supplement_label":
        metrics = []

    parsed: Dict[str, Any] = {
        "metrics": metrics,
        "narratives": narratives,
        "report_date": report_date[:10] if report_date else "",
        "hospital": hospital,
        "source_filename": fname,
        "vision_summary": (resp.summary_text or "").strip(),
        "ocr_text": ocr_text,
        "perception_channel": perception_channel,
        "parse_channel": parse_channel,
        "vision_model": resp.vision_model,
    }
    metrics = list(parsed.get("metrics") or [])
    parsed["metrics_parsed_count"] = len(metrics)
    if metrics:
        parsed["ingest_status"] = "manual_required"
    elif auto_ingest and message_id is not None and narratives:
        ing = _auto_ingest_attachment_payload(
            parsed,
            user_id=user_id,
            message_id=message_id,
            filename=fname,
        )
        parsed["ingest"] = ing
        parsed["ingest_status"] = "auto_ok" if ing else "auto_skipped"
    else:
        parsed["ingest_status"] = "auto_skipped"
    return _annotate_attachment_routing(
        parsed,
        raw=raw,
        filename=fname,
        ocr_text=ocr_text,
        layout_telemetry=_layout_telem,
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
            base = "附件标签问答：定账与背景已预注入，不调用工具"
            return f"{base} · {attach_status_suffix}".strip(" ·") if attach_status_suffix else base
        return "本轮由 Harness 预注入证据，不调用工具"
    if runtime_mode == "model_no_tools":
        if attachment_qa:
            base = "附件标签问答：定账与背景已预注入，单轮流式答复"
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
    attachment_paths: Optional[List[str]] = None,
    attachment_names: Optional[List[str]] = None,
    attachment_parsed_parts: Optional[List[Dict[str, Any]]] = None,
) -> Iterator[str]:
    """
    Yield SSE payloads (JSON per ``data:`` line content):
    status | delta | done | error
    """
    uid = (user_id or "default").strip() or "default"
    msg = (user_message or "").strip()
    _paths_in = [p.strip() for p in (attachment_paths or []) if (p or "").strip()]
    if not _paths_in and (attachment_path or "").strip():
        _paths_in = [(attachment_path or "").strip()]
    _names_in = [n.strip() for n in (attachment_names or []) if (n or "").strip()]
    if not msg and not _paths_in:
        yield json.dumps({"event": "error", "message": "消息不能为空"}, ensure_ascii=False)
        return
    if not msg and _paths_in:
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

    att_path = _paths_in[0] if len(_paths_in) == 1 else json.dumps(_paths_in, ensure_ascii=False)
    att_name = (
        _names_in[0]
        if len(_names_in) == 1
        else " + ".join(_names_in[:4])
        if _names_in
        else (attachment_name or "").strip()
    )
    raw_user_msg = (msg or "").strip()
    parsed_payload: Optional[Dict[str, Any]] = None
    attach_parse_failed = False
    attachment_asset_qa = False
    attach_status_suffix = ""
    attach_client_reuse = False
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

    if _paths_in:
        yield json.dumps(
            {
                "event": "status",
                "message": f"📎 正在 OCR + 视觉解析（{len(_paths_in)} 个附件）…",
            },
            ensure_ascii=False,
        )
        try:
            from pha.vision_label_ledger import enrich_parsed_payload, merge_parsed_payloads
            from pha.perception_family import (
                WEARABLE_FAMILY,
                coerce_wearable_family,
                parts_should_finalize_as_wearable,
                requires_label_ledger_v1,
            )

            _parsed_parts: List[Dict[str, Any]] = []
            _client_parts = [
                dict(p)
                for p in (attachment_parsed_parts or [])
                if isinstance(p, dict)
            ]
            # Chat send must be server-authoritative: client-side parse can race
            # (user sends before 2nd image parse completes) or carry stale single-image ledger.
            # Never reuse client-side parse for attachments: server Vision+merge is authoritative.
            _use_client = False
            attach_client_reuse = _use_client
            for _i, _p in enumerate(_paths_in):
                _n = _names_in[_i] if _i < len(_names_in) else Path(_p).name
                if len(_paths_in) > 1:
                    yield json.dumps(
                        {
                            "event": "status",
                            "message": f"📎 正在解析第 {_i + 1}/{len(_paths_in)} 张：{_n}…",
                            "attachment_index": _i + 1,
                            "attachment_total": len(_paths_in),
                        },
                        ensure_ascii=False,
                    )
                if _use_client and _i < len(_client_parts):
                    _cp = _client_parts[_i]
                    if not (_cp.get("ocr_text") or "").strip():
                        _parsed_parts.append(
                            _vision_parse_attachment(
                                _p,
                                _n,
                                user_id=uid,
                                message_id=user_row.id,
                                auto_ingest=(len(_paths_in) == 1),
                            ),
                        )
                    else:
                        _parsed_parts.append(
                            enrich_parsed_payload(
                                _cp,
                                ocr_text=str(_cp.get("ocr_text") or ""),
                                filename=_n,
                            ),
                        )
                else:
                    _parsed_parts.append(
                        coerce_wearable_family(
                            _vision_parse_attachment(
                                _p,
                                _n,
                                user_id=uid,
                                message_id=user_row.id,
                                auto_ingest=(len(_paths_in) == 1),
                            ),
                        ),
                    )
            if len(_parsed_parts) > 1 and parts_should_finalize_as_wearable(_parsed_parts):
                parsed_payload = {
                    "ocr_text": "\n\n".join(
                        str(p.get("ocr_text") or "") for p in _parsed_parts
                    ),
                    "document_family": WEARABLE_FAMILY,
                    "document_type": "apple_watch",
                }
                for _pp in _parsed_parts:
                    if str(_pp.get("perception_channel") or "") == "vision_structured":
                        parsed_payload["perception_channel"] = "vision_structured"
                        break
            else:
                parsed_payload = (
                    merge_parsed_payloads(_parsed_parts)
                    if len(_parsed_parts) > 1
                    else _parsed_parts[0]
                )
            from pha.perception_worker import finalize_attachment_parse

            _best_channel = "ocr_only"
            for _pp in _parsed_parts:
                if str(_pp.get("perception_channel") or "") == "vision_structured":
                    _best_channel = "vision_structured"
                    break
            parsed_payload = finalize_attachment_parse(
                parsed_payload,
                attachment_path_count=len(_paths_in),
                parts=_parsed_parts,
                client_parse_reuse=False,
                perception_channel=_best_channel,  # type: ignore[arg-type]
                user_message=raw_user_msg,
            )
            if (
                requires_label_ledger_v1(parsed_payload)
                and len(_paths_in) >= 2
                and int(parsed_payload.get("attachment_count") or 0) < len(_paths_in)
            ):
                parsed_payload["parse_confidence"] = "low"
                _rr = list(parsed_payload.get("reject_reasons") or [])
                if "merge_incomplete" not in _rr:
                    _rr.append("merge_incomplete")
                parsed_payload["reject_reasons"] = _rr
            _fam_attach = str(parsed_payload.get("document_family") or "")
            _ing_n = len(parsed_payload.get("ingredient_rows") or [])
            _wear_metric_n = len(
                parsed_payload.get("wearable_metrics") or parsed_payload.get("metrics") or [],
            )
            logger.info(
                "[Chat Attach] paths=%s merged_parts=%s ingredients=%s wearable_metrics=%s client_reuse=%s",
                len(_paths_in),
                len(_parsed_parts),
                _ing_n,
                _wear_metric_n,
                _use_client,
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
            _ac = int(parsed_payload.get("attachment_count") or len(_paths_in))
            if _fam_attach == "wearable":
                if _ac > 1 or len(_paths_in) > 1:
                    attach_status_suffix = (
                        f"已合并 {max(_ac, len(_paths_in))} 张·穿戴 KPI {_wear_metric_n} 项"
                    )
                elif _wear_metric_n:
                    attach_status_suffix = f"穿戴 KPI {_wear_metric_n} 项"
            elif _ac > 1 or len(_paths_in) > 1:
                attach_status_suffix = (
                    f"已合并 {max(_ac, len(_paths_in))} 张"
                    f"·定账 {_ing_n} 行"
                    + ("·复用选图解析" if _use_client else "")
                )
            elif _ing_n:
                attach_status_suffix = f"定账 {_ing_n} 行"
            if (parsed_payload.get("parse_confidence") or "") == "low":
                _reasons = parsed_payload.get("reject_reasons") or []
                _fam_low = str(parsed_payload.get("document_family") or "")
                _low_hint = (
                    "：截图 KPI 未完全识别，将结合数仓对比"
                    if _fam_low == "wearable"
                    else "：回答将避免编造剂量，建议补拍 Supplement Facts 面"
                )
                yield json.dumps(
                    {
                        "event": "status",
                        "message": (
                            "⚠️ 定账置信度偏低"
                            + (f"（{','.join(_reasons[:3])}）" if _reasons else "")
                            + _low_hint
                        ),
                    },
                    ensure_ascii=False,
                )
            _ledger_prev = (parsed_payload.get("label_ledger") or parsed_payload.get("vision_summary") or "")
            _prev_cap = int(os.environ.get("PHA_CHAT_ATTACH_PREVIEW_MAX", "2200"))
            preview = _ledger_prev[:_prev_cap] if _ledger_prev else ""
            if preview:
                msg = f"{msg}\n\n【附件定账摘要 · 供核对】\n{preview}"
        except Exception as exc:
            logger.exception("chat attachment vision parse failed")
            attach_parse_failed = True
            ocr_text = ""
            try:
                from pha.vision_engine import image_file_to_png_list
                from pha.vision_ocr import tesseract_ocr_png
                from pha.vision_supplement import (
                    extraction_from_ocr_fallback,
                    parsed_payload_from_extraction,
                )

                pages = image_file_to_png_list(Path(att_path).read_bytes(), filename=att_name)
                if pages:
                    ocr_text = tesseract_ocr_png(pages[0])
                fb_ext = extraction_from_ocr_fallback(ocr_text, raw_model_snippet=str(exc)[:2000])
                parsed_payload = parsed_payload_from_extraction(
                    fb_ext,
                    filename=att_name or Path(att_path).name,
                    parse_channel="ocr_fallback",
                )
                update_message_parsed_json(
                    user_row.id,
                    json.dumps(parsed_payload, ensure_ascii=False),
                )
                preview = (parsed_payload.get("vision_summary") or "")[:800]
                if preview:
                    msg = f"{msg}\n\n【附件 OCR 兜底摘要 · 未写入化验指标】\n{preview}"
                attach_parse_failed = False
            except Exception:
                logger.exception("chat attachment OCR fallback failed")
            try:
                from pha.chat_background import store_unstructured_vision_note

                store_unstructured_vision_note(
                    uid,
                    ocr_text=ocr_text,
                    error=str(exc),
                    source_message_id=user_row.id,
                    session_id=sid or "",
                )
            except Exception:
                logger.exception("store_unstructured_vision_note failed")
            try:
                record_chat_attachment_parse_failure(
                    uid,
                    attachment_path=att_path,
                    attachment_name=att_name or Path(att_path).name,
                    error=str(exc),
                )
            except Exception:
                logger.exception("record_chat_attachment_parse_failure failed")
            if attach_parse_failed:
                yield json.dumps(
                    {
                        "event": "attach_error",
                        "code": "vision_parse_failed",
                        "message": str(exc)[:800],
                    },
                    ensure_ascii=False,
                )
                yield json.dumps(
                    {
                        "event": "status",
                        "message": f"附件解析失败（已保留原文件）: {exc}",
                    },
                    ensure_ascii=False,
                )
            else:
                yield json.dumps(
                    {
                        "event": "status",
                        "message": "⚠️ Vision JSON 失败，已用 OCR 兜底写入背景（未污染化验菜单）",
                    },
                    ensure_ascii=False,
                )

    if not parsed_payload and not _paths_in and sid:
        from pha.chat_storage import get_latest_session_attachment_parse
        from pha.perception_family import ocr_suggests_wearable_ui

        if user_message_needs_wearable_query(raw_user_msg) or user_message_needs_attachment_recall(
            raw_user_msg,
        ):
            _prev_parse = get_latest_session_attachment_parse(sid or "")
            if _prev_parse:
                parsed_payload = _prev_parse
                if not (parsed_payload.get("wearable_metrics") or []):
                    _ocr = str(parsed_payload.get("ocr_text") or "")
                    if _ocr and ocr_suggests_wearable_ui(_ocr):
                        from pha.wearable_snapshot_v1 import finalize_wearable_attachment

                        parsed_payload = finalize_wearable_attachment(
                            {
                                "ocr_text": _ocr,
                                "document_family": "wearable",
                                "document_type": "apple_watch",
                            },
                            attachment_count=max(
                                1,
                                int(parsed_payload.get("attachment_count") or 1),
                            ),
                            user_message=raw_user_msg,
                        )
                attach_status_suffix = "复用上一轮附件解析"
                yield json.dumps(
                    {
                        "event": "status",
                        "message": "📎 本轮未附带图片，已复用本会话最近一次附件解析结果",
                    },
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

        from pha.attachment_asset_qa import (
            build_lipid_bridge_snapshot_block,
            focus_tokens_from_text,
            is_attachment_qa_profile,
            resolve_attachment_qa_mode,
        )
        from pha.session_turn_focus import (
            consume_session_turn_focus,
            focus_summary_from_parsed,
            get_session_turn_focus,
            revive_session_turn_focus_for_message,
            save_session_turn_focus,
        )

        _has_parse = False
        from pha.perception_family import attachment_parse_is_actionable, family_from_parsed

        if parsed_payload:
            _has_parse = attachment_parse_is_actionable(parsed_payload)
        _existing_focus = get_session_turn_focus(sid or "")
        _route_focus = revive_session_turn_focus_for_message(sid or "", raw_user_msg) or _existing_focus
        _focus_tokens = list(_route_focus.focus_tokens) if _route_focus else []
        _attach_family = family_from_parsed(parsed_payload) if parsed_payload else ""
        if user_message_needs_wearable_query(raw_user_msg) and _route_focus and _route_focus.active:
            _prev_doc = str(_route_focus.document_type or "").strip().lower()
            if _prev_doc in ("supplement", "supplement_label", ""):
                from pha.session_turn_focus import clear_session_turn_focus

                clear_session_turn_focus(sid or "")
                _route_focus = None
                _focus_tokens = []
        _qa_mode = resolve_attachment_qa_mode(
            raw_user_msg,
            has_parsed_attachment=_has_parse,
            session_focus_active=bool(_route_focus and _route_focus.active),
            focus_tokens=_focus_tokens,
            document_family=_attach_family,
        )
        from pha.wearable_harness import (
            is_wearable_screenshot_profile,
            should_use_wearable_screenshot_review,
        )

        wearable_screenshot_review = should_use_wearable_screenshot_review(
            document_family=_attach_family,
            has_parsed_attachment=_has_parse,
            user_message=raw_user_msg,
        )
        attachment_asset_qa = (
            not wearable_screenshot_review
            and _qa_mode
            in (
                "initial",
                "lipid_bridge",
                "episodic_bridge",
            )
        )
        session_focus_row = None
        if _qa_mode in ("lipid_bridge", "episodic_bridge"):
            session_focus_row = consume_session_turn_focus(sid or "")
            if not session_focus_row and _route_focus:
                session_focus_row = _route_focus
        elif _has_parse and parsed_payload:
            _fsum = focus_summary_from_parsed(parsed_payload)
            _ftoks = focus_tokens_from_text(_fsum)
            _doc_type = str(
                parsed_payload.get("document_family")
                or parsed_payload.get("document_type")
                or "unknown",
            )
            if _doc_type not in ("wearable", "apple_watch") and _attach_family != "wearable":
                if (
                    _route_focus
                    and _route_focus.active
                    and _route_focus.document_type
                    and _doc_type != _route_focus.document_type
                    and _doc_type in ("wearable", "supplement", "lab")
                ):
                    from pha.session_turn_focus import clear_session_turn_focus

                    clear_session_turn_focus(sid or "")
                save_session_turn_focus(
                    sid or "",
                    focus_summary=_fsum,
                    document_type=_doc_type,
                    focus_tokens=_ftoks,
                )
            if attachment_asset_qa:
                session_focus_row = get_session_turn_focus(sid or "")

        plan = build_turn_evidence_plan(
            msg,
            is_temporal_dynamic=is_temporal_dynamic,
            attachment_asset_qa=attachment_asset_qa,
            attachment_qa_mode=_qa_mode if attachment_asset_qa else "initial",
            wearable_screenshot_review=wearable_screenshot_review,
        )
        qtype = plan.legacy_question_type

        ldl_authority = ""
        if "LDL_AUTHORITY" in plan.all_slots:
            if _qa_mode == "lipid_bridge":
                ldl_authority = build_lipid_bridge_snapshot_block(uid)
            else:
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

        session_focus_summary = ""
        attachment_label_block = ""
        wearable_snapshot_block = ""
        wearable_compare_table_block = ""
        wearable_compare_table_obj = None
        wearable_metric_probe_payload: Optional[Dict[str, Any]] = None
        data_availability_block = ""
        if parsed_payload and is_wearable_screenshot_profile(plan.profile):
            from pha.wearable_snapshot_v1 import build_wearable_snapshot_tier0_block
            from pha.wearable_compare_table_v1 import (
                build_wearable_compare_table_v1,
                persist_compare_table_to_parsed,
            )

            wearable_snapshot_block = build_wearable_snapshot_tier0_block(parsed_payload)
            if "WEARABLE_COMPARE_TABLE" in plan.slots_tier0:
                wearable_compare_table_obj = build_wearable_compare_table_v1(
                    parsed_payload,
                    user_id=uid,
                    user_message=raw_user_msg,
                )
                wearable_compare_table_block = wearable_compare_table_obj.to_llm_markdown()
                persist_compare_table_to_parsed(parsed_payload, wearable_compare_table_obj)
                if user_row.id and (_paths_in or parsed_payload.get("wearable_metrics")):
                    update_message_parsed_json(
                        user_row.id,
                        json.dumps(parsed_payload, ensure_ascii=False),
                    )
                from dataclasses import replace
                from pha.wearable_harness import build_wearable_screenshot_review_task

                plan = replace(
                    plan,
                    task_text=build_wearable_screenshot_review_task(wearable_compare_table_obj),
                )
        elif parsed_payload:
            attachment_label_block = focus_summary_from_parsed(parsed_payload)
        from pha.intent_gates import user_message_needs_wearable_query
        from pha.wearable_metric_probe import (
            infer_requested_compare_metric_ids,
            probe_wearable_metric_needs,
        )

        _probe_compare = wearable_screenshot_review or (
            bool(infer_requested_compare_metric_ids(raw_user_msg))
            and user_message_needs_wearable_query(raw_user_msg)
        )
        if _probe_compare:
            wearable_metric_probe_payload = probe_wearable_metric_needs(uid, raw_user_msg)
            _probe_msg = str(wearable_metric_probe_payload.get("user_message_zh") or "").strip()
            if _probe_msg and not wearable_metric_probe_payload.get("all_ready"):
                yield json.dumps(
                    {
                        "event": "status",
                        "message": f"📦 数据探针：{_probe_msg}",
                        "open_data_drawer": bool(
                            wearable_metric_probe_payload.get("ingest_modules"),
                        ),
                    },
                    ensure_ascii=False,
                )
        if is_attachment_qa_profile(plan.profile):
            from pha.attachment_asset_qa import build_attachment_supplement_context

            focus_text = attachment_label_block or raw_user_msg
            from pha.data_availability import build_data_availability_block
            from pha.attachment_asset_qa import attachment_evidence_scope_enabled

            background_block = build_attachment_supplement_context(
                uid,
                focus_text=focus_text,
                session_focus_summary="",
                include_causal_anchor=(_qa_mode == "lipid_bridge"),
                user_message=msg,
            )
            data_availability_block = (
                build_data_availability_block(uid, user_message=msg)
                if attachment_evidence_scope_enabled()
                else ""
            )
        else:
            background_block = build_user_background_block(uid, user_message=msg)

        recalled_snippets = ""
        if not is_attachment_qa_profile(plan.profile):
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
            if is_wearable_screenshot_profile(plan.profile):
                from pha.harness_plan import build_wearable_90d_macro_summary_block

                wearable_summary = build_wearable_90d_macro_summary_block(uid, msg)
            else:
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
            manifest_block = format_manifest_tier0_block(numerics_manifest, profile=plan.profile)

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
            "ATTACHMENT_LABEL": attachment_label_block,
            "WEARABLE_SNAPSHOT": wearable_snapshot_block,
            "WEARABLE_COMPARE_TABLE": wearable_compare_table_block,
            "DATA_AVAILABILITY": data_availability_block if is_attachment_qa_profile(plan.profile) else "",
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

        recall_focus_block = ""
        _focus_active = bool(
            attachment_asset_qa
            or wearable_screenshot_review
            or (_route_focus and _route_focus.active)
            or (session_focus_row and session_focus_row.active),
        )
        if sid and _focus_active:
            from pha.active_recall_ledger import (
                build_recall_focus_block,
                sync_ledger_after_turn,
            )

            _ledger = sync_ledger_after_turn(
                sid,
                parsed_payload=parsed_payload if _has_parse else None,
                slot_contents=slot_contents,
                user_message=msg,
                profile=plan.profile,
                focus_tokens=_focus_tokens,
                source_turn=2 if _qa_mode in ("episodic_bridge", "lipid_bridge") else 1,
                focus_active=True,
            )
            recall_focus_block = build_recall_focus_block(
                _ledger,
                parse_confidence=str(
                    (parsed_payload or {}).get("parse_confidence") or "",
                ),
            )
            slot_contents["RECALL_FOCUS"] = recall_focus_block

        tier0_supp, tier1_supp, _missing_slots, tier0_integrity = assemble_tiered_supplemental(
            plan=plan,
            slot_contents=slot_contents,
        )
        if is_attachment_qa_profile(plan.profile):
            from pha.attachment_asset_qa import ATTACHMENT_QA_SOUL_ADDENDUM

            tier1_supp = (
                f"{ATTACHMENT_QA_SOUL_ADDENDUM.strip()}\n\n---\n\n{tier1_supp}".strip()
                if tier1_supp
                else ATTACHMENT_QA_SOUL_ADDENDUM.strip()
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
            if not is_wearable_screenshot_profile(plan.profile):
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

        if is_attachment_qa_profile(plan.profile):
            from pha.attachment_asset_qa import PHA_ATTACHMENT_SOUL_MINIMAL

            soul_base = PHA_ATTACHMENT_SOUL_MINIMAL
        elif is_wearable_screenshot_profile(plan.profile):
            from pha.wearable_harness import PHA_WEARABLE_SOUL_MINIMAL

            soul_base = PHA_WEARABLE_SOUL_MINIMAL
        else:
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
            recall_focus_user_block=recall_focus_block,
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
            telemetry["intent_route"]["attachment_qa_mode"] = (
                _qa_mode if attachment_asset_qa else "none"
            )
            if session_focus_row is not None:
                telemetry["intent_route"]["session_focus_turns_remaining"] = int(
                    session_focus_row.turns_remaining,
                )
            if parsed_payload:
                from pha.telemetry_attachment import build_attachment_route_telemetry

                telemetry["intent_route"].update(
                    build_attachment_route_telemetry(
                        parsed_payload,
                        attachment_path_count=len(_paths_in) if _paths_in else 0,
                        client_parse_reuse=bool(
                            parsed_payload.get("client_parse_reuse") or attach_client_reuse
                        ),
                        attachment_qa_mode=_qa_mode if attachment_asset_qa else "none",
                    ),
                )
                telemetry["intent_route"]["vision_parse_confidence"] = str(
                    parsed_payload.get("parse_confidence") or "",
                )
                telemetry["intent_route"]["document_type"] = str(
                    parsed_payload.get("document_type") or "",
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
        skip_llm = False
        _det = ""
        if attachment_asset_qa and parsed_payload:
            from pha.attachment_asset_qa import maybe_deterministic_attachment_reply

            _det = maybe_deterministic_attachment_reply(
                parsed_payload,
                qa_mode=_qa_mode,
                attachment_path_count=len(_paths_in),
                raw_user_message=raw_user_msg,
            )
            if _det:
                skip_llm = True
                yield json.dumps(
                    {
                        "event": "status",
                        "message": "定账置信度偏低：已跳过模型臆测，返回核对指引",
                    },
                    ensure_ascii=False,
                )
        elif wearable_screenshot_review and parsed_payload:
            from pha.wearable_harness import maybe_deterministic_wearable_reply

            _det = maybe_deterministic_wearable_reply(
                parsed_payload,
                raw_user_message=raw_user_msg,
            )
            if _det:
                skip_llm = True
                yield json.dumps(
                    {
                        "event": "status",
                        "message": "穿戴截图定账不足：已跳过模型臆测，返回核对指引",
                    },
                    ensure_ascii=False,
                )

        use_tools = runtime_mode == "tool_loop"
        use_catalog = runtime_mode == "catalog_tool_loop"
        if skip_llm:
            _det_text = _det
            full_parts.append(_det_text)
            yield json.dumps({"event": "delta", "delta": _det_text}, ensure_ascii=False)
        elif fast_path:
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
            post_manifest_block = format_manifest_tier0_block(numerics_manifest, profile=plan.profile)
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
            status_msg = _runtime_status_message(
                runtime_mode,
                attachment_qa=attachment_asset_qa,
                attach_status_suffix=attach_status_suffix,
            )
            if status_msg:
                yield json.dumps({"event": "status", "message": status_msg}, ensure_ascii=False)
            for delta in provider.stream_chat_messages(messages=chat_messages):
                full_parts.append(delta)
                yield json.dumps({"event": "delta", "delta": delta}, ensure_ascii=False)

        raw = "".join(full_parts)
        answer_text, cited = _parse_cited_refs(raw)
        if is_attachment_qa_profile(plan.profile):
            from pha.presentation_filter import polish_user_visible_reply

            polished = polish_user_visible_reply(answer_text or raw)
            if polished:
                answer_text = polished

        numerics_audit: Dict[str, Any] = {}
        compare_table_audit: Dict[str, Any] = {}
        if wearable_screenshot_review and wearable_compare_table_obj is not None:
            from pha.wearable_compare_table_v1 import apply_compare_table_fallback_if_needed
            from pha.wearable_presentation import polish_wearable_user_visible_reply

            answer_text, compare_table_audit = apply_compare_table_fallback_if_needed(
                answer_text or raw,
                wearable_compare_table_obj,
                user_message=raw_user_msg,
            )
            answer_text = polish_wearable_user_visible_reply(answer_text or raw)
            if compare_table_audit.get("fallback_applied"):
                logger.info(
                    "[Wearable Compare Audit] fallback violations=%s tier0_chars=%s advisory_chars=%s",
                    compare_table_audit.get("violations"),
                    len(compare_table_audit.get("tier0_markdown") or ""),
                    compare_table_audit.get("advisory_chars"),
                )
                _fb_mode = compare_table_audit.get("fallback_mode") or "replace"
                _fb_msg = (
                    "穿戴对比审计：对比数字已对齐系统表，并保留基于事实的健康建议"
                    if int(compare_table_audit.get("advisory_chars") or 0) > 0
                    else "穿戴对比审计：答复偏离 CompareTable，已回退至系统定账摘要"
                )
                if _fb_mode == "hybrid" and int(compare_table_audit.get("advisory_chars") or 0) > 0:
                    _fb_msg = (
                        "穿戴对比审计：对比数字已对齐系统表，并保留模型健康建议"
                    )
                yield json.dumps(
                    {"event": "status", "message": _fb_msg},
                    ensure_ascii=False,
                )
        elif numerics_manifest is not None:
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

        l3_focus_violation = False
        if attachment_asset_qa:
            from pha.telemetry_attachment import detect_l3_focus_violation

            l3_focus_violation = detect_l3_focus_violation(
                answer_text or raw,
                attachment_qa_mode=_qa_mode,
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
        if compare_table_audit:
            done_payload["compare_table_audit"] = compare_table_audit
        if wearable_metric_probe_payload:
            done_payload["wearable_metric_probe"] = wearable_metric_probe_payload

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
            telemetry["intent_route"]["attachment_qa_mode"] = (
                _qa_mode if attachment_asset_qa else "none"
            )
            if session_focus_row is not None:
                telemetry["intent_route"]["session_focus_turns_remaining"] = int(
                    session_focus_row.turns_remaining,
                )
            if parsed_payload:
                from pha.telemetry_attachment import build_attachment_route_telemetry

                telemetry["intent_route"].update(
                    build_attachment_route_telemetry(
                        parsed_payload,
                        attachment_path_count=len(_paths_in) if _paths_in else 0,
                        client_parse_reuse=bool(
                            parsed_payload.get("client_parse_reuse") or attach_client_reuse
                        ),
                        attachment_qa_mode=_qa_mode if attachment_asset_qa else "none",
                    ),
                )
                telemetry["intent_route"]["vision_parse_confidence"] = str(
                    parsed_payload.get("parse_confidence") or "",
                )
                telemetry["intent_route"]["document_type"] = str(
                    parsed_payload.get("document_type") or "",
                )
            telemetry["intent_route"]["l3_focus_violation"] = l3_focus_violation
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
            done_payload["ingest_status"] = compute_attachment_ingest_status(parsed_payload)
            done_payload["ingest_metrics_stored"] = int(
                (parsed_payload.get("ingest") or {}).get("metrics_stored") or 0,
            )
        yield json.dumps(done_payload, ensure_ascii=False)
    except Exception as exc:
        logger.exception("stream_pha_chat failed")
        yield json.dumps({"event": "error", "message": str(exc)}, ensure_ascii=False)
