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


def run_reflect(
    *,
    candidates: str,
    e2e_jsonl: str = "",
    out_dir: str = "",
    root: Path | None = None,
) -> int:
    root = root or detect_monorepo_root()
    default_candidates = root / "reports" / "loop" / "slow_round_candidates.jsonl"
    default_out = root / "reports" / "loop"
    cmd_args = [
        "--candidates",
        candidates or str(default_candidates),
        "--out-dir",
        out_dir or str(default_out),
    ]
    if e2e_jsonl:
        cmd_args.extend(["--e2e-jsonl", e2e_jsonl])
    return run_script("pha_reflection_critic.py", cmd_args, root=root)


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


def run_harvest_pipeline(*, root: Path | None = None) -> int:
    """Orchestrate Harvest → Reflect → CHB gap → Distill via portable pipeline.

    Stage bodies remain PHA scripts (reference plugin). Orchestration + ordering
    live in ``harness_loop.pipeline`` — never auto-merges.
    """
    from harness_loop.pipeline import default_out_layout, run_offline_pipeline

    root = root or detect_monorepo_root()
    layout = default_out_layout(root)
    candidates = os.environ.get("PHA_LOOP_CANDIDATES", str(layout["candidates"]))
    proposal_dir = os.environ.get("PHA_LOOP_PROPOSAL_DIR", str(layout["proposals"]))
    e2e = os.environ.get("PHA_E2E_JSONL", "")
    e2e_dir = os.environ.get("PHA_E2E_JSONL_DIR", "")
    dry_distill = os.environ.get("PHA_LOOP_DRY_DISTILL", "0") == "1"
    harness_path = os.environ.get(
        "PHA_HARNESS_REPORT_PATH", "/tmp/pha-harness-reports.jsonl"
    )
    manifest_dir = os.environ.get("PHA_E2E_REPORT_DIR", str(root / "reports" / "e2e"))

    def _harvest() -> int:
        args = [
            "--harness-path",
            harness_path,
            "--manifest-dir",
            manifest_dir,
            "--out",
            candidates,
        ]
        if e2e:
            args.extend(["--e2e-jsonl", e2e])
        elif e2e_dir:
            args.extend(["--e2e-jsonl-dir", e2e_dir])
        print("== stage harvest ==")
        return run_script("pha_telemetry_harvest.py", args, root=root)

    def _reflect() -> int:
        args = ["--candidates", candidates, "--out-dir", str(layout["out_dir"])]
        if e2e:
            args.extend(["--e2e-jsonl", e2e])
        print("== stage reflect (Ring R) ==")
        return run_script("pha_reflection_critic.py", args, root=root)

    def _chb_gap() -> int:
        args = ["--candidates", candidates]
        if e2e:
            args.extend(["--e2e-jsonl", e2e])
        print("== stage chb_gap (Loop B L2) ==")
        return run_script("pha_chb_gap_harvest.py", args, root=root)

    def _distill() -> int:
        args = ["--candidates", candidates, "--out-dir", proposal_dir]
        if dry_distill:
            args.append("--dry-run")
        print("== stage distill (Loop A) ==")
        return run_script("pha_loop_alias_distiller.py", args, root=root)

    result = run_offline_pipeline(
        [
            ("harvest", _harvest),
            ("reflect", _reflect),
            ("chb_gap", _chb_gap),
            ("distill", _distill),
        ]
    )
    print("== pipeline done ==")
    print(f" stages : {result.stages_run}")
    print(f" codes  : {result.exit_codes}")
    print(f" notes  : {result.notes}")
    print(f" candidates : {candidates}")
    print(f" proposals  : {proposal_dir}")
    failed = [c for c in result.exit_codes.values() if c != 0]
    return int(failed[0]) if failed else 0
