"""Resolve monorepo / plugin roots for CLI delegation."""

from __future__ import annotations

import os
from pathlib import Path


def env_repo_root() -> Path | None:
    for key in ("HARNESS_LOOP_REPO_ROOT", "PHA_REPO_ROOT"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return Path(raw).resolve()
    return None


def detect_monorepo_root(start: Path | None = None) -> Path:
    """Find PHA-style monorepo (scripts/ + evals/goldens or packages/harness_loop)."""
    env = env_repo_root()
    if env:
        return env
    here = (start or Path.cwd()).resolve()
    candidates = [here, *list(here.parents)[:8]]
    # Also walk from this package file when installed editable.
    pkg = Path(__file__).resolve()
    candidates.extend(list(pkg.parents)[:8])
    for p in candidates:
        if (p / "scripts" / "pha_loop_run_from_e2e.sh").is_file():
            return p
        if (p / "packages" / "harness_loop" / "pyproject.toml").is_file() and (
            p / "evals" / "goldens"
        ).is_dir():
            return p
    return here


def require_pha_scripts(root: Path) -> Path:
    scripts = root / "scripts"
    if not (scripts / "pha_loop_promote_candidate.py").is_file():
        raise FileNotFoundError(
            f"PHA reference scripts not found under {root}. "
            "Set HARNESS_LOOP_REPO_ROOT to the personal_health_agent checkout."
        )
    return scripts
