"""Stage 3A.1 / 3A.2 / 3A.2.1 — Attachment Q&A, session focus, lipid bridge."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Set

# User-visible output (no harness arrow literals).
_GROUNDED_USER = (
    "   **结合您的情况**（最多 3 点）：每点先写一句依据（仅来自 Context 中「可引用依据」），"
    "再写一句推论；勿使用「【依据】」「→【推论】」「账本」「静态解构」等内部用语。"
    "至少 1 点须引用「可引用依据」档案行；若仅有标签信息，请写明「档案中未见直接相关记录」。"
)

ATTACHMENT_ASSET_QA_TASK = f"""【Turn task · Attachment single-asset Q&A】
The user uploaded a supplement/product label (see Tier0 label ledger block). Use natural conversational tone (language per RESPONSE LANGUAGE directive).

Must:
- **优先照抄对齐**「成分定账」各行（成分名 + 剂量）；勿将多种成分泛称为单一「卵磷脂」除非标签原文仅此一词。
- 若定账中无某成分，不得写出该成分剂量。
- **数据契约**：定账行无 amount/unit 时，禁止用常识填写剂量（不得写「建议每日 100mg」）；须写「标签未见该剂量」或请补拍 Facts 面。
- 用户若同时问「这是什么」与「对我有什么帮助」，**两段都必须写**，不得只答其一。

必须按顺序输出（可用小标题）：
1) **这款补充剂是什么**：必须逐行列出「成分定账」中**全部**成分（名称+剂量）；写清品牌（若有）。**禁止**仅用营销语（如 Supports Memory / Intercellular Communication）代替成分表。
2) **对我有什么帮助**：
{_GROUNDED_USER}
3) **注意什么**：与用药/禁忌相关的冲突有则写清，无则一句带过。

禁止：
- 复述用户已在档案中的整套补剂时间表或餐次方案。
- 展开血脂/HRV/穿戴大盘（除非本条明确问血脂且已注入血脂快照块）。
- 大段照抄「标签摘录」全文。
- 三步看诊法标题；全文约 450 字以内。"""

ATTACHMENT_EPISODIC_BRIDGE_TASK = f"""【Turn task · Focus asset · session continuation】
The user is still discussing the uploaded label asset (session focus active). Use natural conversational tone (language per RESPONSE LANGUAGE directive).

Must:
1) **简要确认焦点资产**（1–2 句，来自 ATTACHMENT_LABEL 定账；勿重复上一轮全文）。
2) **直接回答用户本条问题**（机理/风险/注意/是否还有帮助/与指标关系等）：
{_GROUNDED_USER}
   - 若问身体指标或改善方向：结合 DATA_AVAILABILITY、Patient State、Manifest、穿戴摘要（若已注入）；
   - 每条数字须对应可见证据行；无则写「库内暂无该指标」，禁止「缺乏基线」套话；
   - 允许结论「与焦点补剂关联弱/无关」。
3) 定账无剂量时禁止脑补具体 mg 数。

禁止：
- 切换成「补剂方案整体评审」或分段 a/b/c 更新建议。
- 反问用户「您为何补充/上传」等已知信息。
- 与焦点资产无关的既往补剂/药物清单。
- 三步看诊法标题；复述完整补剂时间表；将历史血脂改善归功于焦点补剂。

全文约 450 字以内。"""

ATTACHMENT_ASSET_QA_FOLLOWUP_TASK = ATTACHMENT_EPISODIC_BRIDGE_TASK

# C 层 · 短句延续（结构信号，非 L0 路由）：len≤120 且非血脂专问时追加。
EPISODIC_BRIDGE_NARROW_ADDENDUM = """
【短句延续 · 文风】
用户本条为短追问：优先 1 句确认焦点 + 直接答问，勿展开无关大盘；仍须满足上文证据与禁止项。"""

ATTACHMENT_LIPID_BRIDGE_TASK = f"""【Turn task · Focus asset × lipids】
The user is still discussing the prior label asset and asks about lipids/LDL. Answer in natural prose (language per RESPONSE LANGUAGE directive).

Must:
- 定账无剂量时禁止脑补具体 mg 数；不得把历史 LDL 改善归功于当轮标签。
1) **简要确认焦点资产**（1 句）。
{_GROUNDED_USER}
3) **明确回答「对降血脂是否有帮助」**：结合 Context 中「血脂快照」与「时空因果审查」；给出清晰立场（有帮助 / 帮助有限 / 不建议为降脂而服用）。

