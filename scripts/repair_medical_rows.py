#!/usr/bin/env python3
"""Thin wrapper — run ``repair_medical_rows`` from project root (PHA v2.1.4)."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    runpy.run_path(str(ROOT / "repair_medical_rows.py"), run_name="__main__")
