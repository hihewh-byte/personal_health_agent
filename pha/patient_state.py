"""Current Patient State — SQLite-backed fact ledger for PHA chat (no template fluff)."""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from pha.date_range_parser import default_wearable_window
from pha.health_data import effective_query_reference_date
from pha.intent_gates import QuestionType
from pha.medical_storage import MedicalMetricRow, get_latest_medical_report, query_metrics_in_range
from pha.medical_metric_catalog import resolve_metric_name_for_read
from pha.sqlite_storage import query_wearable_daily_range

_MAX_MEDICAL_ROWS = 96
_WEARABLE_LOOKBACK_DAYS = 7

PHA_PATIENT_STATE_MAX_CHARS = int(os.environ.get("PHA_PATIENT_STATE_MAX_CHARS", "4500"))

_LAB_ROW_HINT_RE = re.compile(
    r"血脂|ldl|hdl|胆固醇|甘油三酯|化验|体检|肝功能|肾功能|检验|糖化|低密度|高密度",
    re.I,
)


def _format_overlay_value(val: Any) -> str:
    if val is None:
        return "—"
    if isinstance(val, (int, float)):
        return f"{val:g}"
    return str(val).strip() or "—"


def _fmt_val(row: MedicalMetricRow) -> str:
    if row.value is None:
        return "—"
    u = f" {row.unit}".strip() if row.unit else ""
    return f"{row.value:g}{u}"


def _medical_ledger_lines(user_id: str, ref: date, *, max_rows: int = _MAX_MEDICAL_ROWS) -> List[str]:
    """Rows from ``medical_reports`` (user-facing alias: medical ledger)."""
    start = ref - timedelta(days=365 * 8)
    rows = query_metrics_in_range(user_id, start, ref)
    if not rows:
        report_d, latest_rows = get_latest_medical_report(user_id)
        if not latest_rows:
            return ["| （无体检化验记录） | — | 请先上传 PDF/截图至全能解析中心 |"]
        rows = latest_rows
        anchor = report_d
    else:
        anchor = rows[0].report_date

    by_date: dict[str, List[MedicalMetricRow]] = {}
    for r in rows:
        raw_code = (r.metric_code or r.metric_name or "").strip()
        if not raw_code:
            continue
        resolved = resolve_metric_name_for_read(raw_code)
        code = resolved.code
        label = (resolved.name_zh or r.name_zh or r.metric_name or code).strip()
        if not code:
            continue
        key = r.report_date.isoformat()[:10]
        by_date.setdefault(key, []).append(r)

    ordered_dates = sorted(by_date.keys(), reverse=True)
    picked: List[MedicalMetricRow] = []
    cap = max(8, min(max_rows, _MAX_MEDICAL_ROWS))
    for d in ordered_dates:
        for r in by_date[d]:
            picked.append(r)
            if len(picked) >= cap:
                break
        if len(picked) >= cap:
            break

    lines: List[str] = []
    for r in picked:
        metric = r.name_zh or r.metric_name or r.metric_code
        val = _fmt_val(r)
        ref_s = (r.reference_range or "—").strip()
        link = f"报告日 {r.report_date.isoformat()[:10]} · SQLite medical_reports"
        if r.is_abnormal:
            link += " · 异常"
        lines.append(f"| {metric} | {val} | {ref_s} | {link} |")
    if anchor:
        lines.insert(0, f"【体检化验 · 锚定最近报告日 {anchor.isoformat()[:10]}】")
    return lines


