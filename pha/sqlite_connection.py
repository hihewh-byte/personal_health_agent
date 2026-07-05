"""SQLite connection factory: thread-local pool + one-shot schema guard (P1-3)."""

from __future__ import annotations

import sqlite3
import threading
from typing import Callable, Optional

_schema_lock = threading.Lock()
_schema_ready = False
_schema_initializer: Optional[Callable[[sqlite3.Connection], None]] = None
_thread_local = threading.local()


def register_schema_initializer(fn: Callable[[sqlite3.Connection], None]) -> None:
    global _schema_initializer
    _schema_initializer = fn


def configure_sqlite_for_bulk_import(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-64000")


def _new_connection() -> sqlite3.Connection:
    from pha.sqlite_storage import ensure_data_dir, get_db_path

    ensure_data_dir()
    conn = sqlite3.connect(str(get_db_path()), check_same_thread=False, timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def ensure_schema() -> None:
    """Run DDL/migrations once per process."""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        if _schema_initializer is None:
            raise RuntimeError("SQLite schema initializer not registered")
        conn = _new_connection()
        try:
            _schema_initializer(conn)
        finally:
            conn.close()
        _schema_ready = True


def connect_pooled() -> sqlite3.Connection:
    """Thread-local connection reused across short bursts in the same thread."""
    ensure_schema()
    conn = getattr(_thread_local, "conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            conn = None
            _thread_local.conn = None
    if conn is None:
        conn = _new_connection()
        _thread_local.conn = conn
    return conn


def open_connection(*, bulk_import: bool = False) -> sqlite3.Connection:
    """Dedicated connection; caller must ``release_connection`` when done."""
    ensure_schema()
    conn = _new_connection()
    if bulk_import:
        configure_sqlite_for_bulk_import(conn)
    return conn


def release_connection(conn: sqlite3.Connection) -> None:
    if getattr(_thread_local, "conn", None) is conn:
        conn.close()
        _thread_local.conn = None
    else:
        conn.close()


def reset_schema_state_for_tests() -> None:
    global _schema_ready
    with _schema_lock:
        _schema_ready = False
        _thread_local.conn = None
