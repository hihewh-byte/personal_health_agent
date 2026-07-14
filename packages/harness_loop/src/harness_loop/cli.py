"""harness-loop CLI — Harness Loop (Alpha) entrypoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness_loop import __version__
from harness_loop.eval_set import validate_file
from harness_loop.harvest import harvest_file_to_path
from harness_loop.paths import detect_monorepo_root
from harness_loop.pipeline import default_out_layout
from harness_loop.proposals import (
    validate_proposal_file,
    validate_verdict_file,
    write_static_promote_verdict,
)


def _cmd_version(_: argparse.Namespace) -> int:
    print(f"harness-loop {__version__}")
    print("Harness Loop (Alpha) — offline evolution companion to harness-core")
    print("Boundaries: no auto-merge; Core stays online-only; plugins own domain catalogs")
    return 0


def _cmd_eval_check(args: argparse.Namespace) -> int:
    catalog = Path(args.catalog).resolve() if args.catalog else None
    reject_fn = None
    goldens: list[Path] = []

    if getattr(args, "plugin", None) == "pha":
        from harness_loop.plugins import pha as pha_plugin

        root = detect_monorepo_root()
        catalog = catalog or pha_plugin.pha_default_catalog(root)
        reject_fn = pha_plugin.pha_alias_reject
        if args.golden:
            goldens = [Path(args.golden).resolve()]
        else:
            goldens = pha_plugin.pha_default_goldens(root)
    elif args.golden:
        goldens = [Path(args.golden).resolve()]
    else:
        print("ERROR: provide --golden PATH or --plugin pha", file=sys.stderr)
        return 2

    failed = 0
    for g in goldens:
        if not g.is_file():
            print(f"FAIL missing {g}")
            failed += 1
            continue
        errors = validate_file(
            g,
            offline=True,
            catalog_path=catalog,
            alias_reject_fn=reject_fn,
        )
        if errors:
            print(f"FAIL {g.name}")
            for e in errors:
                print("  - " + e.encode("unicode_escape").decode("ascii"))
            failed += 1
        else:
            print(f"PASS {g.name}")
    return 1 if failed else 0


def _cmd_reflect(args: argparse.Namespace) -> int:
    if args.plugin != "pha":
        print("ERROR: α reflect currently requires --plugin pha (reference impl)", file=sys.stderr)
        return 2
    from harness_loop.plugins import pha as pha_plugin

    print("== harness-loop reflect → Ring R Reflection Critic (read-only) ==")
    print("NOTE: attribution only; never auto-merges or edits routing")
    return pha_plugin.run_reflect(
        candidates=args.candidates,
        e2e_jsonl=args.e2e_jsonl,
        out_dir=args.out_dir,
    )


def _cmd_proposal_check(args: argparse.Namespace) -> int:
    path = Path(args.path).resolve()
    if not path.is_file():
        print(f"FAIL missing {path}")
        return 1
    if args.kind == "verdict":
        errors = validate_verdict_file(path)
        label = "promote_verdict"
    else:
        errors = validate_proposal_file(path)
        label = "loop_proposal"
    if errors:
        print(f"FAIL {label} {path.name}")
        for e in errors:
            print("  - " + e)
        return 1
    print(f"PASS {label} {path.name}")
    return 0


def _cmd_harvest(args: argparse.Namespace) -> int:
    # Portable path: domain-agnostic failed-turn harvest (no PHA required).
    if args.e2e_jsonl:
        out = args.out
        if not out:
            root = detect_monorepo_root()
            out = str(default_out_layout(root)["candidates"])
        classify = None
        if args.plugin == "pha":
            try:
                from harness_loop.plugins import pha as pha_plugin

                root = detect_monorepo_root()
                if str(root) not in sys.path:
                    sys.path.insert(0, str(root))
                from pha.loop_failure_taxonomy import classify_e2e_check  # noqa: WPS433

                classify = classify_e2e_check
            except Exception as exc:  # noqa: BLE001
                print(f"WARN: PHA classify unavailable ({exc}); using default", file=sys.stderr)
        print("== harness-loop harvest → portable failed-turn JSONL ==")
        print("NOTE: candidates only; never auto-merges")
        path, n_sig, n_rows = harvest_file_to_path(
            args.e2e_jsonl,
            out,
            classify_check=classify,
        )
        print(f" signals : {n_sig}")
        print(f" rows    : {n_rows}")
        print(f" output  : {path}")
        return 0

    if args.plugin != "pha":
        print(
            "ERROR: provide --e2e-jsonl PATH for portable harvest, "
            "or --plugin pha for full PHA pipeline",
            file=sys.stderr,
        )
        return 2
    from harness_loop.plugins import pha as pha_plugin

    print("== harness-loop harvest → PHA reference pipeline (orchestrated) ==")
    print("NOTE: proposal-only; never auto-merges")
    return pha_plugin.run_harvest_pipeline()


def _cmd_promote(args: argparse.Namespace) -> int:
    if not args.proposal:
        print("ERROR: --proposal PATH required", file=sys.stderr)
        return 2

    if args.static_only or args.plugin is None:
        out_dir = args.out_dir
        if not out_dir:
            root = detect_monorepo_root()
            out_dir = str(default_out_layout(root)["verdicts"])
        print("== harness-loop promote → portable static veto (dry-run) ==")
        print("NOTE: no regression suite; no catalog write; no auto-merge")
        path, verdict = write_static_promote_verdict(
            args.proposal,
            out_dir=out_dir,
            patch_path_prefix=args.patch_prefix,
        )
        status = "PASS" if verdict.get("passed") else "VETO"
        print(f" {status} static_veto={verdict.get('static_veto')}")
        print(f" verdict : {path}")
        return 0 if verdict.get("passed") else 1

    if args.plugin != "pha":
        print("ERROR: --plugin pha or --static-only required", file=sys.stderr)
        return 2
    from harness_loop.plugins import pha as pha_plugin

    cmd_args = ["--proposal", args.proposal]
    if args.full_veto:
        cmd_args.append("--full-veto")
    print("== harness-loop promote → PHA reference (dry-run/veto; no apply) ==")
    return pha_plugin.run_script("pha_loop_promote_candidate.py", cmd_args)


def _cmd_adopt(args: argparse.Namespace) -> int:
    if args.plugin != "pha":
        print("ERROR: α adopt currently requires --plugin pha", file=sys.stderr)
        return 2
    if not args.proposal:
        print("ERROR: --proposal PATH required", file=sys.stderr)
        return 2
    if args.confirm != "YES":
        print(
            "REFUSED: adopt is gated. Pass --confirm YES explicitly "
            "(T0 write path; never silent).",
            file=sys.stderr,
        )
        return 3
    from harness_loop.plugins import pha as pha_plugin

    cmd_args = ["--proposal", args.proposal, "--apply", "--confirm", "YES"]
    if args.recompile_chb:
        cmd_args.append("--recompile-chb")
    print("== harness-loop adopt → PHA T0 gated adopter ==")
    return pha_plugin.run_script("pha_t0_gated_adopter.py", cmd_args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="harness-loop",
        description="Harness Loop (Alpha) CLI (offline evolution; no auto-merge)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("version", help="Print suite version and boundaries")
    sp.set_defaults(func=_cmd_version)

    sp = sub.add_parser("eval-check", help="Validate harness.eval_set/v1 goldens offline")
    sp.add_argument("--golden", default="", help="Path to one eval_set JSON")
    sp.add_argument("--catalog", default="", help="Domain catalog JSON (metric_aliases)")
    sp.add_argument(
        "--plugin",
        default=None,
        choices=["pha"],
        help="Reference plugin (pha enables 1E reject expects + default goldens)",
    )
    sp.set_defaults(func=_cmd_eval_check)

    sp = sub.add_parser("reflect", help="Ring R: offline failure attribution (read-only)")
    sp.add_argument("--plugin", default="pha", choices=["pha"])
    sp.add_argument(
        "--candidates",
        default="",
        help="slow_round_candidates.jsonl (default: reports/loop/...)",
    )
    sp.add_argument("--e2e-jsonl", default="", help="Optional E2E stress JSONL")
    sp.add_argument("--out-dir", default="", help="Output dir for reflection_*.md/json")
    sp.set_defaults(func=_cmd_reflect)

    sp = sub.add_parser(
        "proposal-check",
        help="Validate loop_proposal/v2 or promote_verdict/v1 JSON shape",
    )
    sp.add_argument("path", help="Proposal or verdict JSON path")
    sp.add_argument(
        "--kind",
        default="proposal",
        choices=["proposal", "verdict"],
        help="Document kind (default: loop proposal)",
    )
    sp.set_defaults(func=_cmd_proposal_check)

    sp = sub.add_parser(
        "harvest",
        help="Portable failed-turn harvest, or full PHA offline pipeline",
    )
    sp.add_argument(
        "--plugin",
        default=None,
        choices=["pha"],
        help="pha = full reference pipeline (when --e2e-jsonl omitted)",
    )
    sp.add_argument("--e2e-jsonl", default="", help="Failed-turn JSONL → portable harvest")
    sp.add_argument("--out", default="", help="Candidates JSONL output path")
    sp.set_defaults(func=_cmd_harvest)

    sp = sub.add_parser("promote", help="Dry-run/veto a loop proposal (never applies)")
    sp.add_argument(
        "--plugin",
        default="pha",
        choices=["pha"],
        help="pha = reference regression veto; use --static-only for portable gates",
    )
    sp.add_argument("--proposal", required=True, help="Path to loop_proposal JSON")
    sp.add_argument("--full-veto", action="store_true")
    sp.add_argument(
        "--static-only",
        action="store_true",
        help="Portable static veto only (no PHA regression suites)",
    )
    sp.add_argument("--out-dir", default="", help="Verdict output dir (static-only)")
    sp.add_argument(
        "--patch-prefix",
        default="/metric_aliases/",
        help="Allowed patch_ops path prefix for static veto",
    )
    sp.set_defaults(func=_cmd_promote)

    sp = sub.add_parser("adopt", help="Gated adopt (requires --confirm YES)")
    sp.add_argument("--plugin", default="pha", choices=["pha"])
    sp.add_argument("--proposal", required=True)
    sp.add_argument("--confirm", default="", help="Must be YES to write")
    sp.add_argument("--recompile-chb", action="store_true")
    sp.set_defaults(func=_cmd_adopt)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
