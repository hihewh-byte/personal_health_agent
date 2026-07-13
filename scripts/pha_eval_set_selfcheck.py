#!/usr/bin/env python3
"""Selfcheck: harness.eval_set/v1 goldens validate offline."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.harness_eval_set import DEFAULT_GOLDENS, validate_file  # noqa: E402


def main() -> int:
    golden = DEFAULT_GOLDENS / "pha_smoke_v0.json"
    if not golden.is_file():
        print(f"FAIL missing golden {golden}")
        return 1
    errors = validate_file(golden, offline=True)
    if errors:
        print("pha_eval_set_selfcheck: FAIL")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"pha_eval_set_selfcheck: PASS ({golden.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