def _wearable_ledger_lines(
    user_id: str,
    ref: date,
    *,
    user_message: str = "",
) -> List[str]:
    msg = (user_message or "").strip()
    if msg:
        window = default_wearable_window(msg, reference=ref)
        start, end = window.start, window.end
        span_label = window.iso_span()
    else:
        start = ref - timedelta(days=_WEARABLE_LOOKBACK_DAYS - 1)
        end = ref
        span_label = f"近{_WEARABLE_LOOKBACK_DAYS}日"

    rows = query_wearable_daily_range(user_id, start, end)
    if not rows:
        return [f"| （{span_label} 无 wearable_daily） | — | 请导入 Apple Health export.zip |"]

    lines: List[str] = [f"【穿戴 · {span_label} wearable_daily 日均/末日 · n={len(rows)}天】"]
    steps = [r.steps for r in rows if r.steps is not None]
    hrv = [float(r.hrv_rmssd_ms) for r in rows if r.hrv_rmssd_ms is not None]
    sleep = [float(r.sleep_hours) for r in rows if r.sleep_hours is not None]
    rhr = [float(r.resting_heart_rate_bpm) for r in rows if r.resting_heart_rate_bpm is not None]
    spo2 = [float(r.spo2_pct) for r in rows if r.spo2_pct is not None]
    latest = rows[-1]

    def _avg(vals: List[float]) -> Optional[float]:
        return sum(vals) / len(vals) if vals else None

    if latest.steps is not None:
        lines.append(
            f"| 今日步数 | {int(latest.steps):,} 步 | 末日 {latest.day} | wearable_daily |",
        )
    if steps:
        a = sum(steps) / len(steps)
        lines.append(f"| 平均步数 | {int(a):,} 步 | n={len(steps)} | wearable_daily |")
    if hrv:
        a = _avg(hrv)
        lines.append(f"| 平均 HRV | {a:.1f} ms | n={len(hrv)} | wearable_daily |")
    if sleep:
        a = _avg(sleep)
        lines.append(f"| 平均睡眠 | {a:.2f} h | n={len(sleep)} | wearable_daily |")
    if spo2:
        a = _avg(spo2)
        lines.append(f"| 平均血氧 | {a:.1f} % | n={len(spo2)} | wearable_daily |")
    if rhr:
        a = _avg(rhr)
        lines.append(f"| 平均静息心率 | {a:.0f} bpm | n={len(rhr)} | wearable_daily |")

    try:
        from pha.sqlite_storage import query_active_energy_daily_range

        kcal_rows = query_active_energy_daily_range(user_id, start, end)
        if kcal_rows:
            vals = [v for _, v in kcal_rows if v is not None]
            if vals:
                lines.append(
                    f"| 平均活动消耗 | {sum(vals) / len(vals):.0f} kcal/日 | n={len(vals)} | wearable_data |",
                )
    except Exception:
        pass

    return lines


def _wearable_attachment_overlay_lines(
    parsed_payload: Dict[str, Any],
    metrics: List[Dict[str, Any]],
) -> List[str]:
    count = int(parsed_payload.get("attachment_count") or 1)
    conf = str(parsed_payload.get("parse_confidence") or "").strip()
    lines = [
        f"【本轮穿戴截图定账 · {len(metrics)} 项 KPI · {count} 张 · conf={conf or '—'}】",
    ]
    for m in metrics[:32]:
        if not isinstance(m, dict):
            continue
        name = (m.get("metric_id") or m.get("metric_name") or "?").strip()
        val = m.get("value")
        if val is None:
            continue
        unit = (m.get("unit") or "").strip()
        sub = (m.get("sub_value") or "").strip()
        val_s = _format_overlay_value(val)
        if sub and sub not in val_s:
            val_s = f"{val_s} {sub}".strip()
        if unit and unit.lower() not in val_s.lower():
            val_s = f"{val_s} {unit}".strip()
        lines.append(f"| {name} | {val_s} | — | 截图定账 |")
    return lines


