#!/usr/bin/env python3
"""Stage 4-β-2c — offline CHB stale compile loop (环 B 写侧飞轮).

Compares live T0 ledger hash vs on-disk ``brief_{hash}.json`` artifacts.
When stale, triggers ``compile_chronic_health_brief`` asynchronously (never in Turn).

Usage:
  PYTHONPATH=. python3 scripts/pha_chb_compile_all_users.py
  PYTHONPATH=. python3 scripts/pha_chb_compile_all_users.py --dry-run
  PYTHONPATH=. python3 scripts/pha_chb_compile_all_users.py --user-id default --json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.chb_compiler import (  # noqa: E402
    DEFAULT_REPORT_ROOT,
    chb_stale_status,
    list_chb_report_user_ids,
    recompile_chb_if_stale,
)


@dataclass
class UserCompileResult:
    user_id: str
    live_hash: str
    artifact_hash: str | None
    is_stale: bool
    recompiled: bool = False
    artifact_path: str | None = None
    artifact_count: int = 0
    notes: list[str] = field(default_factory=list)


def compile_all_users(
    *,
    user_ids: list[str] | None = None,
    report_root: Path | None = None,
    dry_run: bool = False,
) -> list[UserCompileResult]:
    root = report_root or DEFAULT_REPORT_ROOT
    ids = user_ids or list_chb_report_user_ids(report_root=root)
    results: list[UserCompileResult] = []

    for uid in ids:
        before = chb_stale_status(uid, report_root=root)
        status, path = recompile_chb_if_stale(uid, report_root=root, dry_run=dry_run)
        notes: list[str] = []
        if before["is_stale"] and dry_run:
            notes.append("dry-run: would recompile")
        elif path is not None:
            notes.append(f"wrote {path.name}")
        elif not before["is_stale"]:
            notes.append("fresh: artifact matches live T0")

        results.append(
            UserCompileResult(
                user_id=uid,
                live_hash=str(status.get("live_hash") or ""),
                artifact_hash=status.get("artifact_hash"),
                is_stale=bool(before["is_stale"]),
                recompiled=path is not None,
                artifact_path=str(path) if path else None,
                artifact_count=int(status.get("artifact_count") or 0),
                notes=notes,
            ),
        )
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Offline CHB stale compile loop (Stage 4-β-2c)",
    )
    ap.add_argument(
        "--user-id",
        action="append",
        dest="user_ids",
        help="Limit to specific user_id (repeatable; default: all under reports/chb/)",
    )
    ap.add_argument(
        "--report-root",
        type=Path,
        default=None,
        help=f"CHB artifact root (default: {DEFAULT_REPORT_ROOT})",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Report stale users without writing artifacts",
    )
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON report")
    args = ap.parse_args(argv)

    results = compile_all_users(
        user_ids=args.user_ids,
        report_root=args.report_root,
        dry_run=args.dry_run,
    )

    stale_count = sum(1 for r in results if r.is_stale)
    compiled_count = sum(1 for r in results if r.recompiled)

    if args.json:
        payload = {
            "dry_run": args.dry_run,
            "users": [asdict(r) for r in results],
            "stale_count": stale_count,
            "compiled_count": compiled_count,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("== PHA CHB offline compile loop (4-β-2c) ==")
        for r in results:
            flag = "STALE" if r.is_stale else "FRESH"
            action = "RECOMPILED" if r.recompiled else ("WOULD_COMPILE" if r.is_stale and args.dry_run else "SKIP")
            print(
                f"{r.user_id}: {flag} live={r.live_hash} "
                f"artifact={r.artifact_hash or '—'} "
                f"backlog={r.artifact_count} → {action}",
            )
            for note in r.notes:
                print(f"  · {note}")
        print(
            f"\nSummary: users={len(results)} stale={stale_count} "
            f"compiled={compiled_count} dry_run={args.dry_run}",
        )

    if stale_count > 0 and args.dry_run:
        return 0
    if stale_count > 0 and compiled_count == 0 and not args.dry_run:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
