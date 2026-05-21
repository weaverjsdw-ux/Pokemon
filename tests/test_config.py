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
    assert cfg.retailers["target"].enabled is True
    assert cfg.retailers["walmart"].enabled is False
    assert "foo" in cfg.products


def test_selected_products_all_sealed(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    _write(
        cfg_path,
        "locations: { home: h, work: w }\nproducts: all_sealed\n",
    )
    _write(products_path, "a: {name: A}\nb: {name: B}\n")
    cfg = cfg_mod.load()
    assert set(cfg_mod.selected_products(cfg)) == {"a", "b"}


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


def test_env_var_interpolation(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("MY_HOOK", "https://discord.example/abc")
    monkeypatch.setenv("BESTBUY_KEY", "k-123")
    _write(
        cfg_path,
        "locations: { home: h, work: w }\n"
        "discord_webhook: \"${MY_HOOK}\"\n"
        "retailers:\n"
        "  bestbuy: { enabled: true, api_key: \"${BESTBUY_KEY}\" }\n",
    )
    _write(products_path, "{}\n")
    cfg = cfg_mod.load()
    assert cfg.discord_webhook == "https://discord.example/abc"
    assert cfg.retailers["bestbuy"].api_key == "k-123"


def test_env_var_default_when_unset(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    monkeypatch.delenv("NOT_SET_VAR", raising=False)
    _write(
        cfg_path,
        "locations: { home: h, work: w }\n"
        "ntfy_topic: \"${NOT_SET_VAR:-fallback-topic}\"\n",
    )
    _write(products_path, "{}\n")
    cfg = cfg_mod.load()
    assert cfg.ntfy_topic == "fallback-topic"


def test_timezone_default(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    _write(cfg_path, "locations: { home: h, work: w }\n")
    _write(products_path, "{}\n")
    cfg = cfg_mod.load()
    assert cfg.timezone == "America/Chicago"
    assert str(cfg.tzinfo()) == "America/Chicago"


def test_timezone_explicit(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    _write(
        cfg_path,
        "locations: { home: h, work: w }\ntimezone: UTC\n",
    )
    _write(products_path, "{}\n")
    cfg = cfg_mod.load()
    assert cfg.timezone == "UTC"


def test_timezone_invalid_raises(monkeypatch, tmp_path):
    cfg_path, products_path = _patch_paths(monkeypatch, tmp_path)
    _write(
        cfg_path,
        "locations: { home: h, work: w }\ntimezone: Mars/Olympus\n",
    )
    _write(products_path, "{}\n")
    with pytest.raises(SystemExit, match="unknown timezone"):
        cfg_mod.load()
