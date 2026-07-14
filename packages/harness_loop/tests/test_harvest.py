"""Package-local tests for portable failed-turn harvest."""

from __future__ import annotations

import json
from pathlib import Path

from harness_loop.harvest import harvest_failed_turns_jsonl, harvest_file_to_path

FIXTURES = Path(__file__).parent / "fixtures"
E2E = FIXTURES / "e2e_sample.jsonl"


def test_harvest_only_failed_turns():
    rows: list[dict] = []
    n = harvest_failed_turns_jsonl(E2E, rows)
    assert n == 2
    messages = {r["message"] for r in rows}
    assert "How is my HRV?" not in messages  # passed:true row skipped


def test_harvest_candidate_fields_complete():
    rows: list[dict] = []
    harvest_failed_turns_jsonl(E2E, rows)
    for row in rows:
        for key in ("harvested_at", "message", "signal", "source", "meta"):
            assert key in row
        assert row["source"].startswith("e2e:")


def test_harvest_dedupes_identical_candidates(tmp_path):
    doubled = tmp_path / "doubled.jsonl"
    line = E2E.read_text(encoding="utf-8").splitlines()[0]
    doubled.write_text(line + "\n" + line + "\n", encoding="utf-8")
    rows: list[dict] = []
    n = harvest_failed_turns_jsonl(doubled, rows)
    assert n == 1
    assert len(rows) == 1


def test_harvest_file_to_path_writes_jsonl(tmp_path):
    out = tmp_path / "candidates.jsonl"
    path, n_signals, n_rows = harvest_file_to_path(E2E, out)
    assert path == out and out.is_file()
    assert n_signals == 2 and n_rows == 2
    lines = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2
