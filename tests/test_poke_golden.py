import json
from pathlib import Path

from scanner import config as cfg_mod
from scanner.discovery.golden import golden_check
from scanner.discovery.render import render_sweep

SWEEP = json.loads(Path("data/poke/fixtures/sample-sweep.json").read_text(encoding="utf-8"))
CFG = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})


def test_golden_passes_on_fixture():
    html = render_sweep(SWEEP)
    assert golden_check(html, CFG.poke.min_rows) == []


def test_golden_fails_on_missing_section():
    html = render_sweep(SWEEP).replace("Sources", "Srcs")
    fails = golden_check(html, CFG.poke.min_rows)
    assert any("Sources" in f for f in fails)


def test_golden_fails_on_dangling_anchor():
    html = render_sweep(SWEEP) + '<a href="#nope-nope"></a>'
    fails = golden_check(html, CFG.poke.min_rows)
    assert any("nope-nope" in f for f in fails)


def test_golden_fails_below_row_floor():
    html = render_sweep(SWEEP)
    fails = golden_check(html, min_rows=999)
    assert any("acquisition failure" in f for f in fails)


def _positive_row(**kw):
    row = {
        "item": "Verified ETB", "set": "FakeSet", "asset_class": "sealed",
        "category": "sealed-etb", "deal_price": 39.99, "market_comp": 60.0,
        "pct_off": 33, "retailer": "Walmart",
        "source_url": "https://www.tcgplayer.com/product/1", "captured_at": "2026-07-01",
        "price_confidence": "verified", "comp_confidence": "high", "badges": [],
        "lens_tags": [], "stock_status": "in_stock",
        "stock_evidence": "walmart adapter: status=ONLINE_IN_STOCK price=$39.99",
        "buy_url": "https://www.walmart.com/ip/123",
        "stock_checked_at": "2026-07-01T09:00:00",
        "stock_method": "retailer_adapter:walmart",
    }
    row.update(kw)
    return row


def test_golden_passes_with_evidenced_buyable_row():
    swp = json.loads(json.dumps(SWEEP))
    swp["deals"] = [_positive_row()]
    html = render_sweep(swp)
    assert golden_check(html, min_rows=0) == []


def test_golden_fails_if_buyable_row_lacks_evidence():
    """Belt over the STOP-gate suspenders: even if a bad row reached the Buyable
    now section, golden must catch a row without positive stock evidence."""
    from scanner.discovery.render import section_html
    swp = json.loads(json.dumps(SWEEP))
    swp["deals"] = [_positive_row()]
    html = render_sweep(swp)
    sec = section_html(html, "buyable-now")
    tampered = html.replace(sec, sec.replace("stock-in_stock", "stock-unknown"))
    fails = golden_check(tampered, min_rows=0)
    assert any("buyable" in f.lower() for f in fails)
