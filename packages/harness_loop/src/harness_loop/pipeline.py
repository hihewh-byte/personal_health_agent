"""Offline Loop pipeline orchestration — ordered stages, never auto-merge."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

StageFn = Callable[[], int]


@dataclass
class PipelineResult:
    stages_run: list[str] = field(default_factory=list)
    exit_codes: dict[str, int] = field(default_factory=dict)
    notes: str = "proposal-only; never auto-merges"


def run_offline_pipeline(
    stages: list[tuple[str, StageFn]],
    *,
    stop_on_error: bool = True,
) -> PipelineResult:
    """Run named offline stages in order.

    Stages must not apply catalog patches or merge to main. Callers enforce that
    contract; this helper only sequences and records exit codes.
    """
    result = PipelineResult()
    for name, fn in stages:
        code = int(fn())
        result.stages_run.append(name)
        result.exit_codes[name] = code
        if stop_on_error and code != 0:
            result.notes = f"stopped after stage {name!r} exit={code}; no auto-merge"
            break
    return result


def default_out_layout(repo_root: Path) -> dict[str, Path]:
    loop = repo_root / "reports" / "loop"
    return {
        "candidates": loop / "slow_round_candidates.jsonl",
        "out_dir": loop,
        "proposals": loop / "proposals",
        "verdicts": loop / "verdicts",
    }


__all__ = ["PipelineResult", "run_offline_pipeline", "default_out_layout"]
