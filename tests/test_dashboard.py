"""Dashboard renderers — no real HTTP, just the HTML-building functions."""
from __future__ import annotations

import sqlite3
import time

import pytest

from scanner import dashboard, migrations


@pytest.fixture
def db(tmp_path):
    db = sqlite3.connect(tmp_path / "x.db")
    migrations.apply(db)
    return db


def test_recent_hits_empty_shows_placeholder(db):
    html = dashboard._render_recent_hits(db)
    assert "No alerts logged yet" in html


def test_recent_hits_renders_rows(db):
    now = int(time.time())
    db.execute(
        "INSERT INTO hit_log(retailer, store_id, product_key, status, tier, "
        "url, price_cents, ts) VALUES (?,?,?,?,?,?,?,?)",
        ("target", "1234", "pe_etb", "IN_STOCK", "must_have",
         "https://target.com/x", 4999, now - 30),
    )
    db.commit()
    html = dashboard._render_recent_hits(db)
    assert "target" in html
    assert "pe_etb" in html
    assert "$49.99" in html
    assert "30s ago" in html


def test_render_health_empty():
    assert "No retailer activity" in dashboard._render_health({})


def test_render_health_disabled_pill():
    html = dashboard._render_health({
        "target": {"disabled": True, "requests_last_hour": 0, "fails": 7},
    })
    assert "DISABLED" in html
    assert "target" in html


def test_render_health_ok_pill():
    html = dashboard._render_health({
        "walmart": {"disabled": False, "requests_last_hour": 22, "fails": 0},
    })
    assert "OK" in html
    assert "22" in html


def test_render_products_empty(monkeypatch):
    from scanner import config as cfg_mod
    class FakeCfg: pass
    cfg = FakeCfg()
    cfg.products = {}
    cfg.products_filter = "all_sealed"
    html = dashboard._render_products(cfg)
    assert "No products selected" in html


def test_ago_formatting():
    assert dashboard._ago(15) == "15s ago"
    assert dashboard._ago(120) == "2m ago"
    assert dashboard._ago(7200) == "2h ago"
    assert dashboard._ago(172800) == "2d ago"
