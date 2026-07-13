#!/usr/bin/env python3
"""Fail PRs that touch startup-critical files without consensus log updates."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STARTUP_CHANGELOG = "docs/startup-change-log.md"

STARTUP_GLOBS = (
    "pha/main.py",
    "pha/store.py",
    "pha/data_integrity.py",
    "scripts/pha_restart_accept.sh",
    "scripts/macos/PHA-Serve.command",
    ".github/workflows/ci.yml",
    ".env.example",
)


def run_git(args: list[str], *, suppress_stderr: bool = False) -> str:
    out = subprocess.check_output(
        ["git", *args],
        cwd=REPO,
        stderr=subprocess.DEVNULL if suppress_stderr else None,
    )
    return out.decode("utf-8", errors="replace")


def changed_files() -> list[str]:
    """Return files changed vs origin/main (or last commit / empty on shallow fail)."""
    try:
        base = run_git(["merge-base", "HEAD", "origin/main"], suppress_stderr=True).strip()
        if not base:
            raise RuntimeError("empty merge-base")
        diff = run_git(["diff", "--name-only", f"{base}...HEAD"])
        return [x.strip() for x in diff.splitlines() if x.strip()]
    except Exception:
        pass
    # GitHub Actions PR checkout may be depth=1 (no HEAD~1 / no origin/main).
    base_sha = (os.environ.get("GITHUB_BASE_SHA") or "").strip()
    if base_sha:
        try:
            diff = run_git(["diff", "--name-only", f"{base_sha}...HEAD"])
            return [x.strip() for x in diff.splitlines() if x.strip()]
        except Exception:
            pass
    try:
        diff = run_git(["diff", "--name-only", "HEAD~1..HEAD"])
        return [x.strip() for x in diff.splitlines() if x.strip()]
    except Exception as exc:
        print(
            f"startup-consensus: WARN cannot determine changed files ({exc}); "
            "assuming none (prefer checkout fetch-depth: 0 in CI)",
            file=sys.stderr,
        )
        return []


def is_startup_related(path: str) -> bool:
    return any(path == p or path.startswith(p.rstrip("/")) for p in STARTUP_GLOBS)


def main() -> int:
    files = changed_files()
    touched = [f for f in files if is_startup_related(f)]
    if not touched:
        print("startup-consensus: no startup-critical files changed")
        return 0

    print("startup-consensus: startup-critical files changed:")
    for f in touched:
        print(f"  - {f}")

    if STARTUP_CHANGELOG not in files:
        print(
            "\nERROR: Startup-critical changes require changelog update.\n"
            f"Please update `{STARTUP_CHANGELOG}` in the same PR.\n"
            "This enforces cross-agent shared context for startup/availability changes.",
            file=sys.stderr,
        )
        return 2

    print(f"startup-consensus: `{STARTUP_CHANGELOG}` updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
