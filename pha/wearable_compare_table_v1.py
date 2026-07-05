"""Wearable CompareTableV1 — deterministic 90d compare SSO (Wave 3d-γ-a)."""

from __future__ import annotations

import re
import statistics
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, Field

from pha.date_parser import safe_parse_date
from pha.date_range_parser import default_wearable_window
from pha.health_data import effective_query_reference_date
from pha.wearable_snapshot_v1 import infer_snapshot_reference_date
from pha.models import WearableDailySummary
from pha.sqlite_storage import query_wearable_daily_range
from pha.store import store
from pha.wearable_metric_registry import (
    comparable_wearable_daily_specs,
    metric_labels_zh,
    metric_mention_hints,
    metrics_footer_when_snapshot_only,
    snapshot_only_fallback_metric_ids,
    workout_compare_metric_ids,
)

RowKind = str
Verdict = str

# Wave 3d-δ-c: 元数据真源为 storage/registry/wearable_metric_registry.json
COMPARABLE_METRIC_SPECS: Tuple[Tuple[str, str, str], ...] = comparable_wearable_daily_specs()
WORKOUT_METRICS: Tuple[str, ...] = workout_compare_metric_ids()
SNAPSHOT_ONLY_FALLBACK_METRICS: Tuple[str, ...] = snapshot_only_fallback_metric_ids()
NO_BASELINE_METRICS: Tuple[str, ...] = ()  # 保留兼容；新指标用 Registry snapshot_only_if_no_baseline

_WORKOUT_INTENT_RE = re.compile(
    r"workout|work\s*out|锻炼|跑步|训练|运动强度|心率范围",
    re.I,
)

_COMPARE_ALL_METRICS_RE = re.compile(
    r"所有指标|各项指标|全部指标|多项指标|各.{0,2}指标|是否正常|对比|相比|是不是都|整体",
    re.I,
)

_SLEEP_HR_MIN_RE = re.compile(r"^(\d+)hr(\d+)min$", re.I)
_SLEEP_HR_ONLY_RE = re.compile(r"^(\d+(?:\.\d+)?)hr$", re.I)


class CompareRowV1(BaseModel):
    metric_id: str
    row_kind: RowKind
    snapshot_value: Optional[str] = None
    snapshot_unit: str = ""
    snapshot_source: str = "WEARABLE_SNAPSHOT"
    baseline_90d_value: Optional[str] = None
    baseline_90d_unit: str = ""
    baseline_90d_range: str = ""
    baseline_source: str = "wearable.summary"
    verdict: Verdict = "insufficient_data"
    verdict_note: str = ""


class CompareTableV1(BaseModel):
    schema_version: str = "wearable_compare_table_v1"
    reference_date: str = ""
    window_90d: Dict[str, Any] = Field(default_factory=dict)
    rows: List[CompareRowV1] = Field(default_factory=list)

    def to_markdown(self) -> str:
        return compare_table_to_markdown(self)

    def to_llm_markdown(self) -> str:
        return compare_table_to_llm_markdown(self)

    def to_parsed_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="python")


def user_requests_workout_compare(user_message: str) -> bool:
    return bool(_WORKOUT_INTENT_RE.search(user_message or ""))


def parse_snapshot_numeric(metric_id: str, value: str) -> Optional[float]:
    raw = (value or "").strip()
    if not raw:
        return None
    if metric_id in ("sleep_time_asleep", "sleep_deep", "sleep_rem"):
        m = _SLEEP_HR_MIN_RE.match(raw.replace(" ", ""))
        if m:
            return int(m.group(1)) + int(m.group(2)) / 60.0
        m2 = _SLEEP_HR_ONLY_RE.match(raw.replace(" ", ""))
        if m2:
            return float(m2.group(1))
        return None
    if metric_id in (
        "hrv_rmssd_ms",
        "resting_heart_rate_bpm",
        "spo2_percent",
        "workout_count_recent",
        "respiratory_rate",
    ):
        nums = [float(x) for x in re.findall(r"[\d.]+", raw)]
        if not nums:
            return None
        if len(nums) >= 2 and "-" in raw:
            return (nums[0] + nums[-1]) / 2.0
        return nums[0]
    return None


def compute_verdict(snapshot: float, *, range_min: float, range_max: float) -> Verdict:
    if range_min <= snapshot <= range_max:
        return "within_range"
    if snapshot > range_max:
        return "above_mean"
    if snapshot < range_min:
        return "below_mean"
    return "within_range"


def _verdict_note(verdict: Verdict, *, row_kind: RowKind, metric_id: str = "") -> str:
    if row_kind == "snapshot_only" and metric_id in NO_BASELINE_METRICS:
        return "暂无睡眠分期历史，无法与近 90 天对比"
    if row_kind == "snapshot_only":
        return "仅本次截图读数，暂无对应近 90 天基线"
    if verdict == "within_range":
        return "落在 90 天区间内"
    if verdict == "above_mean":
        return "高于 90 天区间上限"
    if verdict == "below_mean":
        return "低于 90 天区间下限"
    if verdict == "insufficient_data":
        return "本次截图暂无该指标"
    return ""


def _format_range(rmin: float, rmax: float) -> str:
    return f"[{rmin:.1f}-{rmax:.1f}]"


def _baseline_stats(
    rows: Sequence[WearableDailySummary],
    field: str,
) -> Optional[Tuple[float, float, float]]:
    vals: List[float] = []
    for row in rows:
        v = getattr(row, field, None)
        if v is not None:
            vals.append(float(v))
    if not vals:
        return None
    return statistics.mean(vals), min(vals), max(vals)


