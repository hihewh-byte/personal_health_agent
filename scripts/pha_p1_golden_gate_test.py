#!/usr/bin/env python3
"""P1 Golden Gate — D-3d-2 offline (F-tier) + HTTP (H-tier) orchestrator.

P1-c: ``--tier f`` loads offline fixtures, reuses existing selfchecks, runs N-CHB cases.
Does NOT duplicate wearable/compare/numerics logic.

Default: NOT in PR selfcheck_manifest (Stage 4-0 CI layering).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
P1_FIXTURE = ROOT / "tests" / "fixtures" / "p1_golden"
EXPECTATIONS_PATH = P1_FIXTURE / "expectations_v1.json"
NUMERICS_CASES_PATH = P1_FIXTURE / "numerics_cases_chb.json"


@dataclass
class GateReport:
    tier: str
    passed: bool = True
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.passed = False
        self.failures.append(msg)

    def note(self, msg: str) -> None:
        self.notes.append(msg)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def validate_expectations_schema(exp: dict[str, Any]) -> list[str]:
    """Validate expectations_v1.json structure and F-layer fixture cross-refs."""
    errors: list[str] = []
    if exp.get("schema") != "pha.p1_golden_expectations/v1":
        errors.append(f"schema mismatch: {exp.get('schema')!r}")

    fixtures = exp.get("fixtures") or {}
    ocr_path = ROOT / str(fixtures.get("golden_ocr_path") or "")
    cmp_path = ROOT / str(fixtures.get("golden_compare_path") or "")
    if not ocr_path.is_file():
        errors.append(f"missing golden OCR: {ocr_path}")
    if not cmp_path.is_file():
        errors.append(f"missing golden compare: {cmp_path}")

    if ocr_path.is_file():
        ocr = _load_json(ocr_path)
        want_ocr = fixtures.get("golden_ocr_fixture_id")
        if want_ocr and ocr.get("fixture_id") != want_ocr:
            errors.append(f"E1-fixture-ocr: want {want_ocr!r} got {ocr.get('fixture_id')!r}")

    if cmp_path.is_file():
        cmp_doc = _load_json(cmp_path)
        want_cmp = fixtures.get("golden_compare_fixture_id")
        if want_cmp and cmp_doc.get("fixture_id") != want_cmp:
            errors.append(f"E1-fixture-compare: want {want_cmp!r} got {cmp_doc.get('fixture_id')!r}")
        rows = ((cmp_doc.get("expected_standard") or {}).get("rows") or [])
        e1 = (exp.get("scenarios") or {}).get("E1") or {}
        min_rows = int(e1.get("compare_min_rows") or 0)
        if min_rows and len(rows) < min_rows:
            errors.append(f"G-Compare-1-offline: rows={len(rows)} < compare_min_rows={min_rows}")

    for key in ("E1", "E2", "E3"):
        if key not in (exp.get("scenarios") or {}):
            errors.append(f"missing scenario {key}")

    e1 = (exp.get("scenarios") or {}).get("E1") or {}
    if e1.get("profile_expected") != "wearable_screenshot_review":
        errors.append("E1-profile-spec: must be wearable_screenshot_review")
    if "attachment_grounded_review" not in (e1.get("forbidden_profiles") or []):
        errors.append("E1-profile-spec: attachment_grounded_review must be forbidden")

    return errors


def run_subprocess_script(script: str, *, label: str) -> tuple[bool, str]:
    path = ROOT / script
    if not path.is_file():
        return False, f"missing script: {path}"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return False, f"{label} exit={proc.returncode}\n{out[-2000:]}"
    return True, out.strip().splitlines()[-1] if out.strip() else f"{label} OK"


def run_numerics_chb_cases(cases_doc: dict[str, Any]) -> list[str]:
    """Run N-CHB-* / N-ADV-* from numerics_cases_chb.json."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from pha.numerics_manifest import audit_response_numerics, build_numerics_manifest

    errors: list[str] = []
    if cases_doc.get("schema") != "pha.p1_golden_numerics_cases/v1":
        errors.append(f"numerics schema mismatch: {cases_doc.get('schema')!r}")
        return errors

    audit_env = cases_doc.get("audit_env") or {}
    prev_scope = os.environ.get("PHA_NUMERICS_AUDIT_SCOPE")
    prev_m4 = os.environ.get("PHA_NUMERICS_T1_M4_MODE")
    try:
        for k, v in audit_env.items():
            os.environ[str(k)] = str(v)

        mcfg = cases_doc.get("manifest") or {}
        manifest = build_numerics_manifest(
            str(mcfg.get("user_id") or "default"),
            profile=str(mcfg.get("profile") or "combined_review"),
            user_message=str(mcfg.get("user_message") or ""),
        )
        prefix = str(cases_doc.get("t0_baseline_answer_prefix") or "")

        for case in cases_doc.get("cases") or []:
            cid = str(case.get("id") or "?")
            answer = prefix + str(case.get("answer_suffix") or "")
            expect_pass = bool(case.get("expect_pass"))
            vsub = str(case.get("expect_violation_substr") or "")
            require_citation = bool(case.get("require_citation", True))

            audit = audit_response_numerics(answer, manifest, require_citation=require_citation)
            ok = audit.get("passed") == expect_pass
            if vsub and vsub not in "|".join(audit.get("violations") or []):
                ok = False
            if ok:
                print(f"PASS {cid} passed={audit.get('passed')}")
            else:
                errors.append(
                    f"{cid}: expect_pass={expect_pass} got={audit.get('passed')} "
                    f"violations={audit.get('violations')!r} vsub={vsub!r}",
                )
                print(f"FAIL {cid} passed={audit.get('passed')} violations={audit.get('violations')}")
    finally:
        if prev_scope is None:
            os.environ.pop("PHA_NUMERICS_AUDIT_SCOPE", None)
        else:
            os.environ["PHA_NUMERICS_AUDIT_SCOPE"] = prev_scope
        if prev_m4 is None:
            os.environ.pop("PHA_NUMERICS_T1_M4_MODE", None)
        else:
            os.environ["PHA_NUMERICS_T1_M4_MODE"] = prev_m4

    return errors


