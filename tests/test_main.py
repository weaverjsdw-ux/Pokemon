"""Top-level scanner validation behavior."""
from __future__ import annotations

import sys

import pytest

from scanner.config import Config, RetailerCfg
from scanner.main import check_config, config_errors, enabled_retailer_slugs, main
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
    cfg = _cfg(retailers={"costco": RetailerCfg(enabled=True)})
    errors = config_errors(cfg)

    assert any("unsupported" in error and "costco" in error for error in errors)


def test_config_errors_allow_disabled_unsupported_retailer():
    cfg = _cfg(retailers={"costco": RetailerCfg(enabled=False)})

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


def test_check_config_returns_nonzero_for_errors(capsys):
    cfg = _cfg(products={"foo": {"name": "Foo"}})

    assert check_config(cfg) == 1
    assert "configuration errors" in capsys.readouterr().out


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
            "costco": RetailerCfg(enabled=True),
        },
        products={"foo": {"name": "Foo", "target_tcin": "1"}},
    )

    assert enabled_retailer_slugs(cfg) == ["target"]
