"""SQLite schema migrations.

A from-scratch migration framework is overkill for the handful of tables
this scanner needs, but we still need *some* schema-versioning discipline
or Phase 2 features that touch the DB will silently break older installs.

How it works:
  - `PRAGMA user_version` tracks the current schema version (0 on a fresh DB).
  - `MIGRATIONS` is an in-order list of (version, callable) pairs.
  - On boot, `apply(db)` runs every callable whose version is greater than
    the current `user_version`, in order, inside a single transaction.
  - Each callable receives the connection and is responsible for both the
    CREATE/ALTER and any data backfill.

Adding a new migration: append to `MIGRATIONS`. Never reorder, never edit
in place. If you need to undo something, write a new migration that does
the reverse — that's the only way older installs reach the same end state."""
from __future__ import annotations

import sqlite3
from typing import Callable

from .log import get_logger

log = get_logger(__name__)


def _v1_initial_schema(db: sqlite3.Connection) -> None:
    """Mirror the original state.py CREATE TABLE so the bare DB is now
    formally at v1 instead of 'whatever state.py happened to create.'"""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS last_alert (
            retailer TEXT NOT NULL,
            store_id TEXT NOT NULL,
            product_key TEXT NOT NULL,
            status TEXT NOT NULL,
            ts INTEGER NOT NULL,
            PRIMARY KEY (retailer, store_id, product_key)
        )
        """
    )


def _v2_price_history(db: sqlite3.Connection) -> None:
    """Track listed prices over time for the at-or-below-MSRP filter
    + Phase 3 anomaly detection."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS price_history (
            retailer TEXT NOT NULL,
            product_key TEXT NOT NULL,
            store_id TEXT NOT NULL,
            price_cents INTEGER,
            ts INTEGER NOT NULL,
            PRIMARY KEY (retailer, product_key, store_id, ts)
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_price_history_product "
        "ON price_history(product_key, ts)"
    )


def _v3_hit_log(db: sqlite3.Connection) -> None:
    """Every alert we send, written for Phase 3 analytics (per-store hit
    rate, time-of-day heatmap). Separate from last_alert which is just a
    dedupe table."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS hit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            retailer TEXT NOT NULL,
            store_id TEXT NOT NULL,
            product_key TEXT NOT NULL,
            status TEXT NOT NULL,
            tier TEXT NOT NULL,
            url TEXT,
            price_cents INTEGER,
            ts INTEGER NOT NULL
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_hit_log_ts ON hit_log(ts)")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_hit_log_retailer_ts "
        "ON hit_log(retailer, ts)"
    )


def _v4_signal_seen(db: sqlite3.Connection) -> None:
    """Dedupe table for community-signal posts so we don't re-alert on
    the same Reddit/Discord post across scan passes."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS signal_seen (
            source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            ts INTEGER NOT NULL,
            PRIMARY KEY (source, external_id)
        )
        """
    )


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _v1_initial_schema),
    (2, _v2_price_history),
    (3, _v3_hit_log),
    (4, _v4_signal_seen),
]


def current_version(db: sqlite3.Connection) -> int:
    row = db.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def apply(db: sqlite3.Connection) -> int:
    """Bring `db` up to the latest schema version. Returns the new version."""
    version = current_version(db)
    target = MIGRATIONS[-1][0] if MIGRATIONS else 0
    if version >= target:
        return version
    log.info("running schema migrations from v%d -> v%d", version, target)
    try:
        for migration_version, fn in MIGRATIONS:
            if migration_version <= version:
                continue
            log.info("applying migration v%d (%s)", migration_version, fn.__name__)
            fn(db)
            db.execute(f"PRAGMA user_version = {migration_version}")
        db.commit()
    except sqlite3.Error:
        db.rollback()
        raise
    return target