def _snapshot_map(parsed_payload: Mapping[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in parsed_payload.get("wearable_metrics") or parsed_payload.get("metrics") or []:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("metric_id") or "").strip()
        val = str(m.get("value") or "").strip()
        if mid and val:
            out[mid] = val
    return out


def _baseline_from_override(
    baseline_override: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Tuple[float, float, float, str]]:
    out: Dict[str, Tuple[float, float, float, str]] = {}
    for metric_id, field, unit in COMPARABLE_METRIC_SPECS:
        spec = baseline_override.get(metric_id) or {}
        if not spec:
            continue
        mean = float(spec["mean"])
        rmin = float(spec.get("range_min", spec.get("min", mean)))
        rmax = float(spec.get("range_max", spec.get("max", mean)))
        out[metric_id] = (mean, rmin, rmax, str(spec.get("unit") or unit))
    return out


def _baseline_from_warehouse(
    user_id: str,
    user_message: str,
    *,
    reference_date: date,
) -> Tuple[Dict[str, Tuple[float, float, float, str]], Dict[str, Any], int]:
    window = default_wearable_window(user_message, reference=reference_date)
    uid = (user_id or "default").strip() or "default"
    rows: List[WearableDailySummary] = list(
        query_wearable_daily_range(uid, window.start, window.end) or [],
    )
    if not rows:
        rows = [
            r for r in store.list_wearable_rows(uid) if window.start <= r.day <= window.end
        ]
    baselines: Dict[str, Tuple[float, float, float, str]] = {}
    for metric_id, field, unit in COMPARABLE_METRIC_SPECS:
        stats = _baseline_stats(rows, field)
        if stats is None:
            continue
        mean, rmin, rmax = stats
        baselines[metric_id] = (mean, rmin, rmax, unit)
    from pha.workout_storage import baselines_for_workout_compare

    baselines.update(
        baselines_for_workout_compare(
            uid,
            reference_date=reference_date,
            window_start=window.start,
            window_end=window.end,
        ),
    )
    window_meta = {
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "n_days": len(rows),
    }
    return baselines, window_meta, len(rows)


def _format_workout_baseline_value(metric_id: str, mean: float, rmin: float, rmax: float) -> str:
    if metric_id == "workout_heart_rate_range_bpm":
        return f"{rmin:.0f}-{rmax:.0f}"
    if metric_id == "workout_count_recent":
        return f"{mean:.0f}"
    return f"{mean:.1f}"


def _append_workout_compare_rows(
    table_rows: List[CompareRowV1],
    snap: Dict[str, str],
    baselines: Dict[str, Tuple[float, float, float, str]],
    user_message: str,
) -> None:
    wants = user_requests_workout_compare(user_message) or any(
        snap.get(m) for m in WORKOUT_METRICS
    )
    if not wants:
        return

    workout_any = False
    for metric_id in WORKOUT_METRICS:
        snapshot_val = snap.get(metric_id)
        if not snapshot_val:
            continue
        workout_any = True
        base = baselines.get(metric_id)
        if base:
            mean, rmin, rmax, base_unit = base
            snap_num = parse_snapshot_numeric(metric_id, snapshot_val)
            verdict = (
                compute_verdict(snap_num, range_min=rmin, range_max=rmax)
                if snap_num is not None
                else "within_range"
            )
            table_rows.append(
                CompareRowV1(
                    metric_id=metric_id,
                    row_kind="comparable_90d",
                    snapshot_value=snapshot_val,
                    snapshot_unit=base_unit,
                    baseline_90d_value=_format_workout_baseline_value(
                        metric_id,
                        mean,
                        rmin,
                        rmax,
                    ),
                    baseline_90d_unit=base_unit,
                    baseline_90d_range=_format_range(rmin, rmax),
                    baseline_source="wearable.workout",
                    verdict=verdict,
                    verdict_note=_verdict_note(verdict, row_kind="comparable_90d"),
                ),
            )
        else:
            table_rows.append(
                CompareRowV1(
                    metric_id=metric_id,
                    row_kind="snapshot_only",
                    snapshot_value=snapshot_val,
                    baseline_90d_value="NO_BASELINE",
                    baseline_source="none",
                    verdict="snapshot_only",
                    verdict_note=_verdict_note("snapshot_only", row_kind="snapshot_only"),
                ),
            )

    if not workout_any and user_requests_workout_compare(user_message):
        table_rows.append(
            CompareRowV1(
                metric_id="workout_heart_rate_range_bpm",
                row_kind="snapshot_only",
                snapshot_value=None,
                baseline_90d_value="NO_BASELINE",
                baseline_source="none",
                verdict="insufficient_data",
                verdict_note="本次截图暂无锻炼指标",
            ),
        )


def build_wearable_compare_table_v1(
    parsed_payload: Mapping[str, Any],
    *,
    user_id: str = "default",
    user_message: str = "",
    baseline_override: Optional[Mapping[str, Mapping[str, Any]]] = None,
    reference_date: Optional[date] = None,
    window_90d_override: Optional[Mapping[str, Any]] = None,
) -> CompareTableV1:
    ref = reference_date
    if ref is None:
        snap_raw = str(parsed_payload.get("snapshot_reference_date") or "").strip()
        if snap_raw:
            ref = safe_parse_date(snap_raw)
    if ref is None:
        ref = infer_snapshot_reference_date(
            user_message=user_message,
            parsed_payload=parsed_payload,
        )
    ref = ref or effective_query_reference_date()
    snap = _snapshot_map(parsed_payload)
    if baseline_override is not None:
        baselines = _baseline_from_override(baseline_override)
        window_meta = dict(window_90d_override or {})
        if "n_days" not in window_meta:
            window_meta["n_days"] = window_meta.get("n_days", 0)
    else:
        baselines, window_meta, _ = _baseline_from_warehouse(
            (user_id or "default").strip() or "default",
            user_message,
            reference_date=ref,
        )
    if baseline_override is not None:
        from pha.date_range_parser import default_wearable_window
        from pha.workout_storage import baselines_for_workout_compare

        win = default_wearable_window(user_message, reference=ref)
        uid = (user_id or "default").strip() or "default"
        for mid, base in baselines_for_workout_compare(
            uid,
            reference_date=ref,
            window_start=win.start,
            window_end=win.end,
        ).items():
            if mid not in baselines and mid not in (baseline_override or {}):
                baselines[mid] = base

    table_rows: List[CompareRowV1] = []

    for metric_id, _field, unit in COMPARABLE_METRIC_SPECS:
        snapshot_val = snap.get(metric_id)
        if not snapshot_val:
            continue
        base = baselines.get(metric_id)
        if not base:
            continue
        mean, rmin, rmax, base_unit = base
        snap_num = parse_snapshot_numeric(metric_id, snapshot_val)
        verdict = (
            compute_verdict(snap_num, range_min=rmin, range_max=rmax)
            if snap_num is not None
            else "within_range"
        )
        table_rows.append(
            CompareRowV1(
                metric_id=metric_id,
                row_kind="comparable_90d",
                snapshot_value=snapshot_val,
                snapshot_unit=unit,
                baseline_90d_value=f"{mean:.1f}",
                baseline_90d_unit=base_unit,
                baseline_90d_range=_format_range(rmin, rmax),
                baseline_source="wearable.summary",
                verdict=verdict,
                verdict_note=_verdict_note(verdict, row_kind="comparable_90d"),
            ),
        )

    for metric_id in NO_BASELINE_METRICS:
        snapshot_val = snap.get(metric_id)
        if not snapshot_val:
            continue
        table_rows.append(
            CompareRowV1(
                metric_id=metric_id,
                row_kind="snapshot_only",
                snapshot_value=snapshot_val,
                baseline_90d_value="NO_BASELINE",
                baseline_source="none",
                verdict="snapshot_only",
                verdict_note=_verdict_note("snapshot_only", row_kind="snapshot_only", metric_id=metric_id),
            ),
        )

    for metric_id in SNAPSHOT_ONLY_FALLBACK_METRICS:
        snapshot_val = snap.get(metric_id)
        if not snapshot_val:
            continue
        if baselines.get(metric_id):
            continue
        table_rows.append(
            CompareRowV1(
                metric_id=metric_id,
                row_kind="snapshot_only",
                snapshot_value=snapshot_val,
                baseline_90d_value="NO_BASELINE",
                baseline_source="none",
                verdict="snapshot_only",
                verdict_note=_verdict_note(
                    "snapshot_only",
                    row_kind="snapshot_only",
                    metric_id=metric_id,
                ),
            ),
        )

    _append_workout_compare_rows(table_rows, snap, baselines, user_message)

    return CompareTableV1(
        reference_date=ref.isoformat(),
        window_90d=window_meta,
        rows=table_rows,
    )


def compare_table_to_markdown(table: CompareTableV1) -> str:
    lines = [
        "【Wearable Compare Table · Tier0 · SSO】",
        "对比数字仅允许引用下表；禁止自行构造 90d 均值。",
        "| metric_id | 截图 | 90d基线 | 区间 | verdict | 说明 |",
    ]
    for row in table.rows:
        snap = row.snapshot_value or "—"
        base = row.baseline_90d_value or "—"
        rng = row.baseline_90d_range or "—"
        lines.append(
            f"| {row.metric_id} | {snap} | {base} | {rng} | {row.verdict} | {row.verdict_note} |",
        )
    if not table.rows:
        lines.append("| — | — | — | — | insufficient_data | 暂无可对比行 |")
    return "\n".join(lines)


def compare_table_to_llm_markdown(table: CompareTableV1) -> str:
    """User/LLM-facing compare table — Chinese labels, no metric_id."""
    lines = [
        "【截图与过去约 90 天对比 · 仅允许引用下表数字】",
        "| 指标 | 本次截图 | 近 90 天平均 | 常见区间 | 结论 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in table.rows:
        label = _METRIC_LABEL_ZH.get(row.metric_id, row.metric_id)
        snap = (
            _format_snapshot_display(row.metric_id, row.snapshot_value or "")
            if row.snapshot_value
            else "—"
        )
        if (row.baseline_90d_value or "").strip() == "NO_BASELINE":
            base = "—"
            rng = "—"
            verdict = "仅本次截图，无法与 90 天对比"
        elif row.row_kind == "comparable_90d":
            unit = (row.baseline_90d_unit or "").strip()
            base = f"{row.baseline_90d_value or '—'} {unit}".strip()
            rng = _format_range_human(row.baseline_90d_range)
            verdict = _VERDICT_LABEL_ZH.get(row.verdict, row.verdict_note or "")
        else:
            base = "—"
            rng = "—"
            verdict = _VERDICT_LABEL_ZH.get(row.verdict, row.verdict_note or "仅本次截图")
        lines.append(f"| {label} | {snap} | {base} | {rng} | {verdict} |")
    if not table.rows:
        lines.append("| — | — | — | — | 暂无数据 |")
    return "\n".join(lines)


def build_wearable_compare_table_tier0_block(
    parsed_payload: Mapping[str, Any],
    *,
    user_id: str,
    user_message: str,
) -> str:
    table = build_wearable_compare_table_v1(
        parsed_payload,
        user_id=user_id,
        user_message=user_message,
    )
    return table.to_markdown()


def _fallback_footer_for_table(table: CompareTableV1) -> str:
    """Only disclaim metrics that are actually snapshot_only in this CompareTable."""
    labels: List[str] = []
    for row in table.rows:
        if row.row_kind != "snapshot_only" or not row.snapshot_value:
            continue
        if row.metric_id in metrics_footer_when_snapshot_only():
            labels.append(_METRIC_LABEL_ZH.get(row.metric_id, row.metric_id))
    if not labels:
        return ""
    joined = "、".join(labels)
    return (
        f"说明：{joined} 仅来自截图，系统没有保存该项的 90 天历史，无法与过去 90 天对比。"
    )

_METRIC_LABEL_ZH: Dict[str, str] = metric_labels_zh()
_METRIC_MENTION_HINTS: Dict[str, Tuple[str, ...]] = metric_mention_hints()

_VERDICT_LABEL_ZH: Dict[str, str] = {
    "within_range": "落在近 90 天正常区间内",
    "above_mean": "高于近 90 天区间上限",
    "below_mean": "低于近 90 天区间下限",
    "snapshot_only": "仅本次截图",
    "insufficient_data": "暂无可靠读数",
}

_DECIMAL_TOKEN_RE = re.compile(r"(?<!\d)(\d+\.\d{1,2})(?!\d)")

# 仅匹配「分期 + 90d + 均值/数字」类编造（段内匹配，禁止跨段）
_FABRICATED_STAGE_90D_RES: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?:深睡|sleep_deep)[^\n]{0,48}(?:90\s*天|近\s*90|数仓摘要|User Data Snapshot)"
            r"[^\n]{0,32}(?:平均|均值)[^\n]{0,20}(?:\d|hr|小时|min|分钟)",
            re.I,
        ),
        "compare_forbidden_90d_stage:deep",
    ),
    (
        re.compile(
            r"(?:REM|sleep_rem)[^\n]{0,48}(?:90\s*天|近\s*90|数仓摘要|User Data Snapshot)"
            r"[^\n]{0,32}(?:平均|均值)[^\n]{0,20}(?:\d|hr|小时|min|分钟)",
            re.I,
        ),
        "compare_forbidden_90d_stage:rem",
    ),
)

