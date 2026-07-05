#!/usr/bin/env python3
"""P2 — Generate or verify harness profile registry manifest."""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha.harness_profile_registry import (  # noqa: E402
    DEFAULT_REGISTRY_MANIFEST_PATH,
    validate_generated_manifest,
    write_profile_registry_manifest,
)
from pha.universal_catalog_manager import reload_catalog_manager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write rules/harness_profile_registry.generated.json from live introspection",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if generated manifest drifts (default when neither flag set)",
    )
    parser.add_argument(
        "--path",
        default=str(DEFAULT_REGISTRY_MANIFEST_PATH),
        help="Manifest path (default: rules/harness_profile_registry.generated.json)",
    )
    args = parser.parse_args()
    reload_catalog_manager()

    path = DEFAULT_REGISTRY_MANIFEST_PATH if args.path == str(DEFAULT_REGISTRY_MANIFEST_PATH) else args.path
    from pathlib import Path

    target = Path(path)

    if args.write:
        written = write_profile_registry_manifest(target)
        print(f"Wrote {written}")
        return 0

    do_check = args.check or not args.write
    if do_check:
        result = validate_generated_manifest(target)
        if not result.ok:
            for err in result.errors:
                print(f"FAIL  {err}")
            print("\nHint: python scripts/pha_harness_profile_registry_generate.py --write")
            return 1
        print(f"OK manifest matches live introspection ({target})")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
