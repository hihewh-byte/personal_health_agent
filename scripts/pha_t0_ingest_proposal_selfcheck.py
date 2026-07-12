#!/usr/bin/env python3
"""Selfcheck: Loop B T0 ingest proposal extraction is proposal-only and provenance-backed."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.t0_ingest_proposal import build_t0_ingest_proposal, extract_t0_ingest_proposal_rows  # noqa: E402


def main() -> int:
    fixture = ROOT / "scripts" / "fixtures" / "t0_ingest_parsed_sample.json"
    parsed = json.loads(fixture.read_text(encoding="utf-8"))
    rows = extract_t0_ingest_proposal_rows(parsed)
    assert len(rows) == 2, rows
    assert rows[0].prov_type == "lab_report", rows[0]
    assert rows[0].source_ref.startswith("attachment_"), rows[0]
    proposal = build_t0_ingest_proposal([parsed], user_id="default")
    assert proposal["schema"] == "pha.t0_ingest_proposal/v1", proposal
    assert proposal["row_count"] == 2, proposal
    assert "Proposal-only" in proposal["notes"], proposal["notes"]
    print("pha_t0_ingest_proposal_selfcheck: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