# 仅拦截「从 Summary 编造均值」；允许 LLM 写「近 90 天正常区间内」（类型 A）
_FORBIDDEN_PHRASES: Tuple[str, ...] = (
    "数仓摘要平均",
)

_ADVISORY_CUE_RE = re.compile(
    r"建议|综上所述|接下来|最后[，,]|小结|可以注意|保持良好|咨询医生|生活习惯|"
    r"适当增加|连续\s*\d|观察就寝|不必单日焦虑|专项解读|改善效果",
    re.I,
)
_COMPARE_NARRATIVE_BULLET_RE = re.compile(
    r"^\s*(?:\d+\.\s+)?[-*]?\s*\*\*(?:睡眠|HRV|静息|血氧|呼吸|深睡|REM|锻炼|近期锻炼)",
    re.I | re.M,
)
_COMPARE_INLINE_BULLET_RE = re.compile(
    r"落在近\s*90\s*天(?:正常)?区间内|本次\s*\d|过去约\s*90\s*天平均",
    re.I,
)

# 从 Summary 抄均值做对比（须同时出现 Summary 锚点 + 均值词 + 未引用截图 KPI）
_SUMMARY_HIJACK_RE = re.compile(
    r"(?:User Data Snapshot|数仓摘要|近\s*\d+\s*天(?:内)?的?平均)",
    re.I,
)

_STAGE_NEGATION_RE = re.compile(
    r"无法与|不能与|无法对比|禁止与|不含.*历史|NO_BASELINE|仅.*截图|只.*截图",
    re.I,
)

# Wave 3d-ε · Interpretation Policy v1 — NO_BASELINE 行禁止无根评价词
_NO_BASELINE_SUBJECTIVE_RE = re.compile(
    r"(?:较为|非常|相当|比较)?(?:充足|不足|正常|异常|良好|优异|偏差|理想|欠佳)"
    r"|(?:偏低|偏高)"
    r"|(?:sufficient|adequate|normal|abnormal|excellent|poor)",
    re.I,
)

_NO_BASELINE_HINTS_EXTRA: Dict[str, Tuple[str, ...]] = {
    "sleep_deep": ("深睡", "深度睡眠", "睡眠分期"),
    "sleep_rem": ("REM", "快速眼动", "睡眠分期"),
    "workout_heart_rate_range_bpm": ("锻炼", "workout", "运动", "心率范围"),
    "workout_count_recent": ("锻炼", "workout", "运动", "次锻炼"),
}

# 「正常/偏低/偏高」用于 personal 90d 区间描述时允许（类型 A）
_SAFE_COMPARABLE_SUBJECTIVE_RE = re.compile(
    r"落在(?:近\s*90\s*天)?正常区间内|正常区间内|正常范围内|常见区间内",
    re.I,
)

_ABOVE_CUES: Tuple[str, ...] = ("明显偏高", "显著偏高", "远高于", "远高于", "超标")
_BELOW_CUES: Tuple[str, ...] = ("明显偏低", "显著偏低", "远低于", "远低于")


def _format_duration_human(value: str) -> str:
    raw = (value or "").strip().replace(" ", "")
    m = re.match(r"^(\d+)hr(\d+)min$", raw, re.I)
    if m:
        return f"{int(m.group(1))} 小时 {int(m.group(2))} 分钟"
    m2 = re.match(r"^(\d+)hr$", raw, re.I)
    if m2:
        return f"{int(m2.group(1))} 小时"
    return value or "—"


def _format_snapshot_display(metric_id: str, value: str) -> str:
    if metric_id in ("sleep_time_asleep", "sleep_deep", "sleep_rem"):
        return _format_duration_human(value)
    if metric_id == "hrv_rmssd_ms":
        return f"{value} ms"
    if metric_id == "resting_heart_rate_bpm":
        return f"{value} bpm"
    if metric_id == "spo2_percent":
        return f"{value}%"
    if metric_id == "respiratory_rate":
        return f"{value} breaths/min" if value and "breath" not in value.lower() else value
    if metric_id == "workout_heart_rate_range_bpm":
        return f"{value} bpm"
    if metric_id == "workout_count_recent":
        return f"{value} 天（近4周）"
    return value


