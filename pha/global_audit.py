"""PHA global dual-track health audit — local DeepSeek-R1:14b only (Ollama stream)."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, timedelta
from typing import Iterator, List, Optional, Tuple

import httpx

from pha.health_data import effective_query_reference_date
from pha.llm_provider import list_ollama_installed_models, load_dotenv_if_present
from pha.ollama_payload import apply_keep_alive
from pha.medical_storage import (
    get_abnormal_metrics_last_year,
    query_metrics_in_range,
    query_narratives_in_range,
)
from pha.store import store
from pha.wearable_features import build_wearable_temporal_dossier

logger = logging.getLogger(__name__)

# Global audit MUST NOT follow the UI chat model selector — fixed heavyweight route.
GLOBAL_AUDIT_MODEL_ID = "deepseek-r1:14b"
MAX_BRIEF_TOKENS = 6500
_CHARS_PER_TOKEN_EST = 3

PHA_CLINICAL_AUDIT_SYSTEM_PROMPT = """你是 PHA（Personal Health Agent）端侧专属「临床多模态因果诊断审计官」。
你必须严格遵守《临床多模态因果诊断守则》：

1. 证据分层：体检数字指标（health_metrics）、文字叙事（health_narratives）、可穿戴时序特征卷宗（近90日 Python 预提炼）必须分开引用。
2. 因果链：可穿戴趋势 → 化验/影像叙事异常 → 可执行干预；禁止无证据臆断。
3. 可穿戴权重：卷宗中含【睡眠多维全景】【HRV 时序】【运动负荷】与【三维因果交叉矩阵】，不得仅用 1–2 句敷衍可穿戴。
4. 数字严谨：仅对证据中出现的指标给出数值判断；缺失数据须明确写「本地档案未记录」。
5. 典型因果范例（须举一反三）：
   若转氨酶 ALT 偏高 + 近期服用肌酸 + Apple Watch 深睡偏低 + WASO 延长 + HRV 90日走低，
   则倾向慢性工作疲劳与恢复不足，优先睡眠节律与镁剂微调，而非盲目护肝药。
6. 【强制因果问答】必须在报告中明确回答：
   - 关联 A【运动量 vs 夜间清醒 WASO】：白天高强度运动或久坐缺乏运动，是否与 WASO 变长（皮质醇未回落/过度疲劳）存在时序相关？
   - 关联 B【体检指标 vs HRV/WASO】：转氨酶、血脂、CRP 等化验异常，是否与长期 HRV 低迷、WASO 过长指向同一「慢性工作疲劳」轴？
7. 输出结构：先在 <think> 标签内完成完整深度推理；
   闭合 </think> 后输出 Markdown《终极健康大白皮书》（## 标题、列表、表格），简体中文。

