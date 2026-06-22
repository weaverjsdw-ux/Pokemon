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
