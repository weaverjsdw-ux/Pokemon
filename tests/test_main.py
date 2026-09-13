"""Top-level scanner validation behavior."""
from __future__ import annotations

import sys
from pathlib import Path

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


# ---------------------------------------------------------------------------
# --safe-demo calls no retailer, so a missing credential warns instead of blocking
# ---------------------------------------------------------------------------


def _keyless_bestbuy_cfg():
    """bestbuy enabled with no api_key: the shape that blocked --safe-demo."""
    return _cfg(
        retailers={
            "walmart": RetailerCfg(enabled=True),
            "bestbuy": RetailerCfg(enabled=True),
        },
        products={"foo": {"name": "Foo", "walmart_item_id": "2", "bestbuy_sku": "12345"}},
    )


def test_main_safe_demo_runs_and_warns_on_keyless_api_key_retailer(monkeypatch, capsys):
    cfg = _keyless_bestbuy_cfg()
    assert any("bestbuy" in e and "api_key" in e for e in config_errors(cfg))

    monkeypatch.setattr(sys, "argv", ["scanner", "--safe-demo"])
    monkeypatch.setattr("scanner.main.cfg_mod.load", lambda: cfg)
    monkeypatch.setattr(
        "scanner.main.build_corridor",
        lambda cfg: (_ for _ in ()).throw(AssertionError("route setup should not run")),
    )

    assert main() == 0
    out = capsys.readouterr().out
    assert "safe demo: no geocoding" in out
    assert "config warnings" in out
    assert "config.yaml enables bestbuy, but retailers.bestbuy.api_key is required" in out
    assert "walmart (online-only demo)" in out
    assert "synthetic inventory rows:" in out


def test_check_config_still_fails_on_config_the_safe_demo_tolerates(monkeypatch, capsys):
    cfg = _keyless_bestbuy_cfg()
    monkeypatch.setattr(sys, "argv", ["scanner", "--check-config"])
    monkeypatch.setattr("scanner.main.cfg_mod.load", lambda: cfg)

    assert main() == 1
    assert "retailers.bestbuy.api_key is required" in capsys.readouterr().out


def test_scan_path_still_refuses_config_the_safe_demo_tolerates(monkeypatch):
    cfg = _keyless_bestbuy_cfg()
    monkeypatch.setattr(sys, "argv", ["scanner", "--dry-run"])
    monkeypatch.setattr("scanner.main.cfg_mod.load", lambda: cfg)
    monkeypatch.setattr(
        "scanner.main.build_corridor",
        lambda cfg: (_ for _ in ()).throw(AssertionError("gate must refuse before route setup")),
    )

    with pytest.raises(SystemExit, match="retailers.bestbuy.api_key is required"):
        main()


@pytest.mark.parametrize(
    "overrides, needle",
    [
        ({"retailers": {"not_a_retailer": RetailerCfg(enabled=True)}}, "unknown retailers"),
        ({"routing_engine": "bad"}, "routing.engine"),
        ({"route_radius_miles": 0}, "route_radius_miles"),
        ({"products_filter": ["missing_key"]}, "not in catalog"),
    ],
)
def test_main_safe_demo_still_fails_when_the_demo_would_be_meaningless(
    monkeypatch, overrides, needle
):
    cfg = _keyless_bestbuy_cfg()
    for key, value in overrides.items():
        setattr(cfg, key, value)
    monkeypatch.setattr(sys, "argv", ["scanner", "--safe-demo"])
    monkeypatch.setattr("scanner.main.cfg_mod.load", lambda: cfg)

    with pytest.raises(SystemExit, match=needle):
        main()


# ---------------------------------------------------------------------------
# --dry-run is labeled live-network, and the label is pinned to the truth
# ---------------------------------------------------------------------------


