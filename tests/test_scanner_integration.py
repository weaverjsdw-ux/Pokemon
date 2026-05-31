"""Scanner pass integration between retailer results, state, and notifications."""
from __future__ import annotations

from scanner.config import Config, RetailerCfg
from scanner.main import run_pass
from scanner.retailers.base import Retailer, StockResult, Store


def _cfg() -> Config:
    return Config(
        home_address="1 Home St",
        work_address="2 Work Ave",
        route_radius_miles=4,
        routing_engine="osrm",
        google_api_key="",
        retailers={"fake": RetailerCfg(enabled=True, api_key="secret")},
        poll_interval_seconds=180,
        discord_webhook="",
        ntfy_topic="",
        products_filter="all_sealed",
        products={"booster": {"name": "Booster Box", "fake_sku": "sku-1"}},
    )


class FakeRetailer(Retailer):
    name = "Fake Mart"
    product_id_fields = ("fake_sku",)
    seen_api_keys: list[str] = []
    seen_products: list[dict[str, dict[str, str]]] = []
    seen_stores: list[list[Store]] = []
    results: list[StockResult] = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.seen_api_keys.append(kwargs.get("api_key", ""))

    def check(self, products, stores):
        self.seen_products.append(products)
        self.seen_stores.append(stores)
        yield from self.results


class RecordingState:
    def __init__(self, decisions: list[bool]):
        self.decisions = decisions
        self.calls: list[tuple[str, str, str, str]] = []

    def should_alert(self, retailer: str, store_id: str, product_key: str, status: str) -> bool:
        self.calls.append((retailer, store_id, product_key, status))
        return self.decisions.pop(0)


class RecordingNotifier:
    def __init__(self):
        self.alerts = []

    def send(self, alert):
        self.alerts.append(alert)


def test_run_pass_turns_store_stock_result_into_user_alert(monkeypatch):
    store = Store("Fake Mart", "store-1", "Fake Mart #1", 39.0, -86.0, distance_miles=1.25)
    FakeRetailer.seen_api_keys = []
    FakeRetailer.seen_products = []
    FakeRetailer.seen_stores = []
    FakeRetailer.results = [
        StockResult(
            store=store,
            product_key="booster",
            product_name="Booster Box",
            status="IN_STOCK",
            url="https://example.test/booster",
            price="$49.99",
        )
    ]
    monkeypatch.setattr("scanner.main.RETAILER_REGISTRY", {"fake": FakeRetailer})

    state = RecordingState([True])
    notifier = RecordingNotifier()

    run_pass(_cfg(), {"fake": [store]}, state, notifier)

    assert FakeRetailer.seen_api_keys == ["secret"]
    assert FakeRetailer.seen_products == [{"booster": {"name": "Booster Box", "fake_sku": "sku-1"}}]
    assert FakeRetailer.seen_stores == [[store]]
    assert state.calls == [("fake", "store-1", "booster", "IN_STOCK")]
    assert len(notifier.alerts) == 1
    alert = notifier.alerts[0]
    assert alert.retailer == "Fake Mart"
    assert alert.product_name == "Booster Box"
    assert alert.store_label == "Fake Mart #1"
    assert alert.distance_miles == 1.25
    assert alert.status == "IN_STOCK"
    assert alert.url == "https://example.test/booster"
    assert alert.price == "$49.99"


def test_run_pass_suppresses_notification_when_state_blocks_repeat(monkeypatch):
    FakeRetailer.results = [
        StockResult(
            store=None,
            product_key="booster",
            product_name="Booster Box",
            status="ONLINE_IN_STOCK",
            url="https://example.test/online",
        )
    ]
    monkeypatch.setattr("scanner.main.RETAILER_REGISTRY", {"fake": FakeRetailer})

    state = RecordingState([False])
    notifier = RecordingNotifier()

    run_pass(_cfg(), {"fake": []}, state, notifier)

    assert state.calls == [("fake", "_online_", "booster", "ONLINE_IN_STOCK")]
    assert notifier.alerts == []
