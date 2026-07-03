import json
import re
from pathlib import Path

import pytest

from scanner.discovery.render import _safe_href, nav_anchors, element_ids, render_sweep
from scanner.discovery.schema import StopGateError

SWEEP = json.loads(Path("data/poke/fixtures/sample-sweep.json").read_text(encoding="utf-8"))


def test_required_sections_present():
    html = render_sweep(SWEEP)
    for needle in ("Top Steals", "Watch Out", "Sources"):
        assert needle in html


def test_every_nav_anchor_resolves():
    html = render_sweep(SWEEP)
    ids = set(element_ids(html))
    for anchor in nav_anchors(html):
        assert anchor in ids, f"dangling nav anchor #{anchor}"


def test_every_deal_row_carries_source_and_date():
    html = render_sweep(SWEEP)
    rows = re.findall(r'data-source-url="([^"]*)"\s+data-captured-at="([^"]*)"', html)
    assert len(rows) >= 10
    assert all(src and date for src, date in rows)


def test_est_row_renders_est_badge_and_watch_out_reseal():
    html = render_sweep(SWEEP)
    assert "EST" in html
    assert "reseal" in html.lower()


def test_stop_gate_blocks_render_on_bad_row():
    bad = json.loads(json.dumps(SWEEP))
    bad["deals"][0]["source_url"] = ""   # verified row missing source
    with pytest.raises(StopGateError):
        render_sweep(bad)


def test_safe_href_allows_http_blocks_script_uris():
    assert _safe_href("https://example.com/x") == "https://example.com/x"
    assert _safe_href("http://example.com/x") == "http://example.com/x"
    assert _safe_href("javascript:alert(1)") == ""
    assert _safe_href("data:text/html,<script>alert(1)</script>") == ""
    assert _safe_href("") == ""


def test_deal_row_data_source_url_is_scheme_filtered():
    # An untrusted javascript: source_url must never reach the data-source-url
    # attribute either, not just the href. Use an "est" row so it passes the
    # STOP gate without needing a real source_url (verified rows require one).
    evil = json.loads(json.dumps(SWEEP))
    evil["deals"] = [{
        "item": "Suspect ETB",
        "set": "Prismatic Evolutions",
        "asset_class": "sealed",
        "category": "sealed-etb",
        "deal_price": 42.0,
        "market_comp": 60.0,
        "pct_off": 30,
        "retailer": "Marketplace seller",
        "source_url": "javascript:alert(1)",
        "captured_at": "2026-06-27",
        "price_confidence": "est",
        "comp_confidence": "low",
        "derivation_method": "comp_inference",
        "badges": ["EST"],
        "lens_tags": [],
        "stock_status": "unknown",
    }]
    html = render_sweep(evil)
    assert 'data-source-url=""' in html
    assert 'href=""' in html
    assert "javascript:alert" not in html


def _stocked_row(**kw):
    row = {
        "item": "Verified ETB", "set": "FakeSet", "asset_class": "sealed",
        "category": "sealed-etb", "deal_price": 39.99, "market_comp": 60.0,
        "pct_off": 33, "retailer": "Walmart",
        "source_url": "https://www.tcgplayer.com/product/1",
        "captured_at": "2026-07-01", "price_confidence": "verified",
        "comp_confidence": "high", "badges": [], "lens_tags": [],
        "stock_status": "in_stock",
        "stock_evidence": "walmart adapter: status=ONLINE_IN_STOCK price=$39.99",
        "buy_url": "https://www.walmart.com/ip/123",
        "stock_checked_at": "2026-07-01T09:00:00",
        "stock_method": "retailer_adapter:walmart",
    }
    row.update(kw)
    return row


def _render_with(row):
    swp = json.loads(json.dumps(SWEEP))
    swp["deals"] = [row]
    return render_sweep(swp)


def test_stock_column_renders_status_evidence_and_buy_link():
    html = _render_with(_stocked_row())
    assert "<th>Stock</th>" in html
    assert "in stock" in html
    assert "status=ONLINE_IN_STOCK" in html        # evidence visible to operator
    assert 'href="https://www.walmart.com/ip/123"' in html
    assert "2026-07-01T09:00:00" in html


def test_stock_column_unknown_renders_muted_not_positive():
    html = _render_with(_stocked_row(stock_status="unknown", stock_evidence="",
                                     buy_url="", stock_checked_at="",
                                     stock_method=""))
    assert "<th>Stock</th>" in html
    assert "stock-unknown" in html
    assert "buy</a>" not in html


def test_buy_url_is_scheme_filtered_like_source_url():
    # untrusted buy_url must never become a clickable javascript: href
    html = _render_with(_stocked_row(buy_url="javascript:alert(1)"))
    assert "javascript:alert" not in html


def test_buyable_now_section_present_and_positive_only():
    from scanner.discovery.render import section_html
    swp = json.loads(json.dumps(SWEEP))
    swp["deals"] = [
        _stocked_row(item="Verified ETB"),
        _stocked_row(item="Unknown ETB", stock_status="unknown", stock_evidence="",
                     buy_url="", stock_checked_at="", stock_method=""),
    ]
    html = render_sweep(swp)
    assert 'id="buyable-now"' in html
    sec = section_html(html, "buyable-now")
    assert "Verified ETB" in sec        # positive-verified stock shown at the top
    assert "Unknown ETB" not in sec     # unknown-stock excluded from Buyable now


def test_buyable_now_shows_weak_comp_verified_row_labeled_not_hidden():
    from scanner.discovery.render import section_html
    swp = json.loads(json.dumps(SWEEP))
    swp["deals"] = [_stocked_row(item="Weak Comp ETB", price_confidence="est",
                                 comp_confidence="low", derivation_method="comp_inference",
                                 badges=["EST"], source_url="https://ex.com/x")]
    html = render_sweep(swp)
    sec = section_html(html, "buyable-now")
    assert "Weak Comp ETB" in sec       # a weak-comp verified-stock row is NOT hidden
    assert "EST" in sec                 # it is labeled honestly


def test_buyable_now_empty_still_renders_section():
    from scanner.discovery.render import section_html
    swp = json.loads(json.dumps(SWEEP))
    swp["deals"] = [_stocked_row(stock_status="unknown", stock_evidence="", buy_url="",
                                 stock_checked_at="", stock_method="")]
    html = render_sweep(swp)
    assert 'id="buyable-now"' in html   # section (and its nav anchor) always exists
    assert "None this sweep" in section_html(html, "buyable-now")


def test_render_drops_javascript_uri_from_href():
    # An untrusted javascript: source_url must never become a clickable href.
    # (deal_price is a string-ish javascript payload only in source_url; the row
    #  is otherwise valid so it passes the STOP gate and reaches render.)
    evil = json.loads(json.dumps(SWEEP))
    evil["promo_codes"][0]["source_url"] = "javascript:alert(document.cookie)"
    html = render_sweep(evil)
    assert "javascript:alert" not in html
