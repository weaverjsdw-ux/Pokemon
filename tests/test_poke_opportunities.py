"""Phase C — opportunity model + scoring engine (pure, no network, no clock)."""
from __future__ import annotations

import re

import pytest

from scanner import config as cfg_mod
from scanner import main as main_mod
from scanner.poke_api import opportunities as opp


@pytest.fixture
def cfg():
    return cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})


@pytest.fixture
def cfg_policy():
    """cfg with the opportunity business-policy block populated (as in config.example.yaml)."""
    return cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "opportunity": {
            "max_hold_days": {"sealed_retail_arbitrage": 45, "sealed_momentum_watch": 90},
            "exit_venue": {"sealed_retail_arbitrage": "ebay", "sealed_momentum_watch": "ebay"},
        },
    })


# ---- helpers to build the owned comp/momentum shapes the engine consumes -----

def comp_resp(estimate=None, confidence="none", sources=None, stale=False,
              checked_at="2026-07-03", status="ok"):
    return {
        "status": status if estimate is not None else "no_match",
        "estimate": estimate,
        "unopenedPrice": estimate,
        "confidence": confidence,
        "compBasis": "ledger latest",
        "sources": sources if sources is not None else (
            [{"source": "tcgplayer", "status": "ok", "price": estimate, "url": "u"}]
            if estimate is not None else []),
        "sourceUrl": "https://www.tcgplayer.com/product/1",
        "checkedAt": checked_at,
        "stale": stale,
    }


def mom(status="no_history", delta_pct=None, stale=False, latest_confidence=None,
        first_seen=None, last_seen=None):
    return {
        "status": status, "delta_pct": delta_pct, "stale": stale,
        "latest_confidence": latest_confidence,
        "first_seen": first_seen, "last_seen": last_seen,
    }


def candidate(verified_price=None, retailer="Target", source="target_search", in_stock=True):
    return {"source": source, "url": "https://x/y", "item_name": "Booster Bundle",
            "retailer": retailer, "verified_price": verified_price,
            "in_stock": in_stock, "matched_product_key": "jt_bb"}


PRODUCT = {"name": "Journey Together Booster Bundle", "set": "Journey Together",
           "msrp": 26.94, "ppt_id": "610953"}


# ---------------------------------------------------------------- compute_margin

def test_compute_margin_matches_alert_path(cfg):
    """expected_net/roi/tier must equal what scanner.main.verdict_for_alert shows."""
    entry, comp_price, confidence = 58.0, 100.0, "high"
    comp_row = {"status": "ok", "estimate": comp_price, "confidence": confidence}
    headline = main_mod.verdict_for_alert(cfg, PRODUCT, f"${entry}", comp_row)
    net, roi, tier = opp.compute_margin(entry, comp_price, confidence, PRODUCT, cfg)
    # headline looks like "BUY · +$16.29 net, 26.2467% ROI"
    assert headline.split(" ", 1)[0] == tier
    net_in_headline = float(re.search(r"([-+]?\$[\d.]+) net", headline).group(1).replace("$", ""))
    assert abs(net_in_headline - net) < 0.01
    assert tier == "BUY"


def test_compute_margin_none_when_no_entry_or_comp(cfg):
    assert opp.compute_margin(None, 100.0, "high", PRODUCT, cfg) == (None, None, "n/a")
    assert opp.compute_margin(58.0, None, "high", PRODUCT, cfg) == (None, None, "n/a")


# ---------------------------------------------------------------- classify_trade

def test_classify_catalog_gap_no_comp(cfg):
    assert opp.classify_trade(market_comp=None, momentum_status="no_history", stale=False,
                              entry_price=None, discount_pct=None, momentum_delta_pct=None,
                              cfg=cfg) == "sealed_catalog_gap"


def test_classify_catalog_gap_no_history(cfg):
    assert opp.classify_trade(market_comp=90.0, momentum_status="no_history", stale=False,
                              entry_price=None, discount_pct=None, momentum_delta_pct=None,
                              cfg=cfg) == "sealed_catalog_gap"


