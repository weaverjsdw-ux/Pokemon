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
