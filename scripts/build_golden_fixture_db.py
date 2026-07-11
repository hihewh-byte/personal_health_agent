#!/usr/bin/env python3
"""Build minimal SQLite fixture for no-LLM golden run on fresh clones.

Writes ``tests/fixtures/golden/pha_storage_min.db`` — synthetic demo rows only
(no real patient data). Regenerate after schema changes affecting golden run.

Usage (repo root)::

    python scripts/build_golden_fixture_db.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "tests" / "fixtures" / "golden" / "pha_storage_min.db"
UID = "default"


def build(conn: sqlite3.Connection) -> None:
    from pha.chat_background import init_background_schema
    from pha.medical_storage import init_medical_schema
    from pha.sqlite_storage import init_schema

    init_schema(conn)
    init_medical_schema(conn)
    init_background_schema(conn)

    conn.execute("DELETE FROM medical_reports WHERE user_id = ?", (UID,))
    conn.execute("DELETE FROM wearable_data WHERE user_id = ?", (UID,))
    conn.execute("DELETE FROM user_health_background_notes WHERE user_id = ?", (UID,))

    lipids = [
        ("2023-12-15T23:59:59", "TC", "TC", "总胆固醇", 5.62, "mmol/L"),
        ("2023-12-15T23:59:59", "LDL", "LDL", "低密度脂蛋白胆固醇", 4.05, "mmol/L"),
        ("2025-12-07T23:59:59", "TC", "TC", "总胆固醇", 4.24, "mmol/L"),
        ("2025-12-07T23:59:59", "LDL", "LDL", "低密度脂蛋白胆固醇", 2.45, "mmol/L"),
    ]
    conn.executemany(
        """
        INSERT INTO medical_reports
            (user_id, report_date, metric_name, metric_code, name_zh, value, unit)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [(UID, *row) for row in lipids],
    )
    conn.execute(
        """
        INSERT INTO wearable_data (user_id, metric_type, timestamp, value, sample_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (UID, "hrv", "2025-12-01T12:00:00", 45.0, "golden_fixture|hrv|1"),
    )
    conn.execute(
        """
        INSERT INTO user_health_background_notes (user_id, note_date, category, content)
        VALUES (?, ?, ?, ?)
        """,
        (UID, "2025-12-01", "supplement", "蛋白粉30g + 肌酸5g（synthetic golden fixture）"),
    )
    conn.commit()


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    conn = sqlite3.connect(str(OUT))
    try:
        build(conn)
    finally:
        conn.close()
    size_kb = OUT.stat().st_size / 1024
    print(f"Wrote {OUT.relative_to(ROOT)} ({size_kb:.1f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