def test_dry_run_help_says_it_is_not_network_free(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["scanner", "--help"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    options = " ".join(capsys.readouterr().out.split()).split("options:", 1)[1]
    dry_run_help = options.split("--dry-run", 1)[1].split("--safe-demo", 1)[0]
    assert "NOT network-free" in dry_run_help
    assert "geocoding" in dry_run_help and "routing" in dry_run_help


def test_main_dry_run_really_geocodes_and_routes(monkeypatch, capsys):
    """Pins the fact behind the --dry-run label: its plan is built from live
    geocoding + routing. Both seams are spies and requests is fenced off, so
    nothing leaves the machine. If --dry-run is ever made offline, this test
    and the label change together."""
    import requests

    cfg = _cfg(products={"foo": {"name": "Foo", "target_tcin": "1"}})
    geocoded: list[str] = []
    routed: list[tuple] = []
    network: list[str] = []

    def spy_geocode(address):
        geocoded.append(address)
        return (39.0, -86.0)

    def spy_polyline(origin, destination, engine, google_api_key):
        routed.append((origin, destination, engine))
        return [origin, destination]

    def no_network(self, method, url, *args, **kwargs):
        network.append(url)
        raise AssertionError(f"real network attempted: {method} {url}")

    monkeypatch.setattr(sys, "argv", ["scanner", "--dry-run"])
    monkeypatch.setattr("scanner.main.cfg_mod.load", lambda: cfg)
    monkeypatch.setattr("scanner.main.geocode", spy_geocode)
    monkeypatch.setattr("scanner.main.get_polyline", spy_polyline)
    monkeypatch.setattr(
        "scanner.main.discover_stores",
        lambda cfg, home, work, polyline: {"target": []},
    )
    monkeypatch.setattr(requests.Session, "request", no_network)

    assert main() == 0
    assert geocoded == ["1 Home St", "2 Work Ave"]
    assert [engine for _origin, _destination, engine in routed] == ["osrm", "osrm"]
    assert network == []


def test_readme_network_free_first_run_excludes_scanner_dry_run():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    run_section = readme.split("### 5. Run", 1)[1].split("\n### ", 1)[0]
    network_free = run_section.split("#### Network-free first run", 1)[1].split("\n#### ", 1)[0]

    for command in (
        "python -m scanner --check-config",
        "python -m scanner --safe-demo",
        "python -m scanner.discovery.pipeline --dry-run",
    ):
        assert command in network_free
    assert "python -m scanner --dry-run" not in network_free
    assert "`python -m scanner --dry-run` is **not** network-free" in run_section


# ---------------------------------------------------------------------------
# Task 6: verdict_for_alert
# ---------------------------------------------------------------------------
from scanner import main as main_mod
from scanner.notify import StockAlert


def _mini_cfg():
    from scanner import config as cfg_mod
    return cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})


def test_verdict_for_alert_buy():
    # $120 comp on a $50 item clears default thresholds (net $42.20, 78.9% ROI) -> BUY.
    row = {"status": "ok", "estimate": "$120.00", "confidence": "high"}
    v = main_mod.verdict_for_alert(
        cfg=_mini_cfg(), product={"msrp": "$49.99"},
        observed_price="$50.00", comp_row=row,
    )
    assert v.startswith("BUY")


def test_verdict_for_alert_no_comp_returns_empty():
    v = main_mod.verdict_for_alert(
        cfg=_mini_cfg(), product={"msrp": "$49.99"},
        observed_price="$50.00", comp_row=None,
    )
    assert v == ""


def test_verdict_for_alert_default_channel_is_ebay_unchanged():
    # Regression guard: default channel/as_of nets the exact pre-Task-4 eBay dollars.
    # entry 30 -> cost 32.10; fee = 100*0.1325+0.40=13.65; net = 100-13.65-8=78.35 -> margin 46.25
    row = {"status": "ok", "estimate": 100.0, "confidence": "high"}
    v = main_mod.verdict_for_alert(
        cfg=_mini_cfg(), product={}, observed_price="$30.00", comp_row=row,
    )
    assert v.startswith("BUY")
    assert "+$46.25 net" in v


def test_verdict_for_alert_tcgplayer_channel_nets_tcgplayer_fees():
    # Same inputs, channel="tcgplayer": fee = 100*(0.1075+0.025)+0.30=13.55;
    # net = 100-13.55-8=78.45 -> margin 46.35 (a $0.10 delta from eBay).
    row = {"status": "ok", "estimate": 100.0, "confidence": "high"}
    v = main_mod.verdict_for_alert(
        cfg=_mini_cfg(), product={}, observed_price="$30.00", comp_row=row,
        channel="tcgplayer",
    )
    assert v.startswith("BUY")
    assert "+$46.35 net" in v


def test_missing_costco_pc_ids_do_not_break_run_pass(tmp_path):
    """Engine must run with zero Costco/PC IDs (graceful, not an exception)."""
    from scanner import config as cfg_mod
    from scanner.state import State
    from scanner.notify import Notifier
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    # No retailers enabled -> run_pass returns [] without raising.
    state = State(db_path=tmp_path / "state.db")
    results = main_mod.run_pass(cfg, {}, state, Notifier())
    assert results == []
