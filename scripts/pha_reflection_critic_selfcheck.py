#!/usr/bin/env python3
"""Selfcheck: Ring R Reflection Critic end-to-end (fixture → proposal JSON)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE_CANDIDATES = ROOT / "scripts" / "fixtures" / "loop_candidates_sample.jsonl"
FIXTURE_E2E = ROOT / "scripts" / "fixtures" / "loop_e2e_sample.jsonl"


def _run(argv: list[str]) -> int:
    env = {**dict(__import__("os").environ), "PYTHONPATH": str(ROOT)}
    proc = subprocess.run(argv, cwd=str(ROOT), env=env, check=False)
    return int(proc.returncode)


def main() -> int:
    if not FIXTURE_CANDIDATES.is_file() or not FIXTURE_E2E.is_file():
        print("FAIL missing reflection fixtures")
        return 1

    with tempfile.TemporaryDirectory(prefix="pha-reflect-") as tmp:
        out_dir = Path(tmp) / "loop"
        rc = _run(
            [
                sys.executable,
                str(ROOT / "scripts" / "pha_reflection_critic.py"),
                "--candidates",
                str(FIXTURE_CANDIDATES),
                "--e2e-jsonl",
                str(FIXTURE_E2E),
                "--out-dir",
                str(out_dir),
            ]
        )
        if rc != 0:
            print("FAIL pha_reflection_critic.py exit", rc)
            return 1

        proposals = list((out_dir / "proposals").glob("reflection_*.json"))
        mds = list(out_dir.glob("reflection_*.md"))
        if not proposals or not mds:
            print("FAIL reflection outputs missing")
            return 1

        doc = json.loads(proposals[0].read_text(encoding="utf-8"))
        if doc.get("schema") != "pha.loop_proposal/v2":
            print("FAIL proposal schema", doc.get("schema"))
            return 1
        if doc.get("source") != "reflection_critic":
            print("FAIL proposal source", doc.get("source"))
            return 1
        if int(doc.get("critique_count") or 0) < 2:
            print("FAIL expected >=2 critique rows, got", doc.get("critique_count"))
            return 1
        taxonomy = doc.get("failure_taxonomy") or {}
        if "rlp_locale_leak" not in taxonomy and "full_table_repeat" not in taxonomy:
            print("FAIL expected taxonomy signals in", taxonomy)
            return 1

        try:
            from harness_loop.proposals import validate_loop_proposal
        except ImportError:
            print("SKIP harness_loop.proposals (package not installed)")
            validate_loop_proposal = None  # type: ignore[assignment]

        if validate_loop_proposal is not None:
            errors = validate_loop_proposal(doc)
            if errors:
                print("FAIL portable proposal validation:", errors)
                return 1

        curated = ROOT / "scripts" / "fixtures" / "loop_alias_proposal_curated.json"
        if validate_loop_proposal is not None and curated.is_file():
            curated_doc = json.loads(curated.read_text(encoding="utf-8"))
            if validate_loop_proposal(curated_doc):
                print("FAIL curated proposal fixture invalid")
                return 1

    print("pha_reflection_critic_selfcheck: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
