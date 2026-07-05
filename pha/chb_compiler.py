"""Stage 4-β — Chronic Health Brief (CHB) compiler.

Deterministic §Facts assembly from T0 ledger rows; §Interpretation is optional
and feature-flagged (default off).

4-β-2a: Harness Tier1 slot ``USER_CONTEXT_BRIEF`` (lifestyle / combined only).
4-β-2b: LLM §Interpretation via ``PHA_CHB_COMPILER=1`` (BYOK / mockable).

RIGID RED LINE: §Interpretation is advisory text only. It MUST NEVER be used as a
numerics / Manifest / LabelLedger source for control flow or dose math.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from pha.health_data import effective_query_reference_date
from pha.medical_storage import MedicalMetricRow, get_latest_medical_report, query_metrics_in_range
from pha.sqlite_storage import query_wearable_daily_range

logger = logging.getLogger(__name__)

CHB_SCHEMA = "pha.chb/v0.1"
DEFAULT_LOOKBACK_DAYS = 90
DEFAULT_REPORT_ROOT = Path(__file__).resolve().parent.parent / "reports" / "chb"
SLOT_CANDIDATES_PATH = Path(__file__).resolve().parent.parent / "rules" / "loop_slot_candidates.jsonl"

# Profiles allowed to inject USER_CONTEXT_BRIEF (Tier1). Never attachment_grounded_review.
USER_CONTEXT_BRIEF_PROFILES: frozenset[str] = frozenset({"lifestyle", "combined_review"})

INTERPRETATION_ADVISORY_BANNER = (
    "## §Interpretation（解读 · 非数字源 · ADVISORY ONLY）\n"
    "> 本栏仅为健康参考建议，**禁止**作为 Numerics Manifest / LabelLedger / "
    "剂量或控制流的数字来源。数字主权仅属于 §Facts（T0）。"
)

# Callable: facts_markdown -> interpretation body text (no header).
InterpretationLlmFn = Callable[[str], str]


@dataclass
class ChbFactRow:
    text: str
    ref_id: str
    prov_type: str  # lab_report | wearable_import | user_statement | attachment_ingest
    metric_id: str | None = None
    value: str | None = None
    unit: str | None = None
    observed_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChronicHealthBrief:
    schema: str = CHB_SCHEMA
    user_id: str = "default"
    compiled_at: str = ""
    ledger_hash: str = ""
    facts: list[ChbFactRow] = field(default_factory=list)
    interpretation: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    slot_hints: list[dict[str, Any]] = field(default_factory=list)
    facts_markdown: str = ""
    interpretation_markdown: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "user_id": self.user_id,
            "compiled_at": self.compiled_at,
            "ledger_hash": self.ledger_hash,
            "facts": [f.as_dict() for f in self.facts],
            "interpretation": list(self.interpretation),
            "open_questions": list(self.open_questions),
            "slot_hints": list(self.slot_hints),
            "facts_markdown": self.facts_markdown,
            "interpretation_markdown": self.interpretation_markdown,
        }


def chb_compiler_enabled() -> bool:
    return (os.environ.get("PHA_CHB_COMPILER") or "0").strip().lower() in ("1", "true", "yes")


def load_slot_candidates(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or SLOT_CANDIDATES_PATH
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.mean(values))


def read_lab_facts(
    user_id: str,
    *,
    reference_date: date | None = None,
    max_rows: int = 24,
) -> list[ChbFactRow]:
    """Read latest lab metric rows from medical ledger (T0)."""
    ref = reference_date or effective_query_reference_date()
    start = ref - timedelta(days=365 * 3)
    rows = query_metrics_in_range(user_id, start, ref)
    if not rows:
        report_d, latest = get_latest_medical_report(user_id)
        if not latest:
            return []
        rows = latest
        anchor = report_d
    else:
        anchor = rows[0].report_date

    facts: list[ChbFactRow] = []
    seen: set[str] = set()
    for r in rows[:max_rows]:
        code = (r.metric_code or r.metric_name or "").strip()
        if not code:
            continue
        key = f"{r.report_date}:{code}"
        if key in seen:
            continue
        seen.add(key)
        label = (r.name_zh or r.metric_name or code).strip()
        val = r.value
        unit = (r.unit or "").strip()
        val_s = f"{val:g}" if isinstance(val, (int, float)) else str(val or "—")
        ref_id = f"lab_{r.report_date.isoformat()}_{code}"
        facts.append(
            ChbFactRow(
                text=f"{label} {r.report_date.isoformat()}: {val_s}{(' ' + unit) if unit else ''}",
                ref_id=ref_id,
                prov_type="lab_report",
                metric_id=code.lower(),
                value=val_s,
                unit=unit or None,
                observed_at=r.report_date.isoformat(),
            ),
        )
    if not facts and anchor:
        facts.append(
            ChbFactRow(
                text=f"最近化验报告日期: {anchor.isoformat()}",
                ref_id=f"lab_report_{anchor.isoformat()}",
                prov_type="lab_report",
                observed_at=anchor.isoformat(),
            ),
        )
    return facts


def read_wearable_facts(
    user_id: str,
    *,
    reference_date: date | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[ChbFactRow]:
    """Aggregate wearable daily rows into T0 fact lines (90d window default)."""
    ref = reference_date or effective_query_reference_date()
    start = ref - timedelta(days=lookback_days)
    rows = list(query_wearable_daily_range(user_id, start, ref) or [])
    if not rows:
        return []

    sleep_vals = [float(r.sleep_hours) for r in rows if r.sleep_hours is not None]
    hrv_vals = [float(r.hrv_rmssd_ms) for r in rows if r.hrv_rmssd_ms is not None]
    steps_vals = [float(r.steps) for r in rows if r.steps is not None]
    rhr_vals = [float(r.resting_heart_rate_bpm) for r in rows if r.resting_heart_rate_bpm is not None]

    facts: list[ChbFactRow] = []
    ref_base = f"wearable_{lookback_days}d_{ref.isoformat()}"

    def _add(metric_id: str, label: str, mean_val: float | None, unit: str) -> None:
        if mean_val is None:
            return
        val_s = f"{mean_val:.1f}"
        facts.append(
            ChbFactRow(
                text=f"近 {lookback_days}d {label} 均值: {val_s} {unit}",
                ref_id=f"{ref_base}_{metric_id}",
                prov_type="wearable_import",
                metric_id=metric_id,
                value=val_s,
                unit=unit,
                observed_at=ref.isoformat(),
            ),
        )

    _add("sleep", "睡眠", _mean(sleep_vals), "h")
    _add("hrv", "HRV", _mean(hrv_vals), "ms")
    _add("steps", "步数", _mean(steps_vals), "步/日")
    _add("rhr", "静息心率", _mean(rhr_vals), "bpm")
    return facts


def assemble_facts_section(facts: list[ChbFactRow]) -> str:
    """Deterministic §Facts markdown — no LLM."""
    if not facts:
        return "## §Facts（硬事实 · 可引用）\n- （暂无 T0 事实行）"
    lines = ["## §Facts（硬事实 · 可引用）"]
    for f in facts:
        lines.append(f"- {f.text} [ref: {f.ref_id}]")
    return "\n".join(lines)


def compile_interpretation_stub(
    facts: list[ChbFactRow],
    *,
    enable_llm: bool = False,
    facts_markdown: str = "",
    llm_fn: InterpretationLlmFn | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Compile §Interpretation. Default stub; LLM when ``PHA_CHB_COMPILER=1``.

    RIGID RED LINE: output is advisory only — never a numerics source.
    """
    derived = [f.ref_id for f in facts[:12]]
    if enable_llm and chb_compiler_enabled():
        body = compile_interpretation_llm(
            facts,
            facts_markdown=facts_markdown,
            llm_fn=llm_fn,
        )
        if body:
            items = [{"text": body, "derived_from": derived, "prov_type": "llm_advisory"}]
            md = f"{INTERPRETATION_ADVISORY_BANNER}\n- {body}"
            return items, md
    if not facts:
        return [], f"{INTERPRETATION_ADVISORY_BANNER}\n- （事实不足，暂无解读）"
    items = [
        {
            "text": "以上为 T0 账本可引用事实；启用 PHA_CHB_COMPILER=1 可生成趋势解读（仍为非数字源）。",
            "derived_from": derived,
            "prov_type": "stub",
        },
    ]
    md = (
        f"{INTERPRETATION_ADVISORY_BANNER}\n"
        "- 以上为 T0 账本可引用事实；启用 PHA_CHB_COMPILER=1 可生成趋势解读（仍为非数字源）。"
    )
    return items, md