def tier_f_offline() -> GateReport:
    report = GateReport(tier="F")

    print("== P1 Golden Gate · tier F (offline) ==")

    try:
        exp = _load_json(EXPECTATIONS_PATH)
    except FileNotFoundError as exc:
        report.fail(str(exc))
        return report

    schema_errors = validate_expectations_schema(exp)
    for err in schema_errors:
        report.fail(f"expectations: {err}")
    if not schema_errors:
        report.note("expectations_v1.json schema + fixture cross-ref OK")
        print("PASS expectations schema + fixture cross-ref")

    ok, msg = run_subprocess_script("scripts/pha_wearable_golden_fixture.py", label="γ OCR")
    if ok:
        print(f"PASS pha_wearable_golden_fixture — {msg}")
        report.note(f"γ OCR: {msg}")
    else:
        report.fail(f"pha_wearable_golden_fixture: {msg}")

    ok, msg = run_subprocess_script("scripts/pha_wearable_compare_table_selfcheck.py", label="Compare build")
    if ok:
        print(f"PASS pha_wearable_compare_table_selfcheck — {msg}")
        report.note(f"Compare: {msg}")
    else:
        report.fail(f"pha_wearable_compare_table_selfcheck: {msg}")

    try:
        cases_doc = _load_json(NUMERICS_CASES_PATH)
    except FileNotFoundError as exc:
        report.fail(str(exc))
        return report

    print("\n-- N-CHB / N-ADV numerics cases --")
    numerics_errors = run_numerics_chb_cases(cases_doc)
    if numerics_errors:
        for err in numerics_errors:
            report.fail(f"numerics: {err}")
    else:
        n = len(cases_doc.get("cases") or [])
        report.note(f"numerics N-cases {n}/{n} PASS")
        print(f"PASS numerics N-cases {n}/{n}")

    return report


