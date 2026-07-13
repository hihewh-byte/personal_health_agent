"""harness-loop CLI — Official Loop Suite α entrypoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness_loop import __version__
from harness_loop.eval_set import validate_file
from harness_loop.paths import detect_monorepo_root


def _cmd_version(_: argparse.Namespace) -> int:
    print(f"harness-loop {__version__}")
    print("Official Loop Suite α — offline evolution companion to harness-core")
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


def _cmd_harvest(args: argparse.Namespace) -> int:
    if args.plugin != "pha":
        print("ERROR: α harvest currently requires --plugin pha (reference impl)", file=sys.stderr)
        return 2
    from harness_loop.plugins import pha as pha_plugin

    print("== harness-loop harvest → PHA reference pipeline ==")
    print("NOTE: proposal-only; never auto-merges")
    return pha_plugin.run_shell("scripts/pha_loop_run_from_e2e.sh")


def _cmd_promote(args: argparse.Namespace) -> int:
    if args.plugin != "pha":
        print("ERROR: α promote currently requires --plugin pha", file=sys.stderr)
        return 2
    if not args.proposal:
        print("ERROR: --proposal PATH required", file=sys.stderr)
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
        description="Official Loop Suite α CLI (offline evolution; no auto-merge)",
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

    sp = sub.add_parser("harvest", help="Run offline harvest/critic/distill pipeline")
    sp.add_argument("--plugin", default="pha", choices=["pha"])
    sp.set_defaults(func=_cmd_harvest)

    sp = sub.add_parser("promote", help="Dry-run/veto a loop proposal (never applies)")
    sp.add_argument("--plugin", default="pha", choices=["pha"])
    sp.add_argument("--proposal", required=True, help="Path to loop_proposal JSON")
    sp.add_argument("--full-veto", action="store_true")
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
