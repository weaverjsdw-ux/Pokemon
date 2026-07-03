"""Slice 3: Slickdeals discovery adapter — fixture-proven against real HTML."""
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from scanner import confidence
from scanner.discovery.adapters import ALL as DISCOVERY_REGISTRY
from scanner.discovery.adapters import slickdeals as sd_mod
from scanner.discovery.adapters.slickdeals import Slickdeals

FIXTURES = Path("tests/fixtures/discovery")
POPULATED = (FIXTURES / "slickdeals_search_populated.html").read_text(encoding="utf-8")
EMPTY = (FIXTURES / "slickdeals_search_empty.html").read_text(encoding="utf-8")

CATALOG = {
    "prismatic_etb": {"name": "Prismatic Evolutions Elite Trainer Box",
                      "set": "Prismatic Evolutions", "type": "ETB", "msrp": "$49.99"},
}
SET_WATCH = ["Mega Evolution"]
CFG = SimpleNamespace()


def _discover(text=POPULATED, status=200, exc=None):
    adapter = Slickdeals()

    def fake_get(url, **kwargs):
        if exc is not None:
            raise exc
        return SimpleNamespace(status_code=status, text=text)

    return adapter, adapter.discover(CFG, CATALOG, SET_WATCH, http_get=fake_get)


def test_registry_exposes_wave1_slugs():
    assert set(DISCOVERY_REGISTRY) == {"target_search", "slickdeals",
                                       "ebay_browse", "trackalacker"}
    for slug, cls in DISCOVERY_REGISTRY.items():
        assert cls.slug == slug


def test_populated_fixture_parses_live_cards_with_exact_values():
    adapter, cands = _discover()
    assert adapter.state == confidence.WORKING
    # fixture holds 8 real cards: 6 expired (skipped), 2 live
    assert len(cands) == 2
    by_id = {c.listing_id: c for c in cands}
    mega_box = by_id["19710354"]
    assert mega_box.price == 49.99          # precise price from the title, not the rounded $50
    assert mega_box.retailer == "Walmart"
    assert mega_box.url.startswith("https://slickdeals.net/f/19710354-")
    assert "?" not in mega_box.url          # tracking query stripped
    assert mega_box.source == "slickdeals"
    assert mega_box.seen_at
    assert mega_box.evidence_excerpt and len(mega_box.evidence_excerpt) <= 200
    assert mega_box.matched_set == "Mega Evolution"      # Ring 2 via set watch
    deck = by_id["19650840"]
    assert deck.price == 27.95
    assert deck.retailer == "Amazon"
    assert deck.matched_product_key is None and deck.matched_set == ""


def test_expired_cards_are_never_candidates():
    _, cands = _discover()
    assert all(c.listing_id not in {"19704582"} for c in cands)   # known expired card


def test_empty_real_page_yields_zero_rows_and_parser_suspect():
    # the standing query should never return zero results — zero parsed cards
    # on HTTP 200 means parser drift, flagged, never crashed
    adapter, cands = _discover(text=EMPTY)
    assert cands == []
    assert adapter.state == confidence.PARSER_SUSPECT


def test_garbage_html_is_parser_suspect_not_a_crash():
    adapter, cands = _discover(text="<html><body>nothing here</body></html>")
    assert cands == []
    assert adapter.state == confidence.PARSER_SUSPECT


def test_blocked_status_maps_to_blocked_state():
    adapter, cands = _discover(status=403)
    assert cands == []
    assert adapter.state == confidence.BLOCKED


def test_transport_error_degrades_without_raising():
    adapter, cands = _discover(exc=requests.ConnectionError("boom"))
    assert cands == []
    assert adapter.state == confidence.DEGRADED


def test_stub_adapters_report_not_implemented():
    for slug in ("target_search", "trackalacker"):
        adapter = DISCOVERY_REGISTRY[slug]()
        result = adapter.discover(CFG, CATALOG, SET_WATCH)
        assert result == []
        assert adapter.state == confidence.NOT_IMPLEMENTED
        assert adapter.state_detail            # reason recorded, never silent
    assert DISCOVERY_REGISTRY["target_search"].requires == "playwright"


def test_card_price_prefers_figure_closest_to_displayed_price():
    # 'Reg. $50.49 ... now $49.99' with displayed '$50': the deal price wins,
    # not the first figure in the title
    assert sd_mod._card_price(
        "Pokemon ETB (Reg. $50.49) now $49.99", "50") == 49.99
    assert sd_mod._card_price(
        "Pokemon ETB was $59.99 now $49.99", "50") == 49.99
    # single agreeing figure still preferred over the rounded display
    assert sd_mod._card_price("Pokemon ETB $49.99", "50") == 49.99
    # no title figure -> displayed price
    assert sd_mod._card_price("Pokemon ETB great deal", "50") == 50.0
