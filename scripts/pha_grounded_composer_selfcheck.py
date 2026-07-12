#!/usr/bin/env python3
"""Stage 3C-ε: GroundedAnswerComposer fact_card + follow_ups (H-ε1–ε4)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["PHA_GROUNDED_COMPOSER"] = "1"

from pha.grounded_answer_composer import (
    apply_english_locale_leak_guard,
    answer_has_cjk_locale_leak,
    build_composer_meta_event,
    build_fact_card_event,
    build_follow_ups_event,
    build_manifest_locale_fallback_summary,
    fact_card_values_subset_of_manifest,
    grounded_composer_enabled,
)
from pha.numerics_manifest import ManifestEntry, NumericsManifest


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_he1_flag() -> None:
    _assert(grounded_composer_enabled(), "PHA_GROUNDED_COMPOSER=1")
    print("PASS H-ε1 PHA_GROUNDED_COMPOSER flag")


def test_he2_meta_event() -> None:
    ev = build_composer_meta_event(
        session_id="s1",
        profile="wearable_only",
        turn_scope={"metricKeys": ["hrv"]},
    )
    _assert(ev["event"] == "meta" and ev["profile"] == "wearable_only", ev)
    _assert(ev["turn_scope"]["metricKeys"] == ["hrv"], ev)
    print("PASS H-ε2 meta SSE event")


def test_he3_fact_card_subset() -> None:
    manifest = NumericsManifest(
        profile="lab_cross_year",
        user_id="default",
        entries=[
            ManifestEntry(
                domain="lipid",
                metric="LDL",
                value=3.2,
                unit="mmol/L",
                anchor="2023-05-01",
                source="medical_reports",
            ),
        ],
    )
    fc = build_fact_card_event(manifest)
    _assert(fc is not None and fc["event"] == "fact_card", fc)
    _assert(len(fc["items"]) == 1, fc)
    _assert(fact_card_values_subset_of_manifest(fc, manifest), "subset check")
    print("PASS H-ε3 fact_card ⊆ manifest")


def test_he5_wearable_fact_card_manifest() -> None:
    """RFC §6.6: wearable_only composer fact_card from numerics_manifest entries."""
    manifest = NumericsManifest(
        profile="wearable_only",
        user_id="selfcheck",
        entries=[
            ManifestEntry(
                domain="wearable",
                metric="HRV均值",
                value=33.1,
                unit="ms",
                anchor="2025-09-01~2025-11-29",
                source="selfcheck.in_memory",
            ),
        ],
    )
    fc = build_fact_card_event(manifest)
    _assert(fc is not None and fc.get("items"), fc)
    _assert(fact_card_values_subset_of_manifest(fc, manifest), "wearable subset")
    print("PASS H-ε5 wearable fact_card from manifest")


def test_he4_follow_ups_catalog() -> None:
    ev = build_follow_ups_event(profile="wearable_only", metric_keys=["hrv"])
    _assert(ev["event"] == "follow_ups", ev)
    choices = ev.get("choices") or []
    _assert(len(choices) == 3, choices)
    _assert(all("id" in c and "label" in c for c in choices), choices)
    print("PASS H-ε4 follow_ups (3 catalog choices)")


def test_he6_locale_leak_guard() -> None:
    zh_blob = "### Trend review\n从 health records 账本中，我们可以看到您的 LDL胆固醇水平在过去一年内有显著改善。" * 3
    _assert(answer_has_cjk_locale_leak(zh_blob, locale="en"), "cjk leak detect")
    manifest = NumericsManifest(
        profile="combined_review",
        user_id="default",
        entries=[
            ManifestEntry(
                domain="lipid",
                metric="LDL",
                value=2.45,
                unit="mmol/L",
                anchor="2025-06-01",
                source="medical_reports",
            ),
        ],
    )
    fb = build_manifest_locale_fallback_summary(manifest, locale="en")
    _assert("LDL" in fb and "2.45" in fb, fb)
    guarded, audit = apply_english_locale_leak_guard(
        zh_blob,
        locale="en",
        numerics_manifest=None,
        user_id="default",
        profile="lifestyle",
        user_message="How do lipids trend across years?",
    )
    _assert(audit.get("locale_fallback_applied"), audit)
    _assert(not answer_has_cjk_locale_leak(guarded, locale="en"), guarded[:120])
    print("PASS H-ε6 english locale leak guard")


def main() -> None:
    test_he1_flag()
    test_he2_meta_event()
    test_he3_fact_card_subset()
    test_he5_wearable_fact_card_manifest()
    test_he4_follow_ups_catalog()
    test_he6_locale_leak_guard()
    print("ALL PASS pha_grounded_composer_selfcheck")


if __name__ == "__main__":
    main()