def _audit_incomplete_coverage(
    text: str,
    table: CompareTableV1,
    user_message: str,
) -> List[str]:
    """When user asks broad compare, every CompareTable row must appear in the answer."""
    if not _COMPARE_ALL_METRICS_RE.search(user_message or ""):
        return []
    violations: List[str] = []
    for row in table.rows:
        if row.row_kind == "comparable_90d" and row.snapshot_value:
            if not _snapshot_cited(text, row):
                violations.append(f"compare_incomplete:{row.metric_id}")
    if user_requests_workout_compare(user_message):
        for row in table.rows:
            if row.metric_id in WORKOUT_METRICS and row.snapshot_value:
                if not _snapshot_cited(text, row):
                    violations.append(f"compare_incomplete:{row.metric_id}")
    return violations


def compare_table_from_parsed(parsed_payload: Mapping[str, Any]) -> Optional[CompareTableV1]:
    raw = parsed_payload.get("wearable_compare_table_v1")
    if not isinstance(raw, dict):
        return None
    try:
        return CompareTableV1.model_validate(raw)
    except Exception:
        return None


def _float_token_variants(value: float) -> Set[str]:
    out = {f"{value:.1f}", f"{value:.2f}"}
    if abs(value - round(value)) < 1e-6:
        out.add(str(int(round(value))))
    return out


def _authorized_tokens(table: CompareTableV1) -> Set[str]:
    allowed: Set[str] = set()
    for row in table.rows:
        if row.snapshot_value:
            sv = row.snapshot_value.replace(" ", "")
            allowed.add(sv)
            num = parse_snapshot_numeric(row.metric_id, row.snapshot_value)
            if num is not None:
                allowed.update(_float_token_variants(num))
            # Wave 3d-ε+: authorize range endpoints (e.g. respiratory 11-17.5 → 17.5)
            for part in re.findall(r"[\d.]+", row.snapshot_value):
                allowed.add(part)
                try:
                    allowed.update(_float_token_variants(float(part)))
                except ValueError:
                    pass
        base = (row.baseline_90d_value or "").strip()
        if base and base != "NO_BASELINE":
            allowed.add(base)
            try:
                allowed.update(_float_token_variants(float(base)))
            except ValueError:
                pass
        if row.baseline_90d_range:
            for part in re.findall(r"[\d.]+", row.baseline_90d_range):
                allowed.add(part)
    return allowed


def _decimal_near_allowed(token: str, allowed: Set[str], *, eps: float = 0.15) -> bool:
    try:
        fv = float(token)
    except ValueError:
        return False
    for a in allowed:
        try:
            if abs(fv - float(a)) <= eps:
                return True
        except ValueError:
            continue
    return False


def _format_range_human(rng: str) -> str:
    s = (rng or "").strip()
    if s.startswith("[") and s.endswith("]"):
        return s[1:-1].replace("-", "–")
    return s or "—"


def _human_duration_cited(text: str, metric_id: str, snapshot_value: str) -> bool:
    """Match polished zh duration (e.g. 8hr43min → 8 小时 43 分钟) in user-visible replies."""
    if metric_id not in ("sleep_time_asleep", "sleep_deep", "sleep_rem"):
        return False
    raw = (snapshot_value or "").replace(" ", "")
    m = _SLEEP_HR_MIN_RE.match(raw)
    if m:
        hr, mn = int(m.group(1)), int(m.group(2))
        return bool(re.search(rf"{hr}\s*小时\s*{mn}\s*分钟", text or ""))
    m2 = _SLEEP_HR_ONLY_RE.match(raw)
    if m2:
        hr = int(float(m2.group(1)))
        return bool(re.search(rf"{hr}\s*小时(?:\s*|$|[，。；、])", text or ""))
    return False


def _snapshot_cited(text: str, row: CompareRowV1) -> bool:
    sv = (row.snapshot_value or "").replace(" ", "")
    if not sv:
        return False
    compact = (text or "").replace(" ", "")
    if sv in compact:
        return True
    if _human_duration_cited(text, row.metric_id, row.snapshot_value or ""):
        return True
    num = parse_snapshot_numeric(row.metric_id, row.snapshot_value or "")
    if num is None:
        return False
    for variant in _float_token_variants(num):
        if variant in compact:
            return True
    return False


def _metric_discussed(text: str, metric_id: str) -> bool:
    blob = text or ""
    if metric_id in blob:
        return True
    for hint in _METRIC_MENTION_HINTS.get(metric_id, ()):
        if hint.lower() in blob.lower():
            return True
    return False


def _audit_missing_snapshot_citation(text: str, table: CompareTableV1) -> List[str]:
    violations: List[str] = []
    for row in table.rows:
        if row.row_kind != "comparable_90d" or not row.snapshot_value:
            continue
        if not _metric_discussed(text, row.metric_id):
            continue
        if not _snapshot_cited(text, row):
            violations.append(f"compare_missing_snapshot:{row.metric_id}")
    return violations


def _audit_summary_hijack(text: str, table: CompareTableV1) -> List[str]:
    if not _SUMMARY_HIJACK_RE.search(text or ""):
        return []
    violations: List[str] = []
    for row in table.rows:
        if row.row_kind != "comparable_90d" or not row.snapshot_value:
            continue
        if _metric_discussed(text, row.metric_id) and not _snapshot_cited(text, row):
            violations.append("compare_summary_mean_hijack")
            break
    return violations


def _no_baseline_rows(table: CompareTableV1) -> List[CompareRowV1]:
    return [
        r
        for r in table.rows
        if (r.baseline_90d_value or "").strip() == "NO_BASELINE"
        or r.row_kind == "snapshot_only"
    ]


def _segment_mentions_no_baseline_metric(segment: str, row: CompareRowV1) -> bool:
    blob = segment or ""
    hints = list(_METRIC_MENTION_HINTS.get(row.metric_id, ())) + list(
        _NO_BASELINE_HINTS_EXTRA.get(row.metric_id, ()),
    )
    if row.metric_id in blob:
        return True
    return any(h.lower() in blob.lower() for h in hints if h)


def _subjective_hit_is_safe_comparable_phrase(blob: str, start: int, end: int) -> bool:
    """Allow 「正常区间内」等类型 A 区间描述，不误伤 NO_BASELINE 审计。"""
    window = blob[max(0, start - 28) : min(len(blob), end + 28)]
    if _SAFE_COMPARABLE_SUBJECTIVE_RE.search(window):
        token = (blob[start:end] or "").strip().lower()
        if token in ("正常", "偏低", "偏高", "normal"):
            return True
    return False


def _audit_no_baseline_subjective(text: str, table: CompareTableV1) -> List[str]:
    """Block subjective quality judgments on metrics without personal 90d baseline."""
    rows = _no_baseline_rows(table)
    if not rows:
        return []
    violations: List[str] = []
    seen: Set[str] = set()
    blob = text or ""
    for row in rows:
        mid = row.metric_id
        if mid in seen:
            continue
        hints = list(_METRIC_MENTION_HINTS.get(mid, ())) + list(
            _NO_BASELINE_HINTS_EXTRA.get(mid, ()),
        )
        for match in _NO_BASELINE_SUBJECTIVE_RE.finditer(blob):
            if _subjective_hit_is_safe_comparable_phrase(blob, match.start(), match.end()):
                continue
            window = blob[max(0, match.start() - 90) : min(len(blob), match.end() + 90)]
            if any(h and h.lower() in window.lower() for h in hints):
                seen.add(mid)
                violations.append(f"compare_no_baseline_subjective:{mid}")
                break
    return violations