def compile_interpretation_llm(
    facts: list[ChbFactRow],
    *,
    facts_markdown: str = "",
    llm_fn: InterpretationLlmFn | None = None,
) -> str:
    """BYOK LLM trend synthesis from §Facts snapshot only (no raw device dump).

    Returns advisory prose only. Callers MUST NOT treat output as numerics source.
    """
    if llm_fn is not None:
        return llm_fn(facts_markdown or assemble_facts_section(facts)).strip()

    fm = facts_markdown or assemble_facts_section(facts)
    system = (
        "你是慢性健康简报编译器。仅基于用户提供的 §Facts 事实块做趋势研判。"
        "禁止编造 §Facts 中未出现的数字、日期或诊断。"
        "输出 2-4 条短句，每条须可追溯到 §Facts 中的 [ref:…]。"
        "禁止输出具体剂量或用药指令。"
    )
    user = f"§Facts 快照：\n{fm}\n\n请输出 §Interpretation 趋势研判（纯文本，非数字源）："
    try:
        from pha.llm_provider import get_llm_provider

        provider = get_llm_provider()
        raw = provider.chat_completion(system_prompt=system, user_message=user)
        return str(raw or "").strip()
    except Exception as exc:
        logger.warning("CHB LLM interpretation failed: %s", exc)
        return ""


