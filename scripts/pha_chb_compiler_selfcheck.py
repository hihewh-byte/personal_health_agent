#!/usr/bin/env python3
"""Stage 4-β CHB compiler selfcheck — §Facts deterministic + 4-β-2a/b harness hooks."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.chb_compiler import (  # noqa: E402
    CHB_SCHEMA,
    INTERPRETATION_ADVISORY_BANNER,
    ChbFactRow,
    USER_CONTEXT_BRIEF_PROFILES,
    assemble_facts_section,
    build_user_context_brief_block,
    chb_compiler_enabled,
    chb_stale_status,
    compile_chronic_health_brief,
    compile_interpretation_stub,
    compute_ledger_hash,
    compute_live_ledger_hash,
    load_latest_chb_artifact,
    load_slot_candidates,
    recompile_chb_if_stale,
    write_chb_artifact,
)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_facts_section_has_refs() -> None:
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
    ]
    md = assemble_facts_section(facts)
    _assert("§Facts" in md, md)
    _assert("[ref: lab_2025-12-07_ldl]" in md, md)


def test_ledger_hash_stable() -> None:
    facts = [
        ChbFactRow(text="x", ref_id="r1", prov_type="wearable_import"),
        ChbFactRow(text="y", ref_id="r2", prov_type="wearable_import"),
    ]
    h1 = compute_ledger_hash(facts)
    h2 = compute_ledger_hash(facts)
    _assert(h1 == h2, "hash must be stable")
    _assert(len(h1) == 16, h1)


def test_slot_candidates_loaded() -> None:
    slots = load_slot_candidates()
    _assert(len(slots) >= 2, slots)
    kinds = {s.get("kind") for s in slots}
    _assert("time" in kinds and "aggregation" in kinds, kinds)


def test_compile_brief_structure() -> None:
    brief = compile_chronic_health_brief("default")
    _assert(brief.schema == CHB_SCHEMA, brief.schema)
    _assert(brief.user_id == "default", brief.user_id)
    _assert(brief.ledger_hash, "ledger_hash required")
    _assert("§Facts" in brief.facts_markdown, brief.facts_markdown)
    _assert("§Interpretation" in brief.interpretation_markdown, brief.interpretation_markdown)
    for f in brief.facts:
        _assert(f.ref_id and f.prov_type, f.as_dict())
        _assert("[ref:" in brief.facts_markdown or not brief.facts, brief.facts_markdown)


def test_interpretation_stub_only() -> None:
    brief = compile_chronic_health_brief("default")
    _assert("§Interpretation" in brief.interpretation_markdown, brief.interpretation_markdown)
    _assert(
        "derived_from" in json.dumps(brief.interpretation, ensure_ascii=False) or not brief.interpretation,
        brief.interpretation,
    )


def test_chb_compiler_default_off() -> None:
    prev = os.environ.pop("PHA_CHB_COMPILER", None)
    try:
        _assert(not chb_compiler_enabled(), "PHA_CHB_COMPILER must default off")
    finally:
        if prev is not None:
            os.environ["PHA_CHB_COMPILER"] = prev


def test_interpretation_mock_llm_advisory_only() -> None:
    """Mock LLM path — no network; §Interpretation is advisory, not numerics source."""
    facts = [
        ChbFactRow(
            text="近 90d 睡眠 均值: 7.2 h",
            ref_id="wearable_90d_sleep",
            prov_type="wearable_import",
            metric_id="sleep",
            value="7.2",
            unit="h",
        ),
    ]
    facts_md = assemble_facts_section(facts)

    def _mock_llm(_fm: str) -> str:
        return "睡眠均值趋势平稳（mock advisory，非数字源）。"

    prev = os.environ.get("PHA_CHB_COMPILER")
    os.environ["PHA_CHB_COMPILER"] = "1"
    try:
        items, md = compile_interpretation_stub(
            facts,
            enable_llm=True,
            facts_markdown=facts_md,
            llm_fn=_mock_llm,
        )
        _assert(items and items[0].get("prov_type") == "llm_advisory", items)
        _assert(INTERPRETATION_ADVISORY_BANNER in md, md)
        _assert("mock advisory" in md, md)
        _assert("7.2" not in items[0].get("text", ""), "interpretation must not invent numerics")
    finally:
        if prev is None:
            os.environ.pop("PHA_CHB_COMPILER", None)
        else:
            os.environ["PHA_CHB_COMPILER"] = prev


def test_user_context_brief_profiles() -> None:
    _assert("lifestyle" in USER_CONTEXT_BRIEF_PROFILES, USER_CONTEXT_BRIEF_PROFILES)
    _assert("combined_review" in USER_CONTEXT_BRIEF_PROFILES, USER_CONTEXT_BRIEF_PROFILES)
    _assert("attachment_grounded_review" not in USER_CONTEXT_BRIEF_PROFILES, USER_CONTEXT_BRIEF_PROFILES)


def test_user_context_brief_block_from_artifact() -> None:
    brief = compile_chronic_health_brief("default")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        write_chb_artifact(brief, report_root=root)
        block = build_user_context_brief_block("default", profile="lifestyle", report_root=root)
        _assert("USER_CONTEXT_BRIEF" in block, block)
        _assert("§Facts" in block, block)
        loaded = load_latest_chb_artifact("default", report_root=root)
        _assert(loaded is not None and loaded.ledger_hash == brief.ledger_hash, loaded)


def test_user_context_brief_empty_without_artifact() -> None:
    with tempfile.TemporaryDirectory() as td:
        block = build_user_context_brief_block("no_such_user", profile="lifestyle", report_root=Path(td))
        _assert(block == "", f"expected empty block, got: {block!r}")


def test_user_context_brief_forbidden_on_grounded() -> None:
    brief = compile_chronic_health_brief("default")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        write_chb_artifact(brief, report_root=root)
        block = build_user_context_brief_block(
            "default",
            profile="attachment_grounded_review",
            report_root=root,
        )
        _assert(block == "", "attachment_grounded_review must not inject USER_CONTEXT_BRIEF")


def test_write_artifact() -> None:
    brief = compile_chronic_health_brief("default")
    with tempfile.TemporaryDirectory() as td:
        path = write_chb_artifact(brief, report_root=Path(td))
        _assert(path.is_file(), str(path))
        doc = json.loads(path.read_text(encoding="utf-8"))
        _assert(doc.get("schema") == CHB_SCHEMA, doc)
        _assert(doc.get("slot_hints"), "slot hints from loop_slot_candidates.jsonl")


def test_chb_stale_detection() -> None:
    """4-β-2c: live T0 hash vs on-disk artifact."""
    live = compute_live_ledger_hash("default")
    _assert(live and len(live) == 16, live)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        status = chb_stale_status("default", report_root=root)
        _assert(status["is_stale"], "missing artifact must be stale")
        _assert(status["live_hash"] == live, status)

        brief = compile_chronic_health_brief("default")
        write_chb_artifact(brief, report_root=root)
        status = chb_stale_status("default", report_root=root)
        _assert(not status["is_stale"], status)
        _assert(status["artifact_hash"] == live, status)

        stale_doc = {
            "schema": CHB_SCHEMA,
            "user_id": "default",
            "compiled_at": "2099-01-01T00:00:00+00:00",
            "ledger_hash": "deadbeefdeadbeef",
            "facts": [],
            "interpretation": [],
            "open_questions": [],
            "slot_hints": [],
            "facts_markdown": "",
            "interpretation_markdown": "",
        }
        stale_path = root / "default" / "brief_deadbeefdeadbeef.json"
        stale_path.write_text(json.dumps(stale_doc) + "\n", encoding="utf-8")
        status = chb_stale_status("default", report_root=root)
        _assert(status["is_stale"], "wrong ledger_hash in newest artifact must be stale")


def test_recompile_if_stale_dry_run_and_write() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        status, path = recompile_chb_if_stale("default", report_root=root, dry_run=True)
        _assert(status["is_stale"], status)
        _assert(path is None, "dry-run must not write")

        status, path = recompile_chb_if_stale("default", report_root=root)
        _assert(path is not None and path.is_file(), path)
        _assert(not status["is_stale"], status)

        status2, path2 = recompile_chb_if_stale("default", report_root=root)
        _assert(path2 is None, "fresh artifact must skip recompile")
        _assert(not status2["is_stale"], status2)
        _assert(status2["artifact_count"] >= 1, status2)


def main() -> int:
    test_facts_section_has_refs()
    print("PASS §Facts ref markers")
    test_ledger_hash_stable()
    print("PASS ledger hash stable")
    test_slot_candidates_loaded()
    print("PASS slot candidates loaded")
    test_compile_brief_structure()
    print("PASS compile brief structure")
    test_interpretation_stub_only()
    print("PASS interpretation stub")
    test_chb_compiler_default_off()
    print("PASS PHA_CHB_COMPILER default off")
    test_interpretation_mock_llm_advisory_only()
    print("PASS mock LLM interpretation (advisory only)")
    test_user_context_brief_profiles()
    print("PASS USER_CONTEXT_BRIEF profile gate")
    test_user_context_brief_block_from_artifact()
    print("PASS USER_CONTEXT_BRIEF block from artifact")
    test_user_context_brief_empty_without_artifact()
    print("PASS USER_CONTEXT_BRIEF empty without artifact")
    test_user_context_brief_forbidden_on_grounded()
    print("PASS USER_CONTEXT_BRIEF forbidden on grounded")
    test_write_artifact()
    print("PASS write artifact")
    test_chb_stale_detection()
    print("PASS CHB stale detection (4-β-2c)")
    test_recompile_if_stale_dry_run_and_write()
    print("PASS recompile_if_stale dry-run + write")
    print("OK pha_chb_compiler_selfcheck (Stage 4-β-2a/b/c)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
