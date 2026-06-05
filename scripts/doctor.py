#!/usr/bin/env python3
"""PHA environment doctor — wrapper for ``pha.doctor.run_doctor``."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.doctor_cli import main

if __name__ == "__main__":
    main()
