"""Price filters: at-MSRP gating + per-product max_price ceiling."""
from __future__ import annotations

import pytest

from scanner import filters as f


def test_default_filter_allows_everything():
    pf = f.parse_price_filter({})
    assert f.passes({}, "$49.99", pf) is True
    assert f.passes({}, "$999.99", pf) is True


def test_max_price_blocks_above_ceiling():
    pf = f.parse_price_filter({})
    assert f.passes({"max_price": "$60.00"}, "$70.00", pf) is False
    assert f.passes({"max_price": "$60.00"}, "$59.99", pf) is True


def test_unparseable_price_abstains():
    pf = f.parse_price_filter({"only_at_or_near_msrp": True})
    assert f.passes({"msrp": "$49.99"}, "", pf) is True
    assert f.passes({"msrp": "$49.99"}, "see store", pf) is True


def test_at_msrp_filter_blocks_scalper_pricing():
    pf = f.parse_price_filter({"only_at_or_near_msrp": True, "msrp_multiplier": 1.10})
    msrp = {"msrp": "$50.00"}
    assert f.passes(msrp, "$45.00", pf) is True
    assert f.passes(msrp, "$50.00", pf) is True
    assert f.passes(msrp, "$55.00", pf) is True   # within 10%
    assert f.passes(msrp, "$60.00", pf) is False  # 20% over


def test_at_msrp_with_no_msrp_abstains():
    """If MSRP isn't declared we don't know what to compare to."""
    pf = f.parse_price_filter({"only_at_or_near_msrp": True})
    assert f.passes({}, "$999.00", pf) is True


def test_max_price_and_msrp_both_evaluated():
    pf = f.parse_price_filter({"only_at_or_near_msrp": True, "msrp_multiplier": 1.10})
    prod = {"msrp": "$50.00", "max_price": "$70.00"}
    assert f.passes(prod, "$55.00", pf) is True   # under both
    assert f.passes(prod, "$56.00", pf) is False  # over msrp*1.10
    assert f.passes(prod, "$75.00", pf) is False  # over max_price


def test_negative_multiplier_raises():
    with pytest.raises(SystemExit):
        f.parse_price_filter({"msrp_multiplier": -1})


def test_non_numeric_multiplier_raises():
    with pytest.raises(SystemExit):
        f.parse_price_filter({"msrp_multiplier": "free"})


def test_comma_in_price():
    """Some retailers return '$1,299.99'."""
    pf = f.parse_price_filter({"only_at_or_near_msrp": True, "msrp_multiplier": 1.0})
    assert f.passes({"msrp": "$1,200.00"}, "$1,199.99", pf) is True
