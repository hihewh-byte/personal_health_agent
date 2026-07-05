#!/usr/bin/env python3
"""Spawn a command in a new session (immune to parent shell SIGHUP). Prints child PID."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: pha_detach_spawn.py <cwd> <logfile> <cmd...>", file=sys.stderr)
        return 2

    cwd = Path(argv[1]).resolve()
    log_path = Path(argv[2])
    cmd = argv[3:]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as lf:
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=lf,
            stderr=lf,
            cwd=str(cwd),
            env=os.environ.copy(),
            start_new_session=True,
        )
    print(proc.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
