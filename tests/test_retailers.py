"""Retailer registry sanity — every adapter imports cleanly and conforms
to the base interface. No network."""
from __future__ import annotations

from pathlib import Path

import yaml

from scanner.retailers import ALL
from scanner.retailers.bestbuy import BestBuy
from scanner.retailers.base import Retailer


def test_registry_is_non_empty():
    assert len(ALL) >= 1


def test_every_registered_retailer_subclasses_base():
    for slug, cls in ALL.items():
        assert issubclass(cls, Retailer), f"{slug} -> {cls} is not a Retailer"


def test_every_registered_retailer_has_a_name():
    for slug, cls in ALL.items():
        assert cls.name, f"{slug} -> {cls.__name__} has empty .name"


def test_retailer_can_be_instantiated_without_args():
    for slug, cls in ALL.items():
        r = cls()
        assert hasattr(r, "find_stores")
        assert hasattr(r, "check")


def test_example_config_retailers_are_registered():
    root = Path(__file__).resolve().parent.parent
    raw = yaml.safe_load((root / "config.example.yaml").read_text()) or {}
    configured = set((raw.get("retailers") or {}).keys())
    assert configured <= set(ALL)


def test_bestbuy_requires_api_key_before_checking():
    retailer = BestBuy()
    products = {"foo": {"name": "Foo", "bestbuy_sku": "12345"}}
    assert list(retailer.check(products, [])) == []