def tier_h_http(*, assets: str, exp: dict[str, Any] | None = None) -> GateReport:
    """HTTP E2E — P1-d (synthetic) / P1-e (real pixel)."""
    report = GateReport(tier="H")
    print(f"\n== P1 Golden Gate · tier H (HTTP · assets={assets}) ==")

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    scripts = ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))

    from p1_http_e2e_lib import (
        assert_e1_turn,
        assert_e2_turn,
        assert_e3_turn,
        preflight_http,
        snapshot_from_dict,
        synthetic_result_to_snapshot,
    )

    try:
        expectations = exp or _load_json(EXPECTATIONS_PATH)
    except FileNotFoundError as exc:
        report.fail(str(exc))
        return report

    port = os.environ.get("PHA_PORT", "8788")
    base = f"http://127.0.0.1:{port}"
    ok, build_or_err = preflight_http(base)
    if not ok:
        report.fail(f"P1-preflight: {build_or_err} (restart: bash scripts/pha_restart_accept.sh)")
        return report
    report.note(f"preflight OK build={build_or_err}")
    print(f"PASS preflight build={build_or_err}")

    scenarios = expectations.get("scenarios") or {}
    e1_spec = scenarios.get("E1") or {}
    e2_spec = scenarios.get("E2") or {}
    e3_spec = scenarios.get("E3") or {}
    all_fails: list[str] = []

    if assets == "synthetic":
        from pha_e2e_6panel_realdevice import USER_MSG, run_synthetic_e1_session

        print("\n-- P1-d synthetic 6-panel E1 --")
        try:
            syn = run_synthetic_e1_session(verbose=True)
        except Exception as exc:
            report.fail(f"P1-d synthetic run: {exc}")
            return report

        e1_snap = synthetic_result_to_snapshot(syn, message=USER_MSG)
        fails = assert_e1_turn(e1_snap, e1_spec)
        if fails and int(syn.get("metrics_count") or 0) == 0:
            assets_dir = Path(
                os.environ.get(
                    "PHA_P1_ASSETS_DIR",
                    os.environ.get(
                        "PHA_JUN11_ASSETS",
                        "/Users/hwh/.cursor/projects/Users-hwh-Documents-myAgents/assets",
                    ),
                ),
            )
            if list(assets_dir.glob("IMG_690*.png")):
                print(
                    "\n-- P1-d fallback: synthetic OCR yielded 0 metrics; retry E1 with real pixels --",
                )
                from pha_e2e_jun11_realdevice_multiturn import run_p1_real_scenarios

                real_e1 = run_p1_real_scenarios(assets_dir, verbose=False)
                if not real_e1.get("error"):
                    e1_snap = snapshot_from_dict((real_e1.get("turns") or {}).get("E1") or {})
                    fails = assert_e1_turn(e1_snap, e1_spec)
                    report.note("P1-d: synthetic OCR miss → real-pixel E1 fallback")
        for f in fails:
            all_fails.append(f)
            print(f"FAIL {f}")
        if not fails:
            print(
                f"PASS E1 synthetic profile={e1_snap.harness_profile} "
                f"metrics={len(e1_snap.metrics)} compare_rows={e1_snap.compare_rows}",
            )
            report.note(
                f"P1-d E1: profile={e1_snap.harness_profile} metrics={len(e1_snap.metrics)} "
                f"rows={e1_snap.compare_rows}",
            )

    if assets == "real":
        from pha_e2e_jun11_realdevice_multiturn import run_p1_real_scenarios

        assets_dir = Path(
            os.environ.get(
                "PHA_P1_ASSETS_DIR",
                os.environ.get(
                    "PHA_JUN11_ASSETS",
                    "/Users/hwh/.cursor/projects/Users-hwh-Documents-myAgents/assets",
                ),
            ),
        )
        print(f"\n-- P1-e real-pixel E1/E2/E3 (assets={assets_dir}) --")
        try:
            real = run_p1_real_scenarios(assets_dir, verbose=True)
        except Exception as exc:
            report.fail(f"P1-e real run: {exc}")
            return report

        if real.get("error"):
            report.fail(str(real["error"]))
            return report

        if real.get("e1_legacy_fails"):
            for f in real["e1_legacy_fails"]:
                all_fails.append(f"E1-legacy: {f}")

        turns = real.get("turns") or {}
        e1_snap = snapshot_from_dict(turns.get("E1") or {})
        e2_snap = snapshot_from_dict(turns.get("E2") or {})
        e3_snap = snapshot_from_dict(turns.get("E3") or {})

        for label, snap, spec, fn in (
            ("E1", e1_snap, e1_spec, lambda: assert_e1_turn(e1_snap, e1_spec)),
            ("E2", e2_snap, e2_spec, lambda: assert_e2_turn(e1_snap, e2_snap, e2_spec)),
            ("E3", e3_snap, e3_spec, lambda: assert_e3_turn(e3_snap, e3_spec)),
        ):
            fails = fn()
            for f in fails:
                all_fails.append(f)
                print(f"FAIL {f}")
            if not fails:
                print(
                    f"PASS {label} profile={snap.harness_profile} "
                    f"metrics={len(snap.metrics)} audit={snap.compare_audit.get('passed')}",
                )
                report.note(f"P1-e {label}: profile={snap.harness_profile}")

    if all_fails:
        for f in all_fails:
            report.fail(f)
    else:
        report.note(f"HTTP gate PASS assets={assets}")

    _write_p1_report(
        {
            "tier": "H",
            "assets": assets,
            "passed": report.passed,
            "failures": report.failures,
            "notes": report.notes,
        },
    )
    return report


def _write_p1_report(payload: dict[str, Any]) -> None:
    out_dir = Path(os.environ.get("PHA_E2E_REPORT_DIR", str(ROOT / "reports" / "p1_golden")))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "p1_golden_gate_latest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_summary(report: GateReport) -> None:
    print("\n== P1 Golden Gate summary ==")
    print(f"tier={report.tier} passed={report.passed}")
    for n in report.notes:
        print(f"  note: {n}")
    for f in report.failures:
        print(f"  FAIL: {f}")


def main() -> int:
    ap = argparse.ArgumentParser(description="P1 Golden Gate orchestrator (D-3d-2 + N-CHB)")
    ap.add_argument("--tier", choices=["f", "h", "all"], default="f", help="F=offline only")
    ap.add_argument(
        "--assets",
        choices=["synthetic", "real"],
        default="synthetic",
        help="HTTP tier asset mode (P1-d/e)",
    )
    args = ap.parse_args()

    reports: list[GateReport] = []
    if args.tier in ("f", "all"):
        reports.append(tier_f_offline())
    if args.tier in ("h", "all"):
        reports.append(tier_h_http(assets=args.assets))

    overall = all(r.passed for r in reports)
    for r in reports:
        print_summary(r)

    if overall:
        print("\nOK pha_p1_golden_gate_test")
        return 0
    print("\nFAIL pha_p1_golden_gate_test")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
