"""Local web UI API behavior without live network calls."""
from __future__ import annotations

import yaml

from scanner.config import Config, RetailerCfg
from scanner.notify import StockAlert
from scanner.retailers.base import Store
from scanner import web


def _write_fixture_files(tmp_path, monkeypatch):
    products_path = tmp_path / "products.yaml"
    products_path.write_text(
        yaml.safe_dump(
            {
                "booster": {
                    "name": "Booster",
                    "target_tcin": "123",
                    "walmart_item_id": "456",
                    "bestbuy_sku": "",
                    "pokemoncenter_slug": "",
                    "gamestop_pid": "",
                }
            }
        ),
        encoding="utf-8",
    )
    example_path = tmp_path / "config.example.yaml"
    example_path.write_text(
        yaml.safe_dump(
            {
                "locations": {"home": "1 Home St", "work": "2 Work Ave"},
                "route_radius_miles": 4,
                "routing": {"engine": "osrm", "google_api_key": ""},
                "retailers": {
                    "target": {"enabled": True},
                    "walmart": {"enabled": True},
                    "costco": {"enabled": False},
                    "samsclub": {"enabled": False},
                    "bestbuy": {"enabled": False, "api_key": ""},
                    "pokemoncenter": {"enabled": False},
                    "gamestop": {"enabled": False},
                },
                "poll_interval_seconds": 180,
                "discord_webhook": "https://discord.test/hook",
                "ntfy_topic": "",
                "products": "all_sealed",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(web.cfg_mod, "PRODUCTS_PATH", products_path)
    monkeypatch.setattr(web.cfg_mod, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(web, "EXAMPLE_CONFIG_PATH", example_path)
    return example_path


def _cfg():
    return Config(
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
        products={"booster": {"name": "Booster", "target_tcin": "123"}},
    )


def test_status_payload_reports_missing_config_but_loads_example(tmp_path, monkeypatch):
    _write_fixture_files(tmp_path, monkeypatch)

    payload = web.status_payload()

    assert payload["ok"] is False
    assert payload["config"]["configMissing"] is True
    assert payload["config"]["productsSelected"] == 1
    assert {retailer["slug"] for retailer in payload["retailers"]} == set(web.RETAILER_REGISTRY)


def test_save_config_payload_writes_local_config(tmp_path, monkeypatch):
    _write_fixture_files(tmp_path, monkeypatch)

    payload = web.save_config_payload(
        {
            "homeAddress": "10 Main St",
            "workAddress": "20 Market St",
            "routeRadiusMiles": 3.5,
            "pollIntervalSeconds": 120,
            "routingEngine": "osrm",
            "retailers": {
                "target": {"enabled": True},
                "walmart": {"enabled": False},
                "costco": {"enabled": True},
            },
        }
    )

    assert payload["ok"] is True
    saved = yaml.safe_load(web.cfg_mod.CONFIG_PATH.read_text(encoding="utf-8"))
    assert saved["locations"]["home"] == "10 Main St"
    assert saved["discord_webhook"] == "https://discord.test/hook"
    assert saved["retailers"]["target"]["enabled"] is True
    assert saved["retailers"]["walmart"]["enabled"] is False
    assert saved["retailers"]["costco"]["enabled"] is False


def test_dry_run_payload_returns_discovered_stores(monkeypatch):
    store = Store("Target", "123", "Target #123", 39.0, -86.0, distance_miles=1.2)
    monkeypatch.setattr(web, "_load_current_config", lambda: (_cfg(), False))
    monkeypatch.setattr(web, "_prepare_scan", lambda cfg: {"target": [store]})

    payload = web.dry_run_payload()

    assert payload["ok"] is True
    assert payload["stores"]["target"][0]["name"] == "Target #123"
    assert payload["stores"]["target"][0]["distanceMiles"] == 1.2


def test_scan_once_payload_captures_scanner_alert(monkeypatch):
    store = Store("Target", "123", "Target #123", 39.0, -86.0, distance_miles=1.2)

    def fake_run_pass(cfg, stores, state, notifier):
        notifier.send(
            StockAlert(
                retailer="Target",
                product_name="Booster",
                store_label="Target #123",
                distance_miles=1.2,
                status="IN_STOCK",
                url="https://example.test",
                price="$49.99",
            )
        )

    monkeypatch.setattr(web, "_load_current_config", lambda: (_cfg(), False))
    monkeypatch.setattr(web, "_prepare_scan", lambda cfg: {"target": [store]})
    monkeypatch.setattr(web, "run_pass", fake_run_pass)
    monkeypatch.setattr(web, "State", lambda: object())

    payload = web.scan_once_payload()

    assert payload["ok"] is True
    assert payload["alerts"][0]["retailer"] == "Target"
    assert payload["alerts"][0]["status"] == "IN_STOCK"
