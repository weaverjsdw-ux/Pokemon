"""URL -> id extraction and in-place catalog edits (no IO, no network)."""
from __future__ import annotations

import pytest

from scanner.add_id import main as add_id_main
from scanner.identifiers import extract_id, field_for_slug, set_product_id


def test_extract_target_tcin_from_url():
    url = "https://www.target.com/p/prismatic-evolutions-etb/-/A-93954435"
    assert extract_id("target", url) == "93954435"


def test_extract_walmart_item_id_from_url():
    url = "https://www.walmart.com/ip/Pokemon-TCG/15433520586"
    assert extract_id("walmart", url) == "15433520586"


def test_extract_bestbuy_sku_from_url():
    url = "https://www.bestbuy.com/site/pokemon/6566943.p?skuId=6566943"
    assert extract_id("bestbuy", url) == "6566943"


def test_extract_costco_item_id_from_url():
    url = "https://www.costco.com/pokemon-tcg-charizard.product.4000313298.html"
    assert extract_id("costco", url) == "4000313298"


def test_extract_gamestop_slug_from_url():
    url = "https://www.gamestop.com/p/pokemon-tcg-foo?lang=en"
    assert extract_id("gamestop", url) == "pokemon-tcg-foo"


def test_extract_pokemoncenter_slug_from_url():
    url = "https://www.pokemoncenter.com/product/pokemon-tcg-foo-123"
    assert extract_id("pokemoncenter", url) == "pokemon-tcg-foo-123"


def test_bare_id_passes_through():
    assert extract_id("target", "93954435") == "93954435"
    assert extract_id("walmart", "  15433520586 ") == "15433520586"


def test_extract_returns_none_for_unmatched_or_empty():
    assert extract_id("target", "https://www.target.com/p/no-id-here") is None
    assert extract_id("target", "") is None


def test_field_for_slug():
    assert field_for_slug("target") == "target_tcin"
    assert field_for_slug("TARGET") == "target_tcin"
    assert field_for_slug("costco") == "costco_item_id"


CATALOG = (
    "# comment line - keep me\n"
    "prismatic_evolutions_etb:\n"
    '  name: "Prismatic Evolutions Elite Trainer Box"\n'
    '  target_tcin: ""\n'
    '  walmart_item_id: "15433520586"\n'
    "\n"
    "surging_sparks_etb:\n"
    '  name: "Surging Sparks Elite Trainer Box"\n'
    '  target_tcin: "91619922"\n'
)


def test_set_product_id_updates_only_target_field():
    out = set_product_id(CATALOG, "prismatic_evolutions_etb", "target_tcin", "93954435")
    assert '  target_tcin: "93954435"' in out
    # comment + sibling field preserved
    assert "# comment line - keep me" in out
    assert '  walmart_item_id: "15433520586"' in out
    # the OTHER product's tcin must be untouched
    assert '  target_tcin: "91619922"' in out


def test_set_product_id_unknown_key_raises():
    with pytest.raises(KeyError):
        set_product_id(CATALOG, "nonexistent_product", "target_tcin", "1")


def test_set_product_id_unknown_field_raises():
    with pytest.raises(KeyError):
        set_product_id(CATALOG, "prismatic_evolutions_etb", "gamestop_pid", "x")


def test_add_id_cli_updates_temp_catalog(tmp_path, capsys):
    catalog_path = tmp_path / "products.yaml"
    catalog_path.write_text(CATALOG, encoding="utf-8")

    rc = add_id_main(
        [
            "target",
            "prismatic_evolutions_etb",
            "https://www.target.com/p/-/A-93954435",
            "--products",
            str(catalog_path),
        ]
    )

    assert rc == 0
    out = catalog_path.read_text(encoding="utf-8")
    assert '  target_tcin: "93954435"' in out
    assert '  walmart_item_id: "15433520586"' in out
    assert "set prismatic_evolutions_etb.target_tcin = 93954435" in capsys.readouterr().out


def test_add_id_cli_bad_product_key_fails_without_rewriting(tmp_path, capsys):
    catalog_path = tmp_path / "products.yaml"
    catalog_path.write_text(CATALOG, encoding="utf-8")

    rc = add_id_main(
        [
            "target",
            "missing_product",
            "https://www.target.com/p/-/A-93954435",
            "--products",
            str(catalog_path),
        ]
    )

    assert rc == 2
    assert catalog_path.read_text(encoding="utf-8") == CATALOG
    assert "product key not found: missing_product" in capsys.readouterr().err
