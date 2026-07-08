# tests/poke_api/test_tcgcsv_source.py
from scanner.comps.model import SOLD_DERIVED
from scanner.poke_api import tcgcsv_source


_ROWS = [{"productId": 610516, "subTypeName": "Normal", "marketPrice": 1528.09}]


def _fp_ok(_group_id):
    return _ROWS


def _fp_empty(_group_id):
    return []


def test_fetch_ok_builds_tcgcsv_quote():
    src = tcgcsv_source.TcgCsvSource(fetch_prices=_fp_ok)
    product = {"ppt_id": "610516", "tcgcsv_group_id": 23821}
    q = src.fetch("umbreon_box", product, 1_700_000_000)
    assert q.source == "tcgcsv"
    assert q.kind == SOLD_DERIVED
    assert q.status == "ok"
    assert q.price == 1528.09
    assert q.url == "https://tcgcsv.com/tcgplayer/3/23821/prices"


def test_fetch_no_id_is_skipped_zero_network():
    called = {"n": 0}

    def _fp_spy(_g):
        called["n"] += 1
        return _ROWS

    src = tcgcsv_source.TcgCsvSource(fetch_prices=_fp_spy)
    q = src.fetch("x", {"tcgcsv_group_id": 23821}, 1_700_000_000)  # no ppt_id
    assert q.status == "skipped"
    assert q.price is None
    assert called["n"] == 0  # never fetched without an id


def test_fetch_no_group_is_skipped():
    src = tcgcsv_source.TcgCsvSource(fetch_prices=_fp_ok)
    q = src.fetch("x", {"ppt_id": "610516"}, 1_700_000_000)  # no group
    assert q.status == "skipped"
    assert q.price is None


def test_fetch_unresolved_price_is_no_match():
    src = tcgcsv_source.TcgCsvSource(fetch_prices=_fp_empty)
    product = {"ppt_id": "610516", "tcgcsv_group_id": 23821}
    q = src.fetch("x", product, 1_700_000_000)
    assert q.status == "no_match"
    assert q.price is None


def test_fetch_non_numeric_id_is_skipped_never_crashes():
    src = tcgcsv_source.TcgCsvSource(fetch_prices=_fp_ok)
    product = {"ppt_id": "abc", "tcgcsv_group_id": 23821}
    q = src.fetch("x", product, 1_700_000_000)
    assert q.status == "skipped"


def test_raw_reference_quote_ok():
    asset = {"tcgplayer_id": "610516", "tcgcsv_group_id": 23821}
    q = tcgcsv_source.raw_reference_quote(asset, 1_700_000_000, fetch_prices=_fp_ok)
    assert q.source == "tcgcsv"
    assert q.status == "ok"
    assert q.price == 1528.09
