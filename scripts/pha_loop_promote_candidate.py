#!/usr/bin/env python3
"""R2 — proposal promote dry-run/veto.

Reads a ``pha.loop_proposal/v2`` artifact and runs deterministic gates. This
script never applies patches or merges. It writes ``promote_verdict_*.json`` so a
human PR can decide whether to adopt the proposal.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 900) -> dict[str, Any]:
    started = datetime.now(timezone.utc).isoformat()
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env={**os.environ, **(env or {}), "PYTHONPATH": "."},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    return {
        "cmd": cmd,
        "started_at": started,
        "exit_code": proc.returncode,
        "passed": proc.returncode == 0,
        "output_tail": proc.stdout[-4000:],
    }


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _proposal_summary(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": doc.get("schema"),
        "source": doc.get("source"),
        "stage": doc.get("stage"),
        "counts": doc.get("counts") or {},
        "accepted_catalog": len(doc.get("accepted_catalog") or []),
        "accepted_schema": len(doc.get("accepted_schema") or []),
        "slot_candidates": len(doc.get("slot_candidates") or []),
        "code_review_items": len(doc.get("code_review_items") or []),
        "patch_ops": len(doc.get("patch_ops") or []),
        "suggested_regression": doc.get("suggested_regression") or [],
    }


def _static_veto(doc: dict[str, Any]) -> list[str]:
    veto: list[str] = []
    if doc.get("schema") != "pha.loop_proposal/v2":
        veto.append("schema_not_pha.loop_proposal/v2")
    if doc.get("code_review_items"):
        veto.append("code_review_items_present")
    for op in doc.get("patch_ops") or []:
        path = str(op.get("path") or "")
        if not path.startswith("/metric_aliases/"):
            veto.append(f"patch_outside_metric_aliases:{path}")
    for item in doc.get("slot_candidates") or []:
        if (item.get("layer") or "") == "catalog":
            veto.append("tier_c_slot_promoted_to_catalog")
    return sorted(set(veto))


def main() -> int:
    ap = argparse.ArgumentParser(description="Loop proposal promote dry-run/veto")
    ap.add_argument("--proposal", required=True, help="pha.loop_proposal/v2 JSON")
    ap.add_argument(
        "--out-dir",
        default=str(ROOT / "reports" / "loop" / "verdicts"),
    )
    ap.add_argument(
        "--en-sessions",
        default=os.environ.get("PHA_LOOP_EN_SESSIONS", ""),
        help="Optional EN stress sessions (comma-separated); default uses proposal.suggested_regression",
    )
    ap.add_argument("--skip-en", action="store_true")
    ap.add_argument("--full-veto", action="store_true", default=os.environ.get("PHA_LOOP_FULL_VETO") == "1")
    args = ap.parse_args()

    proposal_path = Path(args.proposal)
    doc = _load(proposal_path)
    static_veto = _static_veto(doc)
    checks: list[dict[str, Any]] = []

    py = sys.executable
    checks.append(_run([py, "scripts/pha_loop_keyword_conflict_selfcheck.py"], timeout=120))
    checks.append(_run([py, "scripts/pha_loop_failure_taxonomy_selfcheck.py"], timeout=120))
    checks.append(_run([py, "scripts/pha_health_intent_catalog_selfcheck.py"], timeout=120))

    en_sessions = args.en_sessions.strip()
    if not en_sessions:
        suggested = doc.get("suggested_regression") or []
        en_sessions = ",".join(str(s) for s in suggested if str(s).startswith("EN"))
    if en_sessions and not args.skip_en:
        checks.append(
            _run(
                [py, "scripts/pha_e2e_en_stress_50x.py"],
                env={
                    "PHA_E2E_SESSIONS": en_sessions,
                    "PHA_E2E_REPORT_DIR": "/tmp/pha-loop-promote-en",
                },
                timeout=3600,
            ),
        )

    if args.full_veto:
        checks.append(_run(["bash", "scripts/nightly_harness_regression.sh"], timeout=7200))

    passed_checks = all(c.get("passed") for c in checks)
    verdict = {
        "schema": "pha.loop_promote_verdict/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "proposal_path": str(proposal_path),
        "proposal": _proposal_summary(doc),
        "static_veto": static_veto,
        "checks": checks,
        "passed": passed_checks and not static_veto,
        "notes": (
            "Dry-run only. A passing verdict permits human PR review; it does not "
            "apply patches, write T0, or merge main."
        ),
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"promote_verdict_{ts}.json"
    out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("== loop promote candidate ==")
    print(f" proposal : {proposal_path}")
    print(f" static_veto : {static_veto or 'none'}")
    print(f" checks : {[(c['cmd'][-1], c['exit_code']) for c in checks]}")
    print(f" passed : {verdict['passed']}")
    print(f" verdict : {out_path}")
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
