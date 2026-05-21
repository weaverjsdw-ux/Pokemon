"""Generic Shopify LGS adapter."""
from __future__ import annotations

from scanner.retailers.lgs_shopify import LGSShopify

from .replay import Replay, json_resp


def test_fires_for_available_variant_at_configured_store():
    client = Replay({
        ("GET", "https://bobs-tcg.myshopify.com/products/pe-etb.js"):
            json_resp({"variants": [{"available": True}], "price": 4999}),
    })
    adapter = LGSShopify(
        http=client,
        stores=[{"name": "Bob's TCG", "domain": "bobs-tcg.myshopify.com"}],
    )
    results = list(adapter.check(
        {"k": {"name": "PE ETB",
               "lgs_shopify_slugs": {"bobs-tcg.myshopify.com": "pe-etb"}}},
        [],
    ))
    assert len(results) == 1
    assert "Bob's TCG" in results[0].product_name
    assert results[0].price == "$49.99"


def test_skips_unconfigured_stores():
    client = Replay({})  # any unscripted call raises
    adapter = LGSShopify(http=client, stores=[])
    results = list(adapter.check(
        {"k": {"lgs_shopify_slugs": {"bobs-tcg.myshopify.com": "pe-etb"}}},
        [],
    ))
    assert results == []
    assert client.calls == []


def test_skips_products_with_no_slug_for_a_store():
    client = Replay({})  # no requests should be made
    adapter = LGSShopify(
        http=client,
        stores=[{"name": "Bob", "domain": "bobs-tcg.myshopify.com"}],
    )
    results = list(adapter.check(
        {"k": {"lgs_shopify_slugs": {"other.shop": "x"}}},  # no entry for bob
        [],
    ))
    assert results == []
    assert client.calls == []


def test_unavailable_variant_yields_nothing():
    client = Replay({
        ("GET", "https://x.com/products/y.js"):
            json_resp({"variants": [{"available": False}]}),
    })
    adapter = LGSShopify(
        http=client,
        stores=[{"name": "X", "domain": "x.com"}],
    )
    results = list(adapter.check(
        {"k": {"lgs_shopify_slugs": {"x.com": "y"}}},
        [],
    ))
    assert results == []


def test_iterates_all_configured_stores():
    client = Replay({
        ("GET", "https://a.com/products/p.js"):
            json_resp({"variants": [{"available": True}], "price": 1000}),
        ("GET", "https://b.com/products/p.js"):
            json_resp({"variants": [{"available": True}], "price": 1100}),
    })
    adapter = LGSShopify(
        http=client,
        stores=[
            {"name": "A", "domain": "a.com"},
            {"name": "B", "domain": "b.com"},
        ],
    )
    results = list(adapter.check(
        {"k": {"lgs_shopify_slugs": {"a.com": "p", "b.com": "p"}}},
        [],
    ))
    assert len(results) == 2
    assert {r.price for r in results} == {"$10.00", "$11.00"}
