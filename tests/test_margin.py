import pytest

from scanner.margin import FeeModel, MarginResult, cost_basis, net_margin

FEES = FeeModel(ebay_fvf_pct=0.1325, ebay_fixed_fee=0.40, local_haircut_pct=0.15)


def test_cost_basis_applies_tax():
    assert cost_basis(40.0, 0.07) == pytest.approx(42.8)


def test_ebay_margin_matches_spec_example():
    # Buy $43 incl tax, comp $60, ship $8 seller-paid.
    # fee = 60*0.1325 + 0.40 = 7.95 + 0.40 = 8.35; net = 60 - 8.35 - 8 = 43.65
    r = net_margin(43.0, 60.0, "ebay", 8.0, FEES)
    assert r.channel == "ebay"
    assert r.net_proceeds == pytest.approx(43.65)
    assert r.dollar_margin == pytest.approx(0.65)
    assert r.roi_pct == pytest.approx(0.65 / 43.0 * 100, rel=1e-3)
    # breakeven price p: p*(1-0.1325) = cost + fixed + ship = 43 + 0.40 + 8 = 51.40
    assert r.breakeven_price == pytest.approx(51.40 / 0.8675, rel=1e-3)


def test_local_margin_applies_haircut_no_fees():
    # comp $60, haircut 15% -> net 51; cost 43 -> margin 8
    r = net_margin(43.0, 60.0, "local", 0.0, FEES)
    assert r.channel == "local"
    assert r.net_proceeds == pytest.approx(51.0)
    assert r.dollar_margin == pytest.approx(8.0)
    # breakeven comp where comp*(1-haircut) = cost -> 43/0.85
    assert r.breakeven_price == pytest.approx(43.0 / 0.85, rel=1e-3)


def test_unknown_channel_raises():
    with pytest.raises(ValueError):
        net_margin(43.0, 60.0, "whatnot", 0.0, FEES)


def test_zero_cost_roi_is_zero_not_crash():
    r = net_margin(0.0, 60.0, "ebay", 8.0, FEES)
    assert r.roi_pct == 0.0
