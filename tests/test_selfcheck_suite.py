"""Pytest entry for PHA offline selfcheck manifest (P1-4)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pha_selfcheck_runner as runner  # noqa: E402


def _check_ids() -> list[str]:
    return [c.id for c in runner.load_manifest()]


@pytest.mark.parametrize("check_id", _check_ids())
def test_selfcheck_manifest(check_id: str) -> None:
    spec = next(c for c in runner.load_manifest() if c.id == check_id)
    result = runner.run_check(spec, python=runner._resolve_python(None), verbose=False)
    if result.status == "missing":
        pytest.skip(f"missing script: {spec.script}")
    assert result.status == "pass", (
        f"{check_id} ({spec.script}) failed with exit {result.exit_code}"
    )