def test_classify_stale_comp(cfg):
    assert opp.classify_trade(market_comp=90.0, momentum_status="ok", stale=True,
                              entry_price=40.0, discount_pct=55.0, momentum_delta_pct=2.0,
                              cfg=cfg) == "sealed_stale_comp"


def test_classify_retail_arbitrage(cfg):
    assert opp.classify_trade(market_comp=90.0, momentum_status="ok", stale=False,
                              entry_price=40.0, discount_pct=55.0, momentum_delta_pct=1.0,
                              cfg=cfg) == "sealed_retail_arbitrage"


def test_classify_arbitrage_needs_min_discount(cfg):
    # discount below poke.min_discount_pct (5) is not arbitrage
    assert opp.classify_trade(market_comp=90.0, momentum_status="ok", stale=False,
                              entry_price=88.0, discount_pct=2.0, momentum_delta_pct=3.0,
                              cfg=cfg) == "sealed_momentum_watch"


def test_classify_momentum_watch(cfg):
    assert opp.classify_trade(market_comp=90.0, momentum_status="ok", stale=False,
                              entry_price=None, discount_pct=None, momentum_delta_pct=4.0,
                              cfg=cfg) == "sealed_momentum_watch"


def test_classify_no_edge(cfg):
    assert opp.classify_trade(market_comp=90.0, momentum_status="ok", stale=False,
                              entry_price=None, discount_pct=None, momentum_delta_pct=-1.0,
                              cfg=cfg) == "sealed_no_edge"


# ---------------------------------------------------------------- decide()

def _decide(cfg, **kw):
    base = dict(trade_type="sealed_retail_arbitrage", verdict_tier="BUY",
                entry_price=40.0, market_comp=90.0, stale=False,
                expected_net=30.0, expected_roi_pct=40.0, latest_confidence="high")
    base.update(kw)
    return opp.decide(cfg=cfg, **base)


def test_decide_live_packet_eligible(cfg):
    d, _ = _decide(cfg, expected_net=30.0, expected_roi_pct=40.0, latest_confidence="high")
    assert d == "LIVE_PACKET_ELIGIBLE"


def test_decide_paper_buy_below_live_floor(cfg):
    d, reason = _decide(cfg, expected_net=16.0, expected_roi_pct=26.0)  # net < live 25
    assert d == "PAPER_BUY"
    assert "net" in reason.lower()


def test_decide_low_confidence_not_live(cfg):
    # confidence below live floor keeps it paper even with strong numbers
    d, _ = _decide(cfg, verdict_tier="BUY", latest_confidence="low",
                   expected_net=30.0, expected_roi_pct=40.0)
    assert d == "PAPER_BUY"


def test_decide_stale_arbitrage_not_live(cfg):
    d, _ = _decide(cfg, stale=True)
    assert d == "PAPER_BUY"


def test_decide_reject_on_skip(cfg):
    d, _ = _decide(cfg, verdict_tier="SKIP")
    assert d == "REJECT"


def test_decide_watch_on_thin(cfg):
    d, _ = _decide(cfg, verdict_tier="THIN")
    assert d == "WATCH"


def test_decide_no_comp_watch(cfg):
    d, _ = _decide(cfg, trade_type="sealed_catalog_gap", verdict_tier="n/a",
                   entry_price=None, market_comp=None, expected_net=None,
                   expected_roi_pct=None, latest_confidence="none")
    assert d == "WATCH"


def test_decide_momentum_watch_never_live(cfg):
    # even with numbers that would clear the floor, a non-live-eligible type can't go live
    d, _ = _decide(cfg, trade_type="sealed_momentum_watch", verdict_tier="BUY",
                   expected_net=99.0, expected_roi_pct=99.0, latest_confidence="high")
    assert d == "WATCH"


# ---------------------------------------------------------------- scoring

