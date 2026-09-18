"""Singles (raw/graded) feed into discovery + the cross-catalog set-name join.

Two things are proven here:

* the asset catalog reaches the board and the pipeline carrying its REAL
  asset_class / condition / grade — and an asset with no verified exact source
  stays an honest WATCH catalog gap rather than acquiring a number;
* sealed is untouched: the feed is gated off by default, an asset never displaces
  a sealed match, and the sealed sweep dict is byte-identical without the gate.

No network, no PPT: every comp here is either injected or read from an in-test
ledger file.
"""
from __future__ import annotations

import json

from scanner import config as cfg_mod
from scanner import setname as setname_mod
from scanner.discovery import assets_feed, golden, pipeline, render, sweep
from scanner.discovery import verify as verify_mod
from scanner.discovery.adapters.base import DiscoverySource
from scanner.discovery.candidates import CandidateDeal
from scanner.discovery.schema import row_from_dict, assert_sweep
from scanner.state import State

CHECKED = "2026-09-18T12:00:00+00:00"
BUY_URL = "https://www.ebay.com/itm/1234567890"
COMP_URL = "https://www.pricecharting.com/game/pokemon-journey-together/mamoswine-ex-174"

SEALED = {
    "scarlet_violet_151_etb": {
        "name": "Scarlet & Violet 151 Elite Trainer Box", "set": "151",
        "type": "ETB", "msrp": "$49.99",
        "resale_query": "Pokemon TCG Scarlet Violet 151 Elite Trainer Box sealed"},
}

ASSETS = {
    "mamoswine_ex_174_jt_raw_nm": {
        "asset_class": "raw", "name": "Mamoswine ex 174", "set": "Journey Together",
        "card_number": "174", "condition": "NM"},
    "mamoswine_ex_174_jt_psa10": {
        "asset_class": "graded", "name": "Mamoswine ex 174", "set": "Journey Together",
        "card_number": "174", "grader": "PSA", "grade": "10", "grade_key": "psa10"},
    "charizard_ex_199_151_raw_nm": {
        "asset_class": "raw", "name": "Charizard ex 199", "set": "Scarlet & Violet 151",
        "card_number": "199", "condition": "NM"},
}


def _cfg(**poke):
    raw = {"locations": {"home": "A", "work": "B"}}
    if poke:
        raw["poke"] = poke
    cfg = cfg_mod.from_mapping(raw)
    cfg.products = dict(SEALED)
    cfg.products_filter = None
    return cfg


def _obs(asset, *, price, source_url=COMP_URL, date="2026-09-17"):
    """A ledger market_comp observation for an asset, built the way the writer
    builds it: the five identity slots from ``asset_identity`` plus the
    ``item_key`` ``append_observation`` stamps on the record. Hand-rolling either
    half is how a read-first lookup silently returns null."""
    from scanner.discovery import ledger as ledger_mod
    from scanner.poke_api import history as history_mod

    identity = history_mod.asset_identity(asset)
    return identity | {
        "item_key": ledger_mod.item_key(identity),
        "kind": "market_comp", "comp": price, "comp_confidence": "medium",
        "source": "pricecharting", "source_url": source_url, "capture_date": date,
    }


# ---------------------------------------------------------------- the gate

def test_gate_is_off_by_default_and_feeds_nothing():
    cfg = _cfg()
    assert cfg.poke.singles_board is False
    assert assets_feed.singles_enabled(cfg) is False
    assert assets_feed.load_feed_assets(cfg) == ({}, "")


def test_gate_on_reads_the_catalog(tmp_path):
    path = tmp_path / "assets.yaml"
    path.write_text(json.dumps(ASSETS), encoding="utf-8")   # JSON is valid YAML
    assets, error = assets_feed.load_feed_assets(_cfg(singles_board=True), path=path)
    assert error == ""
    assert set(assets) == set(ASSETS)


def test_malformed_catalog_is_contained_not_raised(tmp_path):
    path = tmp_path / "assets.yaml"
    path.write_text("not_a_mapping: [1, 2, 3]\n", encoding="utf-8")
    assets, error = assets_feed.load_feed_assets(_cfg(singles_board=True), path=path)
    assert assets == {}
    assert "asset entry must be a mapping" in error


# ---------------------------------------------------------------- board watch

