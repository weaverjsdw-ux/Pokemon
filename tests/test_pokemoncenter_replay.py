"""Pokemon Center adapter replayed."""
from __future__ import annotations

from scanner.retailers.pokemoncenter import PokemonCenter

from .replay import Replay, json_resp


def test_in_stock_variant_yields_result():
    payload = {
        "variants": [{"available": False}, {"available": True}],
        "price": 4999,
    }
    client = Replay({
        ("GET", "https://www.pokemoncenter.com/products/some-etb.js"): json_resp(payload),
    })
    pc = PokemonCenter(http=client)
    results = list(pc.check(
        {"k": {"name": "Some ETB", "pokemoncenter_slug": "some-etb"}},
        [],
    ))
    assert len(results) == 1
    assert results[0].status == "ONLINE_IN_STOCK"
    assert results[0].price == "$49.99"


def test_all_variants_unavailable_yields_nothing():
    client = Replay({
        ("GET", "https://www.pokemoncenter.com/products/some-etb.js"):
            json_resp({"variants": [{"available": False}], "price": 4999}),
    })
    pc = PokemonCenter(http=client)
    results = list(pc.check(
        {"k": {"pokemoncenter_slug": "some-etb"}}, []
    ))
    assert results == []


def test_multi_region_polls_each_region():
    client = Replay({
        ("GET", "https://www.pokemoncenter.com/products/x.js"):
            json_resp({"variants": [{"available": True}], "price": 4999}),
        ("GET", "https://www.pokemoncenter.com/en-gb/products/x.js"):
            json_resp({"variants": [{"available": True}], "price": 3999}),
    })
    pc = PokemonCenter(
        http=client,
        regions=[
            {"code": "us", "base": "https://www.pokemoncenter.com", "currency": "$"},
            {"code": "gb", "base": "https://www.pokemoncenter.com/en-gb", "currency": "£"},
        ],
    )
    results = list(pc.check({"k": {"pokemoncenter_slug": "x"}}, []))
    assert len(results) == 2
    currencies = {r.price[:1] for r in results}
    assert "$" in currencies
    assert "£" in currencies
    # Non-US region gets tagged in the name
    assert any("[GB]" in r.product_name for r in results)


def test_multiple_variant_slugs_are_polled():
    client = Replay({
        ("GET", "https://www.pokemoncenter.com/products/a.js"):
            json_resp({"variants": [{"available": True}], "price": 1000}),
        ("GET", "https://www.pokemoncenter.com/products/b.js"):
            json_resp({"variants": [{"available": False}]}),
    })
    pc = PokemonCenter(http=client)
    results = list(pc.check(
        {"k": {"pokemoncenter_slug": ["a", "b"]}}, []
    ))
    assert len(results) == 1
    assert "products/a.js" in [c[1] for c in client.calls][0]
