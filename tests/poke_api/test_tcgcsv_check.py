from scanner.poke_api import tcgcsv_check
from scanner.poke_api import history as history_mod


def _pair(diff_pct):
    return {"asset_key": f"a{diff_pct}", "tcgplayer_id": 1, "ppt_price": 100.0,
            "tcgcsv_price": 100.0 * (1 + diff_pct / 100.0), "diff_pct": diff_pct}


def test_pass_when_enough_pairs_all_within_tolerance():
    pairs = [_pair(0.0), _pair(0.5), _pair(1.0), _pair(1.5), _pair(1.9)]
    result = tcgcsv_check.sample_check(pairs)
    assert result["status"] == "pass"
    assert result["n"] == 5


def test_fail_when_any_pair_exceeds_tolerance():
    pairs = [_pair(0.0), _pair(0.5), _pair(1.0), _pair(1.5), _pair(3.0)]
    result = tcgcsv_check.sample_check(pairs)
    assert result["status"] == "fail"
    assert "tolerance" in result["reason"]


def test_fail_when_too_few_pairs():
    pairs = [_pair(0.0), _pair(0.5)]
    result = tcgcsv_check.sample_check(pairs)
    assert result["status"] == "fail"
    assert "n=2" in result["reason"] or "minimum" in result["reason"]


# ------------------------------------------------------- build_pairs (exact tcgcsv_group_id)

def _obs_ppt(asset, price, date="2026-07-07"):
    # An observation carries a precomputed "item_key" STRING (item_key_for_asset returns a
    # str, not a dict) — matches how every existing test in the suite builds observations.
    return {"item_key": history_mod.item_key_for_asset(asset), "kind": history_mod.MARKET_COMP,
            "source": "ppt_cards", "comp": price, "capture_date": date}


def test_build_pairs_uses_exact_group_id_field(monkeypatch):
    asset = {"asset_class": "raw", "name": "Umbreon ex 161", "set": "Prismatic Evolutions",
             "card_number": "161", "tcgplayer_id": "610516", "tcgcsv_group_id": 23821}
    assets = {"umbreon_ex_161_raw_nm": asset}
    obs = [_obs_ppt(asset, 1528.09)]

    seen = {}

    def _fp(group_id):
        seen["group_id"] = group_id
        return [{"productId": 610516, "subTypeName": "Normal", "marketPrice": 1528.09}]

    # groups list is now irrelevant to asset->group resolution; pass empty to prove it.
    pairs, skipped = tcgcsv_check.build_pairs(assets, obs, [], fetch_prices=_fp)
    assert seen["group_id"] == 23821       # resolved from the field, not name-matching
    assert len(pairs) == 1
    assert pairs[0]["tcgplayer_id"] == "610516"


def test_build_pairs_skips_when_no_group_id_field():
    asset = {"asset_class": "raw", "name": "Umbreon ex 161", "set": "Prismatic Evolutions",
             "tcgplayer_id": "610516"}  # no tcgcsv_group_id
    assets = {"umbreon_ex_161_raw_nm": asset}
    obs = [_obs_ppt(asset, 1528.09)]
    pairs, skipped = tcgcsv_check.build_pairs(assets, obs, [], fetch_prices=lambda g: [])
    assert pairs == []
    assert any("tcgcsv_group_id" in s["reason"] for s in skipped)


# ------------------------------------------ resolve_group_id (TCGCSV group-name normalization)
#
# Real TCGCSV group names carry a set-family prefix the catalog's ``set`` field omits
# (e.g. "SV: Prismatic Evolutions" vs catalog "Prismatic Evolutions") — verified live
# against tcgcsv.com/tcgplayer/3/groups (217 groups, 2026-07-07) for every set in
# DEFAULT_SET_WATCH. This is the one piece of novel, production-critical logic in the
# module (everything else is either brief-verbatim or trivial), so it gets its own
# locked-in unit coverage rather than relying solely on the manual live check.

def test_resolve_group_id_strips_set_family_prefix():
    groups = [{"groupId": 23821, "name": "SV: Prismatic Evolutions"}]
    assert tcgcsv_check.resolve_group_id("Prismatic Evolutions", groups) == 23821


def test_resolve_group_id_ambiguous_dup_normalized_name_is_none():
    # Real live-list case: two distinct groups normalize to the same bare name.
    groups = [{"groupId": 1, "name": "SV: Shiny Vault"},
              {"groupId": 2, "name": "SWSH: Shiny Vault"}]
    assert tcgcsv_check.resolve_group_id("Shiny Vault", groups) is None


def test_resolve_group_id_split_on_first_colon_not_a_substring_match():
    # "SWSH: Crown Zenith: Galarian Gallery" must NOT match set "Crown Zenith" — the
    # split-on-first-": " normalization leaves "Crown Zenith: Galarian Gallery", which is
    # not equal to "Crown Zenith". Only the bare "SWSH: Crown Zenith" group matches.
    groups = [{"groupId": 10, "name": "SWSH: Crown Zenith"},
              {"groupId": 11, "name": "SWSH: Crown Zenith: Galarian Gallery"}]
    assert tcgcsv_check.resolve_group_id("Crown Zenith", groups) == 10


def test_resolve_group_id_no_match_is_none():
    groups = [{"groupId": 1, "name": "SV: Paldean Fates"}]
    assert tcgcsv_check.resolve_group_id("Destined Rivals", groups) is None