def load_latest_chb_artifact(
    user_id: str,
    *,
    report_root: Path | None = None,
) -> ChronicHealthBrief | None:
    """Load newest ``brief_*.json`` for user (mtime). Returns None if missing."""
    uid = (user_id or "default").strip() or "default"
    root = report_root or DEFAULT_REPORT_ROOT
    out_dir = root / uid
    if not out_dir.is_dir():
        return None
    candidates = sorted(
        out_dir.glob("brief_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(doc.get("schema") or "") != CHB_SCHEMA:
            continue
        facts = [
            ChbFactRow(
                text=str(r.get("text") or ""),
                ref_id=str(r.get("ref_id") or ""),
                prov_type=str(r.get("prov_type") or ""),
                metric_id=r.get("metric_id"),
                value=r.get("value"),
                unit=r.get("unit"),
                observed_at=r.get("observed_at"),
            )
            for r in (doc.get("facts") or [])
            if isinstance(r, dict)
        ]
        return ChronicHealthBrief(
            schema=CHB_SCHEMA,
            user_id=str(doc.get("user_id") or uid),
            compiled_at=str(doc.get("compiled_at") or ""),
            ledger_hash=str(doc.get("ledger_hash") or ""),
            facts=facts,
            interpretation=list(doc.get("interpretation") or []),
            open_questions=list(doc.get("open_questions") or []),
            slot_hints=list(doc.get("slot_hints") or []),
            facts_markdown=str(doc.get("facts_markdown") or assemble_facts_section(facts)),
            interpretation_markdown=str(doc.get("interpretation_markdown") or ""),
        )
    return None


def build_user_context_brief_block(
    user_id: str,
    *,
    profile: str,
    report_root: Path | None = None,
    recompile_if_stale: bool = False,
) -> str:
    """Tier1 slot body for ``USER_CONTEXT_BRIEF`` (lifestyle / combined only).

    Reads newest artifact by mtime; empty when missing (never blocks turn).
    """
    prof = (profile or "").strip()
    if prof not in USER_CONTEXT_BRIEF_PROFILES:
        return ""
    uid = (user_id or "default").strip() or "default"
    brief = load_latest_chb_artifact(uid, report_root=report_root)
    if brief is None and recompile_if_stale:
        try:
            brief = compile_chronic_health_brief(
                uid,
                enable_llm_interpretation=chb_compiler_enabled(),
            )
            write_chb_artifact(brief, report_root=report_root)
        except Exception as exc:
            logger.warning("CHB compile for USER_CONTEXT_BRIEF failed: %s", exc)
            return ""
    if brief is None:
        return ""

    parts = [
        "【USER_CONTEXT_BRIEF · Tier1 · 慢性健康简报 · 只读】",
        f"ledger_hash={brief.ledger_hash} compiled_at={brief.compiled_at}",
        brief.facts_markdown.strip(),
    ]
    if brief.interpretation_markdown.strip():
        parts.append(brief.interpretation_markdown.strip())
    if brief.open_questions:
        parts.append("## §Open Questions")
        for q in brief.open_questions:
            parts.append(f"- {q}")
    return "\n\n".join(p for p in parts if p).strip()


def compute_ledger_hash(facts: list[ChbFactRow]) -> str:
    payload = json.dumps([f.as_dict() for f in facts], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def read_live_t0_facts(
    user_id: str,
    *,
    reference_date: date | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[ChbFactRow]:
    """Read current live T0 facts from medical + wearable ledgers."""
    uid = (user_id or "default").strip() or "default"
    ref = reference_date or effective_query_reference_date()
    return read_lab_facts(uid, reference_date=ref) + read_wearable_facts(
        uid,
        reference_date=ref,
        lookback_days=lookback_days,
    )


def compute_live_ledger_hash(
    user_id: str,
    *,
    reference_date: date | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> str:
    """Hash of serialized live T0 facts (same algorithm as ``compile_chronic_health_brief``)."""
    return compute_ledger_hash(
        read_live_t0_facts(
            user_id,
            reference_date=reference_date,
            lookback_days=lookback_days,
        ),
    )


def list_chb_report_user_ids(*, report_root: Path | None = None) -> list[str]:
    """Discover user_id directories under ``reports/chb/`` (always includes ``default``)."""
    root = report_root or DEFAULT_REPORT_ROOT
    ids: list[str] = []
    if root.is_dir():
        ids = sorted(
            d.name
            for d in root.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
    if "default" not in ids:
        ids.insert(0, "default")
    return ids


def list_chb_artifact_paths(
    user_id: str,
    *,
    report_root: Path | None = None,
) -> list[Path]:
    """All ``brief_*.json`` paths for user (mtime descending)."""
    uid = (user_id or "default").strip() or "default"
    root = report_root or DEFAULT_REPORT_ROOT
    out_dir = root / uid
    if not out_dir.is_dir():
        return []
    return sorted(out_dir.glob("brief_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def chb_stale_status(
    user_id: str,
    *,
    report_root: Path | None = None,
    reference_date: date | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """Compare live T0 ledger hash vs newest on-disk CHB artifact."""
    uid = (user_id or "default").strip() or "default"
    live_hash = compute_live_ledger_hash(
        uid,
        reference_date=reference_date,
        lookback_days=lookback_days,
    )
    latest = load_latest_chb_artifact(uid, report_root=report_root)
    artifact_hash = (latest.ledger_hash or "").strip() if latest else ""
    exact_path = (report_root or DEFAULT_REPORT_ROOT) / uid / f"brief_{live_hash}.json"
    is_stale = latest is None or live_hash != artifact_hash
    return {
        "user_id": uid,
        "live_hash": live_hash,
        "artifact_hash": artifact_hash or None,
        "is_stale": is_stale,
        "exact_artifact_exists": exact_path.is_file(),
        "artifact_count": len(list_chb_artifact_paths(uid, report_root=report_root)),
    }


def recompile_chb_if_stale(
    user_id: str,
    *,
    report_root: Path | None = None,
    reference_date: date | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    enable_llm_interpretation: bool | None = None,
    dry_run: bool = False,
) -> tuple[dict[str, Any], Path | None]:
    """Offline compile when live T0 hash diverges from newest artifact."""
    uid = (user_id or "default").strip() or "default"
    status = chb_stale_status(
        uid,
        report_root=report_root,
        reference_date=reference_date,
        lookback_days=lookback_days,
    )
    if not status["is_stale"]:
        return status, None
    if dry_run:
        return status, None
    llm = (
        chb_compiler_enabled()
        if enable_llm_interpretation is None
        else enable_llm_interpretation
    )
    brief = compile_chronic_health_brief(
        uid,
        reference_date=reference_date,
        lookback_days=lookback_days,
        enable_llm_interpretation=llm,
    )
    path = write_chb_artifact(brief, report_root=report_root)
    status["artifact_hash"] = brief.ledger_hash
    status["is_stale"] = False
    status["exact_artifact_exists"] = True
    status["artifact_count"] = len(list_chb_artifact_paths(uid, report_root=report_root))
    return status, path


def compile_chronic_health_brief(
    user_id: str,
    *,
    reference_date: date | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    slot_candidates: list[dict[str, Any]] | None = None,
    enable_llm_interpretation: bool = False,
) -> ChronicHealthBrief:
    uid = (user_id or "default").strip() or "default"
    ref = reference_date or effective_query_reference_date()
    lab_facts = read_lab_facts(uid, reference_date=ref)
    wear_facts = read_wearable_facts(uid, reference_date=ref, lookback_days=lookback_days)
    facts = lab_facts + wear_facts
    slots = slot_candidates if slot_candidates is not None else load_slot_candidates()
    facts_md = assemble_facts_section(facts)

    interpretation, interp_md = compile_interpretation_stub(
        facts,
        enable_llm=enable_llm_interpretation,
        facts_markdown=facts_md,
    )
    open_q: list[str] = []
    if not lab_facts:
        open_q.append("尚未有化验面板 T0 行；上传 PDF/截图可补 §Facts。")
    if not wear_facts:
        open_q.append("尚未有穿戴日聚合；导入 Apple Health export.zip 可补 §Facts。")

    brief = ChronicHealthBrief(
        user_id=uid,
        compiled_at=datetime.now(timezone.utc).isoformat(),
        ledger_hash=compute_ledger_hash(facts),
        facts=facts,
        interpretation=interpretation,
        open_questions=open_q,
        slot_hints=slots,
        facts_markdown=facts_md,
        interpretation_markdown=interp_md,
    )
    return brief


def write_chb_artifact(
    brief: ChronicHealthBrief,
    *,
    report_root: Path | None = None,
) -> Path:
    root = report_root or DEFAULT_REPORT_ROOT
    out_dir = root / brief.user_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"brief_{brief.ledger_hash}.json"
    path.write_text(json.dumps(brief.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


__all__ = [
    "CHB_SCHEMA",
    "ChbFactRow",
    "ChronicHealthBrief",
    "INTERPRETATION_ADVISORY_BANNER",
    "InterpretationLlmFn",
    "USER_CONTEXT_BRIEF_PROFILES",
    "assemble_facts_section",
    "build_user_context_brief_block",
    "chb_compiler_enabled",
    "compile_chronic_health_brief",
    "compile_interpretation_llm",
    "compile_interpretation_stub",
    "chb_stale_status",
    "compute_ledger_hash",
    "compute_live_ledger_hash",
    "list_chb_artifact_paths",
    "list_chb_report_user_ids",
    "read_live_t0_facts",
    "recompile_chb_if_stale",
    "load_latest_chb_artifact",
    "load_slot_candidates",
    "read_lab_facts",
    "read_wearable_facts",
    "write_chb_artifact",
]