def _skip_fabricated_stage_codes(table: CompareTableV1) -> Set[str]:
    """δ-a 后深睡/REM 已有 comparable 基线时，允许类型 A 转述个人均值（非 Summary 编造）。"""
    skip: Set[str] = set()
    by_id = {r.metric_id: r for r in table.rows}
    for mid, code in (
        ("sleep_deep", "compare_forbidden_90d_stage:deep"),
        ("sleep_rem", "compare_forbidden_90d_stage:rem"),
    ):
        row = by_id.get(mid)
        if not row:
            continue
        base = (row.baseline_90d_value or "").strip()
        if row.row_kind == "comparable_90d" and base and base != "NO_BASELINE":
            skip.add(code)
    return skip


_FALSE_NO_BASELINE_CLAIM_RE = re.compile(
    r"缺乏\s*90\s*天|没有\s*(?:提供\s*)?(?:过去\s*)?90\s*天|无\s*90\s*天\s*历史|"
    r"无法\s*(?:与\s*)?(?:过去\s*)?90\s*天\s*对比|没有.*历史数据来对比|"
    r"同样也缺乏90天",
    re.I,
)


def _audit_false_no_baseline_claim(
    text: str,
    table: CompareTableV1,
) -> List[str]:
    """CompareTable 已有 comparable 分期时，禁止声称「无 90 天历史」。"""
    violations: List[str] = []
    if not _FALSE_NO_BASELINE_CLAIM_RE.search(text or ""):
        return violations
    for mid in ("sleep_deep", "sleep_rem"):
        row = next((r for r in table.rows if r.metric_id == mid), None)
        if not row or row.row_kind != "comparable_90d":
            continue
        base = (row.baseline_90d_value or "").strip()
        if not base or base == "NO_BASELINE":
            continue
        hints = list(_METRIC_MENTION_HINTS.get(mid, ())) + list(
            _NO_BASELINE_HINTS_EXTRA.get(mid, ()),
        )
        blob = text or ""
        for h in hints:
            if not h:
                continue
            pos = blob.lower().find(h.lower())
            if pos < 0:
                continue
            window = blob[max(0, pos - 80) : min(len(blob), pos + 120)]
            if _FALSE_NO_BASELINE_CLAIM_RE.search(window):
                violations.append(f"compare_false_no_baseline_claim:{mid}")
                break
    return violations


def _audit_fabricated_stage_90d(
    text: str,
    table: Optional[CompareTableV1] = None,
) -> List[str]:
    violations: List[str] = []
    seen: Set[str] = set()
    skip_codes = _skip_fabricated_stage_codes(table) if table is not None else set()
    segments = re.split(r"\n\s*\n", text or "")
    if not any(s.strip() for s in segments):
        segments = [text or ""]
    for segment in segments:
        blob = segment.strip()
        if not blob:
            continue
        for pat, code in _FABRICATED_STAGE_90D_RES:
            if code in seen or code in skip_codes:
                continue
            m = pat.search(blob)
            if not m:
                continue
            window = blob[max(0, m.start() - 24) : min(len(blob), m.end() + 48)]
            if _STAGE_NEGATION_RE.search(window):
                continue
            seen.add(code)
            violations.append(code)
    return violations


_CORRECTION_USER_RE = re.compile(
    r"重新|再次|核实|不对|错误|明显错|解析.*不对|重新分析|再次解析|从哪来|哪里来的|"
    r"睡眠.*(?:不对|错误|核实)|锻炼.*(?:不对|错误|哪里来|从哪来|次数)",
    re.I,
)

_EPISODIC_SHORT_METRIC_RE = re.compile(
    r"^(?:我(?:最近|今天)的?\s*)?"
    r"(?:睡眠|步数|锻炼|心率|血氧|呼吸率?|HRV|静息心率)(?:呢|吗|\?|？)?$",
    re.I,
)

_EXERCISE_SUITABILITY_RE = re.compile(
    r"适合|能否|可以.*运动|明天|后天|跑步|训练|workout",
    re.I,
)

_EXERCISE_ADVICE_ONLY_RE = re.compile(
    r"^(?:那)?(?:明天|后天|今天)?.*(?:适合|能否|可以|能).*(?:运动|锻炼|跑步|训练)"
    r"|^(?:跑多久|跑步).*(?:合适|多久|吗)",
    re.I,
)

_HEALTH_SUMMARY_RE = re.compile(
    r"总结|概览|整体.*(?:健康|情况)|健康数据",
    re.I,
)

_EPISODIC_DELTA_RE = re.compile(
    r"^(?:和上周比呢|和昨天比呢|相比怎么样|比呢|正常吗)[\?？]?$",
    re.I,
)

_CATALOG_PRIMARY_METRIC: Dict[str, str] = {
    "sleep": "sleep_time_asleep",
    "hrv": "hrv_rmssd_ms",
    "rhr": "resting_heart_rate_bpm",
    "spo2": "spo2_percent",
    "respiratory_rate": "respiratory_rate",
}

_SLEEP_FOCUS_METRIC_IDS = frozenset({"sleep_time_asleep", "sleep_deep", "sleep_rem"})
# Workout questions are resolved as a pair (HR range + recent count) by the probe layer's
# _WORKOUT_HINT_RE coupling; treat that pair as a valid narrow focus, mirroring the sleep-stage pair.
_WORKOUT_FOCUS_METRIC_IDS = frozenset({"workout_heart_rate_range_bpm", "workout_count_recent"})
_SINGLE_METRIC_FOCUS_MAX = 2


def _is_allowed_focus_pair(ids: Sequence[str]) -> bool:
    s = set(ids)
    return s <= _SLEEP_FOCUS_METRIC_IDS or s <= _WORKOUT_FOCUS_METRIC_IDS


def infer_single_metric_focus_ids(user_message: str) -> List[str]:
    """
    Narrow wearable follow-up: one metric (or sleep stage pair), not broad compare.

    Uses hint/catalog mapping only — does **not** expand via ``user_message_needs_wearable_query``.
    """
    msg = (user_message or "").strip()
    if not msg:
        return []
    if _EXERCISE_ADVICE_ONLY_RE.search(msg):
        return []
    if _COMPARE_ALL_METRICS_RE.search(msg) or user_requests_snapshot_correction(msg):
        return []
    from pha.intent_gates import infer_wearable_metrics
    from pha.wearable_metric_probe import _CATALOG_TO_REGISTRY, _hint_match_metric_ids

    if _EPISODIC_SHORT_METRIC_RE.match(msg):
        for cat in infer_wearable_metrics(msg):
            primary = _CATALOG_PRIMARY_METRIC.get(cat)
            if primary:
                return [primary]
        return []

    seen: Set[str] = set()
    ordered: List[str] = []
    for mid in _hint_match_metric_ids(msg):
        if mid not in seen:
            seen.add(mid)
            ordered.append(mid)
    # Narrow-hint precedence: an unambiguous registry-hint match (e.g. 「心率范围呢」「请分析心率指标」)
    # must win over the broad bundle `core` fallback, which would otherwise add every comparable
    # metric and blow past the single-focus cap. Only expand via infer_wearable_metrics when hints
    # are empty or already over-broad.
    if ordered and len(ordered) <= _SINGLE_METRIC_FOCUS_MAX and (
        len(ordered) < 2 or _is_allowed_focus_pair(ordered)
    ):
        return ordered
    for cat in infer_wearable_metrics(msg):
        for reg_id in _CATALOG_TO_REGISTRY.get(cat, ()):
            if reg_id not in seen:
                seen.add(reg_id)
                ordered.append(reg_id)
    if not ordered or len(ordered) > _SINGLE_METRIC_FOCUS_MAX:
        return []
    if len(ordered) == 2 and not _is_allowed_focus_pair(ordered):
        return []
    return ordered


