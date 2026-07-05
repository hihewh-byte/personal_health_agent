#!/usr/bin/env python3
"""Keepalive supervisor for PHA (restarts pha.main if the pidfile process dies)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _read_pid(pidfile: Path) -> int | None:
    try:
        raw = pidfile.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        return int(raw)
    except (OSError, ValueError):
        return None


def _alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _log(msg: str) -> None:
    print(msg, flush=True)


def _spawn_app(
    root: Path,
    py: str,
    log_path: Path,
    host: str,
    port: str,
    num_scope: str,
    num_t1: str,
    path_in: str,
) -> int:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(root),
            "PATH": path_in,
            "PHA_HOST": host,
            "PHA_PORT": port,
            "PHA_NUMERICS_AUDIT_SCOPE": num_scope,
            "PHA_NUMERICS_T1_M4_MODE": num_t1,
        }
    )
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[keepalive {stamp}] spawning pha.main\n")
    _log(f"[keepalive {stamp}] spawn pha.main cwd={root}")
    with log_path.open("ab") as lf:
        proc = subprocess.Popen(  # noqa: S603
            [py, "-m", "pha.main"],
            stdin=subprocess.DEVNULL,
            stdout=lf,
            stderr=lf,
            cwd=str(root),
            env=env,
            start_new_session=True,
        )
    return int(proc.pid)


def main(argv: list[str]) -> int:
    if len(argv) != 10:
        print(
            "usage: pha_keepalive.py <root> <py> <pidfile> <log> <host> <port> <scope> <t1> <path>",
            file=sys.stderr,
        )
        return 2

    root_s, py, pidfile_s, log_s, host, port, num_scope, num_t1, path_in = argv[1:]
    root = Path(root_s).resolve()
    pidfile = Path(pidfile_s)
    log_path = Path(log_s)

    running = True

    def _stop(_sig: int, _frame) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    _log(f"[keepalive] started root={root} pidfile={pidfile} port={port}")
    while running:
        pid = _read_pid(pidfile)
        if not _alive(pid):
            if pid:
                _log(f"[keepalive] app pid={pid} dead, restarting")
            new_pid = _spawn_app(root, py, log_path, host, port, num_scope, num_t1, path_in)
            pidfile.write_text(f"{new_pid}\n", encoding="utf-8")
            _log(f"[keepalive] new app pid={new_pid}")
        time.sleep(5)
    _log("[keepalive] stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
