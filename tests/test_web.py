"""Local web UI API behavior without live network calls."""
from __future__ import annotations

import yaml

from scanner.config import Config, RetailerCfg
from scanner.notify import StockAlert
from scanner.retailers.base import StockResult, Store
from scanner import web


def _write_fixture_files(tmp_path, monkeypatch):
    for name in (
        "EBAY_BROWSE_API_TOKEN",
        "EBAY_OAUTH_TOKEN",
        "EBAY_CLIENT_ID",
        "EBAY_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    products_path = tmp_path / "products.yaml"
    products_path.write_text(
        yaml.safe_dump(
            {
                "booster": {
                    "name": "Booster",
                    "msrp": "$26.94",
                    "resale_query": "Pokemon TCG Booster sealed",
                    "target_tcin": "123",
                    "walmart_item_id": "456",
                    "bestbuy_sku": "",
                    "costco_item_id": "789",
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
    monkeypatch.setattr(web, "_health_payload", lambda: [])

    payload = web.status_payload()

    assert payload["ok"] is False
    assert payload["config"]["configMissing"] is True
    assert payload["config"]["productsSelected"] == 1
    assert payload["products"][0]["key"] == "booster"
    assert payload["products"][0]["msrp"] == "$26.94"
    assert payload["products"][0]["resale"]["status"] == "pending"
    assert payload["products"][0]["scanned"] is True
    assert payload["products"][0]["activeRetailers"] == ["target", "walmart"]
    assert payload["coverage"]["score"] == 100
    assert payload["summary"]["coverageScore"] == 100
    assert payload["summary"]["actionableProducts"] == 1
    assert payload["summary"]["activeSources"] == 2
    assert payload["summary"]["sourceHealth"]["unknown"] == 2
    assert "confidence" in payload
    assert "workQueue" in payload
    assert "health" in payload
    assert "recentRestocks" in payload
    assert {retailer["slug"] for retailer in payload["retailers"]} == set(web.RETAILER_REGISTRY)


def test_product_payload_marks_exact_active_retailer_ids():
    payload = web._product_payload(
        Config(
            home_address="1 Home St",
            work_address="2 Work Ave",
            route_radius_miles=4,
            routing_engine="osrm",
            google_api_key="",
            retailers={
                "target": RetailerCfg(enabled=True),
                "walmart": RetailerCfg(enabled=False),
            },
            poll_interval_seconds=180,
            discord_webhook="",
            ntfy_topic="",
            products_filter="all_sealed",
            products={
                "booster": {
                    "name": "Booster",
                    "set": "Test Set",
                    "type": "ETB",
                    "target_tcin": "123",
                    "walmart_item_id": "456",
                }
            },
        )
    )

    product = payload[0]
    assert product["name"] == "Booster"
    assert product["scanned"] is True
    assert product["activeRetailers"] == ["target"]
    target = next(retailer for retailer in product["retailers"] if retailer["slug"] == "target")
    walmart = next(retailer for retailer in product["retailers"] if retailer["slug"] == "walmart")
    assert target["ids"] == {"target_tcin": "123"}
    assert target["active"] is True
    assert walmart["ids"] == {"walmart_item_id": "456"}
    assert walmart["active"] is False


def test_product_payload_includes_catalog_and_resale_prices():
    payload = web._product_payload(
        Config(
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
            products={
                "booster": {
                    "name": "Booster",
                    "msrp": "$26.94",
                    "release_date": "2026-06-26",
                    "target_tcin": "123",
                }
            },
        ),
        {
            "booster": {
                "status": "ok",
                "estimate": "$72.50",
                "low": "$65.00",
                "high": "$80.00",
            }
        },
    )

    assert payload[0]["msrp"] == "$26.94"
    assert payload[0]["releaseDate"] == "2026-06-26"
    assert payload[0]["resale"]["estimate"] == "$72.50"


def test_product_payload_blocks_bestbuy_without_api_key():
    payload = web._product_payload(
        Config(
            home_address="1 Home St",
            work_address="2 Work Ave",
            route_radius_miles=4,
            routing_engine="osrm",
            google_api_key="",
            retailers={"bestbuy": RetailerCfg(enabled=True, api_key="")},
            poll_interval_seconds=180,
            discord_webhook="",
            ntfy_topic="",
            products_filter="all_sealed",
            products={
                "booster": {
                    "name": "Booster",
                    "bestbuy_sku": "12345",
                }
            },
        )
    )

    product = payload[0]
    bestbuy = next(retailer for retailer in product["retailers"] if retailer["slug"] == "bestbuy")
    assert product["scanned"] is False
    assert product["activeRetailers"] == []
    assert bestbuy["ids"] == {"bestbuy_sku": "12345"}
    assert bestbuy["missingApiKey"] is True
    assert bestbuy["blockedReason"] == "missing API key"


def test_save_config_payload_writes_local_config(tmp_path, monkeypatch):
    _write_fixture_files(tmp_path, monkeypatch)
    monkeypatch.setattr(web.RESALE_PRICES, "refresh_due_async", lambda cfg: None)

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
    assert saved["retailers"]["costco"]["enabled"] is True


def test_save_product_id_payload_updates_catalog(tmp_path, monkeypatch):
    _write_fixture_files(tmp_path, monkeypatch)

    payload = web.save_product_id_payload(
        {
            "retailer": "target",
            "productKey": "booster",
            "urlOrId": "https://www.target.com/p/-/A-93954435",
        }
    )

    assert payload["ok"] is True
    assert payload["field"] == "target_tcin"
    assert payload["value"] == "93954435"
    saved = yaml.safe_load((tmp_path / "products.yaml").read_text(encoding="utf-8"))
    assert saved["booster"]["target_tcin"] == "93954435"


def test_save_product_id_payload_updates_costco_catalog_id(tmp_path, monkeypatch):
    _write_fixture_files(tmp_path, monkeypatch)

    payload = web.save_product_id_payload(
        {
            "retailer": "costco",
            "productKey": "booster",
            "urlOrId": "https://www.costco.com/foo.product.4000313298.html",
        }
    )

    assert payload["ok"] is True
    assert payload["field"] == "costco_item_id"
    assert payload["value"] == "4000313298"
    saved = yaml.safe_load((tmp_path / "products.yaml").read_text(encoding="utf-8"))
    assert saved["booster"]["costco_item_id"] == "4000313298"


def test_save_product_id_payload_rejects_placeholder_retailer(tmp_path, monkeypatch):
    _write_fixture_files(tmp_path, monkeypatch)

    payload = web.save_product_id_payload(
        {"retailer": "samsclub", "productKey": "booster", "urlOrId": "12345"}
    )

    assert payload["ok"] is False
    assert "supported catalog ID field" in payload["errors"][0]


def test_should_autostart_requires_valid_saved_config(monkeypatch):
    monkeypatch.setattr(web, "_load_current_config", lambda: (_cfg(), False))
    assert web._should_autostart() is True

    monkeypatch.setattr(web, "_load_current_config", lambda: (_cfg(), True))
    assert web._should_autostart() is False


def test_prepare_scan_capture_reports_online_only_sources(monkeypatch):
    cfg = Config(
        home_address="1 Home St",
        work_address="2 Work Ave",
        route_radius_miles=8.5,
        routing_engine="osrm",
        google_api_key="",
        retailers={"walmart": RetailerCfg(enabled=True)},
        poll_interval_seconds=180,
        discord_webhook="",
        ntfy_topic="",
        products_filter="all_sealed",
        products={"booster": {"name": "Booster", "walmart_item_id": "456"}},
    )
    monkeypatch.setattr(
        web,
        "build_corridor",
        lambda cfg: (_ for _ in ()).throw(AssertionError("route setup should not run")),
    )

    stores, diagnostics = web._prepare_scan_capture(cfg)

    assert stores == {"walmart": []}
    assert diagnostics[0]["slug"] == "walmart"
    assert diagnostics[0]["status"] == "skipped"
    assert diagnostics[0]["skippedReason"] == "online_only"
    assert diagnostics[0]["corridorRadiusMiles"] == 8.5


def test_dry_run_payload_returns_discovered_stores(monkeypatch):
    store = Store("Target", "123", "Target #123", 39.0, -86.0, distance_miles=1.2)
    monkeypatch.setattr(web, "_load_current_config", lambda: (_cfg(), False))
    monkeypatch.setattr(web, "_prepare_scan", lambda cfg: {"target": [store]})

    payload = web.dry_run_payload()

    assert payload["ok"] is True
    assert "coverage" in payload
    assert payload["summary"]["coverageScore"] == 100
    assert payload["summary"]["enabledSources"] == 1
    assert "health" in payload
    assert "recentRestocks" in payload
    assert payload["storeDiagnostics"] == []
    assert payload["stores"]["target"][0]["name"] == "Target #123"
    assert payload["stores"]["target"][0]["distanceMiles"] == 1.2
    assert payload["stockBoard"][0]["retailerSlug"] == "target"
    assert payload["stockBoard"][0]["inventoryChecked"] is False
    location = payload["stockBoard"][0]["locations"][0]
    assert location["storeLabel"] == "Target #123"
    assert location["products"][0]["status"] == "SCOPED"
    assert "not been checked" in location["products"][0]["statusReason"]


def test_warning_lines_sanitizes_and_dedupes_target_403_urls():
    stderr = "\n".join(
        [
            "  ! target store search failed: 403 Client Error: Forbidden for url: "
            "https://redsky.target.com/redsky_aggregations/v1/web/nearby_stores_v1?"
            "key=abc&visitor_id=FIRST",
            "  ! target store search failed: 403 Client Error: Forbidden for url: "
            "https://redsky.target.com/redsky_aggregations/v1/web/nearby_stores_v1?"
            "key=abc&visitor_id=SECOND",
        ]
    )

    warnings = web._warning_lines(stderr)

    assert warnings == [
        "Target store discovery is blocked by Target (HTTP 403). "
        "Route-store Target checks are unavailable right now; online checks continue."
    ]
    assert "redsky" not in warnings[0].lower()
    assert "visitor_id" not in warnings[0].lower()


def test_safe_log_text_redacts_browser_log_details():
    raw = (
        "  home: (39.9760163, -86.1970761)\n"
        "  work: (39.9123247, -86.2337369)\n"
        "403 Client Error for url: "
        "https://redsky.target.com/redsky_aggregations/v1/web/nearby_stores_v1?"
        "key=abc&visitor_id=SECRET"
    )

    safe = web._safe_log_text(raw)

    assert "home: (redacted)" in safe
    assert "work: (redacted)" in safe
    assert "key=abc" not in safe
    assert "visitor_id" not in safe
    assert "https://redsky.target.com/redsky_aggregations/v1/web/nearby_stores_v1?..." in safe


def test_stores_payload_omits_coordinates():
    store = Store("Target", "123", "Target #123", 39.0, -86.0, distance_miles=1.2)

    payload = web._stores_payload({"target": [store]})

    assert payload["target"][0] == {
        "storeId": "123",
        "name": "Target #123",
        "distanceMiles": 1.2,
    }


def test_dry_run_payload_redacts_errors(monkeypatch):
    monkeypatch.setattr(web, "_load_current_config", lambda: (_cfg(), False))
    monkeypatch.setattr(
        web,
        "_prepare_scan_capture",
        lambda cfg: (_ for _ in ()).throw(
            RuntimeError(
                "home: (39.9760163, -86.1970761) "
                "https://redsky.target.com/path?key=secret&visitor_id=abc"
            )
        ),
    )

    payload = web.dry_run_payload()

    assert payload["ok"] is False
    assert "home: (redacted)" in payload["errors"][0]
    assert "key=secret" not in payload["errors"][0]
    assert "visitor_id" not in payload["errors"][0]


def test_safe_demo_payload_uses_synthetic_rows_without_route_setup(monkeypatch):
    monkeypatch.setattr(web, "_load_current_config", lambda: (_cfg(), False))
    monkeypatch.setattr(
        web,
        "build_corridor",
        lambda cfg: (_ for _ in ()).throw(AssertionError("route setup should not run")),
    )

    payload = web.safe_demo_payload()

    assert payload["ok"] is True
    assert payload["warnings"][0].startswith("Safe demo only")
    assert payload["storeDiagnostics"][0]["demo"] is True
    assert payload["stockBoard"][0]["locations"][0]["products"][0]["status"] == "OUT"
    assert payload["stores"]["target"][0]["storeId"] == "_demo_store_"


def test_safe_demo_payload_redacts_config_addresses(monkeypatch):
    monkeypatch.setattr(web, "_load_current_config", lambda: (_cfg(), False))

    payload = web.safe_demo_payload()

    assert payload["ok"] is True
    assert payload["config"]["publicSafe"] is True
    assert payload["config"]["homeAddress"] == "set (redacted)"
    assert payload["config"]["workAddress"] == "set (redacted)"
    assert "1 Home St" not in str(payload["config"])
    assert "2 Work Ave" not in str(payload["config"])


def test_stock_board_payload_groups_products_under_store_statuses():
    cfg = _cfg()
    store = Store("Target", "123", "Target #123", 39.0, -86.0, distance_miles=1.2)
    result = StockResult(
        store=store,
        product_key="booster",
        product_name="Booster",
        status="OUT",
        url="https://example.test/booster",
        retailer_slug="target",
    )

    board = web._stock_board_payload(cfg, {"target": [store]}, [result], checked_at=12345)

    assert board[0]["retailerSlug"] == "target"
    assert board[0]["locations"][0]["storeLabel"] == "Target #123"
    assert board[0]["locations"][0]["products"][0]["productName"] == "Booster"
    assert board[0]["locations"][0]["products"][0]["status"] == "OUT"
    assert board[0]["locations"][0]["inStockCount"] == 0


def test_stock_board_payload_explains_missing_result_from_blocked_source():
    cfg = _cfg()
    store = Store("Target", "123", "Target #123", 39.0, -86.0, distance_miles=1.2)
    web.health.reset()
    web.health.record_failure("target", "BLOCKED", "last HTTP 403; retailer endpoint blocked")

    board = web._stock_board_payload(cfg, {"target": [store]}, [], checked_at=12345)

    product = board[0]["locations"][0]["products"][0]
    assert product["status"] == "BLOCKED"
    assert "HTTP 403" in product["statusReason"]
    web.health.reset()


def _web_cfg():
    from scanner import config as cfg_mod
    return cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})


def test_board_row_includes_verdict_field(monkeypatch):
    cfg = _cfg()
    snapshot = {"products": {"booster": {
        "status": "ok", "estimate": "$80.00", "confidence": "high"}}}
    monkeypatch.setattr(web.RESALE_PRICES, "snapshot", lambda c: snapshot)
    lookup = web.build_comp_lookup(cfg)
    row = lookup("booster")
    assert row["status"] == "ok"
    # verdict string is derivable from the row:
    from scanner.main import verdict_for_alert
    v = verdict_for_alert(cfg, {"msrp": "$49.99"}, "$49.99", row)
    assert v.startswith("BUY") or v.startswith("THIN")


def test_scan_once_payload_captures_scanner_alert(monkeypatch):
    store = Store("Target", "123", "Target #123", 39.0, -86.0, distance_miles=1.2)

    def fake_run_pass(cfg, stores, state, notifier, **kwargs):
        result = StockResult(
            store=store,
            product_key="booster",
            product_name="Booster",
            status="IN_STOCK",
            url="https://example.test",
            price="$49.99",
            retailer_slug="target",
        )
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
        return [result]

    monkeypatch.setattr(web, "_load_current_config", lambda: (_cfg(), False))
    monkeypatch.setattr(web, "_prepare_scan", lambda cfg: {"target": [store]})
    monkeypatch.setattr(web, "run_pass", fake_run_pass)
    monkeypatch.setattr(web, "State", lambda: object())

    payload = web.scan_once_payload()

    assert payload["ok"] is True
    assert "coverage" in payload
    assert payload["summary"]["coverageScore"] == 100
    assert payload["summary"]["stockHits"] == 1
    assert "health" in payload
    assert "recentRestocks" in payload
    assert payload["storeDiagnostics"] == []
    assert payload["stockBoard"][0]["locations"][0]["inStockCount"] == 1
    assert payload["lastResults"][0]["status"] == "IN_STOCK"
    assert payload["alerts"][0]["retailer"] == "Target"
    assert payload["alerts"][0]["status"] == "IN_STOCK"
    runner = web.RUNNER.snapshot()
    assert runner["lastScanAt"] is not None
    assert runner["stockBoard"][0]["locations"][0]["inStockCount"] == 1
    assert runner["lastResults"][0]["status"] == "IN_STOCK"