def test_watch_carries_real_asset_class_and_spec():
    watch = assets_feed.build_asset_watch(
        ASSETS, [_obs(ASSETS["mamoswine_ex_174_jt_psa10"], price=210.0)])
    by_key = {w["asset_key"]: w for w in watch}

    graded = by_key["mamoswine_ex_174_jt_psa10"]
    assert graded["asset_class"] == "graded"
    assert (graded["grader"], graded["grade"]) == ("PSA", "10")
    assert graded["estimate"] == 210.0
    assert graded["category"] == assets_feed.SINGLES_CATEGORY

    raw = by_key["charizard_ex_199_151_raw_nm"]
    assert raw["asset_class"] == "raw"
    assert raw["condition"] == "NM"
    # never "sealed" — the whole point of the feed
    assert {w["asset_class"] for w in watch} == {"raw", "graded"}


def test_asset_with_no_verified_source_is_an_honest_watch_gap():
    """Criterion: no exact source -> estimate null / confidence none, and it is
    still SURFACED (a gap is evidence, not a row to hide)."""
    watch = assets_feed.build_asset_watch(ASSETS, [])
    gap = next(w for w in watch if w["asset_key"] == "mamoswine_ex_174_jt_raw_nm")
    assert gap["estimate"] is None
    assert gap["confidence"] == "none"
    assert gap["trade_type"] == "raw_catalog_gap"
    assert gap["decision"] == "WATCH"
    assert assets_feed.watch_counts(watch) == {
        "assets": 3, "comped": 0, "catalog_gap": 3}


def test_a_comped_asset_is_market_watch_not_a_gap():
    watch = assets_feed.build_asset_watch(
        ASSETS, [_obs(ASSETS["charizard_ex_199_151_raw_nm"], price=88.0)])
    row = next(w for w in watch if w["asset_key"] == "charizard_ex_199_151_raw_nm")
    assert row["trade_type"] == "raw_market_watch"
    assert row["decision"] == "WATCH"      # never live-eligible on this path
    assert assets_feed.watch_counts(watch)["comped"] == 1


# ---------------------------------------------------------------- sealed is untouched

def _sealed_sweep(cfg, *, asset_watch=None):
    return sweep.build_sealed_sweep(
        cfg, lambda k, p: {"status": "ok", "estimate": "$70.00", "confidence": "medium",
                           "source": "PokemonPriceTracker", "basis": "TCGplayer sealed market",
                           "sourceUrl": "https://www.tcgplayer.com/product/1",
                           "url": "https://www.tcgplayer.com/product/1"},
        event="sealed", sweep_id="2026-09-18-sealed", captured_at="2026-09-18",
        asset_watch=asset_watch)


def test_sweep_without_asset_watch_is_unchanged():
    swp = _sealed_sweep(_cfg())
    assert "asset_watch" not in swp
    assert set(swp["counts"]) == {"scanned", "comped", "no_comp", "no_msrp", "no_source"}
    assert [d["asset_class"] for d in swp["deals"]] == ["sealed"]


def test_asset_watch_rides_alongside_deals_never_inside_them():
    watch = assets_feed.build_asset_watch(ASSETS, [])
    swp = _sealed_sweep(_cfg(singles_board=True), asset_watch=watch)
    # singles never enter "deals": they have no entry price to compare a comp to
    assert [d["asset_class"] for d in swp["deals"]] == ["sealed"]
    assert len(swp["asset_watch"]) == 3
    # the sealed counts dict is the sealed tally under both gate states
    assert set(swp["counts"]) == {"scanned", "comped", "no_comp", "no_msrp", "no_source"}
    assert swp["counts"]["scanned"] == 1
    assert assets_feed.watch_counts(swp["asset_watch"])["assets"] == 3


def test_singles_section_renders_and_passes_golden():
    watch = assets_feed.build_asset_watch(
        ASSETS, [_obs(ASSETS["mamoswine_ex_174_jt_psa10"], price=210.0)])
    swp = _sealed_sweep(_cfg(singles_board=True), asset_watch=watch)
    html = render.render_sweep(swp)
    section = render.section_html(html, "singles-watch")
    assert "Mamoswine ex 174" in section
    assert "PSA 10" in section
    assert "$210.00" in section
    assert "no verified source" in section          # the gap says so in words
    assert golden.golden_check(html, min_rows=0) == []   # no dangling nav anchor

    plain = render.render_sweep(_sealed_sweep(_cfg()))
    assert render.section_html(plain, "singles-watch") == ""
    assert "singles-watch" not in plain


