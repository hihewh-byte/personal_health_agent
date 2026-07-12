#!/usr/bin/env python3
"""Selfcheck: loop failure taxonomy + E2E harvest mapping."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.loop_failure_taxonomy import (  # noqa: E402
    allowed_proposal_layers,
    classify_e2e_check,
    is_auto_promote_eligible,
    warehouse_llm_zh_heuristic,
)


def _load_harvest_module():
    path = ROOT / "scripts" / "pha_telemetry_harvest.py"
    spec = importlib.util.spec_from_file_location("pha_telemetry_harvest", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _load_reflection_module():
    path = ROOT / "scripts" / "pha_reflection_critic.py"
    spec = importlib.util.spec_from_file_location("pha_reflection_critic", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ok = True

    if classify_e2e_check("non_english_cjk_ratio:0.57") != "rlp_locale_leak":
        print("FAIL non_english mapping")
        ok = False
    if classify_e2e_check("reintroduced_full_table_on_followup") != "full_table_repeat":
        print("FAIL full_table mapping")
        ok = False
    if "catalog_alias" not in allowed_proposal_layers("bank_slot_alias_miss"):
        print("FAIL alias layers")
        ok = False
    if is_auto_promote_eligible("warehouse_llm_zh"):
        print("FAIL warehouse must not auto-promote")
        ok = False
    if not warehouse_llm_zh_heuristic("### Step 1: 纵向趋势对账\n平均步数 14000"):
        print("FAIL warehouse zh heuristic")
        ok = False

    fixture = ROOT / "scripts" / "fixtures" / "loop_e2e_sample.jsonl"
    harvest_mod = _load_harvest_module()
    out: list[dict] = []
    n = harvest_mod.harvest_e2e_jsonl(fixture, out)
    if n < 2:
        print(f"FAIL harvest_e2e_jsonl expected >=2 signals, got {n}")
        ok = False
    signals = {row["signal"] for row in out}
    if "rlp_locale_leak" not in signals or "full_table_repeat" not in signals:
        print(f"FAIL harvest signals {signals}")
        ok = False

    reflection_mod = _load_reflection_module()
    rows = [json.loads(line) for line in fixture.read_text().splitlines() if line.strip()]
    critique = reflection_mod.harvest_signals_from_e2e(rows)
    if not critique:
        print("FAIL reflection critique empty")
        ok = False

    print("pha_loop_failure_taxonomy_selfcheck:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
