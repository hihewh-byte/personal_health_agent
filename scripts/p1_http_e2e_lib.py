"""P1 HTTP E2E helpers — shared turn snapshots for golden gate (orchestration only)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


def harness_profile_from_done(done: dict[str, Any]) -> str:
    harness = done.get("harness") or {}
    plan = harness.get("plan") or {}
    return str(plan.get("profile") or harness.get("profile") or "")


@dataclass
class HttpTurnSnapshot:
    scenario: str
    message: str
    session_id: str = ""
    harness_profile: str = ""
    answer: str = ""
    metrics: dict[str, str] = field(default_factory=dict)
    compare_rows: int = 0
    compare_audit: dict[str, Any] = field(default_factory=dict)
    status_msgs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_done(
        cls,
        *,
        scenario: str,
        message: str,
        done: dict[str, Any],
        status_msgs: list[str] | None = None,
    ) -> HttpTurnSnapshot:
        ingest = done.get("ingest_payload") or {}
        metrics_list = ingest.get("wearable_metrics") or ingest.get("metrics") or []
        ct = ingest.get("wearable_compare_table_v1") or {}
        return cls(
            scenario=scenario,
            message=message,
            session_id=str(done.get("session_id") or ""),
            harness_profile=harness_profile_from_done(done),
            answer=str((done.get("answer") or {}).get("answer_text") or ""),
            metrics={
                str(m.get("metric_id")): str(m.get("value"))
                for m in metrics_list
                if m.get("metric_id")
            },
            compare_rows=len(ct.get("rows") or []),
            compare_audit=dict(done.get("compare_table_audit") or {}),
            status_msgs=list(status_msgs or []),
        )


def preflight_http(base_url: str) -> tuple[bool, str]:
    import httpx

    try:
        r = httpx.get(f"{base_url}/health", timeout=15.0)
        r.raise_for_status()
        data = r.json()
        build = str(data.get("pha_build") or data.get("build") or "")
        if not build:
            return False, "health OK but pha_build empty"
        return True, build
    except Exception as exc:
        return False, f"health check failed: {exc}"


def assert_e1_turn(turn: HttpTurnSnapshot, e1: dict[str, Any]) -> list[str]:
    fails: list[str] = []
    want_profile = str(e1.get("profile_expected") or "")
    if turn.harness_profile != want_profile:
        fails.append(f"E1-profile: want {want_profile!r} got {turn.harness_profile!r}")

    for fp in e1.get("forbidden_profiles") or []:
        if fp and turn.harness_profile == fp:
            fails.append(f"E1-profile-forbidden: {fp!r}")

    min_m = int(e1.get("min_wearable_metrics") or 0)
    if len(turn.metrics) < min_m:
        fails.append(f"E1-metrics: count={len(turn.metrics)} < min={min_m}")

    for mid in e1.get("required_metric_ids") or []:
        if mid not in turn.metrics:
            fails.append(f"E1-metrics-missing: {mid!r}")

    min_rows = int(e1.get("compare_min_rows") or 0)
    if turn.compare_rows < min_rows:
        fails.append(f"G-Compare-1: rows={turn.compare_rows} < min={min_rows}")

    audit = turn.compare_audit
    audit_ok = bool(audit.get("passed")) or bool(audit.get("fallback_applied"))
    status_hit = any("CompareTable" in s for s in turn.status_msgs)
    answer_hit = any(
        k in turn.answer
        for k in ("Apple Watch", "睡眠", "截图", "Compare", "HRV", "workout", "锻炼")
    )
    metrics_ok = len(turn.metrics) >= int(e1.get("min_wearable_metrics") or 0)
    if not audit_ok and not status_hit and not (metrics_ok and answer_hit):
        fails.append(
            f"G-Compare-2: audit passed={audit.get('passed')} "
            f"fallback={audit.get('fallback_applied')} violations={audit.get('violations')}",
        )

    for sub in e1.get("forbidden_answer_substrings") or []:
        if sub and sub in turn.answer:
            fails.append(f"E1-jargon: forbidden substring {sub!r} in answer")

    return fails


def assert_e2_turn(
    e1: HttpTurnSnapshot,
    e2: HttpTurnSnapshot,
    e2_spec: dict[str, Any],
) -> list[str]:
    fails: list[str] = []
    want = str(e2_spec.get("profile_expected") or "wearable_screenshot_review")
    if e2.harness_profile != want:
        fails.append(f"E2-a: profile want {want!r} got {e2.harness_profile!r}")

    for fp in e2_spec.get("forbidden_profile_drift") or []:
        if e2.harness_profile == fp:
            fails.append(f"E2-a-forbidden: {fp!r}")

    if e2_spec.get("require_ingest_or_audit"):
        has_signal = bool(e2.metrics) or bool(e2.compare_audit) or bool(e2.answer.strip())
        if not has_signal:
            fails.append("E2-b: no ingest/audit signal on no-attachment follow-up")

    contra = e2_spec.get("contradiction_check") or {}
    for field_id in contra.get("fields") or []:
        v1 = e1.metrics.get(field_id)
        v2 = e2.metrics.get(field_id)
        if v1 and v2 and v1 != v2:
            fails.append(f"E2-c: {field_id} contradicted E1 {v1!r} vs E2 {v2!r}")

    audit = e2.compare_audit
    violations = audit.get("violations") or []
    if violations and not audit.get("fallback_applied"):
        fails.append(f"E2-d/G-Compare-2: violations={violations!r} without fallback")

    return fails


def assert_e3_turn(e3: HttpTurnSnapshot, e3_spec: dict[str, Any]) -> list[str]:
    fails: list[str] = []
    if e3_spec.get("forbid_specific_wearable_numerics"):
        for pat in e3_spec.get("forbidden_answer_patterns") or []:
            if re.search(str(pat), e3.answer, re.IGNORECASE):
                fails.append(f"E3-a: forbidden pattern {pat!r} in answer")

    if e3.harness_profile in ("lifestyle", "combined_review", "lab_cross_year"):
        if re.search(r"\d+\s*ms", e3.answer, re.IGNORECASE) or re.search(
            r"\d+\s*bpm",
            e3.answer,
            re.IGNORECASE,
        ):
            fails.append(f"E3-b: warehouse profile {e3.harness_profile!r} with wearable numerics")

    return fails


def snapshot_from_dict(doc: dict[str, Any]) -> HttpTurnSnapshot:
    return HttpTurnSnapshot(
        scenario=str(doc.get("scenario") or ""),
        message=str(doc.get("message") or ""),
        session_id=str(doc.get("session_id") or ""),
        harness_profile=str(doc.get("harness_profile") or ""),
        answer=str(doc.get("answer") or ""),
        metrics=dict(doc.get("metrics") or {}),
        compare_rows=int(doc.get("compare_rows") or 0),
        compare_audit=dict(doc.get("compare_audit") or {}),
        status_msgs=list(doc.get("status_msgs") or []),
        errors=list(doc.get("errors") or []),
    )


def synthetic_result_to_snapshot(result: dict[str, Any], *, message: str) -> HttpTurnSnapshot:
    ingest = result.get("ingest") or {}
    metrics_list = ingest.get("wearable_metrics") or ingest.get("metrics") or []
    return HttpTurnSnapshot(
        scenario="E1",
        message=message,
        session_id=str(result.get("session_id") or ""),
        harness_profile=str(result.get("harness_profile") or ""),
        answer=str(result.get("answer") or ""),
        metrics={
            str(m.get("metric_id")): str(m.get("value"))
            for m in metrics_list
            if m.get("metric_id")
        },
        compare_rows=int(result.get("compare_rows") or 0),
        compare_audit=dict(result.get("compare_audit") or {}),
        status_msgs=list(result.get("status_msgs") or []),
    )
