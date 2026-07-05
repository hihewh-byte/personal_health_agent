#!/usr/bin/env python3
"""Stage 3C-δ: clarify SSE short-circuit + chip scope resolution (H-δ1–δ6)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["PHA_CLARIFY_TURNS"] = "1"
os.environ["PHA_HEALTH_TURN_RESOLVER"] = "1"
os.environ["PHA_GOAL_CLASSIFIER"] = "1"
os.environ["PHA_CLARIFY_INTENT_SCOPE"] = "1"

import pha.sqlite_storage as sqlite_storage
from pha.clarify_turns import (
    CLARIFY_FORBIDDEN_SLOTS,
    build_clarify_sse_payload,
    clarify_turns_enabled,
    resolve_scope_from_clarify_choice,
)
from pha.harness_plan import build_clarify_turn_plan, build_turn_evidence_plan
from pha.health_session_focus_store import (
    load_health_session_focus,
    record_health_turn_focus,
)
from pha.health_turn_resolver import resolve_health_turn_scope
from pha.session_turn_focus import get_session_turn_focus, init_session_focus_schema


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_hd1_flag_enabled() -> None:
    _assert(clarify_turns_enabled(), "PHA_CLARIFY_TURNS=1 must enable clarify")
    print("PASS H-δ1 PHA_CLARIFY_TURNS flag")


def test_hd2_sse_payload_shape() -> None:
    """RFC §6.4: event/kind/prompt/choices + turn_scope observability."""
    scope = resolve_health_turn_scope(
        "血脂怎么样",
        available_lab_years=[2023, 2024],
    )
    _assert(scope.needs_clarification, scope)
    _assert(scope.clarify_kind == "lab_year", scope)
    _assert(scope.year_source == "clarify", scope)
    payload = build_clarify_sse_payload(scope)
    _assert(payload["event"] == "clarify", payload)
    _assert(payload["kind"] == "lab_year", payload)
    _assert(isinstance(payload.get("prompt"), str) and payload["prompt"].strip(), payload)
    choices = payload.get("choices") or []
    _assert(len(choices) >= 2, choices)
    ids = {str(c["id"]) for c in choices}
    _assert("2023" in ids and "2024" in ids, ids)
    for ch in choices:
        _assert("label" in ch and "payload" in ch, ch)
        _assert(ch["payload"].get("lab_years"), ch)
    _assert(payload.get("turn_scope", {}).get("needsClarification") is True, payload)
    print("PASS H-δ2 clarify SSE payload (RFC §6.4)")


def test_hd3_clarify_harness_plan() -> None:
    """RFC §6.4 + §7: profile=clarify, slots MASTER_ANCHOR+TASK, Patient State forbidden."""
    plan = build_clarify_turn_plan()
    _assert(plan.profile == "clarify", plan.profile)
    _assert(plan.slots_tier0 == ["MASTER_ANCHOR", "TASK"], plan.slots_tier0)
    _assert(not plan.slots_tier1, plan.slots_tier1)
    _assert(not plan.tools_allowed, plan.tools_allowed)
    for slot in (
        "PATIENT_STATE_LAB",
        "PATIENT_STATE_WEARABLE",
        "USER_SNAPSHOT",
        "LDL_AUTHORITY",
        "NUMERICS_MANIFEST",
        "RECALL",
    ):
        _assert(slot in plan.forbidden, f"missing forbidden {slot}")
    _assert(set(CLARIFY_FORBIDDEN_SLOTS).issubset(set(plan.forbidden)), plan.forbidden)
    print("PASS H-δ3 clarify harness plan (RFC §7)")


def test_hd4_chip_choice_explicit_scope() -> None:
    pending = resolve_health_turn_scope(
        "血脂怎么样",
        available_lab_years=[2023, 2024],
    )
    resolved = resolve_scope_from_clarify_choice(
        "2024",
        pending_scope=pending,
        available_lab_years=[2023, 2024],
    )
    _assert(not resolved.needs_clarification, resolved)
    _assert(resolved.lab_years == [2024], resolved)
    _assert(resolved.year_source == "explicit", resolved)
    _assert(resolved.metric_keys == ["ldl"], resolved)
    print("PASS H-δ4 chip choice → explicit lab scope (RFC §6.4 explicit scope)")


def test_hd5_clarify_skips_episodic_write(tmp_db: Path) -> None:
    """RFC §6.4: 澄清轮不写 episodic / 不递减 TTL."""
    sqlite_storage.DEFAULT_DB_PATH = tmp_db
    sqlite_storage.ensure_data_dir()
    init_session_focus_schema()
    scope = resolve_health_turn_scope(
        "血脂怎么样",
        available_lab_years=[2023, 2024],
    )
    _assert(scope.needs_clarification, scope)
    record_health_turn_focus(
        "hd5",
        turn_scope=scope,
        harness_profile="clarify",
        user_message="血脂怎么样",
        assistant_reply="请指定年份",
    )
    _assert(load_health_session_focus("hd5") is None, "clarify must not persist focus")
    _assert(get_session_turn_focus("hd5") is None, "clarify must not consume TTL row")
    print("PASS H-δ5 clarify skips episodic write/consume")


def test_hd7_chip_plan_lab_cross_year() -> None:
    """RFC §7: clarify chip → turn_scope forces lab_cross_year harness plan."""
    pending = resolve_health_turn_scope(
        "血脂怎么样",
        available_lab_years=[2023, 2024],
    )
    resolved = resolve_scope_from_clarify_choice(
        "2023",
        pending_scope=pending,
        available_lab_years=[2023, 2024],
    )
    plan = build_turn_evidence_plan("2023年", turn_scope=resolved)
    _assert(plan.profile == "lab_cross_year", plan.profile)
    _assert("NUMERICS_MANIFEST" in plan.slots_tier0, plan.slots_tier0)
    _assert("LDL_AUTHORITY" in plan.slots_tier0, plan.slots_tier0)
    print("PASS H-δ7 chip choice → lab_cross_year plan (RFC §7)")


def test_hd6_h4_cross_resolver() -> None:
    """Align with RFC §8 H4 (resolver layer); 3C-δ wires SSE on top."""
    scope = resolve_health_turn_scope("血脂怎么样", available_lab_years=[2023, 2024])
    _assert(scope.needs_clarification and scope.clarify_kind == "lab_year", scope)
    ids = {c["id"] for c in scope.clarify_choices}
    _assert("2023" in ids and "2024" in ids, ids)
    print("PASS H-δ6 H4 resolver cross-check (needs_clarification + choices)")


def test_hd8_catalog_intent_scope_chip_without_pending() -> None:
    """3F-γ: browser chip id resolves via catalog when pending_scope absent."""
    resolved = resolve_scope_from_clarify_choice("wearable_only")
    _assert(not resolved.needs_clarification, resolved)
    _assert(resolved.profile_hint == "wearable_only", resolved)
    plan = build_turn_evidence_plan("仅穿戴近90天", turn_scope=resolved)
    _assert(plan.profile == "wearable_only", plan.profile)
    print("PASS H-δ8 catalog intent_scope chip → wearable_only plan")


def test_hd9_pending_scope_session_roundtrip(tmp_db: Path) -> None:
    """3F-γ: clarify assistant row persists pending scope for chip follow-up."""
    import pha.sqlite_storage as sqlite_storage
    from pha.chat_storage import append_message, create_session, init_chat_schema
    from pha.clarify_turns import load_pending_clarify_scope, persist_pending_clarify_scope

    sqlite_storage.DEFAULT_DB_PATH = tmp_db
    sqlite_storage.ensure_data_dir()
    init_chat_schema()
    sid = create_session("default").id
    pending = resolve_health_turn_scope("血脂怎么样", available_lab_years=[2023, 2024])
    assistant = append_message(sid, "assistant", "请选择年份")
    persist_pending_clarify_scope(sid, pending, message_id=assistant.id)
    loaded = load_pending_clarify_scope(sid)
    _assert(loaded is not None, "pending scope missing")
    _assert(loaded.clarify_kind == "lab_year", loaded)
    resolved = resolve_scope_from_clarify_choice(
        "2023",
        session_id=sid,
        available_lab_years=[2023, 2024],
    )
    _assert(resolved.lab_years == [2023], resolved)
    print("PASS H-δ9 session pending clarify scope roundtrip")


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp_db = Path(td) / "clarify_hd5.db"
        tmp_db2 = Path(td) / "clarify_hd9.db"
        test_hd1_flag_enabled()
        test_hd2_sse_payload_shape()
        test_hd3_clarify_harness_plan()
        test_hd4_chip_choice_explicit_scope()
        test_hd5_clarify_skips_episodic_write(tmp_db)
        test_hd7_chip_plan_lab_cross_year()
        test_hd6_h4_cross_resolver()
        test_hd8_catalog_intent_scope_chip_without_pending()
        test_hd9_pending_scope_session_roundtrip(tmp_db2)
    print("ALL PASS pha_clarify_turns_selfcheck")


if __name__ == "__main__":
    main()
