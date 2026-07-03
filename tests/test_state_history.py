"""Restock memory: stock_history accumulation in State."""
from __future__ import annotations

from pathlib import Path

from scanner import state as state_mod
from scanner.state import State


def _state(tmp_path):
    return State(db_path=tmp_path / "state.db")


def test_first_observation_creates_history(tmp_path):
    s = _state(tmp_path)
    s.record_observation("target", "123", "booster", "OUT", ts=1000)
    h = s.history_for("target", "123", "booster")
    assert h["firstSeen"] == 1000
    assert h["lastSeen"] == 1000
    assert h["checkCount"] == 1
    assert h["inStockCount"] == 0
    assert h["lastInStockTs"] is None


def test_in_stock_counts_distinct_restocks_not_polls(tmp_path):
    s = _state(tmp_path)
    # OUT, then IN (restock #1), stays IN (still 1), OUT, then IN (restock #2)
    s.record_observation("target", "123", "booster", "OUT", ts=1000)
    s.record_observation("target", "123", "booster", "IN_STOCK", ts=1100)
    s.record_observation("target", "123", "booster", "IN_STOCK", ts=1200)
    s.record_observation("target", "123", "booster", "OUT", ts=1300)
    s.record_observation("target", "123", "booster", "IN_STOCK", ts=1400)
    h = s.history_for("target", "123", "booster")
    assert h["inStockCount"] == 2
    assert h["checkCount"] == 5
    assert h["lastInStockTs"] == 1400
    assert h["firstSeen"] == 1000
    assert h["lastSeen"] == 1400


def test_last_in_stock_ts_persists_when_back_out(tmp_path):
    s = _state(tmp_path)
    s.record_observation("target", "123", "booster", "IN_STOCK", ts=1000)
    assert s.history_for("target", "123", "booster")["lastInStockTs"] == 1000
    s.record_observation("target", "123", "booster", "OUT", ts=1100)
    assert s.history_for("target", "123", "booster")["lastInStockTs"] == 1000


def test_recent_restocks_orders_by_last_in_stock(tmp_path):
    s = _state(tmp_path)
    s.record_observation("target", "1", "a", "IN_STOCK", ts=1000)
    s.record_observation("walmart", "_online_", "b", "ONLINE_IN_STOCK", ts=3000)
    s.record_observation("target", "2", "c", "OUT", ts=2000)  # never in stock
    recent = s.recent_restocks(limit=10)
    keys = [r["productKey"] for r in recent]
    assert keys == ["b", "a"]  # c excluded (never in stock); b newest first
    assert recent[0]["retailer"] == "walmart"


def test_history_for_unknown_returns_none(tmp_path):
    s = _state(tmp_path)
    assert s.history_for("nope", "x", "y") is None


def test_source_health_snapshot_persists_between_state_instances(tmp_path):
    s = _state(tmp_path)
    row = {
        "slug": "target",
        "state": "degraded",
        "last_status": "BLOCKED",
        "last_detail": "last HTTP 403",
    }
    s.record_source_health_snapshot([row], ts=1234)

    fresh = _state(tmp_path)
    assert fresh.source_health_snapshot() == [row]


def test_default_state_falls_back_when_primary_db_cannot_open(tmp_path, monkeypatch):
    primary = tmp_path / "state.db"
    runtime = tmp_path / "state.runtime.db"
    real_connect = state_mod.sqlite3.connect

    def fake_connect(path, *args, **kwargs):
        if Path(path) == primary:
            raise state_mod.sqlite3.OperationalError("disk I/O error")
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(state_mod, "DB_PATH", primary)
    monkeypatch.setattr(state_mod, "RUNTIME_DB_PATH", runtime)
    monkeypatch.setattr(state_mod.sqlite3, "connect", fake_connect)

    s = State()

    assert s.db_path == runtime
    s.record_observation("target", "123", "booster", "OUT", ts=1000)
    assert s.history_for("target", "123", "booster")["lastStatus"] == "OUT"


def test_default_state_falls_back_when_primary_schema_init_fails(tmp_path, monkeypatch):
    primary = tmp_path / "state.db"
    runtime = tmp_path / "state.runtime.db"
    real_connect = state_mod.sqlite3.connect

    class FailingConnection:
        def execute(self, *args, **kwargs):
            raise state_mod.sqlite3.OperationalError("disk I/O error")

        def close(self):
            pass

    def fake_connect(path, *args, **kwargs):
        if Path(path) == primary:
            return FailingConnection()
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(state_mod, "DB_PATH", primary)
    monkeypatch.setattr(state_mod, "RUNTIME_DB_PATH", runtime)
    monkeypatch.setattr(state_mod.sqlite3, "connect", fake_connect)

    s = State()

    assert s.db_path == runtime
    s.record_observation("target", "123", "booster", "OUT", ts=1000)
    assert s.history_for("target", "123", "booster")["lastStatus"] == "OUT"


def test_comp_cache_roundtrip(tmp_path):
    from scanner.state import State
    state = State(db_path=tmp_path / "state.db")
    assert state.comp_cache_get("set|item|||") is None
    state.comp_cache_put("set|item|||", {"status": "ok", "estimate": "$10.00"}, ts=1000)
    payload, fetched_at = state.comp_cache_get("set|item|||")
    assert payload["estimate"] == "$10.00" and fetched_at == 1000
    state.comp_cache_put("set|item|||", {"status": "ok", "estimate": "$12.00"}, ts=2000)
    payload, fetched_at = state.comp_cache_get("set|item|||")
    assert payload["estimate"] == "$12.00" and fetched_at == 2000   # upsert, one row


def test_seen_listings_upsert_tracks_first_and_last_seen(tmp_path):
    s = State(db_path=tmp_path / "state.db")
    s.record_listing("slickdeals", "19710354", 49.99, "live", ts=1000)
    row = s.listing_history("slickdeals", "19710354")
    assert row == {"source": "slickdeals", "listingId": "19710354", "price": 49.99,
                   "status": "live", "firstSeen": 1000, "lastSeen": 1000}
    s.record_listing("slickdeals", "19710354", 44.99, "live", ts=2000)
    row = s.listing_history("slickdeals", "19710354")
    assert row["firstSeen"] == 1000          # first sighting preserved
    assert row["lastSeen"] == 2000
    assert row["price"] == 44.99             # latest price recorded


def test_listing_history_unknown_returns_none(tmp_path):
    s = State(db_path=tmp_path / "state.db")
    assert s.listing_history("slickdeals", "nope") is None
