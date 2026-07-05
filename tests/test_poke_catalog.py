"""Track D1 — raw/graded asset catalog: loader, validation, identity.

Pure, no network. Proves sealed identity is untouched and raw / graded / sealed
item keys never collide (spec proofs #2, #3, #5, and the #1 sealed regression)."""
from __future__ import annotations

import textwrap

import pytest

from scanner.poke_api import catalog, history


RAW_NM = {"asset_class": "raw", "name": "Umbreon ex", "set": "Prismatic Evolutions",
          "card_number": "161", "condition": "NM"}
RAW_LP = {**RAW_NM, "condition": "LP"}
PSA10 = {"asset_class": "graded", "name": "Umbreon ex", "set": "Prismatic Evolutions",
         "card_number": "161", "grader": "PSA", "grade": "10", "grade_key": "psa10"}
PSA9 = {**PSA10, "grade": "9", "grade_key": "psa9"}
SEALED_PRODUCT = {"name": "Prismatic Evolutions Elite Trainer Box",
                  "set": "Prismatic Evolutions", "type": "ETB"}


# --- normalize_grade_key -------------------------------------------------------

def test_normalize_grade_key():
    assert catalog.normalize_grade_key("PSA", "10") == "psa10"
    assert catalog.normalize_grade_key("CGC", "9.5") == "cgc9.5"
    assert catalog.normalize_grade_key("BGS", " 9 ") == "bgs9"


# --- validation (#2 raw needs condition, #3 graded needs grader+grade) ---------

def test_raw_asset_requires_condition():
    assert catalog.validate_asset("umbreon_raw_nm", RAW_NM) == []
    missing = catalog.validate_asset(
        "umbreon_raw", {k: v for k, v in RAW_NM.items() if k != "condition"})
    assert any("condition" in m for m in missing)


def test_graded_asset_requires_grader_and_grade():
    assert catalog.validate_asset("umbreon_psa10", PSA10) == []
    no_grader = catalog.validate_asset("x", {k: v for k, v in PSA10.items() if k != "grader"})
    assert any("grader" in m for m in no_grader)
    no_grade = catalog.validate_asset("x", {k: v for k, v in PSA10.items() if k != "grade"})
    assert any("grade" in m for m in no_grade)


def test_validate_requires_name_and_set():
    problems = catalog.validate_asset("x", {"asset_class": "raw", "condition": "NM"})
    assert any("name" in m for m in problems)
    assert any("set" in m for m in problems)


def test_validate_rejects_unknown_asset_class():
    # sealed lives in products.yaml; the asset catalog is raw|graded only
    problems = catalog.validate_asset("x", {"asset_class": "sealed", "name": "n", "set": "s"})
    assert any("asset_class" in m for m in problems)


# --- identity (#5 no collision, #1 sealed regression) --------------------------

def test_item_keys_do_not_collide():
    keys = {
        history.item_key_for_asset(RAW_NM),
        history.item_key_for_asset(RAW_LP),
        history.item_key_for_asset(PSA10),
        history.item_key_for_asset(PSA9),
        history.item_key_for_product(SEALED_PRODUCT, "prismatic_evolutions_etb"),
    }
    assert len(keys) == 5


def test_sealed_item_key_unchanged_regression():
    assert (history.item_key_for_product(SEALED_PRODUCT, "prismatic_evolutions_etb")
            == "prismatic evolutions|prismatic evolutions elite trainer box|||")


def test_asset_key_slots_grade_and_condition():
    assert history.item_key_for_asset(PSA10) == "prismatic evolutions|umbreon ex|161|psa10|"
    assert history.item_key_for_asset(RAW_NM) == "prismatic evolutions|umbreon ex|161||nm"


# --- loader --------------------------------------------------------------------

def test_load_assets_missing_file_is_empty(tmp_path):
    assert catalog.load_assets(tmp_path / "nope.yaml") == {}


def test_load_assets_reads_and_derives_grade_key(tmp_path):
    p = tmp_path / "assets.yaml"
    p.write_text(textwrap.dedent("""
        umbreon_psa10:
          asset_class: graded
          name: Umbreon ex
          set: Prismatic Evolutions
          card_number: "161"
          grader: PSA
          grade: "10"
        pikachu_raw_nm:
          asset_class: raw
          name: Pikachu ex
          set: Surging Sparks
          card_number: "247"
          condition: NM
    """), encoding="utf-8")
    assets = catalog.load_assets(p)
    assert set(assets) == {"umbreon_psa10", "pikachu_raw_nm"}
    assert assets["umbreon_psa10"]["grade_key"] == "psa10"   # derived when omitted


def test_load_assets_raises_on_invalid(tmp_path):
    p = tmp_path / "assets.yaml"
    p.write_text(textwrap.dedent("""
        bad_raw:
          asset_class: raw
          name: No Condition Card
          set: Some Set
    """), encoding="utf-8")
    with pytest.raises(catalog.AssetCatalogError):
        catalog.load_assets(p)


def test_load_assets_raises_asset_catalog_error_on_malformed_yaml(tmp_path):
    """A syntactically broken catalog must surface as AssetCatalogError (not a raw
    yaml.YAMLError) so build_deps' containment keeps it off the sealed routes."""
    p = tmp_path / "assets.yaml"
    # a tab in the indentation is a hard YAML scanner error, not merely an invalid asset
    p.write_text("umbreon_psa10:\n  asset_class: graded\n\tname: bad tab indent\n",
                 encoding="utf-8")
    with pytest.raises(catalog.AssetCatalogError):
        catalog.load_assets(p)


def test_asset_summary_shape():
    s = catalog.asset_summary("umbreon_psa10", PSA10)
    assert s["asset_key"] == "umbreon_psa10"
    assert s["asset_class"] == "graded"
    assert s["grader"] == "PSA" and s["grade"] == "10" and s["grade_key"] == "psa10"
    assert s["card_number"] == "161"
