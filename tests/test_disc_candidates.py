"""Slice 3: CandidateDeal schema + catalog/set-watch title matching."""
import dataclasses
import hashlib

import pytest

from scanner.discovery import candidates

CATALOG = {
    "prismatic_etb": {"name": "Prismatic Evolutions Elite Trainer Box",
                      "set": "Prismatic Evolutions", "type": "ETB", "msrp": "$49.99"},
    "prismatic_bundle": {"name": "Prismatic Evolutions Booster Bundle",
                         "set": "Prismatic Evolutions", "type": "Booster Bundle",
                         "msrp": "$26.94"},
    "surging_etb": {"name": "Surging Sparks Elite Trainer Box",
                    "set": "Surging Sparks", "type": "ETB", "msrp": "$49.99"},
}
SET_WATCH = ["Prismatic Evolutions", "Surging Sparks", "Paldean Fates"]


def _candidate(**kw):
    base = dict(source="slickdeals", listing_id="123", item_name="X", price=10.0,
                shipping=None, url="https://example.com/x", retailer="Amazon",
                seen_at="2026-07-03T10:00:00+00:00", evidence_excerpt="X $10",
                matched_product_key=None, matched_set="")
    base.update(kw)
    return candidates.CandidateDeal(**base)


def test_candidate_deal_is_frozen_evidence():
    c = _candidate()
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.price = 5.0
    assert c.asset_class == "sealed"


def test_stable_listing_id_is_sha256_of_url():
    url = "https://example.com/deal/42"
    assert candidates.stable_listing_id(url) == hashlib.sha256(
        url.encode("utf-8")).hexdigest()


# ------------------------------------------------------------- ring matching


def _match(title):
    return candidates.match_title(title, CATALOG, SET_WATCH)


def test_etb_title_matches_etb_not_bundle():
    key, set_name = _match("Pokemon TCG Prismatic Evolutions Elite Trainer Box Sealed")
    assert key == "prismatic_etb"


def test_bundle_title_matches_bundle_not_etb():
    key, _ = _match("Pokemon TCG Prismatic Evolutions Booster Bundle Sealed")
    assert key == "prismatic_bundle"


def test_etb_abbreviation_expands():
    key, _ = _match("Pokemon Prismatic Evolutions ETB New In Hand")
    assert key == "prismatic_etb"


def test_pokemon_center_exclusive_falls_to_set_watch():
    # _title_allowed rejects PC-exclusive variants for non-PC catalog entries;
    # the set is watched, so it stays a Ring-2 candidate instead of vanishing.
    key, set_name = _match(
        "Pokemon TCG Surging Sparks Elite Trainer Box Pokemon Center Exclusive")
    assert key is None
    assert set_name == "Surging Sparks"


def test_watched_set_without_catalog_product_is_ring2():
    key, set_name = _match("Pokemon TCG Paldean Fates Mini Tin Display Sealed")
    assert key is None and set_name == "Paldean Fates"


def test_junk_titles_are_rejected_everywhere():
    for title in ("Prismatic Evolutions ETB EMPTY BOX no cards",
                  "Pokemon Prismatic Evolutions Japanese Booster Box",
                  "Prismatic Evolutions code card digital"):
        assert candidates.junk_title(title)
        key, set_name = _match(title)
        assert key is None and set_name == ""


def test_unrelated_title_matches_nothing():
    key, set_name = _match("Disney Lorcana TCG Illumineer's Trove Sealed")
    assert key is None and set_name == ""


def test_accented_pokemon_titles_still_match():
    # real Slickdeals titles say "Pokémon" — the é must not break token matching
    key, _ = _match("Pokémon TCG: Prismatic Evolutions Elite Trainer Box")
    assert key == "prismatic_etb"
    key2, set_name = _match("Pokémon TCG Paldean Fates Tin")
    assert key2 is None and set_name == "Paldean Fates"
