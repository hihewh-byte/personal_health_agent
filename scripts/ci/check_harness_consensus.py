#!/usr/bin/env python3
"""Fail PRs that touch harness-critical files without harness changelog update."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HARNESS_CHANGELOG = "docs/harness-change-log.md"

HARNESS_PATH_PREFIXES = (
    "pha/chat_service.py",
    "pha/chat_turn_",
    "pha/harness_",
    "pha/intent_",
    "pha/schema_",
    "pha/numerics_manifest.py",
    "pha/catalog_",
    "pha/shadow_routing.py",
)


def run_git(args: list[str], *, suppress_stderr: bool = False) -> str:
    out = subprocess.check_output(
        ["git", *args],
        cwd=REPO,
        stderr=subprocess.DEVNULL if suppress_stderr else None,
    )
    return out.decode("utf-8", errors="replace")


def changed_files() -> list[str]:
    try:
        base = run_git(["merge-base", "HEAD", "origin/main"], suppress_stderr=True).strip()
        if not base:
            raise RuntimeError("empty merge-base")
        diff = run_git(["diff", "--name-only", f"{base}...HEAD"])
    except Exception:
        diff = run_git(["diff", "--name-only", "HEAD~1..HEAD"])
    return [x.strip() for x in diff.splitlines() if x.strip()]


def is_harness_related(path: str) -> bool:
    for p in HARNESS_PATH_PREFIXES:
        if p.endswith("_"):
            if path.startswith(p):
                return True
        elif path == p:
            return True
    return False


def run_registry_validation() -> int:
    """P2: deterministic profile/registry validation gate."""
    sys.path.insert(0, str(REPO))
    from pha.harness_profile_registry import validate_harness_profile_registry

    result = validate_harness_profile_registry()
    if result.errors:
        print("\nERROR: Harness profile registry validation failed:", file=sys.stderr)
        for err in sorted(set(result.errors)):
            print(f"  - {err}", file=sys.stderr)
        return 3
    print("harness-consensus: registry validation PASS")
    return 0


def main() -> int:
    files = changed_files()
    touched = [f for f in files if is_harness_related(f)]
    if not touched:
        print("harness-consensus: no harness-critical files changed")
        return 0

    print("harness-consensus: harness-critical files changed:")
    for f in touched:
        print(f"  - {f}")

    if HARNESS_CHANGELOG not in files:
        print(
            "\nERROR: Harness-critical changes require changelog update.\n"
            f"Please update `{HARNESS_CHANGELOG}` in the same PR.",
            file=sys.stderr,
        )
        return 2

    print(f"harness-consensus: `{HARNESS_CHANGELOG}` updated")
    return run_registry_validation()


if __name__ == "__main__":
    raise SystemExit(main())
