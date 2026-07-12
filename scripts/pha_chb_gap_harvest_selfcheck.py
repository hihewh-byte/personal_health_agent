#!/usr/bin/env python3
"""Selfcheck: CHB gap harvest + compile merge."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.chb_gap_harvest import (  # noqa: E402
    extract_chb_gap_candidates,
    load_gap_open_questions,
    write_gap_candidates,
)
from pha.chb_compiler import compile_chronic_health_brief  # noqa: E402


def main() -> int:
    rows = [
        {
            "user_id": "gap_user",
            "session_name": "EN99",
            "turn": 3,
            "message": "Can I drink coffee with my supplements?",
            "answer": (
                "Maintain a balanced diet and consult your doctor for personalized advice. "
                "Regular exercise and sleep hygiene are important."
            ),
            "checks": [],
        }
    ]
    gaps = extract_chb_gap_candidates(rows)
    assert len(gaps) == 1, gaps
    assert gaps[0]["signal"] == "generic_lifestyle_answer", gaps[0]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        write_gap_candidates(gaps, user_id="gap_user", report_root=root)
        loaded = load_gap_open_questions("gap_user", report_root=root)
        assert loaded and "coffee" in loaded[0].lower(), loaded

        # compile merge uses DEFAULT_REPORT_ROOT; patch via writing to default path under temp
        import pha.chb_compiler as chb_mod

        prev = chb_mod.DEFAULT_REPORT_ROOT
        chb_mod.DEFAULT_REPORT_ROOT = root
        try:
            brief = compile_chronic_health_brief("gap_user")
            assert any("coffee" in q.lower() for q in brief.open_questions), brief.open_questions
        finally:
            chb_mod.DEFAULT_REPORT_ROOT = prev

    print("pha_chb_gap_harvest_selfcheck: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
