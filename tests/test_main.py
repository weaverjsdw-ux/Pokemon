"""Top-level scanner validation behavior."""
from __future__ import annotations

import sys

import pytest

from scanner.config import Config, RetailerCfg
from scanner.main import (
    check_config,
    config_errors,
    discover_stores,
    enabled_retailer_slugs,
    main,
    _route_discovery_centers,
    safe_demo_results,
    safe_demo_stores,
)
from scanner.retailers.base import Store


def _cfg(**overrides):
    cfg = Config(
        home_address="1 Home St",
        work_address="2 Work Ave",
        route_radius_miles=4,
        routing_engine="osrm",
        google_api_key="",
        retailers={"target": RetailerCfg(enabled=True)},
        poll_interval_seconds=180,
        discord_webhook="",
        ntfy_topic="",
        products_filter="all_sealed",
        products={},
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def test_config_errors_reject_enabled_unsupported_retailer():
    cfg = _cfg(retailers={"samsclub": RetailerCfg(enabled=True)})
    errors = config_errors(cfg)

    assert any("unsupported" in error and "samsclub" in error for error in errors)


def test_config_errors_allow_disabled_unsupported_retailer():
    cfg = _cfg(retailers={"samsclub": RetailerCfg(enabled=False)})

    assert config_errors(cfg) == []


def test_config_errors_reject_invalid_route_and_poll_values():
    cfg = _cfg(route_radius_miles=0, poll_interval_seconds=30, routing_engine="bad")
    errors = config_errors(cfg)

    assert any("routing.engine" in error for error in errors)
    assert any("route_radius_miles" in error for error in errors)
    assert any("poll_interval_seconds" in error for error in errors)


def test_config_errors_reject_enabled_retailer_without_selected_product_ids():
    cfg = _cfg(products={"foo": {"name": "Foo"}})
    errors = config_errors(cfg)

    assert any("target_tcin" in error for error in errors)


def test_config_errors_reject_enabled_api_key_retailer_without_key():
    cfg = _cfg(
        retailers={"bestbuy": RetailerCfg(enabled=True)},
        products={"foo": {"name": "Foo", "bestbuy_sku": "12345"}},
    )

    errors = config_errors(cfg)

    assert any("bestbuy" in error and "api_key" in error for error in errors)


def test_check_config_returns_nonzero_for_errors(capsys):
    cfg = _cfg(products={"foo": {"name": "Foo"}})

    assert check_config(cfg) == 1
    assert "configuration errors" in capsys.readouterr().out


def test_check_config_redacts_private_addresses(capsys):
    cfg = _cfg(products={"foo": {"name": "Foo", "target_tcin": "1"}})

    assert check_config(cfg) == 0
    out = capsys.readouterr().out
    assert "1 Home St" not in out
    assert "2 Work Ave" not in out
    assert "home:  set (redacted)" in out
    assert "work:  set (redacted)" in out


def test_main_dry_run_prints_online_only_retailer(monkeypatch, capsys):
    cfg = _cfg(
        retailers={
            "target": RetailerCfg(enabled=True),
            "walmart": RetailerCfg(enabled=True),
        },
        products={"foo": {"name": "Foo", "target_tcin": "1", "walmart_item_id": "2"}},
    )
    store = Store("Target", "123", "Target #123", 39.0, -86.0, distance_miles=1.5)

    monkeypatch.setattr(sys, "argv", ["scanner", "--dry-run"])
    monkeypatch.setattr("scanner.main.cfg_mod.load", lambda: cfg)
    monkeypatch.setattr("scanner.main.build_corridor", lambda cfg: ((0, 0), (1, 1), []))
    monkeypatch.setattr(
        "scanner.main.discover_stores",
        lambda cfg, home, work, polyline: {"target": [store], "walmart": []},
    )

    assert main() == 0
    out = capsys.readouterr().out
    assert "target (1 stores in corridor)" in out
    assert "walmart (online-only)" in out


def test_main_online_only_dry_run_skips_route_setup(monkeypatch, capsys):
    cfg = _cfg(
        retailers={"walmart": RetailerCfg(enabled=True)},
        products={"foo": {"name": "Foo", "walmart_item_id": "2"}},
    )

    monkeypatch.setattr(sys, "argv", ["scanner", "--dry-run"])
    monkeypatch.setattr("scanner.main.cfg_mod.load", lambda: cfg)
    monkeypatch.setattr(
        "scanner.main.build_corridor",
        lambda cfg: (_ for _ in ()).throw(AssertionError("route setup should not run")),
    )

    assert main() == 0
    assert "walmart (online-only)" in capsys.readouterr().out


def test_main_reports_route_setup_failure(monkeypatch):
    cfg = _cfg(products={"foo": {"name": "Foo", "target_tcin": "1"}})

    monkeypatch.setattr(sys, "argv", ["scanner", "--dry-run"])
    monkeypatch.setattr("scanner.main.cfg_mod.load", lambda: cfg)
    monkeypatch.setattr(
        "scanner.main.build_corridor",
        lambda cfg: (_ for _ in ()).throw(RuntimeError("routing unavailable")),
    )

    with pytest.raises(SystemExit, match="route setup failed: routing unavailable"):
        main()


def test_enabled_retailer_slugs_ignores_unsupported_enabled_retailers():
    cfg = _cfg(
        retailers={
            "target": RetailerCfg(enabled=True),
            "samsclub": RetailerCfg(enabled=True),
        },
        products={"foo": {"name": "Foo", "target_tcin": "1", "samsclub_item_id": "2"}},
    )

    assert enabled_retailer_slugs(cfg) == ["target"]


def test_discover_stores_reports_radius_diagnostics(monkeypatch):
    class FakeRetailer:
        name = "Fake Route Store"
        online_only = False

        def __init__(self, **kwargs):
            pass

        def find_stores(self, lat, lng, radius_miles):
            return [
                Store("Fake", "near", "Near Store", 0.01, 0.5),
                Store("Fake", "far", "Far Store", 5.0, 0.5),
            ]

    cfg = _cfg(
        route_radius_miles=100,
        retailers={"fake": RetailerCfg(enabled=True)},
    )
    diagnostics = []
    monkeypatch.setattr("scanner.main.RETAILER_REGISTRY", {"fake": FakeRetailer})

    stores = discover_stores(cfg, (0, 0), (0, 1), [(0, 0), (0, 1)], diagnostics)

    assert [store.store_id for store in stores["fake"]] == ["near"]
    assert diagnostics[0]["candidateSearchRadiusMiles"] == 105
    assert diagnostics[0]["centersPlanned"] == 2
    assert diagnostics[0]["centersQueried"] == 2
    assert diagnostics[0]["uniqueCandidateStores"] == 2
    assert diagnostics[0]["keptStores"] == 1
    assert diagnostics[0]["filteredOutStores"] == 1
    assert diagnostics[0]["status"] == "ready"


def test_route_discovery_centers_samples_long_routes():
    centers = _route_discovery_centers((0, 0), (0, 2), [(0, 0), (0, 2)], 10)

    assert len(centers) > 2
    assert len(centers) <= 8
    assert centers[0] == (0, 0)
    assert centers[1] == (0, 2)


def test_safe_demo_stores_and_results_are_local_only():
    cfg = _cfg(
        retailers={
            "target": RetailerCfg(enabled=True),
            "walmart": RetailerCfg(enabled=True),
        },
        products={"foo": {"name": "Foo", "target_tcin": "1", "walmart_item_id": "2"}},
    )

    stores, diagnostics = safe_demo_stores(cfg)
    results = safe_demo_results(cfg, stores)

    assert stores["target"][0].store_id == "_demo_store_"
    assert diagnostics[0]["demo"] is True
    assert {result.status for result in results} == {"OUT", "ONLINE_OUT"}
    assert all(result.url == "" for result in results)


def test_main_safe_demo_skips_route_setup(monkeypatch, capsys):
    cfg = _cfg(
        retailers={"walmart": RetailerCfg(enabled=True)},
        products={"foo": {"name": "Foo", "walmart_item_id": "2"}},
    )

    monkeypatch.setattr(sys, "argv", ["scanner", "--safe-demo"])
    monkeypatch.setattr("scanner.main.cfg_mod.load", lambda: cfg)
    monkeypatch.setattr(
        "scanner.main.build_corridor",
        lambda cfg: (_ for _ in ()).throw(AssertionError("route setup should not run")),
    )

    assert main() == 0
    out = capsys.readouterr().out
    assert "safe demo: no geocoding" in out
    assert "walmart (online-only demo)" in out
