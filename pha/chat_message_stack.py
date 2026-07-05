"""PHA chat message stack, history window, and system prompt constants."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from pha.agent import EvidenceItem
from pha.agent_tools import SNAPSHOT_MARKER
from pha.chat_context import recent_turns
from pha.chat_storage import list_messages
from pha.health_data import build_system_date_block, effective_query_reference_date

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

PHA_MEDICAL_SOUL_LITE_SYSTEM_PROMPT = """Role: You are PHA, a local personal health assistant. The user sent a brief social/acknowledgment message.
Rules: Reply in one natural sentence; do not expand the three-step clinical review; do not invent lab or wearable numbers; if the user suddenly asks for health data, prompt them to ask a focused health question."""

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
- Sound like an experienced, rigorous, insightful private physician. Match the response language per the RESPONSE LANGUAGE directive at the end of this system prompt.
- For medical terms and biomarkers, use "localized name (English abbreviation/Canonical Code)" in the active response language.
- Output clean standard Markdown only; no custom step wrappers like `[Step 1]`; use Markdown headings (e.g. `### Trend review`) for the three-step review when applicable."""

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
