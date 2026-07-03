"""Slice 3: eBay Browse discovery adapter — keyset-gated, recorded-shape JSON.

A live-recorded Browse payload is impossible until the operator provisions the
keyset; these payloads mirror the Browse item_summary shape already pinned in
tests/test_resale.py (itemSummaries / price.value / shippingOptions) plus the
itemId/itemWebUrl fields real responses carry.
"""
from types import SimpleNamespace

import requests

from scanner import confidence
from scanner.discovery.adapters.ebay_browse import EbayBrowse

CATALOG = {
    "prismatic_etb": {"name": "Prismatic Evolutions Elite Trainer Box",
                      "set": "Prismatic Evolutions", "type": "ETB", "msrp": "$49.99"},
}
SET_WATCH = ["Prismatic Evolutions"]

NO_KEYSET_CFG = SimpleNamespace(
    ebay_browse_api_token="", ebay_client_id="", ebay_client_secret="",
    ebay_marketplace_id="EBAY_US")


def _item(item_id, title, price, shipping="0.00", url=None):
    return {
        "itemId": item_id,
        "title": title,
        "itemWebUrl": url or f"https://www.ebay.com/itm/{item_id}",
        "price": {"value": price, "currency": "USD"},
        "shippingOptions": [{"shippingCost": {"value": shipping, "currency": "USD"}}],
    }


PAYLOAD = {"itemSummaries": [
    _item("v1|111|0", "Pokemon TCG Prismatic Evolutions Elite Trainer Box Sealed",
          "89.99", "5.00"),
    _item("v1|222|0", "Pokemon Prismatic Evolutions Booster Bundle Sealed", "45.00"),
    _item("v1|333|0", "Pokemon Prismatic Evolutions ETB EMPTY BOX", "9.99"),
    _item("v1|444|0", "Pokemon Prismatic Evolutions ETB Japanese", "59.99"),
]}


def test_without_keyset_reports_needs_api_key_and_yields_nothing():
    adapter = EbayBrowse()
    out = adapter.discover(NO_KEYSET_CFG, CATALOG, SET_WATCH)
    assert out == []
    assert adapter.state == confidence.NEEDS_API_KEY
    assert "keyset" in adapter.state_detail


def test_recorded_payload_parses_to_candidates_with_junk_dropped():
    adapter = EbayBrowse()
    out = adapter.discover(NO_KEYSET_CFG, CATALOG, SET_WATCH,
                           search_fn=lambda q: PAYLOAD)
    assert adapter.state == confidence.WORKING
    assert [c.listing_id for c in out] == ["v1|111|0", "v1|222|0"]   # junk dropped
    etb = out[0]
    assert etb.matched_product_key == "prismatic_etb"                # Ring 1
    assert etb.price == 89.99 and etb.shipping == 5.0
    assert etb.url == "https://www.ebay.com/itm/v1|111|0"
    assert etb.retailer == "eBay" and etb.source == "ebay_browse"
    assert etb.seen_at and etb.evidence_excerpt
    bundle = out[1]
    assert bundle.matched_product_key is None
    assert bundle.matched_set == "Prismatic Evolutions"              # Ring 2


def test_priceless_or_linkless_items_never_become_candidates():
    payload = {"itemSummaries": [
        {"itemId": "v1|5|0", "title": "Pokemon Prismatic Evolutions ETB",
         "itemWebUrl": "https://www.ebay.com/itm/5", "price": {}},
        {"itemId": "v1|6|0", "title": "Pokemon Prismatic Evolutions ETB",
         "price": {"value": "50.00"}},
    ]}
    adapter = EbayBrowse()
    out = adapter.discover(NO_KEYSET_CFG, CATALOG, SET_WATCH,
                           search_fn=lambda q: payload)
    assert out == []


def test_query_errors_degrade_without_raising():
    def boom(query):
        raise requests.ConnectionError("api down")
    adapter = EbayBrowse()
    out = adapter.discover(NO_KEYSET_CFG, CATALOG, SET_WATCH, search_fn=boom)
    assert out == []
    assert adapter.state == confidence.DEGRADED
    assert "api down" in adapter.state_detail