# ---------------------------------------------------------------- listing matching

def test_graded_listing_matches_the_graded_asset_not_the_raw_one():
    assert assets_feed.match_asset(
        "Pokemon Mamoswine ex 174 Journey Together PSA 10", ASSETS
    ) == "mamoswine_ex_174_jt_psa10"


def test_raw_listing_matches_the_raw_asset():
    assert assets_feed.match_asset(
        "Pokemon Mamoswine ex 174 Journey Together NM", ASSETS
    ) == "mamoswine_ex_174_jt_raw_nm"


def test_ambiguous_listing_is_refused_not_guessed():
    """No grade/condition token: raw NM and PSA 10 are both plausible and they are
    different money. Refuse — a wrong pick is a wrong number."""
    assert assets_feed.match_asset("Pokemon Mamoswine ex 174", ASSETS) is None


def test_non_pokemon_listing_does_not_match_an_asset():
    assert assets_feed.match_asset("Mamoswine ex 174 custom art proxy", ASSETS) is None


# ---------------------------------------------------------------- pipeline rows

class _FakeSource(DiscoverySource):
    def __init__(self, candidates):
        super().__init__()
        self.slug = "slickdeals"
        self.min_interval_seconds = 0
        self._candidates = candidates

    def discover(self, cfg, catalog, set_watch, **kwargs):
        self._set_state("WORKING", "")
        # the asset catalog is deliberately NOT handed to adapters
        assert "mamoswine_ex_174_jt_psa10" not in catalog
        return list(self._candidates)


def _candidate(title, listing_id="c1", *, price=120.0, matched=None):
    return CandidateDeal(
        source="slickdeals", listing_id=listing_id, item_name=title, price=price,
        shipping=None, url=BUY_URL, retailer="SomeStore", seen_at=CHECKED,
        evidence_excerpt=f"{title} | ${price:.2f}",
        matched_product_key=matched, matched_set="151" if matched else "")


def _verified(price=120.0):
    return verify_mod.StockVerification(
        state=verify_mod.VERIFIED_BUYABLE, stock_status="in_stock",
        verified_price=price, expected_price=None, price_matches=True,
        buy_url=BUY_URL, checked_at=CHECKED, source="slickdeals",
        method="page_fetch", evidence=f"in stock ${price:.2f}", degraded_reason="")


def _asset_comp_row(estimate="$150.00"):
    return {"status": "ok", "estimate": estimate, "confidence": "medium",
            "source": "PriceCharting", "basis": "graded market",
            "compBasis": "pricecharting sold-derived",
            "sourceUrl": COMP_URL, "url": COMP_URL}


def _run(cfg, tmp_path, candidates, *, assets=None):
    return pipeline.run_once(
        cfg, sources=[_FakeSource(candidates)],
        verifier=lambda c: _verified(c.price),
        comp_lookup=lambda c, p: _asset_comp_row(),
        notifier=type("N", (), {"send_deal": lambda self, d, *, push: None})(),
        state=State(db_path=tmp_path / "s.db"), catalog=dict(SEALED), assets=assets,
        now_ts=1_000_000, captured_at="2026-09-18")


def test_graded_candidate_becomes_a_graded_row_that_survives_the_stop_gate(tmp_path):
    manifest = _run(
        _cfg(singles_board=True), tmp_path,
        [_candidate("Pokemon Mamoswine ex 174 Journey Together PSA 10")],
        assets=dict(ASSETS))
    row = manifest["board"]["deals"][0]
    assert row["asset_class"] == "graded"
    assert (row["grader"], row["grade"]) == ("PSA", "10")
    assert row["category"] == assets_feed.SINGLES_CATEGORY
    assert row["deal_price"] == 120.0          # the real verified listing price
    assert manifest["assets_fed"] == 3
    assert_sweep([row_from_dict(d) for d in manifest["board"]["deals"]])


def test_raw_candidate_becomes_a_raw_row_with_its_condition(tmp_path):
    manifest = _run(
        _cfg(singles_board=True), tmp_path,
        [_candidate("Pokemon Mamoswine ex 174 Journey Together NM", price=14.0)],
        assets=dict(ASSETS))
    row = manifest["board"]["deals"][0]
    assert row["asset_class"] == "raw"
    assert row["condition"] == "NM"
    assert row["variant"] == "174"
    assert_sweep([row_from_dict(d) for d in manifest["board"]["deals"]])


