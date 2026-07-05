#!/usr/bin/env python3
"""Stage 3C-β: episodic SQLite roundtrip, bridge block, harness turnScope."""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.harness_plan import build_turn_evidence_plan
from pha.harness_report import HarnessTurnInputs, build_harness_report
from pha.harness_plan import assemble_tiered_supplemental
from pha.health_episodic_focus import HealthSessionFocus, WearableWindow
from pha.health_session_focus_store import (
    episodic_report_meta,
    health_episodic_bridge_block,
    load_health_session_focus,
    record_health_turn_focus,
    revive_health_session_focus,
    save_health_session_focus,
)
from pha.health_turn_resolver import resolve_health_turn_scope
from pha.intent_gates import QuestionType
from pha.session_turn_focus import get_session_turn_focus, init_session_focus_schema
import pha.sqlite_storage as sqlite_storage


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _use_db(tmp_db: Path) -> None:
    sqlite_storage.DEFAULT_DB_PATH = tmp_db
    sqlite_storage.ensure_data_dir()


def test_sqlite_roundtrip(tmp_db: Path) -> None:
    _use_db(tmp_db)
    init_session_focus_schema()
    focus = HealthSessionFocus(
        session_id="beta-1",
        focus_profile="wearable_only",
        focus_metric="hrv",
        focus_wearable_window=WearableWindow(start=date(2026, 3, 12), end=date(2026, 6, 10)),
        focus_summary="HRV 近90天",
        focus_tokens=["hrv"],
        turns_remaining=8,
        last_user_message="HRV 怎么样",
        last_assistant_digest="近90天 HRV 均值约 33ms",
    )
    save_health_session_focus("beta-1", focus)
    loaded = load_health_session_focus("beta-1")
    _assert(loaded is not None, "load failed")
    _assert(loaded.focus_profile == "wearable_only", loaded)
    _assert(loaded.focus_metric == "hrv", loaded)
    _assert(loaded.turns_remaining == 8, loaded)
    row = get_session_turn_focus("beta-1")
    _assert(row is not None and row.focus_profile == "wearable_only", row)
    print("PASS sqlite roundtrip health focus columns")


def test_record_and_revive(tmp_db: Path) -> None:
    _use_db(tmp_db)
    init_session_focus_schema()
    scope1 = resolve_health_turn_scope("HRV 怎么样", reference_date=date(2026, 6, 10))
    record_health_turn_focus(
        "beta-2",
        turn_scope=scope1,
        harness_profile="wearable_only",
        user_message="HRV 怎么样",
        assistant_reply="近90天 HRV 正常",
    )
    row = get_session_turn_focus("beta-2")
    _assert(row is not None and row.turns_remaining == 8, row)
    _assert(row.focus_profile == "wearable_only", row)
    revived = revive_health_session_focus("beta-2", "那上个月呢")
    _assert(revived is not None and revived.active, revived)
    print("PASS record_health_turn_focus + revive")


def test_bridge_block() -> None:
    focus = HealthSessionFocus(
        session_id="b",
        focus_profile="wearable_only",
        focus_metric="hrv",
        turns_remaining=6,
        last_user_message="HRV 怎么样",
        last_assistant_digest="摘要",
    )
    block = health_episodic_bridge_block(focus)
    _assert("EPISODIC_BRIDGE" in block or "上轮对话摘要" in block, block)
    _assert("HRV" in block.upper() or "hrv" in block, block)
    print("PASS health_episodic_bridge_block")


def test_harness_turn_scope() -> None:
    scope = resolve_health_turn_scope("HRV 怎么样", reference_date=date(2026, 6, 10))
    meta = episodic_report_meta(turn_scope=scope, bridge_injected=True, recall_focus_injected=False)
    inputs = HarnessTurnInputs(
        user_id="default",
        session_id="s1",
        user_message_id=1,
        model="test",
        user_message="HRV 怎么样",
        question_type=QuestionType.WEARABLE,
        temporal_years=[],
        turn_scope=dict(meta.get("turnScope") or {}),
        episodic=dict(meta.get("episodic") or {}),
    )
    report = build_harness_report(inputs)
    _assert(report.get("schema") == "pha.harness_report/v1.2", report.get("schema"))
    _assert("turnScope" in report and report["turnScope"].get("metricKeys"), report)
    _assert("episodic" in report and report["episodic"].get("bridgeInjected") is True, report)
    print("PASS harnessReport.turnScope runtime")


def test_episodic_bridge_tier0() -> None:
    plan = build_turn_evidence_plan("HRV 怎么样")
    block = health_episodic_bridge_block(
        HealthSessionFocus(
            session_id="t",
            focus_profile="wearable_only",
            focus_metric="hrv",
            turns_remaining=5,
            last_user_message="HRV",
            last_assistant_digest="ok",
        ),
    )
    slots = {"TASK": plan.task_text, "EPISODIC_BRIDGE": block, "WEARABLE_90D_SUMMARY": ""}
    t0, _, _, _ = assemble_tiered_supplemental(plan=plan, slot_contents=slots)
    _assert("上轮对话摘要" in t0, t0[:200])
    print("PASS EPISODIC_BRIDGE tier0 assembly")


def test_attachment_recall_forbidden() -> None:
    plan = build_turn_evidence_plan(
        "为什么有帮助",
        attachment_asset_qa=True,
        attachment_qa_mode="initial",
    )
    _assert("RECALL" in plan.forbidden, plan.forbidden)
    print("PASS attachment RECALL forbidden unchanged")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "episodic.db"
        test_sqlite_roundtrip(db)
        test_record_and_revive(db)
    test_bridge_block()
    test_harness_turn_scope()
    test_episodic_bridge_tier0()
    test_attachment_recall_forbidden()
    print("pha_health_episodic_selfcheck: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
