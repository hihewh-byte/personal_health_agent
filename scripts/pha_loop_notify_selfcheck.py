#!/usr/bin/env python3
"""Offline selfcheck for Loop A+C notify (dry-run only, no network / no gh)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "pha_loop_notify_proposal.py"
CURATED = ROOT / "scripts" / "fixtures" / "loop_alias_proposal_curated.json"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    e = os.environ.copy()
    e["PYTHONPATH"] = str(ROOT)
    e["PHA_LOOP_NOTIFY_APPLY"] = "0"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        env=e,
    )


def main() -> int:
    if not SCRIPT.is_file():
        print("FAIL missing", SCRIPT)
        return 1
    if not CURATED.is_file():
        print("FAIL missing curated fixture", CURATED)
        return 1

    # Non-empty proposal → dry-run both channels.
    r = _run(["--proposal", str(CURATED), "--channels", "both"])
    if r.returncode != 0:
        print("FAIL non-empty dry-run", r.returncode, r.stdout, r.stderr)
        return 1
    out = r.stdout or ""
    if "Loop notify (dry-run)" not in out:
        print("FAIL expected dry-run banner", out)
        return 1
    if "draft-pr" not in out:
        print("FAIL expected draft-pr channel", out)
        return 1
    if "SKIP notify: no accepted_catalog" in out:
        print("FAIL should notify curated", out)
        return 1

    # Empty proposal → skip (exit 0)
    with tempfile.TemporaryDirectory() as td:
        empty = Path(td) / "alias_proposal_empty.json"
        empty.write_text(
            json.dumps(
                {
                    "schema": "pha.loop_proposal/v2",
                    "accepted_catalog": [],
                    "patch_ops": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        r2 = _run(["--proposal", str(empty), "--channels", "both"])
        if r2.returncode != 0:
            print("FAIL empty should exit 0", r2.stderr)
            return 1
        if "SKIP notify" not in (r2.stdout or ""):
            print("FAIL expected SKIP for empty", r2.stdout)
            return 1

    # Webhook dry-run with URL present must not require network.
    r3 = _run(
        [
            "--proposal",
            str(CURATED),
            "--channels",
            "webhook",
            "--webhook-url",
            "https://example.invalid/hook",
            "--webhook-format",
            "feishu",
        ],
    )
    if r3.returncode != 0:
        print("FAIL webhook dry-run", r3.stdout, r3.stderr)
        return 1
    if "webhook" not in (r3.stdout or ""):
        print("FAIL webhook channel missing", r3.stdout)
        return 1

    print("pha_loop_notify_selfcheck: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