def test_score_deterministic_and_bounded(cfg):
    s1, b1 = opp.score_opportunity(
        discount_pct=40.0, expected_net=30.0, expected_roi_pct=50.0,
        momentum_status="ok", momentum_delta_pct=3.0, confidence="high",
        source_agreement="agree", stale=False, risks=[], cfg=cfg)
    s2, b2 = opp.score_opportunity(
        discount_pct=40.0, expected_net=30.0, expected_roi_pct=50.0,
        momentum_status="ok", momentum_delta_pct=3.0, confidence="high",
        source_agreement="agree", stale=False, risks=[], cfg=cfg)
    assert (s1, b1) == (s2, b2)
    assert 0.0 <= s1 <= 100.0
    raw = round(sum(b1.values()), 1)
    assert s1 == round(min(max(raw, 0.0), 100.0), 1)


def test_score_penalties_pull_down(cfg):
    strong, _ = opp.score_opportunity(
        discount_pct=40.0, expected_net=30.0, expected_roi_pct=50.0,
        momentum_status="ok", momentum_delta_pct=3.0, confidence="high",
        source_agreement="agree", stale=False, risks=[], cfg=cfg)
    weak, b = opp.score_opportunity(
        discount_pct=None, expected_net=None, expected_roi_pct=None,
        momentum_status="no_history", momentum_delta_pct=None, confidence="none",
        source_agreement="none", stale=True,
        risks=["single_source_comp", "declining_momentum"], cfg=cfg)
    assert weak < strong
    assert b["staleness_penalty"] < 0
    assert b["no_history_penalty"] < 0
    assert b["risk_penalty"] < 0


# ---------------------------------------------------------------- build_opportunity

def test_build_opportunity_live_packet(cfg_policy):
    o = opp.build_opportunity(
        "jt_bb", PRODUCT,
        comp_resp(estimate=90.0, confidence="high",
                  sources=[{"source": "tcgplayer"}, {"source": "pricecharting"}]),
        mom(status="ok", delta_pct=2.5, last_seen="2026-07-03", first_seen="2026-07-01"),
        candidate(verified_price=40.0),
        cfg_policy, as_of="2026-07-05")
    assert o.trade_type == "sealed_retail_arbitrage"
    assert o.decision_hint == "LIVE_PACKET_ELIGIBLE"
    assert o.entry_price == 40.0 and o.market_comp == 90.0
    assert o.discount_pct is not None and o.expected_net is not None
    assert o.hold_days == 45 and o.exit_venue == "ebay"
    assert any("market comp" in e for e in o.evidence)
    assert o.opportunity_id == opp.opportunity_id("jt_bb", "sealed_retail_arbitrage", "2026-07-05")


def test_build_opportunity_stop_class_no_entry(cfg):
    o = opp.build_opportunity(
        "jt_bb", PRODUCT,
        comp_resp(estimate=90.0, confidence="high"),
        mom(status="ok", delta_pct=3.0, last_seen="2026-07-03"),
        None, cfg, as_of="2026-07-05")
    assert o.entry_price is None
    assert o.expected_net is None and o.expected_roi_pct is None
    assert o.discount_pct is None                 # never MSRP-as-if-a-price
    assert o.trade_type == "sealed_momentum_watch"
    assert o.decision_hint == "WATCH"
    assert "no_verified_entry" in o.risks


def test_build_opportunity_catalog_gap_no_comp(cfg):
    o = opp.build_opportunity(
        "jt_bb", PRODUCT, comp_resp(estimate=None, status="no_match"),
        mom(status="no_history"), None, cfg, as_of="2026-07-05")
    assert o.market_comp is None
    assert o.trade_type == "sealed_catalog_gap"
    assert o.decision_hint == "WATCH"
    # unset business policy for this type surfaces as TBD, never invented
    assert o.hold_days == opp.TBD and o.exit_venue == opp.TBD


def test_build_opportunity_stale_comp(cfg):
    o = opp.build_opportunity(
        "jt_bb", PRODUCT,
        comp_resp(estimate=90.0, confidence="medium", stale=True),
        mom(status="ok", delta_pct=1.0, stale=True, last_seen="2026-05-01"),
        candidate(verified_price=40.0), cfg, as_of="2026-07-05")
    assert o.stale is True
    assert o.trade_type == "sealed_stale_comp"
    assert o.decision_hint == "WATCH"
