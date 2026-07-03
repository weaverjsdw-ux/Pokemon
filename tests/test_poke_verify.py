"""Slice 2: purchasability verifier — terminal states, evidence, alert gate.

The design's reason to exist: no alert without stock AND price verified from
the actual buy page. Every candidate ends in exactly one terminal state and
only VERIFIED_BUYABLE may ever alert.
"""
import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from scanner.discovery import verify
from scanner.discovery.schema import DealRow, validate_row
from scanner.retailers.base import Retailer, StockResult

CHECKED_AT = "2026-07-03T10:00:00"
FIXTURES = Path("tests/fixtures/verify")


def _verification(**kw):
    base = dict(
        state=verify.VERIFIED_BUYABLE,
        stock_status="in_stock",
        verified_price=39.99,
        expected_price=39.99,
        price_matches=True,
        buy_url="https://www.walmart.com/ip/123",
        checked_at=CHECKED_AT,
        source="walmart",
        method="retailer_adapter:walmart",
        evidence="ONLINE_IN_STOCK $39.99",
        degraded_reason="",
    )
    base.update(kw)
    return verify.StockVerification(**base)


# ------------------------------------------------------------------ taxonomy


def test_seven_terminal_states_exactly():
    assert verify.TERMINAL_STATES == {
        verify.VERIFIED_BUYABLE, verify.OUT_OF_STOCK, verify.PRICE_MISMATCH,
        verify.PAGE_UNAVAILABLE, verify.PARSER_SUSPECT, verify.SOURCE_BLOCKED,
        verify.UNKNOWN_NO_ALERT,
    }
    assert verify.ALERTABLE_STATES == {verify.VERIFIED_BUYABLE}


# ------------------------------------------------------------- classify_stock


def test_classify_positive_stock_with_matching_price_is_buyable():
    state, matches, reason = verify.classify_stock("in_stock", 39.99, 39.99)
    assert state == verify.VERIFIED_BUYABLE and matches is True and reason == ""


def test_classify_positive_stock_without_expectation_is_buyable():
    state, matches, _ = verify.classify_stock("limited", 42.0, None)
    assert state == verify.VERIFIED_BUYABLE and matches is None


def test_classify_price_beyond_tolerance_is_mismatch():
    state, matches, reason = verify.classify_stock("in_stock", 55.0, 39.99)
    assert state == verify.PRICE_MISMATCH and matches is False
    assert "55.00" in reason and "39.99" in reason


def test_classify_price_within_tolerance_is_buyable():
    # 41.0 vs 39.99 is ~2.5% — inside the 5% default
    state, matches, _ = verify.classify_stock("in_stock", 41.0, 39.99)
    assert state == verify.VERIFIED_BUYABLE and matches is True


def test_classify_positive_stock_without_price_never_alerts():
    # stock seen but price unverified -> honest UNKNOWN_NO_ALERT, stock kept
    state, matches, reason = verify.classify_stock("in_stock", None, 39.99)
    assert state == verify.UNKNOWN_NO_ALERT and matches is None
    assert "price" in reason.lower()


def test_classify_out_of_stock():
    state, _, _ = verify.classify_stock("out_of_stock", None, 39.99)
    assert state == verify.OUT_OF_STOCK


def test_classify_unknown_stock_is_unknown_no_alert():
    state, _, _ = verify.classify_stock("unknown", 39.99, 39.99)
    assert state == verify.UNKNOWN_NO_ALERT


# ------------------------------------------------- adapter status translation


@pytest.mark.parametrize("adapter_status,expected_stock,expected_state", [
    ("IN_STOCK", "in_stock", verify.VERIFIED_BUYABLE),
    ("ONLINE_IN_STOCK", "in_stock", verify.VERIFIED_BUYABLE),
    ("LIMITED", "limited", verify.VERIFIED_BUYABLE),
    ("OUT", "out_of_stock", verify.OUT_OF_STOCK),
    ("ONLINE_OUT", "out_of_stock", verify.OUT_OF_STOCK),
])
def test_from_stock_result_maps_adapter_statuses(adapter_status, expected_stock, expected_state):
    result = StockResult(store=None, product_key="k", product_name="ETB",
                         status=adapter_status, url="https://w.example/p", price="$39.99")
    v = verify.from_stock_result(result, source="walmart",
                                 expected_price=39.99, checked_at=CHECKED_AT)
    assert v.stock_status == expected_stock
    assert v.state == expected_state
    assert v.method == "retailer_adapter:walmart"
    assert v.checked_at == CHECKED_AT
    assert adapter_status in v.evidence


