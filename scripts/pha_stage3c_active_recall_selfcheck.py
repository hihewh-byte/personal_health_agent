#!/usr/bin/env python3
"""Stage 3C Active Recall ledger + recall_plan selfcheck."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.active_recall_ledger import (
    ActiveRecallLedger,
    build_recall_focus_block,
    resolve_recall_plan,
    sync_ledger_after_turn,
    upsert_anchored_asset_from_parse,
)
from pha.attachment_asset_qa import resolve_attachment_qa_mode


def main() -> int:
    failed = 0
    sid = "_selfcheck_recall_session"

    parsed = {
        "parse_confidence": "high",
        "label_ledger": "NOW PS 100mg; Choline 100mg",
        "ingredient_rows": [
            {"name": "Phosphatidyl Serine", "amount": "100 mg"},
        ],
    }
    ledger = ActiveRecallLedger(session_id=sid)
    upsert_anchored_asset_from_parse(ledger, parsed, source_turn=1)
    if not ledger.by_id("assert_anchored_asset"):
        print("FAIL: anchored asset missing")
        failed += 1

    plan = resolve_recall_plan(
        "和他汀一起吃有副作用吗",
        profile="attachment_episodic_bridge",
        focus_tokens=["Phosphatidyl"],
    )
    if "anchored_asset" not in plan:
        print("FAIL: plan missing anchored_asset", plan)
        failed += 1
    if "interaction_context" not in plan:
        print("FAIL: plan missing interaction_context", plan)
        failed += 1

    block = build_recall_focus_block(ledger, parse_confidence="high")
    if "当前锁定资产" not in block:
        print("FAIL: recall block", block)
        failed += 1

    mode = resolve_attachment_qa_mode(
        "还有帮助吗",
        has_parsed_attachment=False,
        session_focus_active=True,
        focus_tokens=["PS"],
    )
    if mode != "episodic_bridge":
        print("FAIL: episodic mode", mode)
        failed += 1

    sync_ledger_after_turn(
        sid,
        parsed_payload=parsed,
        slot_contents={"DATA_AVAILABILITY": "化验：有"},
        user_message="身体指标",
        profile="attachment_episodic_bridge",
        focus_active=True,
    )
    from pha.active_recall_ledger import load_active_recall_ledger

    loaded = load_active_recall_ledger(sid)
    if not loaded.by_id("assert_clinical_snippet"):
        print("FAIL: clinical snippet not persisted")
        failed += 1

    from pha.active_recall_ledger import clear_active_recall_ledger

    clear_active_recall_ledger(sid)

    if failed:
        return 1
    print("OK: active recall selfcheck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
