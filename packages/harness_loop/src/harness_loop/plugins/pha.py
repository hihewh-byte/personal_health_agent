"""PHA reference-plugin helpers for Harness Loop (Alpha) CLI."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from harness_loop.paths import detect_monorepo_root, require_pha_scripts


def pha_alias_reject(metric: str, alias: str) -> tuple[bool, str]:
    """Delegate to PHA 1E gates (reference plugin)."""
    root = detect_monorepo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from pha.loop_keyword_conflicts import (  # noqa: WPS433
        AliasProposal,
        classify_alias_phrase,
        gate_1e_a_layer_denylist,
        gate_1e_c_narrow_pollution,
        gate_1e_d_ocr_ui_junk,
        validate_alias_proposals,
    )

    if not gate_1e_a_layer_denylist(alias).ok:
        return True, "1e_a"
    if not gate_1e_c_narrow_pollution(alias, metric_id=metric or None).ok:
        return True, "1e_c"
    if not gate_1e_d_ocr_ui_junk(alias).ok:
        return True, "1e_d"
    cl = classify_alias_phrase(alias, metric_id=metric, source_message=alias)
    if cl.tier == "rejected":
        return True, "classify"
    report = validate_alias_proposals(
        [AliasProposal(layer="catalog", target=metric, alias=alias, metric_id=metric)]
    )
    if not report.ok:
        return True, "validate"
    return False, "accepted"


def pha_default_catalog(root: Path | None = None) -> Path:
    root = root or detect_monorepo_root()
    return root / "rules" / "health_intent_catalog.json"


def pha_default_goldens(root: Path | None = None) -> list[Path]:
    root = root or detect_monorepo_root()
    g = root / "evals" / "goldens"
    return [
        g / "pha_smoke_v0.json",
        g / "pha_alias_fuzz_v0.json",
    ]


def run_script(script_rel: str, args: Sequence[str], *, root: Path | None = None) -> int:
    root = root or detect_monorepo_root()
    scripts = require_pha_scripts(root)
    script = scripts / script_rel
    if not script.is_file():
        raise FileNotFoundError(script)
    env = {**os.environ, "PYTHONPATH": str(root)}
    proc = subprocess.run(
        [sys.executable, str(script), *list(args)],
        cwd=str(root),
        env=env,
        check=False,
    )
    return int(proc.returncode)


def run_shell(script_rel: str, *, root: Path | None = None) -> int:
    root = root or detect_monorepo_root()
    script = root / script_rel
    if not script.is_file():
        raise FileNotFoundError(script)
    env = {**os.environ, "PYTHONPATH": str(root)}
    proc = subprocess.run(
        ["bash", str(script)],
        cwd=str(root),
        env=env,
        check=False,
    )
    return int(proc.returncode)
