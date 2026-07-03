"""Slice 2: purchasability verifier — terminal states, evidence, alert gate.

The design's reason to exist: no alert without stock AND price verified from
the actual buy page. Every candidate ends in exactly one terminal state and
only VERIFIED_BUYABLE may ever alert.
"""
import dataclasses

import pytest

from scanner.discovery import verify
from scanner.discovery.schema import DealRow, validate_row
from scanner.retailers.base import StockResult

CHECKED_AT = "2026-07-03T10:00:00"


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
