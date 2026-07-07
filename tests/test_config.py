"""Config loader behavior — no network, no real config.yaml required."""
from __future__ import annotations

from pathlib import Path

import pytest

from scanner import config as cfg_mod


def _write(path: Path, body: str) -> None:
    path.write_text(body)


def _patch_paths(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    cfg_path = tmp_path / "config.yaml"
    products_path = tmp_path / "products.yaml"
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(cfg_mod, "PRODUCTS_PATH", products_path)
    return cfg_path, products_path


def test_missing_config_file_raises(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    with pytest.raises(SystemExit, match="Missing config.yaml"):
        cfg_mod.load()


def test_blank_addresses_raise(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    _write(cfg_path, "locations:\n  home: ''\n  work: ''\n")
    _write(products_path, "{}\n")
    with pytest.raises(SystemExit, match="locations.home and locations.work"):
        cfg_mod.load()


def test_valid_config_loads_with_defaults(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    _write(
        cfg_path,
        "locations:\n"
        "  home: '1 Home St'\n"
        "  work: '2 Work Ave'\n"
        "retailers:\n"
        "  target: { enabled: true }\n"
        "  walmart: { enabled: false }\n",
    )
    _write(products_path, "foo:\n  name: 'Foo'\n")
    cfg = cfg_mod.load()

    assert cfg.home_address == "1 Home St"
    assert cfg.work_address == "2 Work Ave"
    assert cfg.route_radius_miles == 4.0  # default
    assert cfg.routing_engine == "osrm"   # default
    assert cfg.poll_interval_seconds == 180
    assert cfg.resale_price_enabled is True
    assert cfg.resale_price_interval_seconds == 14400
    assert cfg.ebay_marketplace_id == "EBAY_US"
    assert cfg.retailers["target"].enabled is True
    assert cfg.retailers["walmart"].enabled is False
    assert "foo" in cfg.products


def test_resale_price_config_loads(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    _write(
        cfg_path,
        "locations:\n"
        "  home: '1 Home St'\n"
        "  work: '2 Work Ave'\n"
        "resale_prices:\n"
        "  enabled: true\n"
        "  interval_seconds: 7200\n"
        "  ebay:\n"
        "    marketplace_id: EBAY_US\n"
        "    browse_api_token: token-1\n"
        "    client_id: client-1\n"
        "    client_secret: secret-1\n",
    )
    _write(products_path, "foo:\n  name: 'Foo'\n")
    cfg = cfg_mod.load()

    assert cfg.resale_price_enabled is True
    assert cfg.resale_price_interval_seconds == 7200
    assert cfg.ebay_marketplace_id == "EBAY_US"
    assert cfg.ebay_browse_api_token == "token-1"
    assert cfg.ebay_client_id == "client-1"
    assert cfg.ebay_client_secret == "secret-1"


def test_selected_products_all_sealed(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    _write(
        cfg_path,
        "locations: { home: h, work: w }\nproducts: all_sealed\n",
    )
    _write(products_path, "a: {name: A}\nb: {name: B}\n")
    cfg = cfg_mod.load()
    assert set(cfg_mod.selected_products(cfg)) == {"a", "b"}


def test_selected_products_all_tcg_alias(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    _write(
        cfg_path,
        "locations: { home: h, work: w }\nproducts: all_tcg\n",
    )
    _write(products_path, "a: {name: A}\nb: {name: B, game: 'Magic: The Gathering'}\n")
    cfg = cfg_mod.load()
    assert set(cfg_mod.selected_products(cfg)) == {"a", "b"}


def test_selected_products_magic_filter(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    _write(
        cfg_path,
        "locations: { home: h, work: w }\nproducts: magic\n",
    )
    _write(
        products_path,
        "pokemon_a: {name: A}\n"
        "magic_a: {name: B, game: 'Magic: The Gathering'}\n"
        "mtg_a: {name: C, game: MTG}\n",
    )
    cfg = cfg_mod.load()
    assert set(cfg_mod.selected_products(cfg)) == {"magic_a", "mtg_a"}


def test_selected_products_pokemon_filter_keeps_legacy_rows(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    _write(
        cfg_path,
        "locations: { home: h, work: w }\nproducts: pokemon\n",
    )
    _write(
        products_path,
        "legacy_pokemon: {name: Legacy Pokemon Row}\n"
        "magic_a: {name: B, game: 'Magic: The Gathering'}\n",
    )
    cfg = cfg_mod.load()
    assert set(cfg_mod.selected_products(cfg)) == {"legacy_pokemon"}


def test_selected_products_explicit_list(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    _write(
        cfg_path,
        "locations: { home: h, work: w }\nproducts: ['a']\n",
    )
    _write(products_path, "a: {name: A}\nb: {name: B}\n")
    cfg = cfg_mod.load()
    selected = cfg_mod.selected_products(cfg)
    assert list(selected) == ["a"]


def test_selected_products_missing_explicit_key_raises(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    _write(
        cfg_path,
        "locations: { home: h, work: w }\nproducts: ['a', 'missing']\n",
    )
    _write(products_path, "a: {name: A}\n")
    cfg = cfg_mod.load()
    with pytest.raises(SystemExit, match="missing"):
        cfg_mod.selected_products(cfg)


def test_selected_products_invalid_filter_raises(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    _write(
        cfg_path,
        "locations: { home: h, work: w }\nproducts: 42\n",
    )
    _write(products_path, "a: {name: A}\n")
    cfg = cfg_mod.load()
    with pytest.raises(SystemExit, match="invalid 'products'"):
        cfg_mod.selected_products(cfg)


def test_retailer_config_must_be_mapping(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    _write(
        cfg_path,
        "locations: { home: h, work: w }\nretailers:\n  target: true\n",
    )
    _write(products_path, "a: {name: A}\n")
    with pytest.raises(SystemExit, match="retailers.target"):
        cfg_mod.load()


def test_deal_intelligence_defaults_when_absent():
    cfg = cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
    })
    assert cfg.tax_rate == 0.07
    assert cfg.ebay_fvf_pct == 0.1325
    assert cfg.ebay_fixed_fee == 0.40
    assert cfg.ebay_est_shipping == 8.0
    assert cfg.local_haircut_pct == 0.15
    assert cfg.skip_floor_net == 5.0
    assert cfg.buy_floor_net == 15.0
    assert cfg.roi_gate_enabled is True
    assert cfg.skip_floor_roi == 10.0
    assert cfg.buy_floor_roi == 20.0
    assert cfg.min_buy_confidence == "medium"
    assert cfg.market_preferred is False
    assert cfg.market_cache_ttl_seconds == 86400


def test_deal_intelligence_overrides_parse():
    cfg = cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "deal_intelligence": {
            "tax_rate": 0.0,
            "fees": {"ebay_fvf_pct": 0.10, "ebay_fixed_fee": 0.30, "local_haircut_pct": 0.2},
            "verdict": {
                "skip_floor_net": 2, "buy_floor_net": 20,
                "roi_gate_enabled": False, "skip_floor_roi": 5, "buy_floor_roi": 30,
                "min_buy_confidence": "high",
            },
        },
        "market": {"preferred": True, "api_key": "k", "cache_ttl_seconds": 3600},
    })
    assert cfg.tax_rate == 0.0
    assert cfg.ebay_fvf_pct == 0.10
    assert cfg.roi_gate_enabled is False
    assert cfg.min_buy_confidence == "high"
    assert cfg.market_preferred is True
    assert cfg.market_api_key == "k"
    assert cfg.market_cache_ttl_seconds == 3600


def test_market_api_key_from_neutral_env(monkeypatch):
    """Provider-neutral env var configures the external card key (D.5)."""
    monkeypatch.delenv("PPT_API_KEY", raising=False)
    monkeypatch.setenv("CARD_PRICE_API_KEY", "neutral-key")
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    assert cfg.market_api_key == "neutral-key"


def test_market_api_key_legacy_ppt_env_still_works(monkeypatch):
    """Legacy PPT_API_KEY remains a working compat fallback."""
    monkeypatch.delenv("CARD_PRICE_API_KEY", raising=False)
    monkeypatch.setenv("PPT_API_KEY", "legacy-key")
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    assert cfg.market_api_key == "legacy-key"


def test_market_api_key_prefers_neutral_env_over_legacy(monkeypatch):
    monkeypatch.setenv("CARD_PRICE_API_KEY", "neutral-key")
    monkeypatch.setenv("PPT_API_KEY", "legacy-key")
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    assert cfg.market_api_key == "neutral-key"


def test_invalid_min_buy_confidence_rejected():
    with pytest.raises(SystemExit):
        cfg_mod.from_mapping({
            "locations": {"home": "A", "work": "B"},
            "deal_intelligence": {"verdict": {"min_buy_confidence": "ludicrous"}},
        })


def test_poke_defaults_when_absent():
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    assert cfg.poke.min_rows == 10
    assert cfg.poke.staleness_days == 30
    assert cfg.poke.steal_pct == 30.0
    assert cfg.poke.min_discount_pct == 5.0
    assert cfg.poke.grading_cost_all_in == 97.50


def test_poke_overrides_parse():
    cfg = cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "poke": {"min_rows": 5, "staleness_days": 14, "steal_pct": 25,
                 "min_discount_pct": 8, "grading_cost_all_in": 80},
    })
    assert cfg.poke.min_rows == 5
    assert cfg.poke.staleness_days == 14
    assert cfg.poke.steal_pct == 25.0
    assert cfg.poke.min_discount_pct == 8.0
    assert cfg.poke.grading_cost_all_in == 80.0


def test_poke_must_be_mapping():
    with pytest.raises(SystemExit):
        cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}, "poke": []})


def test_poke_slice_defaults():
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    assert cfg.poke.buy_basis == "msrp"
    assert cfg.poke.daily_credit_cap == 90


def test_poke_slice_overrides_parse():
    cfg = cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "poke": {"buy_basis": "MSRP", "daily_credit_cap": 40},
    })
    assert cfg.poke.buy_basis == "msrp"
    assert cfg.poke.daily_credit_cap == 40


def test_poke_independent_sources_defaults_off():
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    assert cfg.poke.independent_sources is False


def test_poke_independent_sources_overrides_parse():
    cfg = cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "poke": {"independent_sources": True},
    })
    assert cfg.poke.independent_sources is True


