from __future__ import annotations

import pytest

from scanner.tools.extract_sku import extract, main


@pytest.mark.parametrize(
    "url, expected",
    [
        (
            "https://www.target.com/p/pokemon-tcg-prismatic-evolutions/A-93954435",
            ("target_tcin", "93954435"),
        ),
        (
            "https://www.walmart.com/ip/Pokemon-TCG-Surging-Sparks/15433520586",
            ("walmart_item_id", "15433520586"),
        ),
        (
            "https://www.bestbuy.com/site/pokemon-tcg/6566943.p",
            ("bestbuy_sku", "6566943"),
        ),
        (
            "https://www.gamestop.com/p/pokemon-tcg-surging-sparks-etb",
            ("gamestop_pid", "pokemon-tcg-surging-sparks-etb"),
        ),
        (
            "https://www.pokemoncenter.com/product/some-set-elite-trainer-box",
            ("pokemoncenter_slug", "some-set-elite-trainer-box"),
        ),
    ],
)
def test_extract_known_retailers(url, expected):
    assert extract(url) == expected


def test_extract_unknown_host_returns_none():
    assert extract("https://amazon.com/dp/B0CXYZ") is None


def test_extract_known_host_no_id_returns_none():
    assert extract("https://www.target.com/category/foo") is None


def test_main_exits_zero_on_success(capsys):
    rc = main(["https://www.target.com/p/x/A-1234"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "target_tcin" in out
    assert "1234" in out


def test_main_exits_nonzero_on_unrecognized(capsys):
    rc = main(["https://unknown.example/x"])
    assert rc == 1
