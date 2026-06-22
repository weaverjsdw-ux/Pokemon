# tests/test_verdict.py
from scanner.margin import MarginResult
from scanner.verdict import Verdict, VerdictThresholds, buy_verdict

T = VerdictThresholds()  # spec defaults: skip 5/10, buy 15/20, roi gate on, min medium


def m(net, roi, channel="ebay"):
    return MarginResult(channel, net, net, roi, 0.0)


def test_buy_requires_both_net_and_roi_with_good_confidence():
    v = buy_verdict(m(18.0, 42.0), "high", T)
    assert v.tier == "BUY"
    assert "BUY" in v.headline and "42" in v.headline


def test_net_clears_but_roi_fails_is_not_buy():
    # net 18 >= 15 but roi 8 < buy_floor_roi 20, and roi 8 < skip_floor_roi 10 -> SKIP
    v = buy_verdict(m(18.0, 8.0), "high", T)
    assert v.tier == "SKIP"


def test_thin_band():
    # net 10 (between 5 and 15), roi 15 (between 10 and 20) -> THIN
    v = buy_verdict(m(10.0, 15.0), "high", T)
    assert v.tier == "THIN"


def test_low_confidence_caps_buy_to_thin():
    v = buy_verdict(m(18.0, 42.0), "low", T)
    assert v.tier == "THIN"
    assert "low" in v.headline.lower()


def test_derived_local_comp_capped_at_thin():
    v = buy_verdict(m(40.0, 90.0, channel="local"), "high", T, derived_only=True)
    assert v.tier == "THIN"


def test_roi_gate_disabled_uses_net_only():
    t = VerdictThresholds(roi_gate_enabled=False)
    v = buy_verdict(m(18.0, 1.0), "high", t)
    assert v.tier == "BUY"


def test_skip_when_below_net_floor():
    v = buy_verdict(m(2.0, 50.0), "high", T)
    assert v.tier == "SKIP"