def test_poke_tcgcsv_defaults_off():
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    assert cfg.poke.tcgcsv is False


def test_poke_tcgcsv_overrides_parse():
    cfg = cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "poke": {"tcgcsv": True},
    })
    assert cfg.poke.tcgcsv is True


def test_poke_rejects_unknown_buy_basis():
    with pytest.raises(SystemExit):
        cfg_mod.from_mapping({
            "locations": {"home": "A", "work": "B"},
            "poke": {"buy_basis": "observed"},
        })


def test_poke_rejects_non_numeric_daily_credit_cap():
    with pytest.raises(SystemExit):
        cfg_mod.from_mapping({
            "locations": {"home": "A", "work": "B"},
            "poke": {"daily_credit_cap": "forty"},
        })


def test_opportunity_defaults_when_absent():
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    assert cfg.opportunity.live_min_expected_net == 25.0
    assert cfg.opportunity.live_min_roi_pct == 30.0
    assert cfg.opportunity.live_min_confidence == "medium"
    assert cfg.opportunity.stale_after_days == 30
    assert cfg.opportunity.max_hold_days == {}
    assert cfg.opportunity.exit_venue == {}


def test_opportunity_overrides_parse():
    cfg = cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "opportunity": {
            "live_min_expected_net": 40,
            "live_min_roi_pct": 35,
            "live_min_confidence": "HIGH",
            "stale_after_days": 21,
            "max_hold_days": {"sealed_retail_arbitrage": 45, "sealed_momentum_watch": 90},
            "exit_venue": {"sealed_retail_arbitrage": "ebay"},
        },
    })
    assert cfg.opportunity.live_min_expected_net == 40.0
    assert cfg.opportunity.live_min_roi_pct == 35.0
    assert cfg.opportunity.live_min_confidence == "high"
    assert cfg.opportunity.stale_after_days == 21
    assert cfg.opportunity.max_hold_days == {"sealed_retail_arbitrage": 45, "sealed_momentum_watch": 90}
    assert cfg.opportunity.exit_venue == {"sealed_retail_arbitrage": "ebay"}


