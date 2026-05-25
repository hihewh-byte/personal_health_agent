"""Deep health consultation — aggregate local data + Llama 3.2 Vision 11B narrative."""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Dict, List

from pha.health_data import effective_query_reference_date
from pha.llm_provider import OllamaProvider, list_ollama_installed_models, load_dotenv_if_present
from pha.medical_storage import get_abnormal_metrics_last_year, list_health_report_assets
from pha.ollama_runtime import suspend_text_models_for_vision, suspend_vision_model_after_use
from pha.store import store
from pha.vision_parser import resolve_vision_11b_model, VisionModelNotReadyError

logger = logging.getLogger(__name__)

REQUIRED_AUDIT_VISION_MODEL = "llama3.2-vision:11b"

# 1×1 transparent PNG (minimal) — Ollama vision API requires at least one image frame.
_MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

_CONSULT_SYSTEM_PROMPT = """You are a senior clinical health auditor writing in Simplified Chinese.
Output a professional Markdown report (use ## headings, bullet lists, tables where useful).
Do NOT output JSON. Base conclusions only on the evidence block provided; if data is missing, say so explicitly.
Include: executive summary, wearable trends interpretation, lab / screening highlights, risk flags, and actionable lifestyle follow-ups."""


def _ollama_base_url() -> str:
    load_dotenv_if_present()
    return (
        os.environ.get("OLLAMA_BASE_URL")
        or os.environ.get("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).rstrip("/")


def _probe_timeout() -> float:
    return float(os.environ.get("LLM_PROBE_TIMEOUT_SECONDS", "10"))


def _chat_timeout() -> float:
    return float(os.environ.get("LLM_TIMEOUT_SECONDS", "240"))


def _build_evidence_block(user_id: str) -> str:
    uid = (user_id or "default").strip() or "default"
    ref = effective_query_reference_date()
    ctx = store.get_user_context(uid)
    compressed = str(ctx.get("compressed_wearable_trends") or "")
    if len(compressed) > 14_000:
        compressed = compressed[:14_000] + "\n…[truncated]"

    assets = list_health_report_assets(uid, limit=25)
    asset_lines: List[str] = []
    for a in assets:
        asset_lines.append(
            f"- {a.get('report_date', '')} | {a.get('source_filename', '')} | {a.get('metrics_preview', '')}",
        )

    abnormal = get_abnormal_metrics_last_year(uid, ref)
    ab_lines: List[str] = []
    for row in abnormal[:40]:
        ab_lines.append(
            f"- {row.report_date.isoformat() if hasattr(row.report_date, 'isoformat') else row.report_date} "
            f"{row.metric_name}: {row.value} {row.unit} (ref {row.reference_range})",
        )

    events = store.list_recent_health_events(uid, limit=25)
    ev_lines = [f"- {e.occurred_at.date()} {e.event_type.value}: {e.title}" for e in events]

    milestones = store.fetch_milestone_events(uid)
    ms_lines = [f"- {m.occurred_at.date()}: {m.title}" for m in milestones[:15]]

    return (
        f"user_id={uid}\nreference_date={ref.isoformat()}\n\n"
        f"=== 可穿戴趋势压缩 ===\n{compressed}\n\n"
        f"=== 归档报告（最近 25 条）===\n" + ("\n".join(asset_lines) or "（无）") + "\n\n"
        f"=== 近一年异常/关注检验项（最多 40 条）===\n" + ("\n".join(ab_lines) or "（无）") + "\n\n"
        f"=== 近期健康事件 ===\n" + ("\n".join(ev_lines) or "（无）") + "\n\n"
        f"=== 里程碑 ===\n" + ("\n".join(ms_lines) or "（无）")
    )


def generate_deep_consultation_markdown(user_id: str, *, vision_model: str) -> Dict[str, Any]:
    """
    Aggregate SQLite-backed context and run **llama3.2-vision:11b** (text + minimal image) for a long-form audit.

    ``vision_model`` query param must be exactly ``llama3.2-vision:11b`` (API contract); Ollama tag is resolved
    against installed models.
    """
    uid = (user_id or "default").strip() or "default"
    requested = (vision_model or "").strip()
    if requested.lower() != REQUIRED_AUDIT_VISION_MODEL.lower():
        raise ValueError(
            f"深度审计仅支持 vision_model={REQUIRED_AUDIT_VISION_MODEL!r}（当前: {requested!r}）",
        )
    base = _ollama_base_url()
    installed = list_ollama_installed_models(base, timeout_seconds=_probe_timeout())
    vision_name = resolve_vision_11b_model(installed)

    evidence = _build_evidence_block(uid)
    user_block = (
        "以下为本用户在 PHA 中的结构化证据（体检归档、可穿戴压缩摘要、事件与里程碑）。"
        "请生成「深度健康审计报告」全文。\n\n"
        f"{evidence}"
    )

    unloaded: List[str] = []
    report = ""
    try:
        unloaded = suspend_text_models_for_vision(extra_models=[])
        llm = OllamaProvider(
            base_url=base,
            model=vision_name,
            timeout_seconds=_chat_timeout(),
        )
        report = llm.chat_with_vision(
            system_prompt=_CONSULT_SYSTEM_PROMPT,
            user_message=user_block,
            images=[_MINIMAL_PNG_B64],
        )
    finally:
        suspend_vision_model_after_use(vision_name, base_url=base)

    return {
        "user_id": uid,
        "model": vision_name,
        "models_unloaded": unloaded,
        "report_markdown": (report or "").strip(),
        "generated_on": date.today().isoformat(),
    }