def test_from_stock_result_priceless_positive_is_unknown_no_alert():
    result = StockResult(store=None, product_key="k", product_name="ETB",
                         status="IN_STOCK", url="https://t.example/p", price="")
    v = verify.from_stock_result(result, source="target",
                                 expected_price=39.99, checked_at=CHECKED_AT)
    assert v.state == verify.UNKNOWN_NO_ALERT
    assert v.stock_status == "in_stock"          # stock evidence NOT thrown away
    assert v.verified_price is None
    assert not verify.alert_allowed(v)


def test_from_stock_result_evidence_fields_complete():
    result = StockResult(store=None, product_key="k", product_name="ETB",
                         status="ONLINE_IN_STOCK", url="https://bb.example/sku/1",
                         price="$44.99")
    v = verify.from_stock_result(result, source="bestbuy",
                                 expected_price=44.99, checked_at=CHECKED_AT)
    assert v.source == "bestbuy"
    assert v.buy_url == "https://bb.example/sku/1"
    assert v.checked_at == CHECKED_AT
    assert v.verified_price == 44.99
    assert v.expected_price == 44.99
    assert v.stock_status == "in_stock"
    assert v.method == "retailer_adapter:bestbuy"
    assert v.evidence and len(v.evidence) <= 300


# ---------------------------------------------------------------- alert gate


def test_only_verified_buyable_may_alert():
    fixtures = {
        verify.VERIFIED_BUYABLE: _verification(),
        verify.OUT_OF_STOCK: _verification(state=verify.OUT_OF_STOCK,
                                           stock_status="out_of_stock",
                                           verified_price=None, price_matches=None),
        verify.PRICE_MISMATCH: _verification(state=verify.PRICE_MISMATCH,
                                             verified_price=55.0, price_matches=False),
        verify.PAGE_UNAVAILABLE: _verification(state=verify.PAGE_UNAVAILABLE,
                                               stock_status="unverifiable",
                                               verified_price=None, price_matches=None,
                                               degraded_reason="HTTP 404"),
        verify.PARSER_SUSPECT: _verification(state=verify.PARSER_SUSPECT,
                                             stock_status="unverifiable",
                                             verified_price=None, price_matches=None,
                                             degraded_reason="no availability signal"),
        verify.SOURCE_BLOCKED: _verification(state=verify.SOURCE_BLOCKED,
                                             stock_status="unverifiable",
                                             verified_price=None, price_matches=None,
                                             degraded_reason="HTTP 403"),
        verify.UNKNOWN_NO_ALERT: _verification(state=verify.UNKNOWN_NO_ALERT,
                                               stock_status="unknown",
                                               verified_price=None, price_matches=None),
    }
    assert set(fixtures) == verify.TERMINAL_STATES     # every state exercised
    for state, v in fixtures.items():
        assert verify.alert_allowed(v) is (state == verify.VERIFIED_BUYABLE), state


@pytest.mark.parametrize("hole", [
    {"verified_price": None},
    {"buy_url": ""},
    {"evidence": ""},
    {"checked_at": ""},
    {"stock_status": "unknown"},
])
def test_gate_rejects_buyable_state_with_missing_evidence(hole):
    # A hand-built (or buggy) VERIFIED_BUYABLE record with a hole in its
    # evidence must still be refused — the gate re-checks everything.
    v = _verification(**hole)
    assert not verify.alert_allowed(v)
    with pytest.raises(verify.AlertGateError):
        verify.assert_alertable(v)


def test_assert_alertable_passes_complete_record():
    verify.assert_alertable(_verification())      # must not raise


def test_good_comp_with_unknown_stock_never_alerts():
    """Spec 8.5 — the invariant this slice exists for: comp confidence and
    buyability are separate. A maximal-margin, high-confidence comp with
    unknown stock produces no alert AND the STOP gate refuses a positive
    stock claim without evidence."""
    v = _verification(state=verify.UNKNOWN_NO_ALERT, stock_status="unknown",
                      verified_price=None, price_matches=None)
    assert not verify.alert_allowed(v)

    row = DealRow(item="Prismatic ETB", asset_class="sealed", category="sealed-etb",
                  deal_price=39.99, market_comp=200.0, retailer="MSRP",
                  source_url="https://www.tcgplayer.com/product/593355",
                  captured_at="2026-07-03", price_confidence="verified",
                  comp_confidence="high", pct_off=80,
                  stock_status="in_stock")        # positive claim, zero evidence
    assert validate_row(row) != []                # STOP gate refuses it


