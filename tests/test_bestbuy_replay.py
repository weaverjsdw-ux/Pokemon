"""Best Buy adapter replayed."""
from __future__ import annotations

from scanner.retailers.bestbuy import BestBuy
from scanner.retailers.base import Store

from .replay import Replay, json_resp


def _store():
    return Store(retailer="Best Buy", store_id="100", name="Best Buy 100 — A, B",
                 lat=39.78, lng=-89.65)


def test_in_stock_yields_result():
    payload = {"stores": [{"products": [{"sku": "6566943", "salePrice": 49.99, "name": "ETB"}]}]}
    client = Replay({
        ("GET", "https://api.bestbuy.com/v1/stores(storeId=100)+products(sku=6566943)"):
            json_resp(payload),
    })
    bb = BestBuy(http=client, api_key="x")
    result = bb._check_one("6566943", _store(), {"name": "ETB"}, "k", "u")
    assert result is not None
    assert result.status == "IN_STOCK"
    assert result.price == "$49.99"


def test_empty_stores_yields_none():
    client = Replay({
        ("GET", "https://api.bestbuy.com/v1/stores(storeId=100)+products(sku=6566943)"):
            json_resp({"stores": []}),
    })
    bb = BestBuy(http=client, api_key="x")
    assert bb._check_one("6566943", _store(), {}, "k", "u") is None


def test_store_present_but_no_product_yields_none():
    client = Replay({
        ("GET", "https://api.bestbuy.com/v1/stores(storeId=100)+products(sku=6566943)"):
            json_resp({"stores": [{"products": []}]}),
    })
    bb = BestBuy(http=client, api_key="x")
    assert bb._check_one("6566943", _store(), {}, "k", "u") is None


def test_check_skips_when_no_api_key():
    client = Replay({})  # any unscripted call raises
    bb = BestBuy(http=client, api_key="")
    # Iteration must terminate cleanly with no requests.
    results = list(bb.check({"k": {"bestbuy_sku": "6566943"}}, [_store()]))
    assert results == []
    assert client.calls == []
