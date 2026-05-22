"""Schema migrations: fresh DB, idempotency, partial upgrade."""
from __future__ import annotations

import sqlite3

from scanner import migrations


def test_fresh_db_advances_to_latest(tmp_path):
    db = sqlite3.connect(tmp_path / "x.db")
    final = migrations.apply(db)
    assert final == migrations.MIGRATIONS[-1][0]
    # All declared tables exist
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "last_alert" in tables
    assert "price_history" in tables
    assert "hit_log" in tables


def test_apply_is_idempotent(tmp_path):
    db = sqlite3.connect(tmp_path / "x.db")
    migrations.apply(db)
    v_first = migrations.current_version(db)
    migrations.apply(db)
    v_second = migrations.current_version(db)
    assert v_first == v_second


def test_partial_upgrade_runs_only_pending(tmp_path):
    db = sqlite3.connect(tmp_path / "x.db")
    # Simulate an old install at v1
    migrations._v1_initial_schema(db)
    db.execute("PRAGMA user_version = 1")
    db.commit()
    assert migrations.current_version(db) == 1
    migrations.apply(db)
    assert migrations.current_version(db) == migrations.MIGRATIONS[-1][0]
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert {"last_alert", "price_history", "hit_log"} <= tables


def test_existing_last_alert_data_preserved_through_migration(tmp_path):
    db = sqlite3.connect(tmp_path / "x.db")
    migrations._v1_initial_schema(db)
    db.execute("PRAGMA user_version = 1")
    db.execute(
        "INSERT INTO last_alert VALUES ('target', '1', 'k', 'IN_STOCK', 100)"
    )
    db.commit()
    migrations.apply(db)
    rows = db.execute("SELECT * FROM last_alert").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "target"
