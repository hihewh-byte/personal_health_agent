#!/usr/bin/env python3
"""P2 selfcheck: harness profile / schema registry validation."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.harness_profile_registry import validate_harness_profile_registry  # noqa: E402
from pha.universal_catalog_manager import reload_catalog_manager  # noqa: E402


def main() -> int:
    reload_catalog_manager()
    result = validate_harness_profile_registry()
    if not result.ok:
        for err in result.errors:
            print(f"FAIL  {err}")
        print(f"\nFAIL {len(result.errors)} error(s)")
        return 1
    print("OK harness profile registry selfcheck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