def test_opportunity_rejects_bad_live_confidence():
    with pytest.raises(SystemExit):
        cfg_mod.from_mapping({
            "locations": {"home": "A", "work": "B"},
            "opportunity": {"live_min_confidence": "certain"},
        })


def test_opportunity_must_be_mapping():
    with pytest.raises(SystemExit):
        cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}, "opportunity": []})


def test_opportunity_rejects_non_numeric_hold_days():
    with pytest.raises(SystemExit):
        cfg_mod.from_mapping({
            "locations": {"home": "A", "work": "B"},
            "opportunity": {"max_hold_days": {"sealed_retail_arbitrage": "soon"}},
        })


@pytest.fixture
def base_raw():
    """Minimal valid raw config mapping for comps tests."""
    return {
        "locations": {"home": "A", "work": "B"},
    }


def test_comps_defaults(base_raw):
    cfg = cfg_mod.from_mapping(base_raw)
    assert cfg.comps.engine == "legacy"
    assert cfg.comps.agreement_tolerance_pct == 20.0
    assert cfg.comps.ebay_floor_sanity_pct == 50.0
    assert cfg.comps.cache_ttl_seconds == 21600
    assert cfg.comps.politeness_seconds == 1.0


def test_comps_engine_validated(base_raw):
    base_raw["comps"] = {"engine": "warp-drive"}
    with pytest.raises(SystemExit):
        cfg_mod.from_mapping(base_raw)