def _format_metric_focus_rows(
    table: CompareTableV1,
    focus_ids: Set[str],
) -> List[str]:
    lines: List[str] = []
    for row in table.rows:
        if row.metric_id not in focus_ids or not row.snapshot_value:
            continue
        label = _METRIC_LABEL_ZH.get(row.metric_id, row.metric_id)
        snap = _format_snapshot_display(row.metric_id, row.snapshot_value)
        if row.row_kind == "comparable_90d" and (row.baseline_90d_value or "").strip() not in (
            "",
            "NO_BASELINE",
        ):
            base = row.baseline_90d_value or "—"
            rng = _format_range_human(row.baseline_90d_range)
            verdict = _VERDICT_LABEL_ZH.get(row.verdict, row.verdict_note or "")
            unit = (row.baseline_90d_unit or "").strip()
            base_s = f"{base} {unit}".strip()
            lines.append(
                f"- **{label}**：本次截图 **{snap}**；近 90 天平均 **{base_s}**（区间 {rng}），{verdict}。"
            )
        else:
            lines.append(f"- **{label}**：本次截图 **{snap}**（仅来自本次截图）。")
    return lines


def build_compare_table_metric_focus_summary(
    table: CompareTableV1,
    metric_ids: Sequence[str],
    *,
    intro: str = "关于您关心的指标：",
) -> str:
    focus_ids = {m for m in metric_ids if m}
    rows = _format_metric_focus_rows(table, focus_ids)
    if not rows:
        return ""
    lines = [intro, ""] + rows
    if "sleep_time_asleep" in focus_ids:
        lines.append("")
        lines.append(
            "说明：睡眠总时长取自截图顶部 **TIME ASLEEP**，不是 Stages 里的 **Awake（清醒时长）**。"
        )
    if "workout_count_recent" in focus_ids:
        lines.append("")
        lines.append(
            "说明：近期锻炼次数取自 Workouts 页「过去 4 周锻炼天数」，不是日历上的日期数字。"
        )
    return "\n".join(lines).strip()


def infer_episodic_delta_focus_ids(
    user_message: str,
    prior_user_message: str = "",
) -> List[str]:
    """Reuse prior turn metric when user sends a bare delta prompt (e.g. 「和上周比呢」)."""
    msg = (user_message or "").strip()
    if not msg or not _EPISODIC_DELTA_RE.match(msg):
        return []
    prior = (prior_user_message or "").strip()
    if not prior:
        return []
    return infer_single_metric_focus_ids(prior)


def build_episodic_delta_focus_answer(
    table: CompareTableV1,
    user_message: str,
    *,
    prior_user_message: str = "",
) -> str:
    focus_ids = infer_episodic_delta_focus_ids(user_message, prior_user_message)
    if not focus_ids:
        return ""
    body = build_compare_table_metric_focus_summary(
        table,
        focus_ids,
        intro="关于您关心的指标（与近 90 天基线对比；系统无逐周切片）：",
    )
    return body


def build_exercise_suitability_followup_answer(
    table: CompareTableV1,
    user_message: str,
) -> str:
    """Screenshot-session exercise advice without re-pasting full CompareTable."""
    if not _EXERCISE_ADVICE_ONLY_RE.search((user_message or "").strip()):
        return ""
    if not any(r.snapshot_value for r in table.rows):
        return ""
    adv = _deterministic_exercise_advisory(table)
    msg = (user_message or "").strip()
    if re.search(r"跑步|跑多久", msg, re.I):
        adv = (
            f"{adv}\n"
            "- 若选择跑步：睡眠偏短时建议 **20–30 分钟** 轻松慢跑或快走，勿强行长距离。"
        )
    return adv


def build_health_summary_followup_answer(
    table: CompareTableV1,
    user_message: str,
) -> str:
    """Screenshot-session health overview without LLM re-dump."""
    if not _HEALTH_SUMMARY_RE.search((user_message or "").strip()):
        return ""
    if not any(r.snapshot_value for r in table.rows):
        return ""
    summary = compare_table_to_user_summary(table)
    return (
        "### 健康数据概览\n\n"
        f"{summary}\n\n"
        "以上为本次截图读数小结，非医疗诊断。"
    )


def _build_episodic_caution_brief(table: CompareTableV1) -> str:
    """Top caution bullets from CompareTable verdicts — no full-table preamble."""
    lines = ["关于您还需留意的事项：", ""]
    cautions: List[str] = []
    for row in table.rows:
        if not row.snapshot_value:
            continue
        if row.verdict not in ("above_mean", "below_mean"):
            continue
        label = _METRIC_LABEL_ZH.get(row.metric_id, row.metric_id)
        note = (row.verdict_note or "").strip() or _verdict_note(
            row.verdict,
            row_kind=row.row_kind,
            metric_id=row.metric_id,
        )
        cautions.append(f"- **{label}**：本次 **{row.snapshot_value}**；{note}")
        if len(cautions) >= 3:
            break
    if not cautions:
        cautions.append(
            "- 本次读数未见明显越界项；请结合身体感受决定是否调整运动强度。",
        )
    lines.extend(cautions)
    lines.append("")
    lines.append("以上为延伸参考，非医疗诊断。")
    return "\n".join(lines)


def build_weak_episodic_followup_answer(
    table: CompareTableV1,
    user_message: str,
) -> str:
    """
    Screenshot-session weak follow-up: close ack or advisory caution brief.

    Catalog-driven (weak_followup / advisory_followup) — no phrase routing in callers.
    """
    from pha.health_intent_catalog import (
        is_advisory_episodic_followup,
        is_weak_close_followup,
        is_weak_episodic_followup,
    )

    msg = (user_message or "").strip()
    if not msg or not any(r.snapshot_value for r in table.rows):
        return ""
    if is_weak_close_followup(msg):
        return (
            "不客气。请留意先前读数小结中的异常项；"
            "如有胸痛、持续不适或症状持续，请及时就医。"
        )
    if is_advisory_episodic_followup(msg) or (
        is_weak_episodic_followup(msg) and not is_weak_close_followup(msg)
    ):
        return _build_episodic_caution_brief(table)
    return ""


def user_message_needs_wearable_session_reuse(
    user_message: str,
    prior_user_message: str = "",
) -> bool:
    """Follow-up turns that should reload session screenshot parse (skip_llm path)."""
    from pha.intent_gates import (
        user_message_needs_attachment_recall,
        user_message_needs_wearable_query,
    )
    from pha.wearable_snapshot_v1 import user_requests_wearable_snapshot_remerge

    msg = (user_message or "").strip()
    if not msg:
        return False
    from pha.health_intent_catalog import is_weak_episodic_followup

    if is_weak_episodic_followup(msg):
        return True
    if user_message_needs_wearable_query(msg):
        return True
    if user_message_needs_attachment_recall(msg):
        return True
    if user_requests_wearable_snapshot_remerge(msg):
        return True
    if user_requests_snapshot_correction(msg):
        return True
    if infer_single_metric_focus_ids(msg):
        return True
    if infer_episodic_delta_focus_ids(msg, prior_user_message):
        return True
    if _EXERCISE_ADVICE_ONLY_RE.search(msg):
        return True
    if _HEALTH_SUMMARY_RE.search(msg):
        return True
    return False


def build_single_metric_focus_answer(
    table: CompareTableV1,
    user_message: str,
    *,
    prior_user_message: str = "",
) -> str:
    """Deterministic single-metric reply from CompareTable (screenshot session follow-up)."""
    delta = build_episodic_delta_focus_answer(
        table,
        user_message,
        prior_user_message=prior_user_message,
    )
    if delta:
        return delta
    focus_ids = infer_single_metric_focus_ids(user_message)
    if not focus_ids:
        return ""
    has_snap = any(
        r.metric_id in focus_ids and r.snapshot_value for r in table.rows
    )
    if not has_snap and set(focus_ids) <= _SLEEP_FOCUS_METRIC_IDS:
        return (
            "关于您关心的指标：\n\n"
            "- **深睡/REM**：本次截图未识别到可靠的睡眠分期数值（总睡眠时长已读取）。"
            "请查看 Health 睡眠「Stages」页核对。"
        )
    if not has_snap:
        return ""
    return build_compare_table_metric_focus_summary(table, focus_ids)


