import pytest

from scanner import margin
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


def test_ebay_high_value_defaults_to_full_fvf_until_pinned():
    # FAIL-SAFE: the >=$1,000 discount is OFF by default -> full 13.25% FVF, never fake profit.
    # A real-discount test is added ONLY after the live eBay Trading Cards category is pinned+cited.
    fees = margin.FeeModel()
    r = margin.net_margin(cost_incl_tax=1000.0, comp=1500.0, channel="ebay",
                          est_shipping=8.0, fees=fees)
    # fee = 1500*0.1325 + 0.40 = 199.15 ; net = 1500 - 199.15 - 8 = 1292.85 (matches reality, not +$100)
    assert round(r.net_proceeds, 2) == 1292.85


def test_ebay_standard_fvf_below_threshold():
    fees = margin.FeeModel()
    r = margin.net_margin(cost_incl_tax=30.0, comp=100.0, channel="ebay",
                          est_shipping=8.0, fees=fees)
    # fee = 100*0.1325 + 0.40 = 13.65 ; net = 100 - 13.65 - 8 = 78.35
    assert round(r.net_proceeds, 2) == 78.35


def test_tcgplayer_channel_nets_commission_processing_and_fixed():
    fees = margin.FeeModel()
    r = margin.net_margin(cost_incl_tax=30.0, comp=100.0, channel="tcgplayer",
                          est_shipping=8.0, fees=fees)
    # fee = 100*(0.1075+0.025) + 0.30 = 13.25 + 0.30 = 13.55 ; net = 100 - 13.55 - 8 = 78.45
    # (brief's original comment/assertion (78.75) dropped the +0.30 fixed fee in its own
    # arithmetic -- that would understate fees / overstate net, i.e. fake profit. Corrected
    # here to match the interface spec's stated formula and the eBay/local fixed-fee pattern.)
    assert round(r.net_proceeds, 2) == 78.45
    assert r.channel == "tcgplayer"


def test_unknown_channel_still_raises():
    import pytest
    with pytest.raises(ValueError):
        margin.net_margin(30.0, 100.0, "carrier-pigeon", 8.0, margin.FeeModel())
