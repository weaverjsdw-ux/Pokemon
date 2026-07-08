from scanner.poke_api import tcgcsv_ingest


def test_exact_number_match_proposes_productid():
    products = [{"productId": 111, "name": "Umbreon ex",
                 "extendedData": [{"name": "Number", "value": "161/131"}]}]
    assets = [{"asset_key": "umbreon_ex_161", "name": "Umbreon ex", "card_number": "161/131"}]
    out = tcgcsv_ingest.propose_mappings(products, assets)
    assert out[0]["match"] == "exact"
    assert out[0]["tcgplayer_id"] == 111


def test_no_number_match_is_none_never_guessed():
    products = [{"productId": 111, "name": "Umbreon ex",
                 "extendedData": [{"name": "Number", "value": "160/131"}]}]
    assets = [{"asset_key": "umbreon_ex_161", "name": "Umbreon ex", "card_number": "161/131"}]
    out = tcgcsv_ingest.propose_mappings(products, assets)
    assert out[0]["match"] == "none"
    assert out[0]["tcgplayer_id"] is None


def test_number_match_but_name_mismatch_is_none_never_guessed():
    # Same card_number, different printing/name at that number — never guessed.
    products = [{"productId": 111, "name": "Umbreon ex (Alt Art)",
                 "extendedData": [{"name": "Number", "value": "161/131"}]}]
    assets = [{"asset_key": "umbreon_ex_161", "name": "Umbreon ex", "card_number": "161/131"}]
    out = tcgcsv_ingest.propose_mappings(products, assets)
    assert out[0]["match"] == "none"
    assert out[0]["tcgplayer_id"] is None


def test_ambiguous_multiple_exact_candidates_is_none_never_guessed():
    # Two products share both the number and the normalized name — cannot pick one.
    products = [
        {"productId": 111, "name": "Umbreon ex",
         "extendedData": [{"name": "Number", "value": "161/131"}]},
        {"productId": 222, "name": "Umbreon EX",
         "extendedData": [{"name": "Number", "value": "161/131"}]},
    ]
    assets = [{"asset_key": "umbreon_ex_161", "name": "Umbreon ex", "card_number": "161/131"}]
    out = tcgcsv_ingest.propose_mappings(products, assets)
    assert out[0]["match"] == "none"
    assert out[0]["tcgplayer_id"] is None


def test_name_normalization_is_case_and_whitespace_insensitive():
    products = [{"productId": 111, "name": "  Umbreon   ex  ",
                 "extendedData": [{"name": "Number", "value": "161/131"}]}]
    assets = [{"asset_key": "umbreon_ex_161", "name": "umbreon EX", "card_number": "161/131"}]
    out = tcgcsv_ingest.propose_mappings(products, assets)
    assert out[0]["match"] == "exact"
    assert out[0]["tcgplayer_id"] == 111


def test_asset_missing_card_number_is_none_never_guessed():
    products = [{"productId": 111, "name": "Umbreon ex",
                 "extendedData": [{"name": "Number", "value": "161/131"}]}]
    assets = [{"asset_key": "umbreon_ex_unknown_num", "name": "Umbreon ex"}]
    out = tcgcsv_ingest.propose_mappings(products, assets)
    assert out[0]["match"] == "none"
    assert out[0]["tcgplayer_id"] is None


def test_multiple_assets_independent_results_preserve_order():
    products = [{"productId": 111, "name": "Umbreon ex",
                 "extendedData": [{"name": "Number", "value": "161/131"}]}]
    assets = [
        {"asset_key": "a_match", "name": "Umbreon ex", "card_number": "161/131"},
        {"asset_key": "b_no_match", "name": "Someone Else", "card_number": "999/131"},
    ]
    out = tcgcsv_ingest.propose_mappings(products, assets)
    assert [o["asset_key"] for o in out] == ["a_match", "b_no_match"]
    assert out[0]["match"] == "exact"
    assert out[1]["match"] == "none"


def test_proposal_carries_group_id():
    products = [{"productId": 111, "name": "Umbreon ex",
                 "extendedData": [{"name": "Number", "value": "161/131"}]}]
    assets = [{"asset_key": "umbreon_ex_161", "name": "Umbreon ex", "card_number": "161/131"}]
    out = tcgcsv_ingest.propose_mappings(products, assets, group_id=23821)
    assert out[0]["match"] == "exact"
    assert out[0]["tcgcsv_group_id"] == 23821
