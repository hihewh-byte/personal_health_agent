#!/usr/bin/env python3
"""Selfcheck: Official Loop Suite α — import, CLI, PHA goldens, toy attach."""

from __future__ import annotations

import os
import subprocess
import sys
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
