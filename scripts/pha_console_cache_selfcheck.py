#!/usr/bin/env python3
"""Ensure console HTML injects app.js cache bust from build_marker."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.build_marker import PHA_SERVER_BUILD, asset_cache_version
from pha.console import CONSOLE_PAGE_HTML

PLACEHOLDER = "__PHA_ASSET_VERSION__"


def main() -> int:
    failed = 0
    ver = asset_cache_version()
    needle = f"app.js?v={ver}"

    if PLACEHOLDER in CONSOLE_PAGE_HTML:
        print("FAIL: placeholder leaked into served HTML")
        failed += 1
    if needle not in CONSOLE_PAGE_HTML:
        print("FAIL: missing", needle)
        failed += 1
    if ver not in PHA_SERVER_BUILD:
        print("FAIL: asset version not derived from build", ver, PHA_SERVER_BUILD)
        failed += 1

    if failed:
        return 1
    print("OK console cache bust:", needle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