禁止输出 JSON。禁止编造未在证据中出现的诊断、用药或手术。"""


def _ollama_base_url() -> str:
    load_dotenv_if_present()
    return (
        os.environ.get("OLLAMA_BASE_URL")
        or os.environ.get("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).rstrip("/")


def _probe_timeout() -> float:
    return float(os.environ.get("LLM_PROBE_TIMEOUT_SECONDS", "10"))


def _audit_timeout() -> float:
    return float(os.environ.get("PHA_GLOBAL_AUDIT_TIMEOUT_SECONDS", "600"))


def _estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // _CHARS_PER_TOKEN_EST)


def require_deepseek_r1_14b(installed: Optional[List[str]] = None) -> str:
    """Resolve installed Ollama tag for ``deepseek-r1:14b`` (global audit hard route)."""
    if installed is None:
        installed = list_ollama_installed_models(_ollama_base_url(), timeout_seconds=_probe_timeout())
    if not installed:
        raise ValueError(
            "Ollama 未安装任何模型。请先执行: ollama pull deepseek-r1:14b",
        )
    want = GLOBAL_AUDIT_MODEL_ID.lower()
    for name in installed:
        if name.lower() == want:
            return name
    for name in installed:
        nlow = name.lower()
        if "deepseek-r1" in nlow and "14b" in nlow:
            return name
    raise ValueError(
        f"全局大审计强制使用 {GLOBAL_AUDIT_MODEL_ID!r}，当前已安装: {installed!r}。"
        " 请执行: ollama pull deepseek-r1:14b",
    )


def _query_all_user_metrics(user_id: str) -> list:
    ref = effective_query_reference_date()
    start = ref - timedelta(days=3650)
    return query_metrics_in_range(user_id, start, ref)


def _query_all_user_narratives(user_id: str) -> list:
    ref = effective_query_reference_date()
    start = ref - timedelta(days=3650)
    return query_narratives_in_range(user_id, start, ref)


def _fit_section(lines: List[str], token_budget: int) -> Tuple[List[str], int]:
    """Keep as many leading lines as fit in *token_budget* tokens."""
    kept: List[str] = []
    used = 0
    for line in lines:
        need = _estimate_tokens(line + "\n")
        if used + need > token_budget:
            break
        kept.append(line)
        used += need
    return kept, used


def build_dual_track_brief(user_id: str, *, max_tokens: int = MAX_BRIEF_TOKENS) -> str:
    """Pack clinical + wearable temporal features into the joint audit dossier."""
    uid = (user_id or "default").strip() or "default"
    ref = effective_query_reference_date()

    metrics = _query_all_user_metrics(uid)
    narratives = _query_all_user_narratives(uid)
    abnormal = get_abnormal_metrics_last_year(uid, ref)

    wearable_dossier = build_wearable_temporal_dossier(uid, reference_date=ref)

    metric_lines: List[str] = []
    for r in metrics:
        val = f"{r.value:g}" if r.value is not None else "?"
        flag = " [异常]" if r.is_abnormal else ""
        metric_lines.append(
            f"- {r.report_date.isoformat()} | {r.metric_name} | {val} {r.unit} | ref {r.reference_range or '—'}{flag}",
        )

    narr_lines: List[str] = []
    for n in narratives:
        body = (n.content or n.summary or "").strip()
        if len(body) > 380:
            body = body[:380] + "…"
        narr_lines.append(
            f"- {n.report_date.isoformat()} | {n.hospital or '—'} | [{n.category}] {body}",
        )

    ab_lines: List[str] = []
    for r in abnormal[:40]:
        val = f"{r.value:g}" if r.value is not None else "?"
        ab_lines.append(f"- {r.report_date.isoformat()} {r.metric_name}={val} {r.unit}")

    events = store.list_recent_health_events(uid, limit=12)
    ev_lines = [f"- {e.occurred_at.date()} {e.event_type.value}: {e.title}" for e in events]

    header = (
        f"user_id={uid}\nreference_date={ref.isoformat()}\n"
        f"metrics_total={len(metrics)} narratives_total={len(narratives)}\n"
        f"《时序-临床联合特征卷宗》\n"
    )
    budget = max_tokens - _estimate_tokens(header) - _estimate_tokens(wearable_dossier) - 120

    ab_kept, ab_used = _fit_section(ab_lines, min(500, max(200, budget // 6)))
    budget -= ab_used
    met_kept, met_used = _fit_section(metric_lines, int(max(400, budget * 0.5)))
    budget -= met_used
    nar_kept, nar_used = _fit_section(narr_lines, int(max(300, budget * 0.9)))
    budget -= nar_used
    ev_kept, _ = _fit_section(ev_lines, min(200, budget))

    body = (
        header
        + "\n"
        + wearable_dossier
        + f"\n\n=== 体检数字轨 health_metrics（入库 {len(metrics)} 项，卷宗收录 {len(met_kept)} 项）===\n"
        + ("\n".join(met_kept) or "（无）")
        + f"\n\n=== 文字叙事轨 health_narratives（入库 {len(narratives)} 段，卷宗收录 {len(nar_kept)} 段）===\n"
        + ("\n".join(nar_kept) or "（无）")
        + "\n\n=== 近一年异常指标摘要 ===\n"
        + ("\n".join(ab_kept) or "（无）")
        + "\n\n=== 近期健康事件 ===\n"
        + ("\n".join(ev_kept) or "（无）")
    )
    if _estimate_tokens(body) > max_tokens:
        cap = max_tokens * _CHARS_PER_TOKEN_EST
        body = body[:cap] + f"\n…[卷宗已按 {max_tokens} token 上限截断]"
    return body


_THINK_OPEN = re.compile(r"<think>", re.I)
_THINK_CLOSE = re.compile(r"</think>", re.I)
_TAG_FRAGMENTS = ("</think>", "<think>")


def _hold_incomplete_tag_suffix(buf: str) -> int:
    hold = 0
    for marker in _TAG_FRAGMENTS:
        for k in range(1, len(marker)):
            if buf.endswith(marker[:k]):
                hold = max(hold, k)
    return hold


def _split_thinking_and_report(full_text: str) -> tuple[str, str]:
    text = full_text or ""
    m_close = _THINK_CLOSE.search(text)
    if m_close:
        thinking = _THINK_OPEN.sub("", text[: m_close.start()]).strip()
        return thinking, text[m_close.end() :].strip()
    if _THINK_OPEN.search(text):
        parts = _THINK_OPEN.split(text, maxsplit=1)
        if len(parts) > 1:
            return parts[1].strip(), ""
    return "", text.strip()


class _CoTStreamSplitter:
    """Route Ollama deltas into thinking vs report by <think> boundaries."""

    def __init__(self) -> None:
        self.mode = "thinking"
        self.buf = ""

    def feed(self, delta: str) -> tuple[str, str]:
        if not delta:
            return "", ""
        if self.mode == "report":
            return "", delta

        self.buf += delta
        m_close = _THINK_CLOSE.search(self.buf)
        if m_close:
            seg = self.buf[: m_close.start()]
            self.buf = self.buf[m_close.end() :]
            self.mode = "report"
            think_out = _THINK_OPEN.sub("", seg)
            report_out = self.buf
            self.buf = ""
            return think_out, report_out

        hold = _hold_incomplete_tag_suffix(self.buf)
        emit = self.buf[:-hold] if hold else self.buf
        self.buf = self.buf[-hold:] if hold else ""
        think_out = _THINK_OPEN.sub("", emit)
        return think_out, ""


def stream_global_audit_ndjson(user_id: str) -> Iterator[str]:
    """Yield NDJSON: status | thinking | report | done | error (SSE-compatible chunks)."""
    uid = (user_id or "default").strip() or "default"
    status_msg = (
        "M4 显存已满载 · 本地 DeepSeek-R1:14b 正在疯狂推导中… "
        "（已加载 SQLite 双轨档案，忽略 UI 日常对话模型选择）"
    )
    yield json.dumps(
        {"event": "status", "message": status_msg, "model": GLOBAL_AUDIT_MODEL_ID},
        ensure_ascii=False,
    ) + "\n"

    try:
        base = _ollama_base_url()
        installed = list_ollama_installed_models(base, timeout_seconds=_probe_timeout())
        model = require_deepseek_r1_14b(installed)
    except Exception as exc:
        yield json.dumps({"event": "error", "message": str(exc)}, ensure_ascii=False) + "\n"
        return

    evidence = build_dual_track_brief(uid)
    user_msg = (
        "请基于以下《时序-临床联合特征卷宗》（含近90日可穿戴多维提炼 + 完整体检指标），"
        "生成《终极健康大白皮书》Markdown。\n"
        "必须串联：睡眠/WASO、HRV、运动负荷、化验异常、叙事结论；并明确回答关联 A 与关联 B。\n"
        "务必先在 <think> 内完成完整因果推理，闭合 </think> 后再输出报告正文。\n\n"
        f"{evidence}"
    )

    body = apply_keep_alive(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": PHA_CLINICAL_AUDIT_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "stream": True,
        },
    )

    splitter = _CoTStreamSplitter()
    full_parts: List[str] = []

    try:
        url = f"{base}/api/chat"
        timeout = httpx.Timeout(_audit_timeout(), connect=30.0)
        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", url, json=body) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue
                    try:
                        chunk = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    msg = chunk.get("message") or {}
                    delta = msg.get("content") or ""
                    if not delta:
                        continue
                    full_parts.append(delta)
                    think_delta, report_delta = splitter.feed(delta)
                    if think_delta:
                        yield json.dumps(
                            {"event": "thinking", "delta": think_delta},
                            ensure_ascii=False,
                        ) + "\n"
                    if report_delta:
                        yield json.dumps(
                            {"event": "report", "delta": report_delta},
                            ensure_ascii=False,
                        ) + "\n"
    except Exception as exc:
        logger.exception("global-audit stream failed")
        yield json.dumps({"event": "error", "message": str(exc)}, ensure_ascii=False) + "\n"
        return

    full_text = "".join(full_parts)
    thinking, report = _split_thinking_and_report(full_text)
    if splitter.mode == "thinking" and splitter.buf.strip():
        thinking = (thinking + "\n" + _THINK_OPEN.sub("", splitter.buf)).strip()
    if not report and thinking and not _THINK_CLOSE.search(full_text):
        report = thinking
        thinking = ""

    yield json.dumps(
        {
            "event": "done",
            "model": model,
            "generated_on": date.today().isoformat(),
            "thinking": thinking,
            "report_markdown": report or full_text,
        },
        ensure_ascii=False,
    ) + "\n"
