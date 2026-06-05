"""CLI entry point: ``pha-doctor``."""

from __future__ import annotations

import argparse

from pha.doctor import run_doctor


def main() -> None:
    parser = argparse.ArgumentParser(description="PHA environment diagnostics")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Docker mode: Ollama/model gaps are warnings only",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Extra detail")
    args = parser.parse_args()
    raise SystemExit(run_doctor(quick=args.quick, verbose=args.verbose))


if __name__ == "__main__":
    main()
