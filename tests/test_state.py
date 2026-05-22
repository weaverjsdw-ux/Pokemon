"""State dedupe + backup."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from scanner import state as state_mod
from scanner.state import State, restore_latest


@pytest.fixture
def fresh_state(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "DB_PATH", tmp_path / "state.db")
    monkeypatch.setattr(state_mod, "BACKUP_DIR", tmp_path / "backups")
    return State(cooldown_seconds=60)


def test_first_alert_returns_true(fresh_state):
    assert fresh_state.should_alert("target", "1234", "etb", "IN_STOCK") is True


def test_same_status_within_cooldown_suppressed(fresh_state):
    fresh_state.should_alert("target", "1234", "etb", "IN_STOCK")
    assert fresh_state.should_alert("target", "1234", "etb", "IN_STOCK") is False


def test_status_change_fires_again(fresh_state):
    fresh_state.should_alert("target", "1234", "etb", "IN_STOCK")
    assert fresh_state.should_alert("target", "1234", "etb", "LIMITED") is True


def test_backup_writes_file(tmp_path, fresh_state):
    fresh_state.should_alert("target", "1234", "etb", "IN_STOCK")
    backup_path = fresh_state.maybe_backup(interval_seconds=0, keep=5)
    assert backup_path is not None
    assert backup_path.exists()
    # File is a valid SQLite DB with our row in it
    with sqlite3.connect(backup_path) as db:
        rows = db.execute("SELECT * FROM last_alert").fetchall()
    assert len(rows) == 1


def test_backup_respects_interval(tmp_path, fresh_state):
    first = fresh_state.maybe_backup(interval_seconds=0, keep=5)
    assert first is not None
    # Second call within interval — should be skipped
    second = fresh_state.maybe_backup(interval_seconds=24 * 3600, keep=5)
    assert second is None


def test_backup_prunes_to_keep_count(tmp_path, fresh_state, monkeypatch):
    bdir = tmp_path / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    # Create 5 stale backups, then trigger a real one with keep=3.
    base = int(time.time()) - 1000
    for i in range(5):
        f = bdir / f"state-2026010{i}T000000Z.db"
        f.touch()
    fresh_state.maybe_backup(interval_seconds=0, keep=3, backup_dir=bdir)
    remaining = sorted(bdir.glob("state-*.db"))
    assert len(remaining) == 3


def test_restore_latest_copies_file(tmp_path, fresh_state, monkeypatch):
    monkeypatch.setattr(state_mod, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(state_mod, "DB_PATH", tmp_path / "state.db")
    fresh_state.should_alert("target", "1234", "etb", "IN_STOCK")
    backup_path = fresh_state.maybe_backup(
        interval_seconds=0, keep=5, backup_dir=tmp_path / "backups"
    )
    # Wipe the live DB; restore should recreate it.
    (tmp_path / "state.db").unlink()
    src = restore_latest(
        target=tmp_path / "state.db",
        backup_dir=tmp_path / "backups",
    )
    assert src == backup_path
    assert (tmp_path / "state.db").exists()


def test_runtime_mute_round_trip(fresh_state):
    from scanner import state as state_mod
    assert state_mod.is_runtime_muted(fresh_state.db, "pe_etb") is False
    state_mod.set_runtime_mute(fresh_state.db, "pe_etb", True)
    assert state_mod.is_runtime_muted(fresh_state.db, "pe_etb") is True
    state_mod.set_runtime_mute(fresh_state.db, "pe_etb", False)
    assert state_mod.is_runtime_muted(fresh_state.db, "pe_etb") is False


def test_suppress_drop_blocks_subsequent_alert(fresh_state):
    from scanner import state as state_mod
    state_mod.suppress_drop(
        fresh_state.db, "target", "pe_etb", "1234",
        duration_seconds=3600, reason="bought",
    )
    assert state_mod.is_suppressed(fresh_state.db, "target", "pe_etb", "1234") is True
    # Different store -> not suppressed
    assert state_mod.is_suppressed(fresh_state.db, "target", "pe_etb", "9999") is False


def test_suppress_drop_expires(fresh_state):
    from scanner import state as state_mod
    state_mod.suppress_drop(
        fresh_state.db, "target", "pe_etb", "1234",
        duration_seconds=0,  # already expired
    )
    assert state_mod.is_suppressed(fresh_state.db, "target", "pe_etb", "1234") is False


def test_record_feedback_persists(fresh_state):
    from scanner import state as state_mod
    state_mod.record_feedback(fresh_state.db, hit_id=42, verdict="bought", note="x")
    rows = fresh_state.db.execute(
        "SELECT hit_id, verdict, note FROM feedback"
    ).fetchall()
    assert rows == [(42, "bought", "x")]


def test_restore_with_no_backups_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        restore_latest(
            target=tmp_path / "x.db",
            backup_dir=tmp_path / "empty",
        )
