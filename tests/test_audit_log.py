"""Audit log endpoint rendering + pagination."""
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


def test_empty_log_shows_total(db):
    html = dashboard._render_audit_log(db, page=1)
    assert "No alerts" in html
    assert "Total in log: 0" in html


def test_renders_rows_with_data_labels(db):
    now = int(time.time())
    db.execute(
        "INSERT INTO hit_log(retailer, store_id, product_key, status, tier, "
        "url, price_cents, ts) VALUES (?,?,?,?,?,?,?,?)",
        ("target", "1234", "pe_etb", "IN_STOCK", "must_have",
         "https://target.com/x", 4999, now - 30),
    )
    db.commit()
    html = dashboard._render_audit_log(db, page=1)
    assert "target" in html
    assert "pe_etb" in html
    # Mobile-friendly: every cell carries a data-label
    assert "data-label=Retailer" in html
    assert "data-label=Product" in html


def test_pagination_links(db):
    now = int(time.time())
    for i in range(60):
        db.execute(
            "INSERT INTO hit_log(retailer, store_id, product_key, status, tier, "
            "url, price_cents, ts) VALUES (?,?,?,?,?,?,?,?)",
            ("target", "1", f"p{i}", "IN_STOCK", "fyi", "", 1000, now - i),
        )
    db.commit()
    page1 = dashboard._render_audit_log(db, page=1, page_size=20)
    assert "Older" in page1
    assert "Newer" not in page1
    page2 = dashboard._render_audit_log(db, page=2, page_size=20)
    assert "Newer" in page2
    assert "Older" in page2
    page3 = dashboard._render_audit_log(db, page=3, page_size=20)
    assert "Newer" in page3
    assert "Older" not in page3   # last page


def test_log_respects_page_size(db):
    now = int(time.time())
    for i in range(40):
        db.execute(
            "INSERT INTO hit_log(retailer, store_id, product_key, status, tier, "
            "url, price_cents, ts) VALUES (?,?,?,?,?,?,?,?)",
            ("walmart", "1", "k", "IN_STOCK", "fyi", "", 1000, now - i),
        )
    db.commit()
    html = dashboard._render_audit_log(db, page=1, page_size=10)
    assert "Showing 10 of 40" in html
