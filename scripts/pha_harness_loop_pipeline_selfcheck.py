#!/usr/bin/env python3
"""Selfcheck: portable harness_loop harvest/pipeline/static promote (no PHA domain)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    try:
        from harness_loop.harvest import harvest_file_to_path
        from harness_loop.pipeline import run_offline_pipeline
        from harness_loop.proposals import static_veto, write_static_promote_verdict
    except ImportError as exc:
        print(f"FAIL import ({exc}); pip install -e packages/harness_loop")
        return 1

    fixture = ROOT / "scripts" / "fixtures" / "loop_e2e_sample.jsonl"
    curated = ROOT / "scripts" / "fixtures" / "loop_alias_proposal_curated.json"
    if not fixture.is_file() or not curated.is_file():
        print("FAIL missing fixtures")
        return 1

    with tempfile.TemporaryDirectory(prefix="loop-pipeline-") as tmp:
        out = Path(tmp) / "c.jsonl"
        path, n_sig, n_rows = harvest_file_to_path(fixture, out)
        if n_sig < 2 or n_rows < 2:
            print(f"FAIL harvest signals={n_sig} rows={n_rows}")
            return 1
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        row0 = json.loads(lines[0])
        for key in ("message", "signal", "source", "harvested_at"):
            if key not in row0:
                print(f"FAIL candidate missing {key}")
                return 1

        seen: list[str] = []

        def stage_a() -> int:
            seen.append("a")
            return 0

        def stage_b() -> int:
            seen.append("b")
            return 0

        result = run_offline_pipeline([("a", stage_a), ("b", stage_b)])
        if result.stages_run != ["a", "b"] or seen != ["a", "b"]:
            print("FAIL pipeline order", result.stages_run, seen)
            return 1

        doc = json.loads(curated.read_text(encoding="utf-8"))
        veto = static_veto(doc)
        if veto:
            print("FAIL curated should pass static_veto", veto)
            return 1
        vpath, verdict = write_static_promote_verdict(curated, out_dir=tmp)
        if not verdict.get("passed") or not vpath.is_file():
            print("FAIL static promote verdict", verdict)
            return 1

        bad = {
            "schema": "pha.loop_proposal/v2",
            "generated_at": "t",
            "stage": "t",
            "source": "t",
            "code_review_items": [{"x": 1}],
            "patch_ops": [{"op": "add", "path": "/routing/forbidden", "value": 1}],
        }
        if "code_review_items_present" not in static_veto(bad):
            print("FAIL expected code_review veto")
            return 1
        if not any(v.startswith("patch_outside") for v in static_veto(bad)):
            print("FAIL expected patch path veto")
            return 1

    print("pha_harness_loop_pipeline_selfcheck: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
