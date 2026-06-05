#!/usr/bin/env python3
"""PHA v2.1.4 — batch canonicalize historical ``medical_reports`` rows in SQLite."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from pha.medical_metric_catalog import (  # noqa: E402
    METRIC_CATALOG,
    UNKNOWN_REJECT,
    resolve_metric_name,
    resolve_metric_name_for_read,
)
from pha.medical_storage import _connect, init_medical_schema  # noqa: E402
from pha.metric_customs import is_polluted_metric_name  # noqa: E402
from pha.sqlite_storage import get_db_path  # noqa: E402


def _catalog_names(code: str) -> tuple[str, str]:
    entry = METRIC_CATALOG.get(code)
    if not entry:
        return code, code
    name_en, name_zh, _aliases = entry
    return name_en, name_zh


def repair_rows(*, dry_run: bool = False) -> dict[str, int]:
    init_medical_schema()
    conn = _connect()
    conn.row_factory = sqlite3.Row
    stats = {
        "scanned": 0,
        "updated": 0,
        "deleted": 0,
        "skipped": 0,
    }
    try:
        rows = conn.execute(
            """
            SELECT id, user_id, report_date, metric_name, metric_code,
                   name_en, name_zh, value, unit, reference_range
            FROM medical_reports
            ORDER BY id
            """,
        ).fetchall()

        for row in rows:
            stats["scanned"] += 1
            rid = int(row["id"])
            raw_name = (row["metric_name"] or "").strip()
            raw_code = (row["metric_code"] or "").strip()
            label = raw_name or raw_code

            if not label:
                stats["deleted"] += 1
                if not dry_run:
                    conn.execute("DELETE FROM medical_reports WHERE id = ?", (rid,))
                print(f"DELETE id={rid} empty label")
                continue

            resolved = resolve_metric_name_for_read(label)
            new_code = resolved.code
            write_check = resolve_metric_name(label)
            if write_check.code != UNKNOWN_REJECT and write_check.code in METRIC_CATALOG:
                new_code = write_check.code

            if is_polluted_metric_name(raw_name) or is_polluted_metric_name(raw_code):
                if new_code in METRIC_CATALOG:
                    pass
                else:
                    stats["deleted"] += 1
                    if not dry_run:
                        conn.execute("DELETE FROM medical_reports WHERE id = ?", (rid,))
                    print(f"DELETE id={rid} polluted name={raw_name!r} code={raw_code!r}")
                    continue
            if not new_code or new_code == UNKNOWN_REJECT:
                stats["deleted"] += 1
                if not dry_run:
                    conn.execute("DELETE FROM medical_reports WHERE id = ?", (rid,))
                print(f"DELETE id={rid} unmapped label={label!r}")
                continue

            if is_polluted_metric_name(new_code):
                stats["deleted"] += 1
                if not dry_run:
                    conn.execute("DELETE FROM medical_reports WHERE id = ?", (rid,))
                print(f"DELETE id={rid} polluted after map code={new_code!r}")
                continue

            if new_code in METRIC_CATALOG:
                new_en, new_zh = _catalog_names(new_code)
            else:
                new_en = resolved.name_en
                new_zh = resolved.name_zh

            new_name = new_code
            val = row["value"]
            unit = row["unit"] or ""
            ref = row["reference_range"] or ""

            changed = (
                raw_name != new_name
                or raw_code != new_code
                or (row["name_zh"] or "") != new_zh
                or (row["name_en"] or "") != new_en
            )
            if not changed:
                stats["skipped"] += 1
                continue

            if dry_run:
                print(
                    f"UPDATE id={rid} {raw_name!r}/{raw_code!r} -> "
                    f"{new_name!r}/{new_code!r} zh={new_zh!r}",
                )
            else:
                conn.execute(
                    """
                    UPDATE medical_reports
                    SET metric_name = ?, metric_code = ?, name_en = ?, name_zh = ?
                    WHERE id = ?
                    """,
                    (new_name, new_code, new_en, new_zh, rid),
                )
            stats["updated"] += 1

        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Canonicalize historical medical_reports using resolve_metric_name_for_read",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    args = parser.parse_args()
    db = get_db_path()
    print(f"database: {db}")
    stats = repair_rows(dry_run=args.dry_run)
    print(
        "repair_medical_rows",
        "(dry-run)" if args.dry_run else "DONE",
        stats,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