def _parsed_attachment_overlay_lines(parsed_payload: Optional[Dict[str, Any]]) -> List[str]:
    if not parsed_payload:
        return []
    wearable_metrics = [
        m for m in (parsed_payload.get("wearable_metrics") or []) if isinstance(m, dict)
    ]
    fam = str(parsed_payload.get("document_family") or "").strip().lower()
    if wearable_metrics or fam == "wearable":
        metrics = wearable_metrics or [
            m for m in (parsed_payload.get("metrics") or []) if isinstance(m, dict)
        ]
        if metrics:
            return _wearable_attachment_overlay_lines(parsed_payload, metrics)
    metrics = list(parsed_payload.get("metrics") or [])
    narratives = list(parsed_payload.get("narratives") or [])
    if not metrics and narratives:
        rd = (parsed_payload.get("report_date") or "")[:10] or "本轮附件"
        lines = [
            f"【本轮附件解析 · 叙事/标签 · report_date={rd} · narratives={len(narratives)}】",
        ]
        for n in narratives[:32]:
            if not isinstance(n, dict):
                continue
            cat = (n.get("category") or "未分类").strip()
            content = (n.get("content") or n.get("summary") or "").strip()
            if content:
                lines.append(f"- [{cat}] {content[:400]}")
        summary = (parsed_payload.get("vision_summary") or "").strip()
        if summary and len(lines) < 6:
            lines.append(f"摘要: {summary[:600]}")
        return lines
    if not metrics:
        return []
    rd = (parsed_payload.get("report_date") or "")[:10] or "本轮附件"
    ingest = parsed_payload.get("ingest") or {}
    stored = ingest.get("metrics_stored")
    stored_hint = f"已写入 {stored} 条" if stored is not None else "写入状态未知"
    lines = [f"【本轮附件解析 · report_date={rd} · parsed={len(metrics)} · {stored_hint}】"]
    for m in metrics[:48]:
        name = (
            m.get("metric_name")
            or m.get("metric_id")
            or m.get("name_zh")
            or m.get("item")
            or m.get("metric_code")
            or m.get("label")
            or "?"
        )
        val = m.get("value")
        if val is None:
            continue
        unit = (m.get("unit") or "").strip()
        ref_s = (m.get("reference_range") or "—").strip()
        val_s = f"{_format_overlay_value(val)}{(' ' + unit) if unit else ''}"
        lines.append(f"| {name} | {val_s} | {ref_s} | 附件解析·{rd} |")
    return lines


def _cap_block(text: str) -> str:
    s = (text or "").strip()
    if len(s) <= PHA_PATIENT_STATE_MAX_CHARS:
        return s
    return s[: PHA_PATIENT_STATE_MAX_CHARS - 20] + "\n…（Patient State 已按 PHA_PATIENT_STATE_MAX_CHARS 熔断）"


