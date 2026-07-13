#!/usr/bin/env python3
"""Selfcheck: harness.eval_set/v1 goldens validate offline."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Keep stdout/stderr UTF-8 even under LANG=C (CI).
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.harness_eval_set import goldens_dir, repo_root, validate_file  # noqa: E402


def main() -> int:
    golden = goldens_dir() / "pha_smoke_v0.json"
    # Fallback: cwd-relative (CI runs from repo root)
    if not golden.is_file():
        alt = Path.cwd() / "evals" / "goldens" / "pha_smoke_v0.json"
        if alt.is_file():
            golden = alt
    if not golden.is_file():
        print(f"FAIL missing golden {golden} (repo_root={repo_root()})")
        return 1
    try:
        errors = validate_file(golden, offline=True)
    except Exception as exc:  # noqa: BLE001
        print(f"pha_eval_set_selfcheck: FAIL exception: {exc!r}")
        return 1
    if errors:
        print("pha_eval_set_selfcheck: FAIL")
        for e in errors:
            # ascii-safe for ancient pipes; content still readable via \u escapes
            print("  - " + e.encode("unicode_escape").decode("ascii"))
        return 1
    print(f"pha_eval_set_selfcheck: PASS ({golden.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())