"""Retailer registry sanity — every adapter imports cleanly and conforms
to the base interface. No network."""
from __future__ import annotations

from pathlib import Path

import yaml

from scanner.retailers import ALL
from scanner.retailers.bestbuy import BestBuy
from scanner.retailers.costco import Costco
from scanner.retailers.samsclub import SamsClub
from scanner.retailers.base import Retailer
from scanner.retailers.base import Store
from scanner.retailers.target import Target


def test_registry_is_non_empty():
    assert len(ALL) >= 1


def test_every_registered_retailer_subclasses_base():
    for slug, cls in ALL.items():
        assert issubclass(cls, Retailer), f"{slug} -> {cls} is not a Retailer"


def test_every_registered_retailer_has_a_name():
    for slug, cls in ALL.items():
        assert cls.name, f"{slug} -> {cls.__name__} has empty .name"


def test_retailer_can_be_instantiated_without_args():
    for slug, cls in ALL.items():
        r = cls()
        assert hasattr(r, "find_stores")
        assert hasattr(r, "check")


def test_example_config_retailers_are_registered():
    root = Path(__file__).resolve().parent.parent
    raw = yaml.safe_load((root / "config.example.yaml").read_text()) or {}
    configured = set((raw.get("retailers") or {}).keys())
    assert configured == set(ALL)


def test_bestbuy_requires_api_key_before_checking(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("BestBuy attempted network call without an API key")

    monkeypatch.setattr("scanner.retailers.bestbuy.requests.get", fail_if_called)
    retailer = BestBuy()
    products = {"foo": {"name": "Foo", "bestbuy_sku": "12345"}}
    assert list(retailer.check(products, [])) == []


def test_disabled_placeholder_adapters_are_noop():
    products = {
        "foo": {
            "name": "Foo",
            "costco_item_id": "12345",
            "samsclub_item_id": "67890",
        }
    }

    for cls in (Costco, SamsClub):
        retailer = cls()
        assert retailer.find_stores(39.0, -86.0, 10) == []
        assert list(retailer.check(products, [])) == []


def test_target_uses_in_store_stock_when_pickup_is_out(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "data": {
                    "product": {
                        "fulfillment": {
                            "store_options": [
                                {
                                    "store": {"store_id": "123"},
                                    "order_pickup": {"availability_status": "OUT_OF_STOCK"},
                                    "in_store_only": {"availability_status": "IN_STOCK"},
                                }
                            ]
                        }
                    }
                }
            }

    monkeypatch.setattr("scanner.retailers.target.requests.get", lambda *a, **k: FakeResponse())
    store = Store("Target", "123", "Target #123", 39.0, -86.0)
    result = Target()._check_one("999", store, {"name": "Foo"}, "foo", "https://example.test")

    assert result is not None
    assert result.status == "IN_STOCK"


def test_target_accepts_single_store_option_without_store_object(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "data": {
                    "product": {
                        "fulfillment": {
                            "store_options": [
                                {
                                    "order_pickup": {"availability_status": "UNAVAILABLE"},
                                    "in_store_only": {"availability_status": "OUT_OF_STOCK"},
                                }
                            ]
                        }
                    }
                }
            }

    monkeypatch.setattr("scanner.retailers.target.requests.get", lambda *a, **k: FakeResponse())
    store = Store("Target", "123", "Target #123", 39.0, -86.0)
    result = Target()._check_one(
        "999",
        store,
        {"name": "Foo"},
        "foo",
        "https://example.test",
        include_out=True,
    )

    assert result is not None
    assert result.status == "OUT"
    assert result.product_name == "Foo"


def test_target_inventory_includes_out_status_but_check_does_not(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "data": {
                    "product": {
                        "fulfillment": {
                            "store_options": [
                                {
                                    "store": {"store_id": "123"},
                                    "order_pickup": {"availability_status": "OUT_OF_STOCK"},
                                    "in_store_only": {"availability_status": "OUT_OF_STOCK"},
                                }
                            ]
                        }
                    }
                }
            }

    monkeypatch.setattr("scanner.retailers.target.requests.get", lambda *a, **k: FakeResponse())
    store = Store("Target", "123", "Target #123", 39.0, -86.0)
    products = {"foo": {"name": "Foo", "target_tcin": "999"}}

    assert list(Target().check(products, [store])) == []
    inventory = list(Target().inventory(products, [store]))

    assert inventory[0].status == "OUT"
    assert inventory[0].product_name == "Foo"


def test_target_find_stores_uses_place_and_geocodes_store_address(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": {
                    "nearby_stores": {
                        "stores": [
                            {
                                "store_id": "123",
                                "mailing_address": {
                                    "address_line1": "10 Main St",
                                    "city": "Indianapolis",
                                    "region": "IN",
                                    "postal_code": "46204",
                                },
                                "geographic_specifications": {},
                            }
                        ]
                    }
                }
            }

    def fake_get(url, **kwargs):
        captured.update(kwargs["params"])
        return FakeResponse()

    monkeypatch.setattr("scanner.retailers.target.requests.get", fake_get)
    monkeypatch.setattr("scanner.retailers.target.geocode", lambda address: (39.0, -86.0))

    stores = Target().find_stores(39.1, -86.1, 5)

    assert captured["place"] == "39.1,-86.1"
    assert captured["limit"] == 20
    assert stores[0].lat == 39.0
    assert stores[0].lng == -86.0