def build_catalog_followup_focus_answer(
    table: CompareTableV1,
    user_message: str,
) -> str:
    """Screenshot session: 「睡眠呢」→ CompareTable 主指标，而非数仓均值。"""
    from pha.intent_gates import infer_wearable_metrics

    cats = infer_wearable_metrics(user_message or "")
    if len(cats) != 1:
        return ""
    primary = _CATALOG_PRIMARY_METRIC.get(cats[0])
    if not primary:
        return ""
    has_snap = any(r.metric_id == primary and r.snapshot_value for r in table.rows)
    if not has_snap:
        return ""
    return build_compare_table_metric_focus_summary(table, [primary])


def _deterministic_exercise_advisory(table: CompareTableV1) -> str:
    """Brief exercise guidance from CompareTable verdicts (no LLM)."""
    sleep_row = next((r for r in table.rows if r.metric_id == "sleep_time_asleep"), None)
    hrv_row = next((r for r in table.rows if r.metric_id == "hrv_rmssd_ms"), None)
    lines = ["### 运动建议", ""]
    notes: List[str] = []
    if sleep_row and sleep_row.snapshot_value:
        notes.append(f"今日睡眠 {sleep_row.snapshot_value}")
    if hrv_row and hrv_row.snapshot_value:
        notes.append(f"HRV {hrv_row.snapshot_value}")
    if notes:
        lines.append(f"综合 {'、'.join(notes)} 与近 90 天对比：")
    lines.append(
        "- 明天可进行**低至中等强度**运动（散步、轻度阻力训练、椭圆机等）；"
        "若感疲劳或睡眠偏短，优先恢复性活动并避免高强度间歇。"
    )
    lines.append("- 以上为健康参考，非医疗诊断；如有胸痛、持续不适请就医。")
    return "\n".join(lines)


def build_compare_first_upload_answer(
    table: CompareTableV1,
    user_message: str,
) -> str:
    """
    First screenshot upload: CompareTable SSO before LLM (~180s → ~0s).

    Skips when user asks single-metric or correction-only turns.
    """
    if infer_single_metric_focus_ids(user_message) or user_requests_snapshot_correction(
        user_message,
    ):
        return ""
    if not any(r.snapshot_value for r in table.rows):
        return ""
    summary = compare_table_to_user_summary(table)
    if _EXERCISE_SUITABILITY_RE.search(user_message or ""):
        return f"{summary}\n\n{_deterministic_exercise_advisory(table)}"
    return summary


def compare_table_to_llm_markdown_focused(
    table: CompareTableV1,
    metric_ids: Sequence[str],
) -> str:
    """Tier0 compare block narrowed to requested metrics (reduces LLM re-dump)."""
    focus = {m for m in metric_ids if m}
    if not focus:
        return compare_table_to_llm_markdown(table)
    subset = CompareTableV1(
        schema_version=table.schema_version,
        reference_date=table.reference_date,
        window_90d=dict(table.window_90d or {}),
        rows=[r for r in table.rows if r.metric_id in focus],
    )
    if not subset.rows:
        return compare_table_to_llm_markdown(table)
    head = "【本次仅关注以下指标 · 勿列举其他截图 KPI】"
    return f"{head}\n\n{compare_table_to_llm_markdown(subset)}"


_CORRECTION_METRIC_HINTS: Dict[str, Tuple[str, ...]] = {
    "sleep_time_asleep": ("睡眠", "睡觉", "asleep"),
    "workout_count_recent": ("锻炼", "workout", "运动", "次数"),
    "sleep_deep": ("深睡",),
    "sleep_rem": ("REM", "快速眼动"),
}


def user_requests_snapshot_correction(user_message: str) -> bool:
    return bool(_CORRECTION_USER_RE.search(user_message or ""))


def _correction_metric_ids(user_message: str, table: CompareTableV1) -> List[str]:
    msg = user_message or ""
    ids: List[str] = []
    for metric_id, hints in _CORRECTION_METRIC_HINTS.items():
        if any(h.lower() in msg.lower() for h in hints):
            ids.append(metric_id)
    if ids:
        return ids
    if user_requests_snapshot_correction(msg):
        return [r.metric_id for r in table.rows if r.snapshot_value][:3]
    return []


def build_compare_table_correction_summary(
    table: CompareTableV1,
    user_message: str,
) -> str:
    """Focused re-statement for user correction turns (avoid full-table paste loop)."""
    focus_ids = _correction_metric_ids(user_message, table)
    if not focus_ids:
        return ""
    return build_compare_table_metric_focus_summary(
        table,
        focus_ids,
        intro="根据截图重新核对后的关键指标：",
    )


def compare_table_to_user_summary(table: CompareTableV1) -> str:
    """User-visible fallback summary (no Tier0 / metric_id jargon)."""
    lines = ["根据您上传的 Apple Watch 截图，与过去约 90 天记录对比：", ""]
    comparable = [r for r in table.rows if r.row_kind == "comparable_90d"]

    for row in comparable:
        label = _METRIC_LABEL_ZH.get(row.metric_id, row.metric_id)
        snap = _format_snapshot_display(row.metric_id, row.snapshot_value or "")
        base = row.baseline_90d_value or "—"
        rng = _format_range_human(row.baseline_90d_range)
        verdict = _VERDICT_LABEL_ZH.get(row.verdict, row.verdict_note or "")
        unit = row.baseline_90d_unit or ""
        base_s = f"{base} {unit}".strip()
        lines.append(
            f"- **{label}**：本次 **{snap}**；过去约 90 天平均 **{base_s}**（常见区间 {rng}），{verdict}。"
        )

    stage_snap_only = [
        r
        for r in table.rows
        if r.metric_id in ("sleep_deep", "sleep_rem")
        and r.row_kind == "snapshot_only"
        and r.snapshot_value
    ]
    if stage_snap_only:
        parts = []
        for row in stage_snap_only:
            label = _METRIC_LABEL_ZH.get(row.metric_id, row.metric_id)
            parts.append(f"{label} {_format_snapshot_display(row.metric_id, row.snapshot_value)}")
        lines.append("")
        lines.append(
            f"- **睡眠分期**：本次为 {'、'.join(parts)}。"
            "系统没有保存深睡/REM 的 90 天历史，**无法**与过去 90 天对比。"
        )

    workout_snap_only = [
        r
        for r in table.rows
        if r.metric_id in WORKOUT_METRICS and r.row_kind == "snapshot_only"
    ]
    if workout_snap_only:
        lines.append("")
        lines.append("- **锻炼**：")
        for row in workout_snap_only:
            label = _METRIC_LABEL_ZH.get(row.metric_id, row.metric_id)
            if row.snapshot_value:
                disp = _format_snapshot_display(row.metric_id, row.snapshot_value)
                lines.append(f"  - {label}：**{disp}**（仅来自本次截图）")
            elif row.verdict == "insufficient_data":
                lines.append(f"  - {label}：本次截图未识别到该数据")

    footer = _fallback_footer_for_table(table)
    if footer:
        lines.append("")
        lines.append(footer)
    return "\n".join(lines)


