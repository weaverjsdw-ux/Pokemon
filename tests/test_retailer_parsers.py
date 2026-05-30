"""Parser-level checks for retailer adapters.

These stay network-free and protect the assumptions each adapter makes about
response payloads or fragments.
"""
from __future__ import annotations

from scanner.retailers.gamestop import GameStop
from scanner.retailers.pokemoncenter import PokemonCenter
from scanner.retailers.target import Target
from scanner.retailers.walmart import Walmart


def test_target_store_option_prefers_in_stock_over_pickup_out():
    option = {
        "order_pickup": {"availability_status": "OUT_OF_STOCK"},
        "in_store_only": {"availability_status": "IN_STOCK"},
    }

    assert Target._status_from_store_option(option) == "IN_STOCK"


def test_target_store_option_maps_limited_stock():
    option = {
        "order_pickup": {"availability_status": "OUT_OF_STOCK"},
        "in_store_only": {"availability_status": "LIMITED_STOCK"},
    }

    assert Target._status_from_store_option(option) == "LIMITED"


def test_walmart_prefers_status_near_matching_item_id():
    page = (
        '{"itemId":"other","availabilityStatus":"OUT_OF_STOCK"}'
        '{"itemId":"15433520586","availabilityStatus":"IN_STOCK"}'
    )

    assert Walmart._availability_status_from_page(page, "15433520586") == "IN_STOCK"


def test_walmart_falls_back_to_legacy_page_status():
    page = '{"availabilityStatus":"LIMITED_STOCK"}'

    assert Walmart._availability_status_from_page(page, "missing") == "LIMITED_STOCK"


def test_gamestop_inventory_text_rejects_negative_fragments():
    assert GameStop._inventory_text_in_stock("Not available in stock at this store") is False
    assert GameStop._inventory_text_in_stock("Out-of-stock nearby") is False


def test_gamestop_inventory_text_accepts_in_stock_fragment():
    assert GameStop._inventory_text_in_stock("Available now: in stock") is True


def test_pokemoncenter_product_json_availability_and_price():
    data = {"variants": [{"available": False}, {"available": True}], "price": 5999}

    assert PokemonCenter._available_from_product_json(data) is True
    assert PokemonCenter._price_from_product_json(data) == "$59.99"


def test_pokemoncenter_product_json_handles_missing_variants():
    assert PokemonCenter._available_from_product_json({"variants": []}) is False
    assert PokemonCenter._price_from_product_json({"price": ""}) == ""
