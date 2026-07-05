#!/usr/bin/env python3
"""Selfcheck: e2e question bank structure + seed resolution."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.e2e_question_bank import BANK_PATH, load_bank, resolve_bank_sessions


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_bank_file() -> None:
    bank = load_bank()
    _assert(bank.get("bank_version") == "1.0", "version")
    _assert(float(bank.get("colloquial_ratio_target", 0)) == 0.7, "ratio")
    sets = bank.get("sets") or []
    _assert(len(sets) == 20, f"set count {len(sets)}")
    pools = bank.get("variant_pools") or {}
    _assert(len(pools) >= 40, f"pools {len(pools)}")
    for spec in sets:
        turns = spec.get("turns") or []
        _assert(len(turns) >= 8, f"{spec.get('set_id')} turns={len(turns)}")
        _assert(len(turns) <= 10, f"{spec.get('set_id')} turns={len(turns)}")
        for t in turns:
            slot = t.get("slot")
            _assert(slot in pools, f"missing pool {slot}")
    print("PASS bank structure 20 sets × 8–10 turns")


def test_seed_deterministic() -> None:
    a, ma = resolve_bank_sessions(seed=42)
    b, mb = resolve_bank_sessions(seed=42)
    _assert(len(a) == 20 and len(b) == 20, "count")
    _assert(a[0].turns[0].message == b[0].turns[0].message, "deterministic")
    _assert(ma["seed"] == 42, "seed in manifest")
    print("PASS seed determinism")


def test_seed_varies() -> None:
    a, _ = resolve_bank_sessions(seed=1)
    b, _ = resolve_bank_sessions(seed=2)
    # at least one message should differ across seeds
    msgs_a = {t.message for s in a for t in s.turns}
    msgs_b = {t.message for s in b for t in s.turns}
    _assert(msgs_a != msgs_b, "seeds should produce different text")
    print("PASS seed exploration variance")


def test_colloquial_mix() -> None:
    resolved, _ = resolve_bank_sessions(seed=99)
    styles = [t.style for s in resolved for t in s.turns]
    col = sum(1 for s in styles if s == "colloquial")
    _assert(col > 0, "need some colloquial")
    print(f"PASS colloquial sample seed=99 colloquial_turns={col}/{len(styles)}")


def main() -> int:
    _assert(BANK_PATH.is_file(), f"missing {BANK_PATH}")
    test_bank_file()
    test_seed_deterministic()
    test_seed_varies()
    test_colloquial_mix()
    print("pha_e2e_question_bank_selfcheck: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
