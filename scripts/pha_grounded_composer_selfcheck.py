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
    build_composer_meta_event,
    build_fact_card_event,
    build_follow_ups_event,
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
    from pha.numerics_manifest import build_numerics_manifest

    manifest = build_numerics_manifest(
        "default",
        profile="wearable_only",
        user_message="我最近的 HRV 怎么样？",
        include_lipid=False,
        include_wearable=True,
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


def main() -> None:
    test_he1_flag()
    test_he2_meta_event()
    test_he3_fact_card_subset()
    test_he5_wearable_fact_card_manifest()
    test_he4_follow_ups_catalog()
    print("ALL PASS pha_grounded_composer_selfcheck")


if __name__ == "__main__":
    main()
