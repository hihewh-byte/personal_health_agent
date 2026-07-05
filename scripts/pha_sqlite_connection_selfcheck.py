#!/usr/bin/env python3
"""P1-3 selfcheck: thread-local SQLite pool + concurrent read/write without database locked."""

from __future__ import annotations

import concurrent.futures
import sys
import time
from datetime import date, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_schema_runs_once() -> bool:
    from pha import sqlite_connection
    from pha.sqlite_storage import _apply_schema_migrations, init_schema

    sqlite_connection.reset_schema_state_for_tests()
    calls = {"n": 0}

    def _counting_migrations(conn):
        calls["n"] += 1
        _apply_schema_migrations(conn)

    sqlite_connection.register_schema_initializer(_counting_migrations)
    init_schema()
    init_schema()
    from pha.sqlite_storage import count_wearable_samples

    count_wearable_samples("default")
    if calls["n"] != 1:
        print("FAIL schema initializer invoked", calls["n"], "times (expected 1)")
        sqlite_connection.register_schema_initializer(_apply_schema_migrations)
        return False
    sqlite_connection.register_schema_initializer(_apply_schema_migrations)
    print("OK schema runs once per process")
    return True


def test_concurrent_read_write() -> bool:
    from pha.sqlite_storage import (
        count_wearable_samples,
        query_wearable_daily_range,
        upsert_import_sync_state,
    )

    errors: list[str] = []

    def reader(tid: int) -> None:
        try:
            for _ in range(40):
                count_wearable_samples("default")
                list(
                    query_wearable_daily_range(
                        "default",
                        date(2026, 1, 1),
                        date(2026, 6, 10),
                    ),
                )
        except Exception as exc:
            errors.append(f"reader-{tid}: {exc}")

    def writer(tid: int) -> None:
        try:
            for i in range(25):
                upsert_import_sync_state(
                    "default",
                    status="running",
                    message=f"selfcheck-{tid}-{i}",
                )
        except Exception as exc:
            errors.append(f"writer-{tid}: {exc}")

    def batch_writer(tid: int) -> None:
        from pha.sqlite_storage import WearableDataBatchWriter

        try:
            w = WearableDataBatchWriter("default")
            ts = datetime.utcnow()
            for i in range(30):
                w.add_sample(
                    "steps",
                    ts,
                    float(i),
                    sample_id=f"selfcheck-p13-{tid}-{i}|watch",
                )
            w.close()
        except Exception as exc:
            errors.append(f"batch-{tid}: {exc}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futs = []
        futs += [pool.submit(reader, i) for i in range(4)]
        futs += [pool.submit(writer, i) for i in range(2)]
        futs += [pool.submit(batch_writer, i) for i in range(2)]
        for fut in concurrent.futures.as_completed(futs):
            fut.result()

    locked = [e for e in errors if "locked" in e.lower()]
    if locked:
        print("FAIL database locked:", locked[:3])
        return False
    if errors:
        print("FAIL concurrent errors:", errors[:5])
        return False
    print("OK concurrent read/write/batch (10 workers)")
    return True


def test_stale_pooled_after_raw_close() -> bool:
    from pha.medical_storage import init_medical_schema
    from pha.chat_storage import init_chat_schema
    from pha.sqlite_connection import connect_pooled, release_connection

    init_medical_schema()
    init_chat_schema()
    conn = connect_pooled()
    try:
        row = conn.execute("SELECT 1 AS ok").fetchone()
        if not row or int(row["ok"]) != 1:
            print("FAIL stale pooled SELECT 1", row)
            return False
    finally:
        release_connection(conn)
    print("OK startup schemas + pooled after legacy close paths")
    return True


def test_pooled_reuse_same_thread() -> bool:
    from pha.sqlite_connection import connect_pooled, release_connection

    a = connect_pooled()
    b = connect_pooled()
    same = a is b
    release_connection(a)
    c = connect_pooled()
    reopened = c is not a
    release_connection(c)
    if not same or not reopened:
        print("FAIL pooled reuse", same, reopened)
        return False
    print("OK thread-local pool reuse")
    return True


def main() -> int:
    t0 = time.perf_counter()
    ok = all(
        [
            test_schema_runs_once(),
            test_stale_pooled_after_raw_close(),
            test_pooled_reuse_same_thread(),
            test_concurrent_read_write(),
        ],
    )
    print(f"pha_sqlite_connection_selfcheck: {'PASS' if ok else 'FAIL'} ({time.perf_counter() - t0:.1f}s)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
