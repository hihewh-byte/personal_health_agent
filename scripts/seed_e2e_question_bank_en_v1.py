#!/usr/bin/env python3
"""Generator for rules/e2e_question_bank_en_v1.json — 50 English sets × ≥8 turns."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "rules" / "e2e_question_bank_en_v1.json"

W = 0.7


def pool(colloquial: list[str], formal: list[str]) -> dict:
    return {"colloquial_weight": W, "colloquial": colloquial, "formal": formal}


POOLS = {
    "upload_exercise": pool(
        [
            "Attached are today's Apple Watch metrics; morning workout was resistance training — can I train tomorrow, and what type?",
            "Uploading my wearable screenshots — did strength work this morning; should I rest or train tomorrow?",
            "Here are today's body metrics; AM resistance workout done — good to exercise tomorrow? Any type tips?",
            "Apple Watch panels attached; morning was strength — advise tomorrow's training suitability and type.",
        ],
        [
            "Attached are today's wearable body metrics. Note: this morning's workout was resistance training. Please assess whether tomorrow is suitable for exercise and, if so, recommend exercise types.",
            "I uploaded today's Apple Watch screenshots. After morning resistance training, please evaluate tomorrow's exercise suitability and suggest types.",
        ],
    ),
    "upload_lab_image": pool(
        [
            "Attached is a lab/report image from my PHA library — please parse lipids and key values.",
            "Here's a medical report screenshot I previously saved — extract cholesterol and LDL if present.",
        ],
        [
            "Please analyze the attached lab/report image and extract lipid panel values when available.",
            "Attached medical report image — parse key lipid metrics and cite any dates found.",
        ],
    ),
    "lipid": pool(
        ["How are my lipids?", "Check my cholesterol", "Is LDL high?", "Lipid panel looking ok?"],
        ["Please analyze my lipid markers.", "How is my LDL cholesterol?", "Summarize my lipid panel."],
    ),
    "hrv": pool(
        ["How's HRV?", "Check RMSSD", "HRV looking decent?", "Heart rate variability?"],
        ["Please analyze HRV.", "Is my HRV within a normal range?", "Report heart rate variability."],
    ),
    "sleep_duration": pool(
        ["How long did I sleep?", "Sleep duration?", "Hours asleep last night?", "Total sleep time?"],
        ["Please report sleep duration.", "What was total time asleep?"],
    ),
    "sleep_verify": pool(
        ["Sleep numbers look wrong — re-check them.", "Re-verify today's sleep from the screenshots.", "Sleep ledger seems off, please re-parse."],
        [
            "Please verify today's sleep data; if wrong, re-analyze the screenshots.",
            "Re-check the sleep values from the uploaded panels.",
        ],
    ),
    "deep_sleep": pool(
        ["Deep sleep how long?", "Deep sleep enough?", "Deep sleep time?"],
        ["What was deep sleep duration?", "Please report deep sleep time."],
    ),
    "workout_origin": pool(
        ["Where does the workout count of 8 come from?", "How is workout count calculated?", "Workout count source?"],
        ["Where does the recent workout count come from?", "Please explain the workout count data source."],
    ),
    "workout_recent": pool(
        ["How many workout days in the last 4 weeks?", "Training days last month?", "Recent workout frequency?"],
        ["How many days did I exercise in the last 4 weeks?", "Report recent workout day count."],
    ),
    "steps": pool(
        ["Steps?", "How many steps?", "Step count today?", "Walking volume?"],
        ["Recent step count?", "Please report steps.", "What is average daily steps?"],
    ),
    "steps_warehouse": pool(
        ["Recent steps from the warehouse?", "How's my step trend?", "Daily step average?"],
        ["Query recent 90-day steps.", "Report mean daily steps from warehouse."],
    ),
    "thanks": pool(["Thanks", "Thanks a lot", "Appreciate it", "Cool, thanks"], ["Thank you.", "Thanks for the analysis."]),
    "advisory": pool(
        ["Anything else I should watch?", "Other cautions?", "Any more tips?"],
        ["What else should I pay attention to?", "Please list additional advisories."],
    ),
    "ok_close": pool(["OK", "Got it", "Understood", "Noted"], ["OK.", "Understood.", "Noted."]),
    "hrv_normal": pool(
        ["Is HRV normal?", "HRV in range?", "RMSSD ok?"],
        ["Is HRV within a normal range?", "Please assess whether HRV is normal."],
    ),
    "delta_week": pool(
        ["Vs last week?", "Compared to last week?", "Week-over-week change?"],
        ["How does this compare to last week?", "Please compare with the prior week."],
    ),
    "exercise_tomorrow": pool(
        ["OK to train tomorrow?", "Tomorrow workout ok?", "Can I exercise tomorrow?"],
        ["Is tomorrow suitable for exercise?", "Please assess tomorrow's exercise suitability."],
    ),
    "exercise_day_after": pool(
        ["What about the day after?", "Day after tomorrow?", "And the next day?"],
        ["Is the day after tomorrow suitable for exercise?", "Assess exercise suitability for the following day."],
    ),
    "low_intensity": pool(
        ["Low-intensity cardio ok?", "Easy aerobic recommended?", "Easy jog fine?"],
        ["Is low-intensity aerobic exercise appropriate?", "Recommend low-intensity cardio?"],
    ),
    "running": pool(
        ["Can I run tomorrow?", "OK to run?", "Running ok?"],
        ["Is running appropriate tomorrow?", "Please assess running suitability."],
    ),
    "running_duration": pool(
        ["How long should I run?", "Run duration tip?", "Minutes of running?"],
        ["What running duration do you recommend?", "Suggested run length?"],
    ),
    "year_2023": pool(["2023", "Look at 2023", "Year 2023"], ["Please use 2023 data.", "Focus on 2023."]),
    "year_2025": pool(["2025", "Look at 2025", "Year 2025"], ["Please use 2025 data.", "Focus on 2025."]),
    "lipid_year": pool(["Which year?", "What year?", "Pick a year"], ["Which year should we use?", "Please specify the year."]),
    "remerge_sleep": pool(
        ["Do I need to re-upload sleep screenshots to re-parse?", "Can you re-parse sleep without re-upload?"],
        ["Can you re-parse the sleep screenshot data? Do I need to upload again?"],
    ),
    "remerge_workout": pool(
        ["Re-analyze workout from screenshots.", "Re-check workout panels."],
        ["Please re-analyze workout data from the uploaded screenshots."],
    ),
    "respiratory": pool(
        ["Respiratory rate?", "Breathing rate ok?", "Resp rate?"],
        ["How is respiratory rate?", "Please report respiratory rate."],
    ),
    "respiratory_normal": pool(
        ["Is respiratory rate normal?", "Breathing rate in range?"],
        ["Is respiratory rate within normal range?", "Assess respiratory rate normality."],
    ),
    "resting_hr": pool(
        ["Resting HR?", "Resting heart rate?", "RHR value?"],
        ["What is resting heart rate?", "Please report resting heart rate."],
    ),
    "hr_range": pool(
        ["Workout HR range?", "Heart rate range?", "HR zone during workout?"],
        ["Please report workout heart rate range.", "What was the exercise HR range?"],
    ),
    "spo2": pool(
        ["SpO2?", "Blood oxygen?", "Oxygen saturation?"],
        ["How is SpO2 / blood oxygen?", "Please report oxygen saturation."],
    ),
    "hr_generic": pool(
        ["How's heart rate?", "HR looking ok?", "Heart rate status?"],
        ["Please analyze heart rate metrics.", "How is my heart rate overall?"],
    ),
    "warehouse_hrv": pool(
        ["How has my recent HRV been?", "Warehouse HRV trend?", "Recent HRV from stored data?"],
        ["Please query recent HRV from the warehouse.", "Report recent 90-day HRV mean if available."],
    ),
    "warehouse_sleep": pool(
        ["Sleep from warehouse?", "Recent sleep quality?", "Sleep averages?"],
        ["Please report warehouse sleep averages.", "Summarize recent sleep from stored data."],
    ),
    "warehouse_steps": pool(
        ["Steps from warehouse?", "Walking enough lately?", "Step averages?"],
        ["Please report warehouse step averages.", "Summarize recent steps from stored data."],
    ),
    "warehouse_lipid": pool(
        ["Lipids from warehouse?", "Stored cholesterol records?", "Historical lipids?"],
        ["Please query stored lipid records.", "Summarize lipid history from the warehouse."],
    ),
    "combine_hrv": pool(
        ["Combine screenshot + warehouse for HRV.", "Overall HRV using both sources?"],
        ["Please combine screenshot and warehouse evidence for HRV.", "Synthesize HRV across uploaded and stored data."],
    ),
    "summary": pool(
        ["Summarize my health data.", "Give me a health overview.", "Overall status?"],
        ["Please summarize my health data.", "Provide a structured health overview."],
    ),
    "summary_follow": pool(
        ["Any outliers?", "Which metrics need attention?", "Red flags?"],
        ["Which metrics are abnormal or need attention?", "List priority concerns."],
    ),
    "rapid_hrv": pool(["HRV", "hrv", "HRV please"], ["HRV", "Please report HRV."]),
    "rapid_sleep": pool(["Sleep", "sleep"], ["Sleep", "Please report sleep."]),
    "rapid_steps": pool(["Steps", "steps"], ["Steps", "Please report steps."]),
    "rapid_workout": pool(["Workout", "Exercise"], ["Workout", "Please report workouts."]),
    "rapid_lipid": pool(["Lipids", "Cholesterol"], ["Lipids", "Please report lipids."]),
    "rapid_spo2": pool(["SpO2", "spo2"], ["SpO2", "Please report SpO2."]),
    "rapid_resp": pool(["Resp rate", "Breathing"], ["Respiratory rate", "Please report respiratory rate."]),
    "rapid_resting": pool(["RHR", "Resting HR"], ["Resting heart rate", "Please report resting HR."]),
    "lipid_trend": pool(
        ["Trend over years?", "Big change vs prior years?", "Lipid trajectory?"],
        ["How do lipids trend across years?", "Please analyze multi-year lipid trend."],
    ),
    "lipid_ldl": pool(["LDL?", "Bad cholesterol?", "LDL specifically?"], ["How is LDL?", "Please report LDL."]),
    "more_tips": pool(["Anything more?", "More advice?", "Keep going."], ["Any additional recommendations?", "Please add more tips."]),
    "got_it": pool(["Yep", "Makes sense", "Clear"], ["Understood.", "I understand."]),
    "supplement": pool(
        ["Any supplement notes from my PHA data?", "Supplements I should consider given lipids/HRV?"],
        ["Please review supplement-related facts if present in my warehouse.", "Any evidence-based supplement cautions from my records?"],
    ),
    "body_age": pool(
        ["Any body age / recovery age signal?", "Biological age vibes from wearables?"],
        ["If available, comment on body-age or recovery-age related signals.", "Summarize recovery-age related wearable signals."],
    ),
    "disclaimer": pool(
        ["This is not medical advice, right?", "Keep it educational please."],
        ["Please keep the reply educational and non-diagnostic.", "Confirm this is not a medical diagnosis."],
    ),
    "english_only": pool(
        ["Please reply in English only.", "English answers only from here."],
        ["Respond in English for all subsequent turns.", "Use English exclusively."],
    ),
    "wearable_import": pool(
        ["I already imported wearable data before — use warehouse.", "Rely on previously ingested wearable samples."],
        ["Please use previously ingested wearable data in the warehouse.", "Query historical wearable samples already stored in PHA."],
    ),
    "pdf_lab": pool(
        ["If I previously uploaded a lab PDF, use those lipids.", "Pull lipid values from prior PDF/report ingest if available."],
        [
            "Please use previously ingested lab PDF / report lipid values when available.",
            "Query prior PDF/report ingest for lipid panel values.",
        ],
    ),
}


def turn(slot: str, attach: bool = False) -> dict:
    return {"slot": slot, "attach": attach}


def chk(check_id: str, **kwargs) -> dict:
    row = {"id": check_id}
    row.update(kwargs)
    return row


def base_upload(legacy: str, lane: str, mid_slots: list[str], checks: list[dict] | None = None) -> dict:
    turns = [turn("upload_exercise", True)] + [turn(s) for s in mid_slots]
    while len(turns) < 8:
        turns.append(turn("ok_close" if len(turns) % 2 else "thanks"))
    return {
        "set_id": "",  # filled later
        "legacy_name": legacy,
        "lane": lane,
        "turns": turns[:10],
        "checks": checks
        or [
            chk("jun11_metrics"),
            chk("english_reply"),
            chk("no_empty"),
            chk("no_repeat"),
        ],
    }


SETS_SPEC: list[dict] = [
    # --- QS01–QS20: English mirrors of Chinese bank lanes ---
    base_upload(
        "upload_holistic_chain",
        "upload_holistic_chain",
        ["lipid", "hrv", "sleep_verify", "workout_origin", "steps", "thanks", "advisory"],
        [chk("jun11_metrics"), chk("english_reply"), chk("no_empty"), chk("correction_sleep"), chk("no_repeat")],
    ),
    base_upload(
        "upload_exercise_chain",
        "upload_exercise_chain",
        ["exercise_tomorrow", "exercise_day_after", "low_intensity", "running", "running_duration", "thanks", "ok_close"],
    ),
    base_upload(
        "upload_lipid_clarify",
        "upload_lipid_clarify",
        ["lipid", "lipid_year", "year_2023", "year_2025", "lipid_trend", "thanks", "ok_close"],
    ),
    base_upload(
        "upload_hrv_delta",
        "upload_hrv_delta",
        ["hrv", "hrv_normal", "delta_week", "sleep_duration", "steps", "spo2", "ok_close"],
    ),
    base_upload(
        "upload_sleep_correct",
        "upload_sleep_correct",
        ["sleep_duration", "sleep_verify", "deep_sleep", "hrv", "steps", "thanks", "ok_close"],
        [chk("jun11_metrics"), chk("english_reply"), chk("no_empty"), chk("correction_sleep")],
    ),
    base_upload(
        "upload_workout_probe",
        "upload_workout_probe",
        ["workout_origin", "workout_recent", "hr_range", "steps", "thanks", "advisory", "ok_close"],
    ),
    {
        "legacy_name": "warehouse_hrv",
        "lane": "warehouse_hrv",
        "turns": [
            turn("warehouse_hrv"),
            turn("warehouse_sleep"),
            turn("warehouse_steps"),
            turn("resting_hr"),
            turn("spo2"),
            turn("respiratory"),
            turn("hrv_normal"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty"), chk("warehouse_hrv")],
    },
    {
        "legacy_name": "warehouse_steps",
        "lane": "warehouse_steps",
        "turns": [
            turn("steps_warehouse"),
            turn("steps"),
            turn("delta_week"),
            turn("lipid_trend"),
            turn("more_tips"),
            turn("thanks"),
            turn("advisory"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty")],
    },
    base_upload(
        "upload_respiratory",
        "upload_respiratory",
        ["respiratory", "respiratory_normal", "spo2", "hrv", "sleep_duration", "thanks", "advisory"],
    ),
    base_upload(
        "upload_resting_hr",
        "upload_resting_hr",
        ["resting_hr", "hr_range", "hr_generic", "sleep_duration", "steps", "thanks", "ok_close"],
    ),
    base_upload(
        "upload_spo2_chain",
        "upload_spo2_chain",
        ["spo2", "respiratory_normal", "sleep_duration", "hrv", "exercise_tomorrow", "thanks", "ok_close"],
    ),
    base_upload(
        "upload_remerge",
        "upload_remerge",
        ["remerge_sleep", "remerge_workout", "sleep_duration", "workout_origin", "thanks", "advisory", "ok_close"],
        [chk("jun11_metrics"), chk("english_reply"), chk("no_empty"), chk("correction_sleep")],
    ),
    base_upload(
        "upload_casual_weak",
        "upload_casual_weak",
        ["thanks", "ok_close", "got_it", "more_tips", "advisory", "disclaimer", "english_only"],
        [chk("jun11_metrics"), chk("english_reply"), chk("no_empty"), chk("weak_followup_skip")],
    ),
    base_upload(
        "upload_long_10",
        "upload_long",
        [
            "hrv",
            "sleep_duration",
            "steps",
            "lipid",
            "spo2",
            "resting_hr",
            "exercise_tomorrow",
            "summary",
            "ok_close",
        ],
    ),
    {
        "legacy_name": "warehouse_lipid",
        "lane": "warehouse_lipid",
        "turns": [
            turn("warehouse_lipid"),
            turn("lipid_ldl"),
            turn("lipid_trend"),
            turn("year_2023"),
            turn("year_2025"),
            turn("lipid_year"),
            turn("thanks"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty")],
    },
    {
        "legacy_name": "warehouse_then_upload",
        "lane": "warehouse_then_upload",
        "turns": [
            turn("steps_warehouse"),
            turn("upload_exercise", True),
            turn("combine_hrv"),
            turn("sleep_duration"),
            turn("exercise_tomorrow"),
            turn("lipid"),
            turn("thanks"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("english_reply"), chk("no_empty")],
    },
    base_upload(
        "upload_hr_generic",
        "upload_hr_generic",
        ["hr_generic", "resting_hr", "hr_range", "sleep_duration", "thanks", "advisory", "ok_close"],
    ),
    base_upload(
        "upload_running",
        "upload_running",
        ["running", "running_duration", "hr_generic", "sleep_duration", "thanks", "more_tips", "ok_close"],
    ),
    base_upload(
        "upload_summary",
        "upload_summary",
        ["summary", "summary_follow", "exercise_tomorrow", "lipid", "hrv", "thanks", "ok_close"],
    ),
    base_upload(
        "upload_rapid_10",
        "upload_rapid",
        [
            "rapid_hrv",
            "rapid_sleep",
            "rapid_steps",
            "rapid_workout",
            "rapid_lipid",
            "rapid_spo2",
            "rapid_resp",
            "rapid_resting",
            "ok_close",
        ],
        [chk("jun11_metrics"), chk("english_reply"), chk("no_empty"), chk("no_repeat")],
    ),
    # --- QS21–QS50: expanded English stress coverage ---
    {
        "legacy_name": "warehouse_then_upload_fixed",
        "lane": "warehouse_then_upload",
        "turns": [
            turn("steps_warehouse"),
            turn("upload_exercise", True),
            turn("combine_hrv"),
            turn("sleep_duration"),
            turn("lipid"),
            turn("exercise_tomorrow"),
            turn("thanks"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("english_reply"), chk("no_empty")],
    },
    {
        "legacy_name": "warehouse_tour_8",
        "lane": "warehouse_tour",
        "turns": [
            turn("wearable_import"),
            turn("warehouse_hrv"),
            turn("warehouse_sleep"),
            turn("warehouse_steps"),
            turn("warehouse_lipid"),
            turn("summary"),
            turn("summary_follow"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty")],
    },
    {
        "legacy_name": "pdf_lab_warehouse",
        "lane": "pdf_lab_warehouse",
        "turns": [
            turn("pdf_lab"),
            turn("warehouse_lipid"),
            turn("lipid_ldl"),
            turn("lipid_trend"),
            turn("year_2023"),
            turn("supplement"),
            turn("disclaimer"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty")],
    },
    {
        "legacy_name": "lab_image_chain",
        "lane": "lab_image_chain",
        "turns": [
            turn("upload_lab_image", True),  # runner maps lab attach separately
            turn("lipid"),
            turn("lipid_ldl"),
            turn("lipid_trend"),
            turn("year_2025"),
            turn("summary_follow"),
            turn("disclaimer"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty"), chk("lab_attach")],
    },
    base_upload(
        "upload_spo2_deep",
        "upload_spo2_deep",
        ["spo2", "respiratory", "sleep_duration", "deep_sleep", "hrv", "thanks", "ok_close"],
    ),
    base_upload(
        "upload_delta_focus",
        "upload_delta_focus",
        ["hrv", "delta_week", "steps", "delta_week", "sleep_duration", "thanks", "ok_close"],
    ),
    {
        "legacy_name": "warehouse_lipid_deep",
        "lane": "warehouse_lipid_deep",
        "turns": [
            turn("warehouse_lipid"),
            turn("lipid"),
            turn("lipid_ldl"),
            turn("lipid_year"),
            turn("year_2023"),
            turn("lipid_trend"),
            turn("supplement"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty")],
    },
    {
        "legacy_name": "warehouse_sleep_deep",
        "lane": "warehouse_sleep_deep",
        "turns": [
            turn("warehouse_sleep"),
            turn("sleep_duration"),
            turn("deep_sleep"),
            turn("delta_week"),
            turn("hrv"),
            turn("exercise_tomorrow"),
            turn("thanks"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty")],
    },
    base_upload(
        "upload_body_age",
        "upload_body_age",
        ["body_age", "summary", "hrv", "sleep_duration", "exercise_tomorrow", "disclaimer", "ok_close"],
    ),
    base_upload(
        "upload_supplement_bridge",
        "upload_supplement_bridge",
        ["lipid", "supplement", "hrv", "disclaimer", "advisory", "thanks", "ok_close"],
    ),
    {
        "legacy_name": "rapid_warehouse_9",
        "lane": "rapid_warehouse",
        "turns": [
            turn("english_only"),
            turn("rapid_hrv"),
            turn("rapid_sleep"),
            turn("rapid_steps"),
            turn("rapid_lipid"),
            turn("rapid_spo2"),
            turn("rapid_resting"),
            turn("summary"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty")],
    },
    base_upload(
        "upload_clarify_years",
        "upload_clarify_years",
        ["lipid", "lipid_year", "year_2023", "lipid_ldl", "year_2025", "lipid_trend", "ok_close"],
    ),
    base_upload(
        "upload_reparse_loop",
        "upload_reparse_loop",
        ["sleep_verify", "remerge_sleep", "deep_sleep", "remerge_workout", "workout_origin", "thanks", "ok_close"],
        [chk("jun11_metrics"), chk("english_reply"), chk("no_empty"), chk("correction_sleep")],
    ),
    {
        "legacy_name": "combined_review_en",
        "lane": "combined_review",
        "turns": [
            turn("upload_exercise", True),
            turn("summary"),
            turn("combine_hrv"),
            turn("warehouse_lipid"),
            turn("summary_follow"),
            turn("exercise_tomorrow"),
            turn("disclaimer"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("english_reply"), chk("no_empty")],
    },
    {
        "legacy_name": "warehouse_only_long",
        "lane": "warehouse_only_long",
        "turns": [
            turn("wearable_import"),
            turn("warehouse_hrv"),
            turn("hrv_normal"),
            turn("delta_week"),
            turn("warehouse_sleep"),
            turn("warehouse_steps"),
            turn("warehouse_lipid"),
            turn("summary"),
            turn("advisory"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty")],
    },
    base_upload(
        "upload_hr_spo2_combo",
        "upload_hr_spo2_combo",
        ["hr_generic", "resting_hr", "spo2", "respiratory", "sleep_duration", "thanks", "ok_close"],
    ),
    base_upload(
        "upload_exercise_caution",
        "upload_exercise_caution",
        ["exercise_tomorrow", "low_intensity", "running", "running_duration", "advisory", "disclaimer", "ok_close"],
    ),
    {
        "legacy_name": "prior_sample_replay",
        "lane": "prior_sample_replay",
        "turns": [
            turn("wearable_import"),
            turn("pdf_lab"),
            turn("warehouse_lipid"),
            turn("warehouse_hrv"),
            turn("summary"),
            turn("summary_follow"),
            turn("disclaimer"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty")],
    },
    base_upload(
        "upload_metric_tour",
        "upload_metric_tour",
        ["hrv", "sleep_duration", "steps", "spo2", "resting_hr", "lipid", "ok_close"],
    ),
    {
        "legacy_name": "english_locale_lock",
        "lane": "english_locale_lock",
        "turns": [
            turn("english_only"),
            turn("warehouse_hrv"),
            turn("lipid"),
            turn("sleep_duration"),
            turn("steps"),
            turn("summary"),
            turn("advisory"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty")],
    },
    base_upload(
        "upload_weak_then_metric",
        "upload_weak_then_metric",
        ["thanks", "got_it", "hrv", "sleep_duration", "steps", "advisory", "ok_close"],
        [chk("jun11_metrics"), chk("english_reply"), chk("no_empty"), chk("weak_followup_skip")],
    ),
    {
        "legacy_name": "lab_then_wearable",
        "lane": "lab_then_wearable",
        "turns": [
            turn("upload_lab_image", True),
            turn("lipid"),
            turn("upload_exercise", True),
            turn("combine_hrv"),
            turn("summary"),
            turn("exercise_tomorrow"),
            turn("disclaimer"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty"), chk("lab_attach")],
    },
    {
        "legacy_name": "warehouse_compare_weeks",
        "lane": "warehouse_compare_weeks",
        "turns": [
            turn("warehouse_hrv"),
            turn("delta_week"),
            turn("warehouse_steps"),
            turn("delta_week"),
            turn("warehouse_sleep"),
            turn("delta_week"),
            turn("summary_follow"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty")],
    },
    base_upload(
        "upload_spo2_sleep",
        "upload_spo2_sleep",
        ["spo2", "sleep_duration", "deep_sleep", "sleep_verify", "hrv", "thanks", "ok_close"],
        [chk("jun11_metrics"), chk("english_reply"), chk("no_empty"), chk("correction_sleep")],
    ),
    {
        "legacy_name": "formal_heavy_warehouse",
        "lane": "formal_heavy_warehouse",
        "turns": [
            turn("warehouse_lipid"),
            turn("lipid_trend"),
            turn("lipid_ldl"),
            turn("supplement"),
            turn("body_age"),
            turn("disclaimer"),
            turn("advisory"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty")],
    },
    base_upload(
        "upload_closing_polite",
        "upload_closing_polite",
        ["summary", "summary_follow", "advisory", "more_tips", "thanks", "got_it", "ok_close"],
    ),
    {
        "legacy_name": "warehouse_spo2_resp",
        "lane": "warehouse_spo2_resp",
        "turns": [
            turn("spo2"),
            turn("respiratory"),
            turn("respiratory_normal"),
            turn("resting_hr"),
            turn("hr_generic"),
            turn("sleep_duration"),
            turn("advisory"),
            turn("ok_close"),
        ],
        "checks": [chk("english_reply"), chk("no_empty")],
    },
    {
        "legacy_name": "upload_then_pdf_bridge",
        "lane": "upload_then_pdf_bridge",
        "turns": [
            turn("upload_exercise", True),
            turn("hrv"),
            turn("pdf_lab"),
            turn("warehouse_lipid"),
            turn("lipid_ldl"),
            turn("summary"),
            turn("disclaimer"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("english_reply"), chk("no_empty")],
    },
    {
        "legacy_name": "mixed_prior_assets",
        "lane": "mixed_prior_assets",
        "turns": [
            turn("upload_exercise", True),
            turn("pdf_lab"),
            turn("warehouse_lipid"),
            turn("combine_hrv"),
            turn("body_age"),
            turn("summary"),
            turn("disclaimer"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("english_reply"), chk("no_empty")],
    },
    {
        "legacy_name": "stress_finale_10",
        "lane": "stress_finale",
        "turns": [
            turn("english_only"),
            turn("upload_exercise", True),
            turn("hrv"),
            turn("sleep_duration"),
            turn("lipid"),
            turn("steps"),
            turn("spo2"),
            turn("summary"),
            turn("summary_follow"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("english_reply"), chk("no_empty"), chk("no_repeat")],
    },
]


def main() -> None:
    assert len(SETS_SPEC) == 50, f"expected 50 sets, got {len(SETS_SPEC)}"
    sets = []
    for i, spec in enumerate(SETS_SPEC, start=1):
        row = dict(spec)
        row["set_id"] = f"EN{i:02d}"
        n_turns = len(row["turns"])
        assert n_turns >= 8, f"{row['set_id']} has {n_turns} turns"
        sets.append(row)

    bank = {
        "bank_version": "en-1.0",
        "language": "en",
        "colloquial_ratio_target": 0.7,
        "description": (
            "50 English E2E stress sets; each ≥8 turns; uses wearable screenshots, "
            "warehouse lipids/wearables, prior lab images, and prior PHA samples. "
            "Seed via PHA_E2E_BANK_SEED."
        ),
        "variant_pools": POOLS,
        "sets": sets,
    }
    OUT.write_text(json.dumps(bank, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} sets={len(sets)} pools={len(POOLS)}")


if __name__ == "__main__":
    main()
