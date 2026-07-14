#!/usr/bin/env python3
"""Selfcheck: Harness Loop (Alpha) — import, CLI, PHA goldens, toy attach."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PHA_HEALTH_INTENT_CATALOG", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run(argv: list[str]) -> int:
    env = {**os.environ, "PYTHONPATH": str(ROOT), "HARNESS_LOOP_REPO_ROOT": str(ROOT)}
    # Prefer installed console script; fall back to module.
    candidates = [
        ["harness-loop", *argv],
        [sys.executable, "-m", "harness_loop.cli", *argv],
    ]
    last = 1
    for cmd in candidates:
        try:
            proc = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
            last = int(proc.returncode)
            if last == 0 or cmd[0] != "harness-loop":
                return last
        except FileNotFoundError:
            continue
    return last


def main() -> int:
    try:
        import harness_loop
        from harness_loop import __version__
    except ImportError as exc:
        print(f"FAIL: harness_loop not importable ({exc})")
        print("  hint: pip install -e packages/harness_loop")
        return 1

    if not __version__.startswith("0.1.0"):
        print(f"FAIL unexpected version {__version__}")
        return 1
    print(f"OK import harness_loop {__version__}")

    curated = ROOT / "scripts" / "fixtures" / "loop_alias_proposal_curated.json"
    if _run(["proposal-check", str(curated)]) != 0:
        print("FAIL harness-loop proposal-check curated fixture")
        return 1
    print("OK proposal-check curated fixture")

    fixture_e2e = ROOT / "scripts" / "fixtures" / "loop_e2e_sample.jsonl"
    fixture_candidates = ROOT / "scripts" / "fixtures" / "loop_candidates_sample.jsonl"
    with tempfile.TemporaryDirectory(prefix="harness-loop-reflect-") as tmp:
        if _run(
            [
                "reflect",
                "--plugin",
                "pha",
                "--candidates",
                str(fixture_candidates),
                "--e2e-jsonl",
                str(fixture_e2e),
                "--out-dir",
                tmp,
            ]
        ) != 0:
            print("FAIL harness-loop reflect --plugin pha")
            return 1
    print("OK reflect --plugin pha")

    with tempfile.TemporaryDirectory(prefix="harness-loop-harvest-") as tmp:
        out_c = str(Path(tmp) / "candidates.jsonl")
        if _run(["harvest", "--e2e-jsonl", str(fixture_e2e), "--out", out_c]) != 0:
            print("FAIL portable harvest --e2e-jsonl")
            return 1
        if not Path(out_c).is_file() or Path(out_c).stat().st_size < 10:
            print("FAIL portable harvest produced empty candidates")
            return 1
        verdict_dir = str(Path(tmp) / "verdicts")
        if (
            _run(
                [
                    "promote",
                    "--static-only",
                    "--proposal",
                    str(curated),
                    "--out-dir",
                    verdict_dir,
                ]
            )
            != 0
        ):
            print("FAIL portable promote --static-only on curated proposal")
            return 1
    print("OK portable harvest + static promote")

    if _run(["version"]) != 0:
        print("FAIL harness-loop version")
        return 1
    print("OK harness-loop version")

    if _run(["eval-check", "--plugin", "pha"]) != 0:
        print("FAIL harness-loop eval-check --plugin pha")
        return 1
    print("OK eval-check --plugin pha")

    toy_g = ROOT / "examples" / "loop_reference_toy" / "evals" / "toy_smoke_v0.json"
    toy_c = ROOT / "examples" / "loop_reference_toy" / "catalog.json"
    if _run(["eval-check", "--golden", str(toy_g), "--catalog", str(toy_c)]) != 0:
        print("FAIL toy eval-check")
        return 1
    print("OK toy attach eval-check")

    # Adopt must refuse without confirm YES.
    rc = _run(["adopt", "--plugin", "pha", "--proposal", "/tmp/does-not-matter.json"])
    if rc == 0:
        print("FAIL adopt must refuse without --confirm YES")
        return 1
    print("OK adopt gate refuses without confirm")

    print("pha_harness_loop_suite_selfcheck: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
