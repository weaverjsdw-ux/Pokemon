"""Drop-pattern + per-store + feedback-quality analytics."""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone

import pytest

from scanner import analytics, migrations


@pytest.fixture
def db(tmp_path):
    db = sqlite3.connect(tmp_path / "x.db")
    migrations.apply(db)
    return db


def _add_hit(db, retailer, store_id, product_key, ts, hit_id=None):
    db.execute(
        "INSERT INTO hit_log(id, retailer, store_id, product_key, status, tier, "
        "url, price_cents, ts) VALUES (?,?,?,?,?,?,?,?,?)",
        (hit_id, retailer, store_id, product_key, "IN_STOCK", "nice_to_have",
         "", 4999, int(ts)),
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_histogram_buckets_by_weekday_and_hour(db):
    # Tuesday 2026-05-19 at 08:00 UTC
    ts = datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc).timestamp()
    for _ in range(3):
        _add_hit(db, "target", "1234", "k", ts)
    grids = analytics.drop_pattern_histogram(db, tz="UTC")
    assert grids["target"][1][8] == 3   # Tuesday, hour 8
    assert grids["target"][2][8] == 0


def test_histogram_respects_cutoff(db):
    old_ts = time.time() - 90 * 86400
    recent_ts = time.time() - 5 * 86400
    _add_hit(db, "target", "1", "k", old_ts)
    _add_hit(db, "target", "1", "k", recent_ts)
    grids = analytics.drop_pattern_histogram(db, days_back=30, tz="UTC")
    total = sum(sum(row) for row in grids["target"])
    assert total == 1


def test_suggest_drop_windows_emits_dense_blocks(db):
    base = datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc).timestamp()
    # 5 alerts spread across hours 8-9 on Tuesdays (3 weeks)
    for week in range(3):
        for hour_offset in range(2):
            _add_hit(db, "target", "1", "k", base + week * 7 * 86400 + hour_offset * 3600)
    suggestions = analytics.suggest_drop_windows(db, tz="UTC")
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s.retailer == "target"
    assert s.weekday == 1   # Tuesday
    assert s.start_hour == 8
    assert s.end_hour == 10
    assert s.sample_count >= 4


def test_suggest_drop_windows_requires_minimum_density(db):
    # Single alert -> no suggestion
    base = datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc).timestamp()
    _add_hit(db, "target", "1", "k", base)
    assert analytics.suggest_drop_windows(db, tz="UTC") == []


def test_per_store_hit_rate_orders_by_bought_then_hits(db):
    now = time.time()
    h1 = _add_hit(db, "target", "1", "k", now - 100)
    h2 = _add_hit(db, "target", "1", "k", now - 50)
    h3 = _add_hit(db, "target", "2", "k", now - 10)
    # Store 1 has 2 hits, store 2 has 1 hit + 1 'bought' feedback
    db.execute("INSERT INTO feedback(hit_id, verdict, ts) VALUES (?, 'bought', ?)",
               (h3, int(now)))
    db.commit()
    stats = analytics.per_store_hit_rate(db)
    assert stats[0].store_id == "2"   # bought wins over more hits
    assert stats[1].store_id == "1"


def test_feedback_quality_ratio(db):
    now = time.time()
    h1 = _add_hit(db, "walmart", "1", "k", now - 100)
    h2 = _add_hit(db, "walmart", "1", "k", now - 50)
    h3 = _add_hit(db, "walmart", "1", "k", now - 10)
    db.execute("INSERT INTO feedback(hit_id, verdict, ts) VALUES (?, 'bought', ?)",
               (h1, int(now)))
    db.execute("INSERT INTO feedback(hit_id, verdict, ts) VALUES (?, 'false', ?)",
               (h2, int(now)))
    db.commit()
    q = analytics.feedback_quality(db)
    assert q["walmart"]["alerts"] == 3
    assert q["walmart"]["bought"] == 1
    assert q["walmart"]["false"] == 1
    assert q["walmart"]["ratio"] == 1 / 3


def test_feedback_quality_handles_no_feedback(db):
    _add_hit(db, "target", "1", "k", time.time())
    q = analytics.feedback_quality(db)
    assert q["target"]["alerts"] == 1
    assert q["target"]["bought"] == 0
    assert q["target"]["ratio"] == 0.0