禁止：
- 把历史血脂改善归功于当轮新拍照的补充剂（见时空因果审查）。
- 三步看诊法、历年趋势大盘、要求用户再发化验单。
- 全文约 420 字以内。"""

CAUSAL_ANCHOR_BLOCK = """【时空因果审查 · 必读】
1. 历史化验改善若发生在用户讨论【当轮焦点资产】之前，主因应归因为档案中已有干预（如他汀、运动），不得归功于当轮新标签。
2. 当轮焦点资产视为「拟引入 / 尚未证明疗效」；不得声称「LDL 下降证明该补剂有效」。
3. 须区分：(a) 该成分对 LDL 的临床证据强度；(b) 用户个体是否已控脂；(c) 与现有方案是否重复。
4. 输出须明确立场，禁止含糊把历史数字与新品捆绑。"""

PHA_ATTACHMENT_SOUL_MINIMAL = """Role: You are PHA, a personal health assistant. This turn only discusses the uploaded label asset and injected profile snippets.
Rules: Natural conversational tone (per RESPONSE LANGUAGE directive); no three-step clinical review structure; no "missing baseline / static deconstruction" boilerplate; do not invent lab numbers."""

# Stage 3H · 通用兜底车道防御性 TASK（就图论事 Grounded）。来源 RFC §4.5。
ATTACHMENT_GROUNDED_REVIEW_TASK = """【Turn task · Attachment grounded review】
The user uploaded a health-related screenshot parsed into the attachment facts block (Tier0 ATTACHMENT_LABEL). Answer naturally (language per RESPONSE LANGUAGE directive).

Must:
1) 先 1–2 句复述这是什么（依据解析事实/标题，勿臆断报告类型）。
2) 仅依据「附件解析事实」块中的 results/narratives 行作答：逐项给出数值、单位、参考区间，
   并指出明显偏离参考区间的项；每条数字须能对应事实块某一行。
3) 若用户问到事实块中不存在的指标：明说「本张截图未见该项」，禁止编造。

严禁：
- 引用或推断任何**数仓历史数据**（历史血脂/HRV/睡眠/步数/补剂时间表）——本轮上下文已物理移除这些块。
- 使用「纵向趋势对账 / 多指标横向联动 / 硬核非药物干预」三步看诊模板标题。
- 把本张截图的指标归因到无关历史，或反向把历史数字套到本张图。
- 编造未在事实块中出现的数值、诊断或参考区间。