def test_verification_is_immutable_evidence():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _verification().state = verify.OUT_OF_STOCK


# ------------------------------------------------- catalog-product verification


def _result(status, price="", url="https://stub.example/p/1"):
    return StockResult(store=None, product_key="fake_etb", product_name="Fake ETB",
                       status=status, url=url, price=price)


def _stub_retailer(slug, results=None, raises=None, online=True, fields=("stub_id",)):
    """Build a fake Retailer class yielding scripted results (or raising)."""
    class _Stub(Retailer):
        name = slug.title()
        online_only = online
        product_id_fields = fields

        def inventory(self, products, stores):
            if raises is not None:
                raise raises
            yield from (results or [])
    _Stub.__name__ = f"Stub{slug.title()}"
    return _Stub


def _cfg_for(slugs):
    return SimpleNamespace(retailers={
        s: SimpleNamespace(enabled=True, api_key="") for s in slugs})


PRODUCT = {"name": "Fake ETB", "stub_id": "123", "msrp": "$39.99"}


def _verify_catalog(registry, product=PRODUCT, expected=39.99, health=None):
    return verify.verify_catalog_product(
        _cfg_for(registry), "fake_etb", product,
        registry=registry, expected_price=expected, checked_at=CHECKED_AT,
        health_lookup=(health or (lambda slug: {})).__call__)


def test_catalog_in_stock_with_price_is_verified_buyable():
    registry = {"stuba": _stub_retailer("stuba",
                                        results=[_result("ONLINE_IN_STOCK", "$39.99")])}
    v = _verify_catalog(registry)
    assert v.state == verify.VERIFIED_BUYABLE
    assert v.source == "stuba" and v.method == "retailer_adapter:stuba"
    assert v.buy_url == "https://stub.example/p/1"
    assert v.verified_price == 39.99 and v.expected_price == 39.99
    assert v.checked_at == CHECKED_AT and v.evidence
    assert verify.alert_allowed(v)


def test_catalog_prefers_positive_stock_across_adapters():
    registry = {
        "outone": _stub_retailer("outone", results=[_result("ONLINE_OUT")]),
        "hit": _stub_retailer("hit", results=[_result("ONLINE_IN_STOCK", "$39.99",
                                                      url="https://hit.example/p")]),
    }
    v = _verify_catalog(registry)
    assert v.state == verify.VERIFIED_BUYABLE and v.source == "hit"


def test_catalog_price_mismatch_is_terminal_and_no_alert():
    registry = {"stuba": _stub_retailer("stuba",
                                        results=[_result("ONLINE_IN_STOCK", "$59.99")])}
    v = _verify_catalog(registry)
    assert v.state == verify.PRICE_MISMATCH and v.price_matches is False
    assert v.verified_price == 59.99      # observed price still recorded honestly
    assert not verify.alert_allowed(v)


def test_catalog_all_out_is_out_of_stock():
    registry = {"stuba": _stub_retailer("stuba", results=[_result("ONLINE_OUT")])}
    v = _verify_catalog(registry)
    assert v.state == verify.OUT_OF_STOCK and v.stock_status == "out_of_stock"


def test_catalog_blocked_adapter_maps_to_source_blocked():
    registry = {"stuba": _stub_retailer(
        "stuba", raises=requests.HTTPError("403 Client Error: Forbidden"))}
    v = _verify_catalog(registry)
    assert v.state == verify.SOURCE_BLOCKED and v.stock_status == "unverifiable"
    assert "403" in v.degraded_reason


def test_catalog_transport_failure_maps_to_page_unavailable():
    registry = {"stuba": _stub_retailer(
        "stuba", raises=requests.ConnectTimeout("connect timed out"))}
    v = _verify_catalog(registry)
    assert v.state == verify.PAGE_UNAVAILABLE
    assert "timed out" in v.degraded_reason


def test_catalog_zero_rows_with_ok_http_is_parser_suspect():
    registry = {"stuba": _stub_retailer("stuba", results=[])}
    v = _verify_catalog(registry, health=lambda slug: {"last_http_status": 200})
    assert v.state == verify.PARSER_SUSPECT
    assert "no inventory row" in v.degraded_reason


