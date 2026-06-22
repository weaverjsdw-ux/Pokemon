"""Costco adapter behavior with mocked first-party endpoints."""
from __future__ import annotations

from scanner.retailers.base import Store
from scanner.retailers.costco import Costco


class FakeResp:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.headers = {}

    def json(self):
        return self._data


def _store() -> Store:
    return Store(
        retailer="Costco",
        store_id="347",
        name="Costco Fortune Park #347 - INDIANAPOLIS, IN",
        lat=39.91713441,
        lng=-86.22706503,
        city="INDIANAPOLIS",
        state="IN",
        postal_code="46268-3184",
    )


def _patch_inventory(monkeypatch, inventory_payload):
    monkeypatch.setattr("scanner.retailers.costco.time.sleep", lambda *_: None)
    captured = {"post_json": None, "dc_params": None}

    def fake_get(url, **kwargs):
        if "products/summary" in url:
            return FakeResp(
                {
                    "productData": [
                        {
                            "descriptions": [
                                {
                                    "languageKey": "en-US",
                                    "object": {
                                        "shortDescription": (
                                            "Pokemon TCG: Charizard ex Super-Premium Collection"
                                        )
                                    },
                                }
                            ],
                            "displayPrice": "$79.99",
                            "childCatalogData": [{"id": "1861371"}],
                        }
                    ]
                }
            )
        if "distributioncenters" in url:
            captured["dc_params"] = kwargs["params"]
            return FakeResp(
                {
                    "distributionCenters": ["725-wm"],
                    "groceryCenters": ["580-bd"],
                }
            )
        raise AssertionError(f"unexpected GET {url}")

    def fake_post(url, **kwargs):
        captured["post_json"] = kwargs["json"]
        return FakeResp(inventory_payload)

    monkeypatch.setattr("scanner.retailers.costco.requests.get", fake_get)
    monkeypatch.setattr("scanner.retailers.costco.requests.post", fake_post)
    return captured


def test_find_stores_parses_modern_costco_locator(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return FakeResp(
            {
                "warehouses": [
                    {
                        "warehouseId": "347",
                        "name": [{"value": "Fortune Park", "localeCode": "en-US"}],
                        "address": {
                            "line1": "9010 MICHIGAN RD",
                            "city": "INDIANAPOLIS",
                            "territory": "IN",
                            "postalCode": "46268-3184",
                            "latitude": 39.91713441,
                            "longitude": -86.22706503,
                        },
                    }
                ]
            }
        )

    monkeypatch.setattr("scanner.retailers.costco.requests.get", fake_get)

    stores = Costco().find_stores(39.7684, -86.1581, 20)

    assert captured["params"]["latitude"] == 39.7684
    assert captured["params"]["longitude"] == -86.1581
    assert captured["params"]["limit"] == 50
    assert captured["headers"]["client-identifier"]
    assert len(stores) == 1
    store = stores[0]
    assert store.store_id == "347"
    assert "Fortune Park" in store.name
    assert store.address == "9010 MICHIGAN RD"
    assert store.state == "IN"
    assert store.postal_code == "46268-3184"


def test_costco_inventory_reports_out_but_check_stays_positive_only(monkeypatch):
    captured = _patch_inventory(
        monkeypatch,
        {
            "inventoryLevels": [
                {
                    "itemNumber": "1861371",
                    "programTypes": {
                        "siteControlledInventory": {
                            "availability": "NOSTOCK",
                            "availableQuantity": 0,
                        }
                    },
                }
            ]
        },
    )
    products = {"charizard": {"name": "Charizard", "costco_item_id": "4000313298"}}
    retailer = Costco()

    assert list(retailer.check(products, [_store()])) == []
    inv = list(retailer.inventory(products, [_store()]))

    assert len(inv) == 1
    assert inv[0].status == "OUT"
    assert inv[0].price == "$79.99"
    assert captured["dc_params"] == {"destinationPostalCode": "46268", "stateCode": "IN"}
    assert captured["post_json"]["selectedWarehouse"] == "347"
    assert captured["post_json"]["itemNumbers"] == ["1861371"]
    assert "725-wm" in captured["post_json"]["distributionCenters"]
    assert "580-bd" in captured["post_json"]["distributionCenters"]


def test_costco_check_reports_in_stock_child_inventory(monkeypatch):
    captured = _patch_inventory(
        monkeypatch,
        {
            "inventoryLevels": [
                {
                    "itemNumber": "1861371",
                    "programTypes": {
                        "locationControlledInventory": {"availability": "INSTOCK"}
                    },
                }
            ]
        },
    )
    products = {"charizard": {"name": "Charizard", "costco_item_id": "4000313298"}}

    results = list(Costco().check(products, [_store()]))

    assert len(results) == 1
    assert results[0].status == "IN_STOCK"
    assert results[0].store.store_id == "347"
    assert results[0].product_name == "Pokemon TCG: Charizard ex Super-Premium Collection"
    assert "pokemon-tcg-charizard-ex-super-premium-collection" in results[0].url
    assert captured["post_json"]["itemNumbers"] == ["1861371"]


def test_costco_low_stock_maps_to_limited(monkeypatch):
    _patch_inventory(
        monkeypatch,
        {
            "inventoryLevels": [
                {
                    "itemNumber": "1861371",
                    "programTypes": {
                        "locationControlledInventory": {"availability": "LOWSTOCK"}
                    },
                }
            ]
        },
    )
    products = {"charizard": {"name": "Charizard", "costco_item_id": "4000313298"}}

    result = list(Costco().check(products, [_store()]))[0]

    assert result.status == "LIMITED"