def build_patient_state_evidence_slice(
    user_id: str,
    user_message: str,
    *,
    question_type: QuestionType,
    has_wearable_user_snapshot: bool,
    parsed_overlay: Optional[Dict[str, Any]] = None,
    reference_date: date | None = None,
) -> str:
    """
    v2.2.2 Evidence Slice — DB remains full; only question-relevant rows reach the LLM.

    CASUAL: empty (no ledger injection).
    WEARABLE: omit full lab unless user message hints at labs; omit 7d wearable if Snapshot already injected.
    LAB: wider medical cap; keep wearable summary.
    LIFESTYLE: narrow medical cap.
    """
    uid = (user_id or "default").strip() or "default"
    ref = reference_date or effective_query_reference_date()
    msg = (user_message or "").strip()
    lab_hint = bool(_LAB_ROW_HINT_RE.search(msg))

    if question_type == QuestionType.CASUAL:
        return ""

    overlay = _parsed_attachment_overlay_lines(parsed_overlay)

    if question_type == QuestionType.WEARABLE:
        if lab_hint:
            medical = overlay + _medical_ledger_lines(uid, ref, max_rows=40)
        else:
            medical = overlay + (
                ["| （化验全表已省略 · 本轮为穿戴/活动问题） | — | 若需对照化验请点名指标或上传报告 |"]
                if not overlay
                else []
            )
        if has_wearable_user_snapshot:
            window = default_wearable_window(msg, reference=ref)
            wearable = [
                f"【穿戴 · User Data Snapshot 已注入 · 区间 {window.iso_span()}】",
                "| （Tier0 已含该区间的睡眠/血氧/HRV 等预计算均值；勿再引用近7日表或索要原始导出） | — | wearable_daily |",
            ]
        else:
            wearable = _wearable_ledger_lines(uid, ref, user_message=msg)
    elif question_type == QuestionType.LAB:
        medical = overlay + _medical_ledger_lines(uid, ref, max_rows=72)
        wearable = _wearable_ledger_lines(uid, ref, user_message=msg)
    elif question_type == QuestionType.COMBINED:
        medical = overlay + _medical_ledger_lines(uid, ref, max_rows=72)
        if has_wearable_user_snapshot:
            window = default_wearable_window(msg, reference=ref)
            wearable = [
                f"【穿戴 · Catalog/Snapshot 已覆盖 · 区间 {window.iso_span()}】",
                "| （复合问：穿戴统计由点单证据与 Manifest 提供；省略短窗表防重复） | — | wearable_daily |",
            ]
        else:
            wearable = _wearable_ledger_lines(uid, ref, user_message=msg)
    else:
        medical = overlay + _medical_ledger_lines(uid, ref, max_rows=28)
        wearable = _wearable_ledger_lines(uid, ref, user_message=msg)

    header = (
        "【Current Patient State · 证据切片（SQLite 实测子集）】\n"
        "以下为本轮问题相关的 SQLite 子集；医疗化验与穿戴分区不变，禁止混读。\n"
        "禁止编造未出现在本表中的指标数字。\n"
        "表头：| 指标 | 真实数值 | 参考/联动 |"
    )
    medical_part = (
        "### 🩺 【医疗化验单指标账本 (Blood Test / Lab Report)】\n" + "\n".join(medical)
        if medical
        else "### 🩺 【医疗化验单指标账本】\n暂无记录"
    )
    wearable_part = (
        "\n\n### ⌚ 【穿戴设备动态指标账本 (Apple Health / Wearable)】\n" + "\n".join(wearable)
        if wearable
        else "\n\n### ⌚ 【穿戴设备动态指标账本】\n暂无记录"
    )
    body = f"{medical_part}\n\n{wearable_part}"
    return _cap_block(f"{header}\n{body}")


def build_current_patient_state_block(
    user_id: str,
    reference_date: date | None = None,
    *,
    parsed_overlay: Optional[Dict[str, Any]] = None,
) -> str:
    """Full ledger (drawer / legacy); chat should prefer ``build_patient_state_evidence_slice``."""
    uid = (user_id or "default").strip() or "default"
    ref = reference_date or effective_query_reference_date()

    medical = _medical_ledger_lines(uid, ref, max_rows=_MAX_MEDICAL_ROWS)
    overlay = _parsed_attachment_overlay_lines(parsed_overlay)
    if overlay:
        medical = overlay + medical
    wearable = _wearable_ledger_lines(uid, ref)

    header = (
        "【Current Patient State · 当前患者事实账本】\n"
        "以下全部为 SQLite 实测值；医疗化验与穿戴设备数据已物理分区，禁止混读或跨区推断。\n"
        "禁止编造未出现在本表中的指标数字。\n"
        "表头：| 指标 | 真实数值 | 参考/联动 |"
    )
    medical_part = (
        "### 🩺 【医疗化验单指标账本 (Blood Test / Lab Report)】\n" + "\n".join(medical)
        if medical
        else "### 🩺 【医疗化验单指标账本】\n暂无记录"
    )
    wearable_part = (
        "\n\n### ⌚ 【穿戴设备动态指标账本 (Apple Health / Wearable)】\n" + "\n".join(wearable)
        if wearable
        else "\n\n### ⌚ 【穿戴设备动态指标账本】\n暂无记录"
    )
    body = f"{medical_part}\n\n{wearable_part}"
    return _cap_block(f"{header}\n{body}")
