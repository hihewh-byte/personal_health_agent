#!/usr/bin/env python3
"""Wave 3c selfcheck: WearableSnapshotLedgerV1 + harness profile routing."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.attachment_asset_qa import maybe_deterministic_attachment_reply, resolve_attachment_qa_mode
from pha.harness_plan import build_turn_evidence_plan
from pha.intent_gates import user_message_needs_attachment_recall
from pha.perception_family import (
    attachment_parse_is_actionable,
    coerce_wearable_family,
    family_from_parsed,
    parts_should_finalize_as_wearable,
    should_skip_vlm_for_wearable,
)
from pha.perception_media import classify_document_family
from pha.perception_worker import finalize_attachment_parse
from pha.wearable_harness import (
    maybe_deterministic_wearable_reply,
    should_use_wearable_screenshot_review,
)
from pha.wearable_snapshot_v1 import (
    extract_metrics_from_ocr,
    finalize_wearable_attachment,
    infer_screen_type,
    merge_wearable_parts,
)


def test_classifier() -> bool:
    ocr = (
        "Heart Rate Variability AVERAGE 40 ms Blood Oxygen 93% "
        "Time Asleep 7 hr 1 min"
    )
    fam, _, _ = classify_document_family(ocr)
    if fam != "wearable":
        print("FAIL classifier", fam)
        return False
    return True


def test_finalize_multi() -> bool:
    parts = [
        {"ocr_text": "Heart Rate Variability AVERAGE 40 ms", "document_family": "wearable"},
        {"ocr_text": "Blood Oxygen 93%", "document_family": "wearable"},
        {"ocr_text": "Time Asleep 7 hr", "document_family": "wearable"},
    ]
    out = finalize_attachment_parse(
        parts[0],
        attachment_path_count=3,
        parts=parts,
        user_message="对比一下是不是都还好",
    )
    if out.get("document_family") != "wearable":
        print("FAIL family", out.get("document_family"))
        return False
    metrics = out.get("wearable_metrics") or []
    if len(metrics) < 2:
        print("FAIL metrics count", len(metrics))
        return False
    if "Supplement Facts" in (out.get("label_ledger") or ""):
        print("FAIL supplement text in ledger")
        return False
    det = maybe_deterministic_attachment_reply(out, qa_mode="initial")
    if det:
        print("FAIL supplement deterministic reply fired", det[:80])
        return False
    return True


def test_harness_profile() -> bool:
    if not should_use_wearable_screenshot_review(
        document_family="wearable",
        has_parsed_attachment=True,
        user_message="指标是否正常",
    ):
        print("FAIL should_use wearable")
        return False
    plan = build_turn_evidence_plan(
        "对比一下是不是都还好",
        wearable_screenshot_review=True,
    )
    if plan.profile != "wearable_screenshot_review":
        print("FAIL profile", plan.profile)
        return False
    if "WEARABLE_SNAPSHOT" not in plan.slots_tier0:
        print("FAIL slots", plan.slots_tier0)
        return False
    if "WEARABLE_COMPARE_TABLE" not in plan.slots_tier0:
        print("FAIL missing WEARABLE_COMPARE_TABLE", plan.slots_tier0)
        return False
    if "ATTACHMENT_LABEL" in plan.slots_tier0:
        print("FAIL ATTACHMENT_LABEL in tier0")
        return False
    return True


def test_coerce_wearable() -> bool:
    p = {
        "ocr_text": "Heart Rate Variability AVERAGE 40 ms Blood Oxygen 93% Time Asleep 7 hr",
        "document_type": "supplement_label",
        "layout_hints": ["supplement_label"],
    }
    out = coerce_wearable_family(p)
    if out.get("document_family") != "wearable":
        print("FAIL coerce family", out.get("document_family"))
        return False
    if "supplement_label" in (out.get("layout_hints") or []):
        print("FAIL coerce still has supplement_label hint")
        return False
    return True


def test_skip_supplement_merge() -> bool:
    parts = [
        {
            "ocr_text": "Heart Rate Variability AVERAGE 40 ms",
            "document_type": "supplement_label",
            "layout_hints": ["supplement_label"],
        },
        {
            "ocr_text": "Blood Oxygen 93% Time Asleep 7 hr",
            "document_type": "supplement_label",
            "layout_hints": ["supplement_label"],
        },
    ]
    coerced = [coerce_wearable_family(p) for p in parts]
    if not parts_should_finalize_as_wearable(coerced):
        print("FAIL should finalize as wearable batch")
        return False
    out = finalize_attachment_parse(
        {
            "ocr_text": "\n\n".join(p["ocr_text"] for p in coerced),
            "document_family": "wearable",
            "document_type": "apple_watch",
        },
        attachment_path_count=2,
        parts=coerced,
        user_message="对比一下是不是都还好",
    )
    if out.get("document_family") != "wearable":
        print("FAIL skip merge family", out.get("document_family"))
        return False
    if "Supplement Facts" in (out.get("label_ledger") or ""):
        print("FAIL supplement ledger leaked")
        return False
    mode = resolve_attachment_qa_mode(
        "对比一下是不是都还好",
        has_parsed_attachment=attachment_parse_is_actionable(out),
        session_focus_active=True,
        focus_tokens=["choline"],
        document_family="wearable",
    )
    if mode != "none":
        print("FAIL qa_mode should be none for wearable", mode)
        return False
    return True


def test_unknown_wearable_coerce() -> bool:
    """Regression: msg-298 class batch — unknown+wearable must not abort metrics."""
    parts = [
        {"ocr_text": "Heart Rate Variability AVERAGE 30 ms", "document_family": "wearable"},
        {"ocr_text": "Cardio Fitness VO2 max 54.6", "document_family": "unknown"},
        {"ocr_text": "TIME ASLEEP 8 hr 43 min Deep REM", "document_family": "unknown"},
    ]
    merged_ocr = "\n\n".join(p["ocr_text"] for p in parts)
    out = finalize_wearable_attachment(
        {
            "ocr_text": merged_ocr,
            "document_family": "wearable",
            "document_type": "apple_watch",
        },
        attachment_count=3,
        parts=parts,
        user_message="对比过去90天是否正常",
    )
    if out.get("document_family") != "wearable":
        print("FAIL coerce finalize family", out.get("document_family"))
        return False
    if out.get("reject_reasons") == ["merge_family_conflict"]:
        print("FAIL still hard conflict", out.get("reject_reasons"))
        return False
    metrics = out.get("wearable_metrics") or []
    if len(metrics) < 2:
        print("FAIL expected metrics after coerce", len(metrics))
        return False
    return True


def test_family_unknown_ocr() -> bool:
    p = {
        "document_family": "unknown",
        "ocr_text": "Heart Rate Variability 30 ms Blood Oxygen 93% Time Asleep 7 hr",
    }
    if family_from_parsed(p) != "wearable":
        print("FAIL family unknown+ocr", family_from_parsed(p))
        return False
    if not attachment_parse_is_actionable(p):
        print("FAIL actionable unknown+ocr")
        return False
    return True


def test_attachment_recall_intent() -> bool:
    if not user_message_needs_attachment_recall("我上传的图片的信息是什么？请分析"):
        print("FAIL attachment recall intent")
        return False
    if not should_use_wearable_screenshot_review(
        document_family="wearable",
        has_parsed_attachment=True,
        user_message="我上传的图片的信息是什么？请分析",
    ):
        print("FAIL screenshot review on recall")
        return False
    return True


def test_wearable_deterministic_no_metrics() -> bool:
    det = maybe_deterministic_wearable_reply(
        {
            "document_family": "unknown",
            "ocr_text": "Heart Rate Variability 30 ms",
            "parse_confidence": "low",
            "reject_reasons": ["merge_family_conflict"],
            "wearable_metrics": [],
        },
        raw_user_message="对比过去90天是否正常",
    )
    if not det or "不会" not in det:
        print("FAIL wearable deterministic", det[:80] if det else "")
        return False
    with_metrics = maybe_deterministic_wearable_reply(
        {
            "document_family": "wearable",
            "wearable_metrics": [{"metric_id": "hrv_rmssd_ms", "value": "30"}],
            "parse_confidence": "medium",
        },
        raw_user_message="对比是否正常",
    )
    if with_metrics:
        print("FAIL should not block when metrics present")
        return False
    return True


def test_kpi_extraction_hardening() -> bool:
    """Regression: msg-305/306 class OCR misreads (RHR/deep/REM/respiratory/workout)."""
    hr_ocr = (
        "Heart Rate May 30\nWalking Average 74 bpm\nResting 58 bpm\n"
        "Heart Rate Range 52-120 bpm"
    )
    hr_metrics = {m.metric_id: m.value for m in extract_metrics_from_ocr(hr_ocr)}
    if hr_metrics.get("resting_heart_rate_bpm") != "58":
        print("FAIL resting hr forward", hr_metrics.get("resting_heart_rate_bpm"))
        return False

    hr_inverted = (
        "Heart Rate\nRANGE\n51-84 bpm\n58 BPM\nResting Rate\nWalking Average\n74 BPM"
    )
    inv_metrics = {m.metric_id: m.value for m in extract_metrics_from_ocr(hr_inverted)}
    if inv_metrics.get("resting_heart_rate_bpm") != "58":
        print("FAIL resting hr inverted", inv_metrics.get("resting_heart_rate_bpm"))
        return False

    sleep_ocr = (
        "TIME ASLEEP 8 hr 43 min\n1 hr 9 min @ Deep\n2 hr 17 min @ REM\nAwake 45 min"
    )
    sleep_metrics = {m.metric_id: m.value for m in extract_metrics_from_ocr(sleep_ocr)}
    if sleep_metrics.get("sleep_deep") != "1hr9min":
        print("FAIL sleep_deep forward", sleep_metrics.get("sleep_deep"))
        return False
    if sleep_metrics.get("sleep_rem") != "2hr17min":
        print("FAIL sleep_rem forward", sleep_metrics.get("sleep_rem"))
        return False

    sleep_misread = (
        "Sleep\n6 hr 32 min TIME ASLEEP\n"
        "TIME IN BED 8 hr\n"
        "Awake 1 hr 55 min\n@ REM 1 hr 29 min"
    )
    sleep_device_ocr = (
        "Sleep\n6M\nTIME IN BED\nTIME ASLEEP\nShr\n6 nr 32 min\nJun 11, 2026\n"
        "@ Awake\n1 hr 55 min\n6h, 32 min"
    )
    device_metrics = {
        m.metric_id: m.value for m in extract_metrics_from_ocr(sleep_device_ocr)
    }
    if device_metrics.get("sleep_time_asleep") != "6hr32min":
        print("FAIL sleep device OCR", device_metrics.get("sleep_time_asleep"))
        return False
    hrv_device = "Heart Rate Variability\nAVERAGE\n34 ins\nToday"
    hrv_val = next(
        (m.value for m in extract_metrics_from_ocr(hrv_device) if m.metric_id == "hrv_rmssd_ms"),
        None,
    )
    if hrv_val != "34":
        print("FAIL hrv device OCR ins->ms", hrv_val)
        return False
    misread_metrics = {
        m.metric_id: m.value for m in extract_metrics_from_ocr(sleep_misread)
    }
    if misread_metrics.get("sleep_time_asleep") != "6hr32min":
        print("FAIL sleep_time_asleep misread awake", misread_metrics.get("sleep_time_asleep"))
        return False

    sleep_apple = (
        "@ Awake\n1hr 22 min\n@ REM\n2 hr 17 min\n@ Core\n4 hr 18 min\n@ Deep\n1hr 9 min"
    )
    apple_metrics = {m.metric_id: m.value for m in extract_metrics_from_ocr(sleep_apple)}
    if apple_metrics.get("sleep_deep") != "1hr9min":
        print("FAIL sleep_deep apple layout", apple_metrics.get("sleep_deep"))
        return False
    if apple_metrics.get("sleep_rem") != "2hr17min":
        print("FAIL sleep_rem apple layout", apple_metrics.get("sleep_rem"))
        return False

    resp_ocr = "Respiratory Rate 6M\n11.0-17.5 breaths/min average"
    resp_metrics = {m.metric_id: m.value for m in extract_metrics_from_ocr(resp_ocr)}
    if resp_metrics.get("respiratory_rate") != "11.0-17.5":
        print("FAIL respiratory", resp_metrics.get("respiratory_rate"))
        return False

    workout_ocr = "Workouts Highlights\n450 kcal\n32 min"
    wo_metrics = extract_metrics_from_ocr(workout_ocr)
    wo_ids = {m.metric_id for m in wo_metrics}
    if "workout_energy_kcal" not in wo_ids:
        print("FAIL workout kcal missing", wo_ids)
        return False

    sleep_only = "Heart Rate Variability 40 ms\nTime Asleep 7 hr"
    if any(m.metric_id.startswith("workout_") for m in extract_metrics_from_ocr(sleep_only)):
        print("FAIL workout metrics on non-workout screen")
        return False
    return True


def test_lane_o_skip_vlm() -> bool:
    ocr = "Heart Rate Variability AVERAGE 40 ms Blood Oxygen 93%"
    if not should_skip_vlm_for_wearable(
        doc_kind="other",
        document_family="unknown",
        ocr_text=ocr,
    ):
        print("FAIL lane-o should trigger on wearable OCR")
        return False
    cardio = (
        "Cardio Fitness\n54.6 VO2 max\nMay 29, 10-11AM\nShow All Cardio Fitness Levels"
    )
    if not should_skip_vlm_for_wearable(
        doc_kind="other",
        document_family="unknown",
        ocr_text=cardio,
    ):
        print("FAIL lane-o cardio fitness screen")
        return False
    if should_skip_vlm_for_wearable(
        doc_kind="other",
        document_family="unknown",
        ocr_text="random grocery receipt",
    ):
        print("FAIL lane-o should not trigger on unrelated OCR")
        return False
    return True


def test_workout_extraction() -> bool:
    wo = (
        "Workouts\nHighlights\n@ Heart Rate: Workout\n"
        "Your heart rate range during your recent run was 76-147 beats per minute.\n"
        "8 Workouts\nIn the last 4 weeks"
    )
    metrics = {m.metric_id: m.value for m in extract_metrics_from_ocr(wo)}
    if metrics.get("workout_heart_rate_range_bpm") != "76-147":
        print("FAIL workout hr range", metrics)
        return False
    if metrics.get("workout_count_recent") != "8":
        print("FAIL workout count", metrics)
        return False
    wo_days = (
        "Workouts\nDuring your last workout, your heart rate was 68-116 beats per minute.\n"
        "You worked out on 20 days in the last 4 weeks."
    )
    days_metrics = {m.metric_id: m.value for m in extract_metrics_from_ocr(wo_days)}
    if days_metrics.get("workout_count_recent") != "20":
        print("FAIL workout 4w days", days_metrics)
        return False
    if days_metrics.get("workout_heart_rate_range_bpm") != "68-116":
        print("FAIL workout last workout hr", days_metrics)
        return False
    if infer_screen_type(wo) != "workout":
        print("FAIL workout screen type", infer_screen_type(wo))
        return False
    return True


def test_ledger_sub_value_dedupe() -> bool:
    from pha.wearable_snapshot_v1 import WearableMetricV1, _metric_display_suffix

    m = WearableMetricV1(metric_id="sleep_time_asleep", value="8hr43min", sub_value="43min", unit="hr")
    if _metric_display_suffix(m):
        print("FAIL sub_value dedupe", _metric_display_suffix(m))
        return False
    return True


def test_gw2_low() -> bool:
    ledger = merge_wearable_parts([{"ocr_text": "unrelated text only"}])
    out = finalize_wearable_attachment(
        {"ocr_text": "unrelated"},
        attachment_count=1,
        user_message="对比一下是否正常",
    )
    if out.get("parse_confidence") != "low":
        print("FAIL gw2 expected low", out.get("parse_confidence"))
        return False
    return True


def main() -> int:
    ok = all(
        [
            test_classifier(),
            test_coerce_wearable(),
            test_skip_supplement_merge(),
            test_unknown_wearable_coerce(),
            test_family_unknown_ocr(),
            test_attachment_recall_intent(),
            test_wearable_deterministic_no_metrics(),
            test_kpi_extraction_hardening(),
            test_workout_extraction(),
            test_ledger_sub_value_dedupe(),
            test_lane_o_skip_vlm(),
            test_finalize_multi(),
            test_harness_profile(),
            test_gw2_low(),
        ],
    )
    print("pha_stage3c_wearable_selfcheck:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
