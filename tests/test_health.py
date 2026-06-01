"""Scanner health registry: state transitions and run_pass integration."""
from __future__ import annotations

import pytest

from scanner import health
from scanner.config import Config, RetailerCfg
from scanner.main import _safe_health_detail, run_pass
from scanner.retailers.base import Retailer, StockResult, Store


@pytest.fixture(autouse=True)
def _clean_registry():
    health.reset()
    yield
    health.reset()


def _h(slug="target"):
    return next(h for h in health.snapshot() if h["slug"] == slug)


def test_unknown_until_first_check():
    assert health.snapshot() == []


def test_success_marks_healthy():
    health.record_check("target")
    health.record_success("target", items=3)
    h = _h()
    assert h["state"] == "healthy"
    assert h["last_status"] == "OK"
    assert h["last_items_found"] == 3
    assert h["total_successes"] == 1


def test_one_failure_is_degraded_then_down_after_threshold():
    health.record_success("target", items=1)  # establish a prior success
    health.record_failure("target", "BLOCKED", "403")
    assert _h()["state"] == "degraded"
    health.record_failure("target", "BLOCKED", "403")
    health.record_failure("target", "BLOCKED", "403")
    assert _h()["state"] == "down"
    assert _h()["consecutive_failures"] == 3


def test_first_failure_without_prior_success_is_degraded_not_down():
    health.record_check("target")
    health.record_failure("target", "BLOCKED", "403")
    assert _h()["state"] == "degraded"


def test_safe_health_detail_redacts_url_query_strings():
    detail = (
        "403 Client Error for url: "
        "https://redsky.target.com/path?key=secret&visitor_id=abc"
    )
    safe = _safe_health_detail(detail)
    assert safe == "403 Client Error for url: https://redsky.target.com/path?..."
    assert "secret" not in safe
    assert "visitor_id" not in safe


def test_success_resets_consecutive_failures():
    health.record_failure("target", "ERROR", "boom")
    health.record_failure("target", "ERROR", "boom")
    health.record_success("target", items=2)
    h = _h()
    assert h["consecutive_failures"] == 0
    assert h["state"] == "healthy"


# ---- run_pass integration -------------------------------------------------

def _cfg():
    return Config(
        home_address="h",
        work_address="w",
        route_radius_miles=4,
        routing_engine="osrm",
        google_api_key="",
        retailers={"fake": RetailerCfg(enabled=True)},
        poll_interval_seconds=180,
        discord_webhook="",
        ntfy_topic="",
        products_filter="all_sealed",
        products={"booster": {"name": "Booster", "fake_sku": "sku-1"}},
    )


class _AlwaysState:
    def should_alert(self, *a):
        return False

    def record_observation(self, *a, **k):
        pass

    def history_for(self, *a):
        return None


class _NullNotifier:
    def send(self, alert):
        pass


def test_run_pass_records_success_for_productive_retailer(monkeypatch):
    store = Store("Fake", "s1", "Fake #1", 39.0, -86.0)

    class FakeRetailer(Retailer):
        name = "Fake Mart"
        product_id_fields = ("fake_sku",)

        def inventory(self, products, stores):
            yield StockResult(store=store, product_key="booster",
                              product_name="Booster", status="IN_STOCK", url="u")

    monkeypatch.setattr("scanner.main.RETAILER_REGISTRY", {"fake": FakeRetailer})
    run_pass(_cfg(), {"fake": [store]}, _AlwaysState(), _NullNotifier())
    assert _h("fake")["last_status"] == "OK"


def test_run_pass_flags_no_data_when_queryable_but_empty(monkeypatch):
    """Has IDs + stores but yields nothing -> parser-broken signal, not silence."""
    store = Store("Fake", "s1", "Fake #1", 39.0, -86.0)

    class EmptyRetailer(Retailer):
        name = "Empty Mart"
        product_id_fields = ("fake_sku",)

        def inventory(self, products, stores):
            return iter(())

    monkeypatch.setattr("scanner.main.RETAILER_REGISTRY", {"fake": EmptyRetailer})
    run_pass(_cfg(), {"fake": [store]}, _AlwaysState(), _NullNotifier())
    h = _h("fake")
    assert h["last_status"] == "NO_DATA"
    assert h["state"] in {"degraded", "down"}


def test_run_pass_flags_empty_result_with_http_403_as_blocked(monkeypatch):
    """A blocked endpoint should not look like parser drift or unknown stock."""
    store = Store("Fake", "s1", "Fake #1", 39.0, -86.0)

    class BlockedRetailer(Retailer):
        name = "Blocked Mart"
        product_id_fields = ("fake_sku",)

        def inventory(self, products, stores):
            health.note_http_status("fake", 403)
            return iter(())

    monkeypatch.setattr("scanner.main.RETAILER_REGISTRY", {"fake": BlockedRetailer})
    run_pass(_cfg(), {"fake": [store]}, _AlwaysState(), _NullNotifier())
    h = _h("fake")
    assert h["last_status"] == "BLOCKED"
    assert "HTTP 403" in h["last_detail"]


def test_run_pass_does_not_overwrite_discovery_failure_for_unqueryable_store_retailer(monkeypatch):
    class RouteRetailer(Retailer):
        name = "Route Mart"
        product_id_fields = ("fake_sku",)

        def inventory(self, products, stores):
            return iter(())

    monkeypatch.setattr("scanner.main.RETAILER_REGISTRY", {"fake": RouteRetailer})
    health.record_failure("fake", "DISCOVERY_FAILED", "403")

    run_pass(_cfg(), {"fake": []}, _AlwaysState(), _NullNotifier())

    h = _h("fake")
    assert h["last_status"] == "DISCOVERY_FAILED"
    assert h["last_detail"] == "403"


def test_run_pass_records_error_when_adapter_raises(monkeypatch):
    store = Store("Fake", "s1", "Fake #1", 39.0, -86.0)

    class BoomRetailer(Retailer):
        name = "Boom Mart"
        product_id_fields = ("fake_sku",)

        def inventory(self, products, stores):
            raise RuntimeError("kaboom")
            yield  # pragma: no cover

    monkeypatch.setattr("scanner.main.RETAILER_REGISTRY", {"fake": BoomRetailer})
    run_pass(_cfg(), {"fake": [store]}, _AlwaysState(), _NullNotifier())
    h = _h("fake")
    assert h["last_status"] == "ERROR"
    assert "kaboom" in h["last_detail"]