def test_catalog_zero_rows_with_blocked_http_is_source_blocked():
    registry = {"stuba": _stub_retailer("stuba", results=[])}
    v = _verify_catalog(registry, health=lambda slug: {"last_http_status": 429})
    assert v.state == verify.SOURCE_BLOCKED


def test_catalog_zero_rows_with_5xx_is_page_unavailable():
    registry = {"stuba": _stub_retailer("stuba", results=[])}
    v = _verify_catalog(registry, health=lambda slug: {"last_http_status": 503})
    assert v.state == verify.PAGE_UNAVAILABLE


def test_catalog_no_online_adapter_is_unknown_and_names_the_gap():
    # store-based adapter holds the only id -> nothing verifiable in this
    # context; the degraded reason says so instead of faking a result
    registry = {"storeonly": _stub_retailer("storeonly", online=False,
                                            results=[_result("IN_STOCK")])}
    v = _verify_catalog(registry)
    assert v.state == verify.UNKNOWN_NO_ALERT and v.stock_status == "unknown"
    assert v.method == "none"
    assert "storeonly" in v.degraded_reason
    assert not verify.alert_allowed(v)


def test_catalog_stock_seen_but_priceless_keeps_stock_evidence():
    registry = {"stuba": _stub_retailer("stuba", results=[_result("ONLINE_IN_STOCK")])}
    v = _verify_catalog(registry)
    assert v.state == verify.UNKNOWN_NO_ALERT
    assert v.stock_status == "in_stock"          # evidence preserved, alert refused
    assert not verify.alert_allowed(v)


# ------------------------------------------------------ merchant page fallback


def _page_response(name, status=200):
    text = (FIXTURES / name).read_text(encoding="utf-8") if name else ""
    return SimpleNamespace(status_code=status, text=text)


def _verify_page(name, status=200, expected=39.99, exc=None):
    def fake_get(url, **kwargs):
        if exc is not None:
            raise exc
        return _page_response(name, status)
    return verify.verify_page("https://megamart.example/p/fake-etb",
                              expected_price=expected, checked_at=CHECKED_AT,
                              http_get=fake_get)


def test_page_in_stock_with_price_is_verified_buyable():
    v = _verify_page("instock_jsonld.html")
    assert v.state == verify.VERIFIED_BUYABLE
    assert v.verified_price == 39.99 and v.price_matches is True
    assert v.buy_url == "https://megamart.example/p/fake-etb"
    assert v.method == "page_fetch" and v.source == "megamart.example"
    assert "InStock" in v.evidence
    assert verify.alert_allowed(v)


def test_page_out_of_stock():
    v = _verify_page("outofstock_jsonld.html")
    assert v.state == verify.OUT_OF_STOCK and v.stock_status == "out_of_stock"
    assert "OutOfStock" in v.evidence


def test_page_price_mismatch():
    v = _verify_page("mismatch_jsonld.html")
    assert v.state == verify.PRICE_MISMATCH
    assert v.verified_price == 59.99 and v.price_matches is False


def test_page_without_signals_is_parser_suspect_never_a_guess():
    # the page contains tempting bare numbers; refusing to guess is the point
    v = _verify_page("garbage.html")
    assert v.state == verify.PARSER_SUSPECT and v.stock_status == "unverifiable"
    assert v.verified_price is None
    assert not verify.alert_allowed(v)


def test_page_403_is_source_blocked():
    v = _verify_page("garbage.html", status=403)
    assert v.state == verify.SOURCE_BLOCKED
    assert "403" in v.degraded_reason


def test_page_404_is_page_unavailable():
    v = _verify_page("garbage.html", status=404)
    assert v.state == verify.PAGE_UNAVAILABLE
    assert "404" in v.degraded_reason


def test_page_transport_error_is_page_unavailable():
    v = _verify_page(None, exc=requests.ConnectionError("dns failure"))
    assert v.state == verify.PAGE_UNAVAILABLE
    assert "dns failure" in v.degraded_reason


# ------------------------------------------------------- review-wave fixes


def test_rank_prefers_alertable_over_mismatch_regardless_of_order():
    # A PRICE_MISMATCH at one retailer must not shadow a genuinely buyable
    # verification at another (was decided by registry dict order).
    registry = {
        "misfit": _stub_retailer("misfit", results=[_result("ONLINE_IN_STOCK", "$59.99")]),
        "buyable": _stub_retailer("buyable", results=[_result("ONLINE_IN_STOCK", "$39.99",
                                                              url="https://buy.example/p")]),
    }
    v = _verify_catalog(registry)
    assert v.state == verify.VERIFIED_BUYABLE and v.source == "buyable"
    assert verify.alert_allowed(v)