def test_comps_inhouse_accepted(base_raw):
    base_raw["comps"] = {"engine": "inhouse", "cache_ttl_seconds": 60}
    cfg = cfg_mod.from_mapping(base_raw)
    assert cfg.comps.engine == "inhouse" and cfg.comps.cache_ttl_seconds == 60


def test_discovery_defaults(base_raw):
    cfg = cfg_mod.from_mapping(base_raw)
    assert cfg.discovery.enabled is True
    assert cfg.discovery.interval_seconds == 7200
    assert cfg.discovery.sources == ["target_search", "slickdeals", "ebay_browse"]
    assert "Prismatic Evolutions" in cfg.discovery.set_watch
    assert cfg.discovery.min_alert_confidence == "medium"


def test_discovery_min_alert_confidence_validated(base_raw):
    base_raw["discovery"] = {"min_alert_confidence": "vibes"}
    with pytest.raises(SystemExit):
        cfg_mod.from_mapping(base_raw)


def test_discovery_overrides_accepted(base_raw):
    base_raw["discovery"] = {"enabled": False, "interval_seconds": 3600,
                             "sources": ["slickdeals"], "set_watch": ["Crown Zenith"],
                             "min_alert_confidence": "high"}
    cfg = cfg_mod.from_mapping(base_raw)
    assert cfg.discovery.enabled is False
    assert cfg.discovery.interval_seconds == 3600
    assert cfg.discovery.sources == ["slickdeals"]
    assert cfg.discovery.set_watch == ["Crown Zenith"]
    assert cfg.discovery.min_alert_confidence == "high"


def test_alerts_defaults(base_raw):
    cfg = cfg_mod.from_mapping(base_raw)
    assert cfg.alerts.quiet_hours == "23:00-08:00"
    assert cfg.alerts.price_drop_realert_pct == 5.0
    assert cfg.alerts.cooldown_hours == 24.0


def test_alerts_overrides_parse(base_raw):
    base_raw["alerts"] = {"quiet_hours": "22:30-06:15",
                          "price_drop_realert_pct": 10, "cooldown_hours": 12}
    cfg = cfg_mod.from_mapping(base_raw)
    assert cfg.alerts.quiet_hours == "22:30-06:15"
    assert cfg.alerts.price_drop_realert_pct == 10.0
    assert cfg.alerts.cooldown_hours == 12.0


def test_alerts_must_be_mapping(base_raw):
    base_raw["alerts"] = []
    with pytest.raises(SystemExit):
        cfg_mod.from_mapping(base_raw)


def test_alerts_rejects_malformed_quiet_hours(base_raw):
    base_raw["alerts"] = {"quiet_hours": "nope"}
    with pytest.raises(SystemExit, match="quiet_hours"):
        cfg_mod.from_mapping(base_raw)


def test_alerts_rejects_out_of_range_quiet_hours(base_raw):
    base_raw["alerts"] = {"quiet_hours": "25:00-08:00"}
    with pytest.raises(SystemExit, match="quiet_hours"):
        cfg_mod.from_mapping(base_raw)


def test_alerts_rejects_non_numeric_pct(base_raw):
    base_raw["alerts"] = {"price_drop_realert_pct": "loads"}
    with pytest.raises(SystemExit, match="price_drop_realert_pct"):
        cfg_mod.from_mapping(base_raw)


def test_alerts_rejects_non_numeric_cooldown(base_raw):
    base_raw["alerts"] = {"cooldown_hours": "forever"}
    with pytest.raises(SystemExit, match="cooldown_hours"):
        cfg_mod.from_mapping(base_raw)


def test_parse_quiet_hours_wrap_and_normal():
    assert cfg_mod.parse_quiet_hours("23:00-08:00") == (23 * 60, 8 * 60)
    assert cfg_mod.parse_quiet_hours("09:30-17:45") == (9 * 60 + 30, 17 * 60 + 45)
