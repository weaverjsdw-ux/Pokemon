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
