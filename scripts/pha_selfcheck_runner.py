#!/usr/bin/env python3
"""P1-4: run all PHA offline selfchecks from ``selfcheck_manifest.json``."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path(__file__).resolve().parent / "selfcheck_manifest.json"


@dataclass
class CheckSpec:
    id: str
    script: str
    tags: List[str]


@dataclass
class CheckResult:
    spec: CheckSpec
    status: str
    seconds: float
    exit_code: Optional[int] = None

    @property
    def ok(self) -> bool:
        return self.status == "pass"


def _resolve_python(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    venv_py = ROOT / ".venv" / "bin" / "python"
    if venv_py.is_file():
        return str(venv_py)
    return sys.executable


def load_manifest(path: Path = DEFAULT_MANIFEST) -> List[CheckSpec]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    checks: List[CheckSpec] = []
    for item in raw.get("checks") or []:
        checks.append(
            CheckSpec(
                id=str(item["id"]),
                script=str(item["script"]),
                tags=[str(t) for t in (item.get("tags") or [])],
            ),
        )
    return checks


def filter_checks(
    checks: Sequence[CheckSpec],
    *,
    only: Optional[Sequence[str]] = None,
    tag: Optional[str] = None,
) -> List[CheckSpec]:
    out = list(checks)
    if only:
        wanted = {x.strip() for x in only if x.strip()}
        out = [c for c in out if c.id in wanted]
    if tag:
        out = [c for c in out if tag in c.tags]
    return out


def run_check(
    spec: CheckSpec,
    *,
    python: str,
    verbose: bool = True,
) -> CheckResult:
    script_path = ROOT / spec.script
    if not script_path.is_file():
        if verbose:
            print(f"SKIP  missing {spec.script}")
        return CheckResult(spec=spec, status="missing", seconds=0.0)

    if verbose:
        print(f"--- {spec.script}")
    t0 = time.perf_counter()
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    proc = subprocess.run(
        [python, str(script_path)],
        cwd=str(ROOT),
        env=env,
    )
    elapsed = time.perf_counter() - t0
    status = "pass" if proc.returncode == 0 else "fail"
    if verbose and status == "fail":
        print(f"FAIL  {spec.id} exit={proc.returncode}")
    return CheckResult(
        spec=spec,
        status=status,
        seconds=elapsed,
        exit_code=proc.returncode,
    )


def print_summary(results: Sequence[CheckResult]) -> None:
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    missing = sum(1 for r in results if r.status == "missing")
    total = len(results)
    print()
    print(f"==> PHA selfcheck summary: {passed}/{total} passed", end="")
    if failed:
        print(f", {failed} failed", end="")
    if missing:
        print(f", {missing} missing", end="")
    print()
    print(f"{'ID':<32} {'STATUS':<8} {'TIME':>7}")
    print("-" * 50)
    for r in results:
        print(f"{r.spec.id:<32} {r.status.upper():<8} {r.seconds:>6.1f}s")
    if failed:
        print("==> SELF CHECK FAILED")
    elif missing:
        print("==> SELF CHECK INCOMPLETE (missing scripts)")
    else:
        print("==> ALL SELF CHECKS PASSED")


def results_to_json(results: Sequence[CheckResult]) -> Dict[str, Any]:
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r.ok),
        "failed": sum(1 for r in results if r.status == "fail"),
        "missing": sum(1 for r in results if r.status == "missing"),
        "checks": [
            {
                "id": r.spec.id,
                "script": r.spec.script,
                "status": r.status,
                "seconds": round(r.seconds, 3),
                "exit_code": r.exit_code,
            }
            for r in results
        ],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run PHA offline selfcheck suite")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to selfcheck_manifest.json",
    )
    parser.add_argument("--python", default=None, help="Python executable")
    parser.add_argument("--only", default="", help="Comma-separated check ids")
    parser.add_argument("--tag", default="", help="Run checks with this tag only")
    parser.add_argument("--list", action="store_true", help="List registered checks and exit")
    parser.add_argument("--json", action="store_true", help="Print JSON summary to stdout")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress per-script headers")
    args = parser.parse_args(list(argv) if argv is not None else None)

    checks = load_manifest(args.manifest)
    if args.list:
        for c in checks:
            tags = f" [{','.join(c.tags)}]" if c.tags else ""
            print(f"{c.id:<32} {c.script}{tags}")
        return 0

    only = [x.strip() for x in args.only.split(",") if x.strip()] or None
    tag = args.tag.strip() or None
    checks = filter_checks(checks, only=only, tag=tag)
    if not checks:
        print("No checks selected", file=sys.stderr)
        return 2

    python = _resolve_python(args.python)
    print(f"==> PHA selfcheck suite ({len(checks)} checks, manifest v1)")
    results = [
        run_check(spec, python=python, verbose=not args.quiet) for spec in checks
    ]

    if args.json:
        print(json.dumps(results_to_json(results), ensure_ascii=False, indent=2))
    else:
        print_summary(results)

    if any(r.status == "fail" for r in results):
        return 1
    if any(r.status == "missing" for r in results):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
