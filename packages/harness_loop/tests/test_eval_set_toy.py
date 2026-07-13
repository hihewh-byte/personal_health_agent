"""Smoke tests for harness-loop eval_set portability."""

from __future__ import annotations

from pathlib import Path

from harness_loop.eval_set import validate_file

ROOT = Path(__file__).resolve().parents[3]


def test_toy_golden_passes() -> None:
    golden = ROOT / "examples" / "loop_reference_toy" / "evals" / "toy_smoke_v0.json"
    catalog = ROOT / "examples" / "loop_reference_toy" / "catalog.json"
    assert golden.is_file()
    errors = validate_file(golden, catalog_path=catalog)
    assert errors == [], errors
