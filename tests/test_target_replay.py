"""Target adapter replayed against frozen response shapes."""
from __future__ import annotations

from scanner.retailers.target import Target
from scanner.retailers.base import Store

from .replay import Replay, json_resp


def _store():
    return Store(retailer="Target", store_id="1234", name="Target #1234 — Springfield, IL",
                 lat=39.78, lng=-89.65, distance_miles=1.2)


def test_in_stock_yields_result():
    payload = {
        "data": {
            "product": {
                "fulfillment": {
                    "store_options": [{
                        "store": {"store_id": "1234"},
                        "order_pickup": {"availability_status": "IN_STOCK"},
                    }]
                }
            }
        }
    }
    client = Replay({
        ("GET", "https://redsky.target.com/redsky_aggregations/v1/web/product_fulfillment_v1"):
            json_resp(payload),
    })
    t = Target(http=client)
    result = t._check_one("93954435", _store(), {"name": "PE ETB"}, "pe_etb",
                          "https://www.target.com/p/A-93954435")
    assert result is not None
    assert result.status == "IN_STOCK"
    assert result.cart_url == "https://www.target.com/co-cart?addToCart=93954435"


def test_limited_stock_yields_limited():
    payload = {
        "data": {"product": {"fulfillment": {"store_options": [{
            "store": {"store_id": "1234"},
            "order_pickup": {"availability_status": "LIMITED_STOCK"},
        }]}}}
    }
    client = Replay({
        ("GET", "https://redsky.target.com/redsky_aggregations/v1/web/product_fulfillment_v1"):
            json_resp(payload),
    })
    t = Target(http=client)
    result = t._check_one("x", _store(), {}, "k", "u")
    assert result is not None
    assert result.status == "LIMITED"


def test_out_returns_none():
    payload = {
        "data": {"product": {"fulfillment": {"store_options": [{
            "store": {"store_id": "1234"},
            "order_pickup": {"availability_status": "OUT_OF_STOCK"},
        }]}}}
    }
    client = Replay({
        ("GET", "https://redsky.target.com/redsky_aggregations/v1/web/product_fulfillment_v1"):
            json_resp(payload),
    })
    t = Target(http=client)
    assert t._check_one("x", _store(), {}, "k", "u") is None


def test_missing_store_in_options_returns_none():
    payload = {
        "data": {"product": {"fulfillment": {"store_options": [{
            "store": {"store_id": "9999"},  # different store
            "order_pickup": {"availability_status": "IN_STOCK"},
        }]}}}
    }
    client = Replay({
        ("GET", "https://redsky.target.com/redsky_aggregations/v1/web/product_fulfillment_v1"):
            json_resp(payload),
    })
    t = Target(http=client)
    assert t._check_one("x", _store(), {}, "k", "u") is None


def test_4xx_returns_none_gracefully():
    client = Replay({
        ("GET", "https://redsky.target.com/redsky_aggregations/v1/web/product_fulfillment_v1"):
            json_resp({}, status=404),
    })
    t = Target(http=client)
    assert t._check_one("x", _store(), {}, "k", "u") is None


def test_store_search_parses_nearby_stores():
    payload = {
        "data": {
            "nearby_stores": {
                "stores": [
                    {
                        "store_id": 1234,
                        "geographic_specifications": {"latitude": 39.78, "longitude": -89.65},
                        "mailing_address": {"city": "Springfield", "state": "IL"},
                    }
                ]
            }
        }
    }
    client = Replay({
        ("GET", "https://redsky.target.com/redsky_aggregations/v1/web/nearby_stores_v1"):
            json_resp(payload),
    })
    t = Target(http=client)
    stores = t.find_stores(39.78, -89.65, 10)
    assert len(stores) == 1
    assert stores[0].store_id == "1234"
    assert "Springfield" in stores[0].name