def test_rank_prefers_alertable_over_priceless_in_stock():
    registry = {
        "priceless": _stub_retailer("priceless", results=[_result("ONLINE_IN_STOCK")]),
        "buyable": _stub_retailer("buyable", results=[_result("LIMITED", "$39.99",
                                                              url="https://buy.example/p")]),
    }
    v = _verify_catalog(registry)
    assert v.state == verify.VERIFIED_BUYABLE and v.source == "buyable"


def test_positive_result_without_buy_url_demotes_instead_of_tripping_gate():
    # One drifted adapter must degrade a row, not kill a whole board run at
    # the STOP gate with a positive status that has no buy link.
    result = _result("ONLINE_IN_STOCK", "$39.99", url="")
    v = verify.from_stock_result(result, source="drifty",
                                 expected_price=39.99, checked_at=CHECKED_AT)
    assert v.state == verify.UNKNOWN_NO_ALERT
    assert v.stock_status == "unknown"
    assert "no buy URL" in v.degraded_reason
    assert not verify.alert_allowed(v)


def test_adapter_error_detail_is_query_string_redacted():
    registry = {"stuba": _stub_retailer("stuba", raises=requests.ConnectionError(
        "https://api.example.com/v1/products/9?apiKey=SECRET123 failed"))}
    v = _verify_catalog(registry)
    assert "SECRET123" not in v.degraded_reason
    assert "SECRET123" not in v.evidence


def test_digits_inside_ids_do_not_classify_as_blocked():
    registry = {"stuba": _stub_retailer("stuba", raises=requests.ConnectionError(
        "https://www.walmart.com/ip/1403559521 timed out"))}
    v = _verify_catalog(registry)
    assert v.state == verify.PAGE_UNAVAILABLE     # 403 inside an item id is not HTTP 403


def _page_from_text(text, expected=39.99):
    return verify.verify_page("https://megamart.example/p/fake-etb",
                              expected_price=expected, checked_at=CHECKED_AT,
                              http_get=lambda url, **kw: SimpleNamespace(
                                  status_code=200, text=text))


def test_page_ambiguous_availability_refuses_to_guess():
    # in-stock carousel product + sold-out main product = no answer, honestly
    v = _verify_page("carousel_ambiguous.html")
    assert v.state == verify.PARSER_SUSPECT
    assert "ambiguous" in v.degraded_reason.lower()


def test_page_price_outside_window_is_not_paired_with_stock():
    filler = "<p>" + ("lorem ipsum " * 200) + "</p>"      # > 1500 chars of distance
    text = ('<html><head><script type="application/ld+json">'
            '{"price":"19.99","name":"Unrelated Sticker"}</script></head><body>'
            + filler +
            '<link itemprop="availability" href="https://schema.org/InStock">'
            + filler + "</body></html>")
    v = _page_from_text(text)
    assert v.state == verify.UNKNOWN_NO_ALERT     # stock seen, price NOT borrowed
    assert v.stock_status == "in_stock"
    assert v.verified_price is None


def test_page_locale_decimal_price_is_refused_not_fabricated():
    text = ('<html><body><script type="application/ld+json">'
            '{"offers":{"price":"39,99",'
            '"availability":"https://schema.org/InStock"}}</script></body></html>')
    v = _page_from_text(text)
    assert v.verified_price is None               # never 3999.0
    assert v.state == verify.UNKNOWN_NO_ALERT


def test_page_presale_marker_is_not_buyable_now():
    text = ('<html><body><script type="application/ld+json">'
            '{"offers":{"price":"39.99",'
            '"availability":"https://schema.org/PreSale"}}</script></body></html>')
    v = _page_from_text(text)
    assert v.state == verify.UNKNOWN_NO_ALERT
    assert v.stock_status == "unknown"
    assert "preorder" in v.degraded_reason.lower()


def test_page_escaped_slash_jsonld_parses():
    text = ('<html><body><script type="application/ld+json">'
            '{"offers":{"price":"39.99",'
            '"availability":"https:\\/\\/schema.org\\/InStock"}}</script></body></html>')
    v = _page_from_text(text)
    assert v.state == verify.VERIFIED_BUYABLE
    assert v.verified_price == 39.99
