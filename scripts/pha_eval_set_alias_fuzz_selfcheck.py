#!/usr/bin/env python3
"""Selfcheck: pha.alias_fuzz.v0 offline eval_set + 1E-d OCR junk gate."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PHA_HEALTH_INTENT_CATALOG", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.harness_eval_set import goldens_dir, repo_root, validate_file  # noqa: E402
from pha.loop_keyword_conflicts import (  # noqa: E402
    AliasProposal,
    classify_alias_phrase,
    gate_1e_d_ocr_ui_junk,
    validate_alias_proposals,
)


def main() -> int:
    golden = goldens_dir() / "pha_alias_fuzz_v0.json"
    if not golden.is_file():
        alt = Path.cwd() / "evals" / "goldens" / "pha_alias_fuzz_v0.json"
        if alt.is_file():
            golden = alt
    if not golden.is_file():
        print(f"FAIL missing golden {golden} (repo_root={repo_root()})")
        return 1

    # Direct gate smoke (faster failure mode than full JSON).
    if gate_1e_d_ocr_ui_junk("Query").ok:
        print("FAIL gate_1e_d must reject Query")
        return 1
    if classify_alias_phrase("Query", metric_id="hrv", source_message="Query").tier != "rejected":
        print("FAIL classify must reject Query→hrv")
        return 1
    if validate_alias_proposals(
        [AliasProposal(layer="catalog", target="hrv", alias="Query", metric_id="hrv")]
    ).ok:
        print("FAIL validate_alias_proposals must reject Query→hrv")
        return 1
    # Curated English alias still allowed.
    if not gate_1e_d_ocr_ui_junk("steps").ok:
        print("FAIL gate_1e_d must allow curated alias 'steps'")
        return 1

    try:
        errors = validate_file(golden, offline=True)
    except Exception as exc:  # noqa: BLE001
        print(f"pha_eval_set_alias_fuzz_selfcheck: FAIL exception: {exc!r}")
        return 1
    if errors:
        print("pha_eval_set_alias_fuzz_selfcheck: FAIL")
        for e in errors:
            print("  - " + e.encode("unicode_escape").decode("ascii"))
        return 1
    print(f"pha_eval_set_alias_fuzz_selfcheck: PASS ({golden.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
