#!/usr/bin/env python3
"""Loop B persona battery (offline, no real user JSONL).

Validates that compiled CHB artifacts personalize allowed profiles while staying
out of attachment-grounded review turns.
"""

from __future__ import annotations

import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.chb_compiler import (  # noqa: E402
    ChbFactRow,
    ChronicHealthBrief,
    assemble_facts_section,
    build_user_context_brief_block,
    compute_ledger_hash,
    write_chb_artifact,
)


def _brief() -> ChronicHealthBrief:
    facts = [
        ChbFactRow(
            text="LDL 2025-12-07: 2.45 mmol/L",
            ref_id="lab_2025-12-07_ldl",
            prov_type="lab_report",
            metric_id="ldl",
            value="2.45",
            unit="mmol/L",
            observed_at="2025-12-07",
        ),
        ChbFactRow(
            text="User stated: taking magnesium supplement at night",
            ref_id="chat_bg_supplement_magnesium",
            prov_type="user_statement",
            metric_id=None,
            value="magnesium",
        ),
    ]
    return ChronicHealthBrief(
        user_id="persona_user",
        compiled_at="2026-07-12T00:00:00+00:00",
        ledger_hash=compute_ledger_hash(facts),
        facts=facts,
        interpretation=[],
        open_questions=["No caffeine sensitivity statement is recorded."],
        facts_markdown=assemble_facts_section(facts),
        interpretation_markdown="## §Interpretation（解读 · 非数字源 · ADVISORY ONLY）\n- Fixture only.",
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        write_chb_artifact(_brief(), report_root=root)
        lifestyle = build_user_context_brief_block("persona_user", profile="lifestyle", report_root=root)
        combined = build_user_context_brief_block("persona_user", profile="combined_review", report_root=root)
        grounded = build_user_context_brief_block(
            "persona_user",
            profile="attachment_grounded_review",
            report_root=root,
        )
        assert "USER_CONTEXT_BRIEF" in lifestyle, lifestyle
        assert "lab_2025-12-07_ldl" in lifestyle, lifestyle
        assert "magnesium" in combined.lower(), combined
        assert "Open Questions" in lifestyle, lifestyle
        assert grounded == "", grounded
    print("pha_persona_personalization_battery: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
