#!/usr/bin/env python3
"""Selfcheck: T0 gated adopter veto + dry-run mapping."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.t0_gated_adopter import (  # noqa: E402
    apply_t0_ingest_proposal,
    proposal_to_metric_rows,
    static_veto_proposal,
)
from pha.t0_ingest_proposal import build_t0_ingest_proposal  # noqa: E402


def main() -> int:
    fixture = ROOT / "scripts" / "fixtures" / "t0_ingest_parsed_sample.json"
    parsed = json.loads(fixture.read_text(encoding="utf-8"))
    proposal = build_t0_ingest_proposal([parsed], user_id="t0_adopt_selfcheck")

    veto = static_veto_proposal(proposal)
    assert not veto, veto

    rows, skips = proposal_to_metric_rows(proposal)
    assert len(rows) == 2, (rows, skips)
    assert rows[0].metric_name == "LDL cholesterol", rows[0]

    dry = apply_t0_ingest_proposal(proposal, dry_run=True)
    assert not dry.veto, dry.veto
    assert dry.rows and dry.rows[0].get("would_apply_rows") == 2, dry.rows

    blocked = apply_t0_ingest_proposal(proposal, dry_run=False, confirm_token="")
    assert blocked.veto == ["confirm_token_required_for_apply"], blocked.veto

    bad = dict(proposal)
    bad["schema"] = "bad"
    assert static_veto_proposal(bad) == ["schema_not_pha.t0_ingest_proposal/v1"]

    print("pha_t0_gated_adopter_selfcheck: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
