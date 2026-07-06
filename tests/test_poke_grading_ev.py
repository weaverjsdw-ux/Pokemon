"""Session E Slice D — pure raw->graded grading EV.

STOP-class: blocks on ANY missing required input (never invents a gem rate, comp,
or fee); computes expected net/ROI + a labeled downside only when everything is
present. No network, no clock."""
from __future__ import annotations

import pytest

from scanner.margin import FeeModel
from scanner.poke_api import grading_ev as gev

FEES = FeeModel()  # defaults: fvf 0.1325, fixed 0.40, haircut 0.15


def _ev(**over):
    kw = dict(raw_entry=400.0, raw_comp=500.0, graded_comp=1000.0, grading_fee=97.5,
              gem_rate=0.4, fees=FEES, tax_rate=0.07, est_shipping=8.0,
              target_grade="psa10", buy_floor_net=15.0,
              gem_rate_basis="operator_assumption 2026-07-05",
              grading_fee_basis="PSA Regular $79.99 all-in; value tiers paused 2026-06")
    kw.update(over)
    return gev.grading_ev(**kw)


def test_missing_gem_rate_blocks():
    r = _ev(gem_rate=None)
    assert r["status"] == "blocked"
    assert r["expected_net"] is None and r["expected_roi_pct"] is None
    assert any("gem rate" in b.lower() for b in r["blockers"])


def test_gem_rate_out_of_range_blocks():
    assert _ev(gem_rate=1.5)["status"] == "blocked"
    assert _ev(gem_rate=0.0)["status"] == "blocked"


def test_missing_graded_comp_blocks():
    r = _ev(graded_comp=None)
    assert r["status"] == "blocked"
    assert any("graded comp" in b.lower() for b in r["blockers"])


def test_missing_raw_entry_blocks():
    r = _ev(raw_entry=None)
    assert r["status"] == "blocked"
    assert any("raw entry" in b.lower() for b in r["blockers"])


def test_missing_grading_fee_blocks():
    r = _ev(grading_fee=None)
    assert r["status"] == "blocked"
    assert any("grading fee" in b.lower() for b in r["blockers"])


def test_computes_ev_when_all_present():
    r = _ev()
    # cost = 400*1.07 + 97.5 = 525.5
    # upside (sell psa10 @1000 on ebay): 1000 - 132.5 - 0.4 - 8 - 525.5 = 333.6
    # downside (sell raw @500 on ebay, grading sunk): 500 - 66.25 - 0.4 - 8 - 525.5 = -100.15
    # EV = 0.4*333.6 + 0.6*(-100.15) = 73.35
    assert r["status"] == "actionable"
    assert r["cost"] == pytest.approx(525.5, abs=0.01)
    assert r["upside_net"] == pytest.approx(333.6, abs=0.02)
    assert r["downside_net"] == pytest.approx(-100.15, abs=0.02)
    assert r["expected_net"] == pytest.approx(73.35, abs=0.02)
    assert r["expected_roi_pct"] == pytest.approx(13.96, abs=0.05)
    assert r["downside_net"] < r["upside_net"]
    assert r["assumptions"]                       # every number cited
    assert r["gem_rate_basis"] == "operator_assumption 2026-07-05"


def test_downside_basis_labeled_when_no_lower_grade_comp():
    r = _ev()
    joined = " ".join(r["assumptions"]).lower()
    assert "downside" in joined and "raw comp" in joined   # explicit downside basis


def test_downside_uses_supplied_lower_grade_comp():
    r = _ev(downside_comp=650.0)                 # e.g. a real PSA9 comp
    # downside now sells at 650 not the raw comp
    assert r["downside_net"] > _ev()["downside_net"]
    joined = " ".join(r["assumptions"]).lower()
    assert "psa9" in joined or "supplied" in joined or "lower-grade" in joined


def test_ev_below_floor_is_watch_not_actionable():
    r = _ev(graded_comp=600.0)                    # thin upside -> EV below buy floor
    assert r["status"] == "watch"
    assert r["expected_net"] is not None          # still computed, just not actionable


# ---------------------------------------------------------------- Phase G: break-even

def test_breakeven_gem_rate_pure():
    # EV(g)=0 at g = downside/(downside-upside). upside 333.6, downside -100.15 -> ~0.231
    be = gev.breakeven_gem_rate(upside_net=333.6, downside_net=-100.15)
    assert be == pytest.approx(0.2309, abs=1e-3)


def test_breakeven_none_on_zero_spread():
    # No spread between upside and downside -> raising the gem rate can never reach 0.
    assert gev.breakeven_gem_rate(upside_net=100.0, downside_net=100.0) is None
    assert gev.breakeven_gem_rate(upside_net=50.0, downside_net=100.0) is None  # upside<downside


def test_grading_ev_includes_breakeven_and_sensitivity():
    r = _ev()
    assert r["status"] == "actionable"
    # break-even sits below the assumed 0.4 (EV is positive at 0.4)
    assert 0.0 < r["breakeven_gem_rate"] < 0.4
    # EV crosses zero at the break-even gem rate (linear model)
    assert isinstance(r["sensitivity"], list) and r["sensitivity"]


def test_sensitivity_has_standard_rates_plus_actual():
    r = _ev(gem_rate=0.35)                          # actual not among 20/30/40/50
    rates = [round(row["gem_rate"], 2) for row in r["sensitivity"]]
    for standard in (0.20, 0.30, 0.40, 0.50):
        assert standard in rates
    assert 0.35 in rates                            # the actual sourced/assumed rate too
    actual_rows = [row for row in r["sensitivity"] if row.get("is_actual")]
    assert len(actual_rows) == 1 and actual_rows[0]["gem_rate"] == 0.35
    # each row carries a net + roi computed on the SAME money model
    assert all("expected_net" in row and "expected_roi_pct" in row for row in r["sensitivity"])


def test_sensitivity_monotonic_in_gem_rate():
    r = _ev()
    nets = [row["expected_net"] for row in sorted(r["sensitivity"], key=lambda x: x["gem_rate"])]
    assert nets == sorted(nets)                     # higher gem rate -> higher EV (upside>downside)


def test_blocked_has_no_breakeven_or_sensitivity():
    r = _ev(gem_rate=None)                           # blocked: no dollar output preserved
    assert r["status"] == "blocked"
    assert r["expected_net"] is None
    assert r.get("breakeven_gem_rate") is None
    assert r.get("sensitivity") in (None, [])


def test_base_rate_proxy_caveat_in_assumptions():
    joined = " ".join(_ev()["assumptions"]).lower()
    assert "proxy" in joined                         # base-rate-as-proxy stated explicitly
    assert "paper_buy" in joined or "never live" in joined


def test_grading_ev_is_paper_only_never_live():
    r = _ev()
    assert r["status"] in ("actionable", "watch")    # never a LIVE token
    assert "never live" in r["reason"].lower()
