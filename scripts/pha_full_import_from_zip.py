#!/usr/bin/env python3
"""CLI: full Apple Health export.zip import (clears user wearable warehouse first)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description="PHA full Apple Health export.zip import")
    ap.add_argument("zip_path", type=Path, help="Path to export.zip")
    ap.add_argument("--user-id", default="default")
    args = ap.parse_args()
    path = args.zip_path.expanduser().resolve()
    if not path.is_file():
        print(f"ERROR: not found: {path}", file=sys.stderr)
        return 1

    from pha.data_importer import run_import_from_path

    uid = (args.user_id or "default").strip() or "default"
    print(f"user_id={uid} full import (will clear existing wearable data for this user)")
    print(f"zip={path}")
    result = run_import_from_path(str(path), user_id=uid, filename=path.name)
    print(result.message)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
