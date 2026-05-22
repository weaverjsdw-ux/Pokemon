"""Dashboard renderers + interactive actions. No real HTTP server."""
from __future__ import annotations

import sqlite3
import time
from unittest.mock import MagicMock

import pytest

from scanner import dashboard, migrations, state as state_mod


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
    assert any(f"{n}s ago" in html for n in (29, 30, 31, 32))
    assert "Bought it" in html
    assert "False alert" in html


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


def test_render_products_empty(db):
    class FakeCfg: pass
    cfg = FakeCfg()
    cfg.products = {}
    cfg.products_filter = "all_sealed"
    html = dashboard._render_products(cfg, db)
    assert "No products selected" in html


def test_render_products_renders_mute_actions(db):
    class FakeCfg: pass
    cfg = FakeCfg()
    cfg.products = {"a": {"name": "A", "set": "S", "type": "T"}}
    cfg.products_filter = "all_sealed"
    html = dashboard._render_products(cfg, db)
    assert "Mute" in html and "Unmute" not in html


def test_render_products_shows_unmute_when_runtime_muted(db):
    state_mod.set_runtime_mute(db, "a", True)
    class FakeCfg: pass
    cfg = FakeCfg()
    cfg.products = {"a": {"name": "A"}}
    cfg.products_filter = "all_sealed"
    html = dashboard._render_products(cfg, db)
    assert "Unmute" in html
    assert "dashboard" in html  # the pill text


def test_render_products_locked_by_file_mute(db):
    class FakeCfg: pass
    cfg = FakeCfg()
    cfg.products = {"a": {"name": "A", "mute": True}}
    cfg.products_filter = "all_sealed"
    html = dashboard._render_products(cfg, db)
    assert "edit products.yaml" in html
    # File mute pill, not dashboard pill
    assert "file</span>" in html


def test_ago_formatting():
    assert dashboard._ago(15) == "15s ago"
    assert dashboard._ago(120) == "2m ago"
    assert dashboard._ago(7200) == "2h ago"
    assert dashboard._ago(172800) == "2d ago"


def test_authorized_open_when_no_token():
    h = MagicMock(spec=dashboard._Handler)
    h.token = ""
    h.headers = {}
    assert dashboard._Handler._authorized(h) is True


def test_authorized_rejects_bad_token():
    h = MagicMock(spec=dashboard._Handler)
    h.token = "secret"
    h.headers = {"X-Dashboard-Token": "wrong"}
    assert dashboard._Handler._authorized(h) is False


def test_authorized_accepts_matching_token():
    h = MagicMock(spec=dashboard._Handler)
    h.token = "secret"
    h.headers = {"X-Dashboard-Token": "secret"}
    assert dashboard._Handler._authorized(h) is True
