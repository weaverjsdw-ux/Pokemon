"""inventory() reports OUT / ONLINE_OUT so the web stock board shows real
state for online + GameStop adapters, while check() stays positives-only."""
from __future__ import annotations

from scanner.retailers.base import Store
from scanner.retailers.bestbuy import BestBuy
from scanner.retailers.gamestop import GameStop
from scanner.retailers.pokemoncenter import PokemonCenter


def _no_sleep(monkeypatch, module):
    monkeypatch.setattr(f"scanner.retailers.{module}.time.sleep", lambda *_: None)


def test_bestbuy_inventory_reports_online_out(monkeypatch):
    _no_sleep(monkeypatch, "bestbuy")

    class FakeResp:
        status_code = 200

        def json(self):
            return {"onlineAvailability": False, "salePrice": 49.99, "name": "Foo"}

    monkeypatch.setattr(
        "scanner.retailers.bestbuy.requests.get", lambda *a, **k: FakeResp()
    )
    retailer = BestBuy(api_key="k")
    products = {"foo": {"name": "Foo", "bestbuy_sku": "123"}}

    assert list(retailer.check(products, [])) == []
    inv = list(retailer.inventory(products, []))
    assert len(inv) == 1
    assert inv[0].status == "ONLINE_OUT"
    assert inv[0].product_name == "Foo"


def test_bestbuy_inventory_still_reports_in_stock(monkeypatch):
    _no_sleep(monkeypatch, "bestbuy")

    class FakeResp:
        status_code = 200

        def json(self):
            return {"onlineAvailability": True, "salePrice": 49.99, "url": "https://bb/x"}

    monkeypatch.setattr(
        "scanner.retailers.bestbuy.requests.get", lambda *a, **k: FakeResp()
    )
    retailer = BestBuy(api_key="k")
    products = {"foo": {"name": "Foo", "bestbuy_sku": "123"}}

    inv = list(retailer.inventory(products, []))
    assert inv[0].status == "ONLINE_IN_STOCK"
    assert inv[0].price == "$49.99"


def test_pokemoncenter_inventory_reports_online_out(monkeypatch):
    _no_sleep(monkeypatch, "pokemoncenter")

    class FakeResp:
        status_code = 200

        def json(self):
            return {"variants": [{"available": False}], "price": 5999}

    monkeypatch.setattr(
        "scanner.retailers.pokemoncenter.requests.get", lambda *a, **k: FakeResp()
    )
    retailer = PokemonCenter()
    products = {"foo": {"name": "Foo", "pokemoncenter_slug": "foo-slug"}}

    assert list(retailer.check(products, [])) == []
    inv = list(retailer.inventory(products, []))
    assert inv[0].status == "ONLINE_OUT"
    assert inv[0].price == "$59.99"


def test_gamestop_inventory_reports_out_per_store(monkeypatch):
    _no_sleep(monkeypatch, "gamestop")

    class FakeResp:
        status_code = 200
        text = "This item is out of stock at this store"

    monkeypatch.setattr(
        "scanner.retailers.gamestop.requests.get", lambda *a, **k: FakeResp()
    )
    store = Store("GameStop", "42", "GameStop #42", 39.0, -86.0)
    retailer = GameStop()
    products = {"foo": {"name": "Foo", "gamestop_pid": "pid-1"}}

    assert list(retailer.check(products, [store])) == []
    inv = list(retailer.inventory(products, [store]))
    assert len(inv) == 1
    assert inv[0].status == "OUT"
    assert inv[0].store is store
