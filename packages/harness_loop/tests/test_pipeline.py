"""Package-local tests for offline pipeline orchestration."""

from __future__ import annotations

from harness_loop.pipeline import run_offline_pipeline


def test_stages_run_in_order():
    seen: list[str] = []
    result = run_offline_pipeline(
        [("a", lambda: seen.append("a") or 0), ("b", lambda: seen.append("b") or 0)]
    )
    assert seen == ["a", "b"]
    assert result.stages_run == ["a", "b"]
    assert result.exit_codes == {"a": 0, "b": 0}


def test_stop_on_error_halts_and_notes_no_auto_merge():
    seen: list[str] = []
    result = run_offline_pipeline(
        [
            ("a", lambda: seen.append("a") or 2),
            ("b", lambda: seen.append("b") or 0),
        ]
    )
    assert seen == ["a"]
    assert result.exit_codes["a"] == 2
    assert "no auto-merge" in result.notes


def test_stop_on_error_false_continues():
    seen: list[str] = []
    result = run_offline_pipeline(
        [
            ("a", lambda: seen.append("a") or 1),
            ("b", lambda: seen.append("b") or 0),
        ],
        stop_on_error=False,
    )
    assert seen == ["a", "b"]
    assert result.exit_codes == {"a": 1, "b": 0}
