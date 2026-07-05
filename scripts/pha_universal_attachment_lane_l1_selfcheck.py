#!/usr/bin/env python3
"""PR-gate L1 probe for Stage 3H universal attachment lane (seconds, no HTTP/LLM).

Wraps ``pha_universal_attachment_stress_battery.py --skip-http`` for selfcheck_manifest.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault("PHA_UNIVERSAL_ATTACHMENT_LANE", "1")
os.environ.setdefault("PHA_HEALTH_INTENT_CATALOG", "1")


def main() -> int:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "pha_universal_attachment_stress_battery.py"),
        "--skip-http",
        "--seed=20260626",
    ]
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