def test_a_sealed_match_is_never_displaced_by_an_asset(tmp_path):
    cand = _candidate("Scarlet & Violet 151 Elite Trainer Box sealed",
                      matched="scarlet_violet_151_etb", price=60.0)
    manifest = _run(_cfg(singles_board=True), tmp_path, [cand], assets=dict(ASSETS))
    row = manifest["board"]["deals"][0]
    assert row["asset_class"] == "sealed"
    assert row["set"] == "151"                 # persisted label, not normalized


def test_gate_off_leaves_the_pipeline_sealed_only(tmp_path):
    manifest = _run(
        _cfg(), tmp_path,
        [_candidate("Pokemon Mamoswine ex 174 Journey Together PSA 10")])
    assert "assets_fed" not in manifest
    assert manifest["counts"]["no_comp"] == 0
    # unmatched, so it stays a ring-3 candidate and never claims to be graded
    assert all(d["asset_class"] == "sealed" for d in manifest["board"]["deals"])


# ---------------------------------------------------------------- set-name join

def test_sealed_151_and_single_151_resolve_to_the_same_set_identity():
    """The join the two catalogs previously failed: products.yaml says "151",
    assets.yaml says "Scarlet & Violet 151". Same set, same identity."""
    sealed_set = SEALED["scarlet_violet_151_etb"]["set"]
    single_set = ASSETS["charizard_ex_199_151_raw_nm"]["set"]
    assert sealed_set != single_set                       # the raw strings differ
    assert setname_mod.set_identity(sealed_set) == setname_mod.set_identity(single_set)
    assert setname_mod.same_set(sealed_set, single_set)
    assert setname_mod.set_identity(sealed_set) == "scarlet violet 151"


def test_the_real_catalogs_join_on_set_identity():
    """The same join against the catalogs ON DISK, not in-test fixtures.

    ``SET_ALIASES`` is keyed on the literal "151". If that string is renamed in
    products.yaml the alias stops firing and the join silently breaks again — a
    fixture-only test would still pass. This one fails loudly, which is the only
    enforcement the "do not rename set: 151 on sight" boundary has. products.yaml
    is read directly: config.yaml is gitignored and must not be a test dependency."""
    import yaml

    from scanner.poke_api import catalog as catalog_mod

    products = yaml.safe_load(
        (cfg_mod.ROOT / "data" / "products.yaml").read_text(encoding="utf-8"))
    assets = catalog_mod.load_assets(cfg_mod.ROOT / "data" / "poke" / "assets.yaml")

    sealed_set = products["scarlet_violet_151_etb"]["set"]
    single_set = assets["charizard_ex_199_151_raw_nm"]["set"]
    assert sealed_set != single_set          # the labels still differ on disk
    assert setname_mod.same_set(sealed_set, single_set)
    assert products["scarlet_violet_151_booster_bundle"]["set"] == sealed_set


def test_set_identity_folds_case_punctuation_and_diacritics():
    assert setname_mod.set_identity("Scarlet & Violet 151") == \
        setname_mod.set_identity("  scarlet and violet 151  ".replace("and", "&"))
    assert setname_mod.set_identity("Pokémon 151") == "pokemon 151"


def test_an_unknown_set_is_left_alone_never_guessed():
    assert setname_mod.canonical_set_name("Surging Sparks") == "Surging Sparks"
    assert setname_mod.set_identity("Surging Sparks") == "surging sparks"
    assert setname_mod.same_set("Surging Sparks", "151") is False


def test_an_absent_set_joins_to_nothing():
    assert setname_mod.set_identity("") == ""
    assert setname_mod.set_identity(None) == ""
    assert setname_mod.same_set("", "") is False
    assert setname_mod.same_set(None, "151") is False


def test_the_watch_row_carries_the_join_key_alongside_the_real_label():
    watch = assets_feed.build_asset_watch(ASSETS, [])
    row = next(w for w in watch if w["asset_key"] == "charizard_ex_199_151_raw_nm")
    assert row["set"] == "Scarlet & Violet 151"        # what the catalog says
    assert row["set_identity"] == "scarlet violet 151"  # what a join compares