def _audit_verdict_contradictions(text: str, table: CompareTableV1) -> List[str]:
    violations: List[str] = []
    blob = text or ""
    for row in table.rows:
        if row.row_kind != "comparable_90d":
            continue
        if not _metric_discussed(blob, row.metric_id):
            continue
        idx = blob.lower().find(row.metric_id.lower())
        if idx < 0:
            for hint in _METRIC_MENTION_HINTS.get(row.metric_id, ()):
                idx = blob.lower().find(hint.lower())
                if idx >= 0:
                    break
        if idx < 0:
            continue
        window = blob[max(0, idx - 60) : idx + 100]
        if row.verdict == "within_range":
            if any(c in window for c in _ABOVE_CUES + _BELOW_CUES):
                violations.append(f"compare_verdict_contradiction:{row.metric_id}:within_vs_extreme")
        elif row.verdict == "above_mean" and any(c in window for c in _BELOW_CUES):
            violations.append(f"compare_verdict_contradiction:{row.metric_id}:above_vs_below")
        elif row.verdict == "below_mean" and any(c in window for c in _ABOVE_CUES):
            violations.append(f"compare_verdict_contradiction:{row.metric_id}:below_vs_above")
    return violations


def audit_wearable_compare_table(
    answer_text: str,
    table: CompareTableV1,
    *,
    user_message: str = "",
) -> Dict[str, Any]:
    """Always-on CompareTable audit (Wave 3d-γ-b). Returns passed + violations."""
    text = answer_text or ""
    violations: List[str] = []

    for phrase in _FORBIDDEN_PHRASES:
        if phrase in text:
            violations.append(f"compare_forbidden_90d_stage:phrase:{phrase}")

    violations.extend(_audit_fabricated_stage_90d(text, table))
    violations.extend(_audit_false_no_baseline_claim(text, table))
    violations.extend(_audit_summary_hijack(text, table))
    violations.extend(_audit_no_baseline_subjective(text, table))

    if table.rows:
        allowed = _authorized_tokens(table)
        for token in set(_DECIMAL_TOKEN_RE.findall(text)):
            if token in allowed or _decimal_near_allowed(token, allowed):
                continue
            violations.append(f"compare_table_numeric_drift:{token}")
        violations.extend(_audit_verdict_contradictions(text, table))
        violations.extend(_audit_missing_snapshot_citation(text, table))
        violations.extend(_audit_incomplete_coverage(text, table, user_message))
        auth_count = len(allowed)
    else:
        auth_count = 0

    unique = sorted(set(violations))
    return {
        "passed": len(unique) == 0,
        "violations": unique,
        "fallback_applied": False,
        "authorized_token_count": auth_count,
    }


def build_compare_table_fallback_answer(table: CompareTableV1) -> str:
    """Deterministic fallback — user-facing summary; Tier0 markdown stays in logs/telemetry."""
    return compare_table_to_user_summary(table)


def _sanitize_advisory_paragraph(paragraph: str, allowed: Set[str]) -> str:
    """Drop lines with hijack anchors or unauthorized compare numerics."""
    lines: List[str] = []
    for line in (paragraph or "").splitlines():
        if any(p in line for p in ("数仓摘要", "User Data Snapshot", "metric_id", "Tier0")):
            continue
        bad_num = False
        for token in _DECIMAL_TOKEN_RE.findall(line):
            if token not in allowed and not _decimal_near_allowed(token, allowed):
                bad_num = True
                break
        if bad_num and _COMPARE_INLINE_BULLET_RE.search(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def extract_llm_health_advisory(
    answer_text: str,
    table: CompareTableV1,
) -> str:
    """
    Preserve LLM fact-based health advice after Compare audit failure.

    Drops duplicate KPI bullets; keeps 建议 / 综上所述 / 睡眠解读 等段落。
    """
    blob = (answer_text or "").strip()
    if not blob:
        return ""
    allowed = _authorized_tokens(table)
    paras = [p.strip() for p in re.split(r"\n\s*\n", blob) if p.strip()]
    kept: List[str] = []
    advisory_mode = False
    for para in paras:
        if _ADVISORY_CUE_RE.search(para):
            advisory_mode = True
        if _COMPARE_NARRATIVE_BULLET_RE.search(para) and _COMPARE_INLINE_BULLET_RE.search(para):
            if not advisory_mode:
                continue
        if para.startswith("根据您上传") and "对比" in para and not advisory_mode:
            continue
        if not advisory_mode and not _ADVISORY_CUE_RE.search(para):
            continue
        clean = _sanitize_advisory_paragraph(para, allowed)
        if len(clean) < 24:
            continue
        kept.append(clean)
    return "\n\n".join(kept)


def build_compare_table_hybrid_answer(
    table: CompareTableV1,
    llm_text: str,
) -> str:
    """SSO compare block + retained LLM advisory (Wave 3d-γ-ux · hybrid fallback)."""
    summary = compare_table_to_user_summary(table)
    advisory = extract_llm_health_advisory(llm_text, table)
    if not advisory:
        return summary
    return f"{summary}\n\n{advisory}"


def apply_compare_table_fallback_if_needed(
    answer_text: str,
    table: CompareTableV1,
    *,
    user_message: str = "",
) -> Tuple[str, Dict[str, Any]]:
    audit = audit_wearable_compare_table(answer_text, table, user_message=user_message)
    if audit.get("passed"):
        return answer_text, audit
    audit["fallback_applied"] = True
    audit["tier0_markdown"] = table.to_markdown()
    if user_requests_snapshot_correction(user_message):
        correction = build_compare_table_correction_summary(table, user_message)
        if correction:
            audit["fallback_mode"] = "correction_focus"
            advisory = extract_llm_health_advisory(answer_text, table)
            audit["advisory_chars"] = len(advisory or "")
            if advisory:
                return f"{correction}\n\n{advisory}", audit
            return correction, audit
    focus_ids = infer_single_metric_focus_ids(user_message)
    if focus_ids:
        focus = build_compare_table_metric_focus_summary(table, focus_ids)
        if focus:
            audit["fallback_mode"] = "metric_focus"
            audit["advisory_chars"] = 0
            return focus, audit
    audit["fallback_mode"] = "hybrid"
    hybrid = build_compare_table_hybrid_answer(table, answer_text)
    audit["advisory_chars"] = max(0, len(hybrid) - len(compare_table_to_user_summary(table)))
    return hybrid, audit


def persist_compare_table_to_parsed(
    parsed_payload: Dict[str, Any],
    table: CompareTableV1,
) -> Dict[str, Any]:
    parsed_payload["wearable_compare_table_v1"] = table.to_parsed_dict()
    return parsed_payload


__all__ = [
    "CompareRowV1",
    "CompareTableV1",
    "apply_compare_table_fallback_if_needed",
    "audit_wearable_compare_table",
    "build_compare_table_fallback_answer",
    "build_compare_table_hybrid_answer",
    "extract_llm_health_advisory",
    "build_wearable_compare_table_tier0_block",
    "build_wearable_compare_table_v1",
    "compare_table_from_parsed",
    "compare_table_to_llm_markdown",
    "compare_table_to_markdown",
    "build_compare_table_correction_summary",
    "compare_table_to_user_summary",
    "compute_verdict",
    "parse_snapshot_numeric",
    "build_compare_table_metric_focus_summary",
    "build_episodic_delta_focus_answer",
    "build_exercise_suitability_followup_answer",
    "build_health_summary_followup_answer",
    "build_weak_episodic_followup_answer",
    "infer_episodic_delta_focus_ids",
    "user_message_needs_wearable_session_reuse",
    "build_compare_first_upload_answer",
    "build_single_metric_focus_answer",
    "compare_table_to_llm_markdown_focused",
    "infer_single_metric_focus_ids",
    "persist_compare_table_to_parsed",
    "user_requests_snapshot_correction",
    "user_requests_workout_compare",
]
