"""Retailer registry sanity — every adapter imports cleanly and conforms
to the base interface. No network."""
from __future__ import annotations

from scanner.retailers import ALL
from scanner.retailers.base import Retailer, variant_ids


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


def test_variant_ids_string():
    assert variant_ids({"target_tcin": "12345"}, "target_tcin") == ["12345"]


def test_variant_ids_list():
    assert variant_ids({"target_tcin": ["12345", "67890"]}, "target_tcin") == ["12345", "67890"]


def test_variant_ids_blank_and_missing():
    assert variant_ids({}, "target_tcin") == []
    assert variant_ids({"target_tcin": ""}, "target_tcin") == []
    assert variant_ids({"target_tcin": None}, "target_tcin") == []
    assert variant_ids({"target_tcin": ["", "  ", "x"]}, "target_tcin") == ["x"]


def test_variant_ids_strips_whitespace():
    assert variant_ids({"target_tcin": ["  12345  "]}, "target_tcin") == ["12345"]


def test_variant_ids_coerces_ints():
    # YAML may load numeric SKUs as ints
    assert variant_ids({"walmart_item_id": [123, "456"]}, "walmart_item_id") == ["123", "456"]
