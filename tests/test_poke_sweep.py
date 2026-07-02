from datetime import date

import pytest

from scanner import config as cfg_mod
from scanner import main as main_mod
from scanner.discovery import score, sweep
from scanner.discovery.schema import row_from_dict

PPT_URL = "https://www.tcgplayer.com/product/593355"
EBAY_URL = "https://www.ebay.com/sch/i.html?_nkw=fake+etb+sealed"

CATALOG = {
    "fake_etb": {"name": "Fake ETB", "set": "FakeSet", "type": "ETB", "msrp": "$49.99"},
    "fake_bundle": {"name": "Fake Bundle", "set": "FakeSet", "type": "Booster Bundle", "msrp": "$26.94"},
    "fake_box": {"name": "Fake Box", "set": "FakeSet", "type": "Surprise Box", "msrp": "$22.99"},
}


def _cfg(catalog=CATALOG, **poke):
    raw = {"locations": {"home": "A", "work": "B"}}
    if poke:
        raw["poke"] = poke
    cfg = cfg_mod.from_mapping(raw)
    cfg.products = dict(catalog)
    cfg.products_filter = None
    return cfg


def _verified_row(estimate="$199.14", confidence="medium"):
    return {"status": "ok", "estimate": estimate, "confidence": confidence,
            "source": "PokemonPriceTracker", "basis": "TCGplayer sealed market",
            "sourceUrl": PPT_URL, "url": PPT_URL}


def _est_row(estimate="$60.00"):
    return {"status": "ok", "estimate": estimate, "confidence": "medium",
            "source": "eBay Browse API", "basis": "active fixed-price asking median",
            "url": EBAY_URL}


def _build(cfg, lookup):
    return sweep.build_sealed_sweep(cfg, lookup, event="sealed",
                                    sweep_id="2026-07-01-sealed",
                                    captured_at="2026-07-01")


def test_verified_comp_maps_to_verified_row():
    swp = _build(_cfg(), lambda k, p: _verified_row())
    assert len(swp["deals"]) == 3
    for d in swp["deals"]:
        assert d["asset_class"] == "sealed"
        assert d["retailer"] == "MSRP"
        assert d["price_confidence"] == "verified"
        assert d["source_url"] == PPT_URL
        assert d["captured_at"] == "2026-07-01"
        assert "EST" not in d["badges"]
    by_item = {d["item"]: d for d in swp["deals"]}
    assert by_item["Fake ETB"]["category"] == "sealed-etb"
    assert by_item["Fake Bundle"]["category"] == "sealed-bundle"
    assert by_item["Fake Box"]["category"] == "sealed-other"
    assert swp["counts"] == {"scanned": 3, "comped": 3, "no_comp": 0,
                             "no_msrp": 0, "no_source": 0}


def test_fallback_comp_maps_to_est_with_attribution():
    swp = _build(_cfg(), lambda k, p: _est_row())
    for d in swp["deals"]:
        assert d["price_confidence"] == "est"
        assert "EST" in d["badges"]
        assert d["source_url"] == EBAY_URL       # search-page attribution
        assert "eBay Browse API" in d["derivation_method"]
        assert "STEAL" not in d["badges"]        # est never a confirmed STEAL


def test_low_confidence_ppt_comp_is_est_even_with_source_url():
    swp = _build(_cfg(), lambda k, p: _verified_row(confidence="low"))
    for d in swp["deals"]:
        assert d["price_confidence"] == "est"
        assert "EST" in d["badges"]


def test_no_comp_product_is_skipped_and_counted():
    def lookup(key, product):
        if key == "fake_etb":
            return {"status": "no_matches"}
        return _verified_row()
    swp = _build(_cfg(), lookup)
    assert len(swp["deals"]) == 2
    assert swp["counts"]["no_comp"] == 1
    assert all(d["item"] != "Fake ETB" for d in swp["deals"])


def test_missing_msrp_is_skipped_and_counted():
    catalog = dict(CATALOG)
    catalog["no_msrp"] = {"name": "No MSRP", "set": "FakeSet", "type": "ETB"}
    swp = _build(_cfg(catalog), lambda k, p: _verified_row())
    assert swp["counts"]["no_msrp"] == 1
    assert len(swp["deals"]) == 3


def test_unattributable_comp_is_skipped_and_counted():
    row = {"status": "ok", "estimate": "$60.00", "confidence": "medium",
           "source": "X", "basis": "y"}  # no sourceUrl, no url
    swp = _build(_cfg(), lambda k, p: row)
    assert len(swp["deals"]) == 0
    assert swp["counts"]["no_source"] == 3


def test_badges_lenses_and_verdict_pin_to_backbone():
    cfg = _cfg()
    comp_rows = {k: _verified_row() for k in CATALOG}
    swp = _build(cfg, lambda k, p: comp_rows[k])
    key_by_item = {p["name"]: k for k, p in CATALOG.items()}
    for d in swp["deals"]:
        row = row_from_dict(d)
        row.badges, row.lens_tags = [], []
        assert score.assign_badges(row, cfg) == d["badges"]
        assert score.lens_tags(row, cfg) == d["lens_tags"]
        key = key_by_item[d["item"]]
        expected = main_mod.verdict_for_alert(
            cfg, CATALOG[key], f"${d['deal_price']:.2f}", comp_rows[key])
        assert d["scanner_verdict"] == expected


def test_deals_sorted_by_pct_off_desc():
    def lookup(key, product):
        return {"fake_etb": _verified_row("$199.14"),      # ~75% off
                "fake_bundle": _verified_row("$30.00"),    # ~10% off
                "fake_box": _verified_row("$100.00")}[key]  # ~77% off
    swp = _build(_cfg(), lookup)
    pcts = [d["pct_off"] for d in swp["deals"]]
    assert pcts == sorted(pcts, reverse=True)


def test_sweep_dict_shape():
    swp = _build(_cfg(), lambda k, p: _verified_row())
    for key in ("event", "sweep_id", "captured_window", "notes", "deals",
                "promo_codes", "bundled_offers", "watchlist_results",
                "sources", "counts"):
        assert key in swp
    assert swp["promo_codes"] == []
    assert swp["bundled_offers"] == []
    assert swp["watchlist_results"] == []
    assert any(s["name"] == "PokemonPriceTracker" for s in swp["sources"])
