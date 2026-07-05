#!/usr/bin/env python3
"""P2 offline selfcheck — combined_review SSE assertion helpers."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.e2e_combined_review_assertions import assert_combined_review_sse_turn


def _assert_empty(fails: list[str], label: str) -> None:
    if fails:
        raise AssertionError(f"{label}: {fails}")


def _golden_harness() -> dict:
    return {
        "runtime_mode": "catalog_tool_loop",
        "plan": {
            "profile": "combined_review",
            "tools_allowed": ["fetch_evidence_by_id"],
        },
        "tools": {
            "executed": [{"name": "fetch_evidence_by_id", "auto": True}],
        },
        "tier0_integrity": {"errors": []},
    }


def test_pass_clean_turn() -> None:
    fails = assert_combined_review_sse_turn(
        turn=1,
        error="",
        events=["status", "delta", "done"],
        answer_chars=120,
        harness=_golden_harness(),
    )
    _assert_empty(fails, "clean turn")
    print("PASS P2-1 clean combined_review SSE turn")


def test_fail_sse_error() -> None:
    fails = assert_combined_review_sse_turn(
        turn=1,
        error="Ollama chat failed: status code: 400 can't find closing '}' symbol",
        events=["status", "error"],
        answer_chars=0,
        harness=_golden_harness(),
    )
    if not fails:
        raise AssertionError("expected failures for SSE error")
    if not any("SSE error" in f for f in fails):
        raise AssertionError(fails)
    if not any("wire-format" in f for f in fails):
        raise AssertionError(fails)
    print("PASS P2-2 detects Ollama 400 SSE error")


def test_skip_non_combined_profile() -> None:
    fails = assert_combined_review_sse_turn(
        turn=2,
        error="should be ignored",
        events=[],
        answer_chars=0,
        harness={"plan": {"profile": "wearable_only"}},
    )
    _assert_empty(fails, "non-combined profile skipped")
    print("PASS P2-3 skips non-combined_review harness")


def test_fail_missing_catalog_tool() -> None:
    h = _golden_harness()
    h["tools"] = {"executed": []}
    fails = assert_combined_review_sse_turn(
        turn=6,
        error="",
        events=["done"],
        answer_chars=80,
        harness=h,
    )
    if not any("fetch_evidence_by_id" in f for f in fails):
        raise AssertionError(fails)
    print("PASS P2-4 requires fetch_evidence_by_id execution")


def main() -> int:
    test_pass_clean_turn()
    test_fail_sse_error()
    test_skip_non_combined_profile()
    test_fail_missing_catalog_tool()
    print("pha_e2e_combined_review_sse_selfcheck: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