全文约 450 字以内。如需历史趋势对比，提示用户「先归档此报告后再问跨期趋势」。"""


def universal_attachment_lane_enabled() -> bool:
    """Stage 3H flag — universal grounded fallback lane for non-wearable attachments."""
    return (os.environ.get("PHA_UNIVERSAL_ATTACHMENT_LANE") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

ATTACHMENT_QA_SOUL_ADDENDUM = """
【附件单资产问答 · 输出宪法】
当轮只讨论「会话焦点资产」。必须包含「结合您的情况」且不超过 3 点。
严禁罗列与焦点无关的历史补剂/药物清单。无血脂快照时不要展开 Patient State 大表。"""

_ATTACHMENT_QA_RE = re.compile(
    r"是什么|什么意思|什么用|有什么用|有什么帮助|对我有什么|适合我吗|能吃吗|可以吃吗|"
    r"help me|what is this|what's this",
    re.I,
)
_HARD_LAB_PIVOT_RE = re.compile(
    r"对比历年|历年趋势|所有报告|整体趋势|历年所有|跨年对比|所有指标|历年.*血脂|"
    r"全部报告|完整趋势",
    re.I,
)
_LIPID_TOPIC_RE = re.compile(
    r"血脂|胆固醇|LDL|HDL|低密度|高密度|降脂|降血脂",
    re.I,
)
_INITIAL_BLOCK_RE = re.compile(
    r"血脂|胆固醇|LDL|HDL|化验|检验|报告|HRV|心率|穿戴|对比|趋势|另一张|换个|新图",
    re.I,
)
_FOCUS_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+./\-]{3,}|\d+(?:\.\d+)?\s*(?:mg|mcg|g|iu)\b", re.I)

_MAX_FOCUS_BG_CHARS = int(os.environ.get("PHA_ATTACHMENT_QA_BG_MAX_CHARS", "1400"))
_LIPID_SNAPSHOT_MAX_CHARS = int(os.environ.get("PHA_LIPID_BRIDGE_SNAPSHOT_MAX_CHARS", "400"))


def is_attachment_asset_qa_turn(
    raw_user_message: str,
    *,
    has_parsed_attachment: bool,
) -> bool:
    if not has_parsed_attachment:
        return False
    raw = (raw_user_message or "").strip()
    if not raw or len(raw) > 220:
        return False
    if _INITIAL_BLOCK_RE.search(raw):
        return False
    return bool(_ATTACHMENT_QA_RE.search(raw))


def is_lipid_bridge_turn(raw_user_message: str) -> bool:
    raw = (raw_user_message or "").strip()
    if not raw or len(raw) > 220:
        return False
    if _HARD_LAB_PIVOT_RE.search(raw):
        return False
    return bool(_LIPID_TOPIC_RE.search(raw))


def user_hits_focus_tokens(raw_user_message: str, focus_tokens: List[str]) -> bool:
    if not focus_tokens:
        return False
    low = (raw_user_message or "").lower()
    for tok in focus_tokens:
        t = (tok or "").strip()
        if len(t) >= 4 and t.lower() in low:
            return True
    return False


def build_episodic_bridge_task(raw_user_message: str = "") -> str:
    """
    C-layer TASK assembly for ``attachment_episodic_bridge`` profile.
    L0 routing does not branch on followup phrases — only structural length hint here.
    """
    raw = (raw_user_message or "").strip()
    task = ATTACHMENT_EPISODIC_BRIDGE_TASK
    if raw and len(raw) <= 120 and not is_lipid_bridge_turn(raw):
        task = f"{task}\n{EPISODIC_BRIDGE_NARROW_ADDENDUM}".strip()
    return task


def has_focus_anchor(
    *,
    session_focus_active: bool,
    focus_tokens: List[str],
    raw_user_message: str,
) -> bool:
    return session_focus_active or user_hits_focus_tokens(raw_user_message, focus_tokens)


def resolve_attachment_qa_mode(
    raw_user_message: str,
    *,
    has_parsed_attachment: bool,
    session_focus_active: bool,
    focus_tokens: Optional[List[str]] = None,
    document_family: str = "",
    has_attachment_paths: bool = False,
    parsed_payload: Optional[Dict[str, Any]] = None,
) -> str:
    """Return ``initial`` | ``lipid_bridge`` | ``episodic_bridge`` | ``grounded`` | ``none``.

    Stage 3H: non-wearable actionable attachments that match no specialized supplement
    lane fall into the universal ``grounded`` lane instead of being kicked out to ``none``
    (which previously degraded to the lifestyle/warehouse path → 张冠李戴).
    """
    from pha.intent_gates import user_message_needs_wearable_query

    fam = (document_family or "").strip().lower()
    # Wearable screenshots own a dedicated specialized lane (handled in routing).
    if fam == "wearable":
        return "none"

    grounded_ok = universal_attachment_lane_enabled() and bool(has_parsed_attachment)

    # 崩塌点 A 物理修复：lab/medication 不再一脚踢出，直接落通用兜底车道。
    # 例外（RFC §4.1）：用户显式跨年化验意图 → 让位 lab_cross_year 专用增强车道。
    if fam in ("lab", "medication"):
        if not grounded_ok:
            return "none"
        if _HARD_LAB_PIVOT_RE.search(raw_user_message or ""):
            return "none"
        return "grounded"

    if user_message_needs_wearable_query(raw_user_message or ""):
        return "none"

    tokens = list(focus_tokens or [])
    anchored = has_focus_anchor(
        session_focus_active=session_focus_active,
        focus_tokens=tokens,
        raw_user_message=raw_user_message,
    )

    if has_parsed_attachment and is_attachment_asset_qa_turn(
        raw_user_message,
        has_parsed_attachment=True,
    ):
        return "initial"

    if _HARD_LAB_PIVOT_RE.search(raw_user_message or ""):
        return "none"

    if anchored and is_lipid_bridge_turn(raw_user_message):
        return "lipid_bridge"

    # Episodic bridge: session focus TTL default lane (followup merged; no phrase whitelist).
    if anchored:
        raw = (raw_user_message or "").strip()
        if raw and len(raw) <= 320:
            return "episodic_bridge"

    # 长尾兜底：unknown/other 可执行附件 → 通用车道（绝不回落 lifestyle 数仓）。
    if grounded_ok and fam in ("unknown", "other"):
        return "grounded"

    # Stage 3H 结构信号强接管：附件在途 + 可落地事实 → 通用兜底（corrupt/异形 family）。
    from pha.perception_family import parsed_has_groundable_facts

    if (
        universal_attachment_lane_enabled()
        and has_attachment_paths
        and fam != "wearable"
        and parsed_has_groundable_facts(parsed_payload)
    ):
        if _HARD_LAB_PIVOT_RE.search(raw_user_message or ""):
            return "none"
        return "grounded"

    return "none"


def maybe_deterministic_attachment_reply(
    parsed: dict,
    *,
    qa_mode: str,
    attachment_path_count: int = 0,
    raw_user_message: str = "",
) -> str:
    """
  When perception confidence is low, return a fixed reply instead of invoking L3.
  Prevents amino-acid confabulation (e.g. Serine → 苏氨酸) on garbage OCR ledgers.
  """
    from pha.perception_family import supplement_deterministic_reply_allowed

    if not supplement_deterministic_reply_allowed(parsed):
        return ""
    if qa_mode not in ("initial", "episodic_bridge", "lipid_bridge"):
        return ""
    conf = str(parsed.get("parse_confidence") or "").strip().lower()
    reasons = list(parsed.get("reject_reasons") or [])
    ac = int(parsed.get("attachment_count") or 0)
    if conf != "low" and not reasons:
        return ""
    if attachment_path_count >= 2 and ac < attachment_path_count:
        reasons = list(dict.fromkeys(reasons + ["merge_incomplete"]))

    ledger = (parsed.get("label_ledger") or "").strip()
    rows = parsed.get("ingredient_rows") or []
    row_lines = []
    for r in rows[:12]:
        if isinstance(r, dict):
            nm = str(r.get("name") or "").strip()
            amt = str(r.get("amount") or "").strip()
            if nm:
                row_lines.append(f"- {nm}" + (f"：{amt}" if amt else ""))

    parts = [
        "我这边**没能从您上传的标签可靠读取成分**（识别置信度偏低），因此**不会**根据模糊 OCR 猜测成分（例如把磷脂酰丝氨酸说成普通「苏氨酸」）。",
    ]
    if attachment_path_count >= 2 and ac < attachment_path_count:
        parts.append(
            f"\n\n**可能原因**：本次只合并了 {ac}/{attachment_path_count} 张图的解析结果。"
            "请确认两张图都已选入且状态显示「已合并 2 张」后再发送。"
        )
    elif "likely_front_only_need_facts" in reasons or "missing_facts_panel" in reasons:
        parts.append(
            "\n\n**建议**：请同时上传 **正面 + Supplement Facts（营养成分表）背面** 两张图；"
            "尽量裁掉购物车/价格条，保证「Supplement Facts / 每份含量」表清晰。"
        )
    elif "incomplete_merge" in reasons or "missing_authoritative_panel" in reasons:
        parts.append(
            "\n\n**建议**：请补拍含 **成分表/营养成分表/Supplement Facts** 的一面，"
            "并确保每张图都已合并（状态栏显示「已合并 N 张」）。"
        )
    elif "facts_panel_unreadable" in reasons or "no_parseable_dose" in reasons:
        parts.append(
            "\n\n**建议**：成分表文字不清晰或剂量行无法识别，请换光线/角度重拍成分表区域。"
        )
    else:
        parts.append("\n\n**建议**：请重拍或补传 **Supplement Facts** 面，并等待状态栏显示「附件已就绪」后再提问。")

    if row_lines:
        parts.append("\n\n**系统当前仅能读到的片段（供核对，不可当作完整成分表）**：\n")
        parts.append("\n".join(row_lines))

    raw = (raw_user_message or "").strip()
    if qa_mode == "initial" and re.search(r"有什么帮助|有什么用", raw):
        parts.append(
            "\n\n在成分读取可靠之前，我**无法**负责任地回答「对我有什么帮助」。"
            "读取完整后我会结合您的档案分点说明。"
        )

    return "".join(parts).strip()


def focus_tokens_from_text(text: str, *, max_tokens: int = 48) -> List[str]:
    found: List[str] = []
    seen: Set[str] = set()
    for m in _FOCUS_TOKEN_RE.finditer(text or ""):
        tok = m.group(0).strip()
        key = tok.lower()
        if key in seen or len(tok) < 3:
            continue
        seen.add(key)
        found.append(tok)
        if len(found) >= max_tokens:
            break
    return found


def build_lipid_bridge_snapshot_block(user_id: str) -> str:
    """Latest LDL/HDL points only — compact for 7B slot budget."""
    from datetime import date

    from pha.health_data import effective_query_reference_date
    from pha.medical_storage import init_medical_schema
    from pha.sqlite_storage import _connect

    uid = (user_id or "default").strip() or "default"
    init_medical_schema()
    conn = _connect()
    lines: List[str] = ["【血脂快照 · 仅最新报告日 · 勿展开历年趋势】"]
    try:
        cur = conn.execute(
            """
            SELECT report_date, metric_code, metric_name, value, unit
            FROM medical_reports
            WHERE user_id = ?
              AND (
                UPPER(COALESCE(metric_code,'')) IN ('LDL','HDL','LDL-C')
                OR metric_name LIKE '%低密度%'
                OR metric_name LIKE '%高密度%'
                OR metric_name LIKE '%LDL%'
                OR metric_name LIKE '%HDL%'
              )
            ORDER BY report_date DESC
            LIMIT 12
            """,
            (uid,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        ref = effective_query_reference_date()
        y = ref.year if isinstance(ref, date) else date.today().year
        return (
            lines[0]
            + f"\n库内暂无 LDL/HDL 入库记录（参考年 {y}）。勿编造数值。"
        )[:_LIPID_SNAPSHOT_MAX_CHARS]

    by_date: dict[str, list] = {}
    for row in rows:
        d = str(row["report_date"] or "")[:10]
        if d:
            by_date.setdefault(d, []).append(row)
    for d in sorted(by_date.keys(), reverse=True)[:2]:
        for row in by_date[d]:
            name = row["metric_name"] or row["metric_code"] or "lipid"
            val = row["value"]
            unit = row["unit"] or ""
            lines.append(f"- {d} · {name}: {val} {unit}".strip())

    block = "\n".join(lines)
    if len(block) > _LIPID_SNAPSHOT_MAX_CHARS:
        block = block[: _LIPID_SNAPSHOT_MAX_CHARS - 1] + "…"
    return block


def build_focused_background_for_attachment_qa(
    user_id: str,
    *,
    focus_text: str = "",
    limit_notes: int = 24,
) -> str:
    from pha.chat_background import list_background_notes

    tokens = [t.lower() for t in focus_tokens_from_text(focus_text)]
    rows = list_background_notes(user_id, limit=limit_notes)
    if not rows:
        return ""

    lines = [
        "【聚焦背景 · 仅供与当轮附件资产交叉推理 · 非完整方案清单】",
        "以下片段可能与当轮标签相关；勿在回答中逐条复述下列全文。",
    ]
    used = 0

    def _append(cat_label: str, body: str) -> None:
        nonlocal used
        b = (body or "").strip()
        if not b:
            return
        chunk = f"- [{cat_label}] {b}"
        if used + len(chunk) > _MAX_FOCUS_BG_CHARS:
            return
        lines.append(chunk)
        used += len(chunk)

    for row in rows:
        cat = (row.get("category") or "general").strip()
        content = (row.get("content") or "").strip()
        if not content:
            continue
        if cat == "unstructured_vision":
            continue
        if cat == "medication":
            from pha.chat_background import _CATEGORY_LABELS, _inject_cap

            _append(_CATEGORY_LABELS.get(cat, cat), _inject_cap(cat, content))
            continue
        if cat in ("supplement", "sleep_lifestyle", "symptom", "general"):
            if not tokens:
                continue
            low = content.lower()
            if not any(t in low for t in tokens if len(t) >= 4):
                continue
            from pha.chat_background import _CATEGORY_LABELS, _inject_cap

            _append(_CATEGORY_LABELS.get(cat, cat), _inject_cap(cat, content))

    if len(lines) <= 2:
        return ""
    return "\n".join(lines)


def build_preselected_grounded_hits(
    user_id: str,
    *,
    focus_text: str = "",
    max_hits: Optional[int] = None,
) -> str:
    from pha.chat_background import _CATEGORY_LABELS, _inject_cap, list_background_notes

    try:
        cap = max(1, int(os.environ.get("PHA_GROUNDED_HITS_MAX", "3")))
    except ValueError:
        cap = 3
    if max_hits is not None:
        cap = max(1, int(max_hits))

    tokens = [t.lower() for t in focus_tokens_from_text(focus_text) if len(t) >= 4]
    rows = list_background_notes(user_id, limit=32)
    hits: List[tuple[int, str, str]] = []

    for row in rows:
        cat = (row.get("category") or "general").strip()
        content = (row.get("content") or "").strip()
        if not content or cat == "unstructured_vision":
            continue
        score = 0
        if cat == "medication":
            score = 100
        elif cat == "symptom":
            score = 40
        elif cat in ("sleep_lifestyle", "supplement"):
            score = 30
        else:
            score = 10
        low = content.lower()
        if tokens and any(t in low for t in tokens):
            score += 50
        if score < 30 and cat != "medication":
            continue
        label = _CATEGORY_LABELS.get(cat, cat)
        body = _inject_cap(cat, content)
        hits.append((score, label, body))

    hits.sort(key=lambda x: -x[0])
    picked = hits[:cap]
    if not picked:
        return "【可引用依据 · 0 条】\n档案片段中未见与当轮标签 token 直接相关的记录；勿编造用户用药/方案。"

    lines = [
        f"【可引用依据 · 最多 {cap} 条 · 回答时只可引用下列，勿复述全文】",
    ]
    for _, label, body in picked:
        lines.append(f"- [{label}] {body}")
    return "\n".join(lines)


def attachment_evidence_scope_enabled() -> bool:
    return (os.environ.get("PHA_ATTACHMENT_EVIDENCE_SCOPE", "focus_plus_availability") or "").strip() not in (
        "focus_only",
        "0",
        "false",
        "no",
    )


def build_attachment_supplement_context(
    user_id: str,
    *,
    focus_text: str = "",
    session_focus_summary: str = "",
    include_causal_anchor: bool = False,
    user_message: str = "",
) -> str:
    parts: List[str] = []
    if (session_focus_summary or "").strip():
        parts.append(
            "【会话焦点资产 · 本轮讨论对象】\n"
            + session_focus_summary.strip()[:2000],
        )
    if include_causal_anchor:
        parts.append(CAUSAL_ANCHOR_BLOCK)
    if attachment_evidence_scope_enabled():
        from pha.data_availability import build_data_availability_block

        parts.append(build_data_availability_block(user_id, user_message=user_message))
    hits = build_preselected_grounded_hits(user_id, focus_text=focus_text)
    if hits:
        parts.append(hits)
    focused = build_focused_background_for_attachment_qa(user_id, focus_text=focus_text)
    if focused:
        parts.append(focused)
    return "\n\n".join(parts).strip()


def is_attachment_qa_profile(profile: str) -> bool:
    p = profile or ""
    return p.startswith("attachment_asset_qa") or p.startswith("attachment_episodic_bridge")


def is_attachment_grounded_profile(profile: str) -> bool:
    """Stage 3H universal grounded fallback lane."""
    return (profile or "") == "attachment_grounded_review"


def is_attachment_asset_followup_turn(raw_user_message: str) -> bool:
    """Deprecated: followup merged into ``episodic_bridge``; always False for L0 routing."""
    return False


__all__ = [
    "ATTACHMENT_ASSET_QA_FOLLOWUP_TASK",
    "ATTACHMENT_ASSET_QA_TASK",
    "ATTACHMENT_EPISODIC_BRIDGE_TASK",
    "ATTACHMENT_GROUNDED_REVIEW_TASK",
    "ATTACHMENT_LIPID_BRIDGE_TASK",
    "ATTACHMENT_QA_SOUL_ADDENDUM",
    "universal_attachment_lane_enabled",
    "is_attachment_grounded_profile",
    "CAUSAL_ANCHOR_BLOCK",
    "EPISODIC_BRIDGE_NARROW_ADDENDUM",
    "PHA_ATTACHMENT_SOUL_MINIMAL",
    "build_attachment_supplement_context",
    "build_episodic_bridge_task",
    "build_focused_background_for_attachment_qa",
    "build_lipid_bridge_snapshot_block",
    "build_preselected_grounded_hits",
    "maybe_deterministic_attachment_reply",
    "focus_tokens_from_text",
    "has_focus_anchor",
    "is_attachment_asset_followup_turn",
    "is_attachment_asset_qa_turn",
    "is_attachment_qa_profile",
    "is_lipid_bridge_turn",
    "resolve_attachment_qa_mode",
    "user_hits_focus_tokens",
]
