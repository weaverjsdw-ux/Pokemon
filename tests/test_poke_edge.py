"""Session E — edge decision policy + source posture (Slices C & E), and the
EdgePacket model + builders (Slice A).

Pure: no network, no clock (as_of injected). The live gate stays strictly stricter
than paper buy and is reachable ONLY through the verified evidence spine; a D-era
raw/graded WATCH-with-comp row never goes live without an E verified entry."""
from __future__ import annotations

from scanner import config as cfg_mod
from scanner.poke_api import edge, opportunities as opp


def _cfg():
    return cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "opportunity": {"live_min_expected_net": 25.0, "live_min_roi_pct": 30.0,
                        "live_min_confidence": "medium",
                        "max_hold_days": {"sealed_retail_arbitrage": 45},
                        "exit_venue": {"sealed_retail_arbitrage": "ebay"}}})


# ---------------------------------------------------------------- source posture (E)

def test_posture_missing_comp():
    assert edge.source_posture({"estimate": None, "sources": [], "stale": False}) == ["missing_comp"]


def test_posture_ask_only_context():
    tags = edge.source_posture(
        {"estimate": None, "sources": [{"source": "ebay"}], "stale": False})
    assert "ask_only_context" in tags
    assert "missing_comp" not in tags


def test_posture_external_only_single_source():
    tags = edge.source_posture(
        {"estimate": 250.0, "sources": [{"source": "ppt_cards"}], "stale": False})
    assert "external_only" in tags and "single_source" in tags
    assert "local_only" not in tags


def test_tcgcsv_slug_is_external_footing_not_local():
    assert "tcgcsv" in edge._EXTERNAL_SLUGS
    assert "tcgcsv" not in edge._LOCAL_SLUGS
    # a tcgcsv + ppt_cards comp is external_only, never local_plus_external_audit
    comp = {"estimate": 1528.09,
            "sources": [{"source": "tcgcsv"}, {"source": "ppt_cards"}]}
    assert "external_only" in edge.source_posture(comp)
    assert "local_plus_external_audit" not in edge.source_posture(comp)


def test_posture_local_plus_external_audit():
    tags = edge.source_posture(
        {"estimate": 50.0, "sources": [{"source": "tcgplayer"}, {"source": "ppt_cards"}],
         "stale": False})
    assert "local_plus_external_audit" in tags
    assert "single_source" not in tags


def test_posture_local_only_and_stale():
    tags = edge.source_posture(
        {"estimate": 50.0, "sources": [{"source": "tcgplayer"}], "stale": True})
    assert "local_only" in tags and "single_source" in tags and "stale_comp" in tags


# ---------------------------------------------------------------- decide_edge (C)

def _decide(**over):
    kw = dict(asset_class="sealed", market_comp=90.0, stale=False, entry_price=40.0,
              verdict_tier="BUY", expected_net=30.0, expected_roi_pct=35.0,
              latest_confidence="high", trade_type="sealed_retail_arbitrage", cfg=_cfg())
    kw.update(over)
    hint, reason, blockers = edge.decide_edge(**kw)
    return hint


def test_decide_no_comp_is_data_needed():
    assert _decide(market_comp=None) == "DATA_NEEDED"


def test_decide_sealed_arbitrage_buy_clears_live_floor_is_live():
    assert _decide() == "LIVE_PACKET_ELIGIBLE"


def test_decide_sealed_arbitrage_buy_below_live_floor_is_paper():
    # net/roi below the stricter live floor -> PAPER_BUY, never LIVE
    assert _decide(expected_net=18.0, expected_roi_pct=22.0) == "PAPER_BUY"


def test_decide_sealed_arbitrage_skip_is_reject():
    assert _decide(verdict_tier="SKIP") == "REJECT"


def test_decide_sealed_arbitrage_thin_is_watch():
    assert _decide(verdict_tier="THIN") == "WATCH"


def test_decide_raw_verified_arbitrage_can_be_live():
    assert _decide(asset_class="raw", trade_type="raw_verified_arbitrage") == "LIVE_PACKET_ELIGIBLE"


def test_decide_stale_arbitrage_never_live():
    assert _decide(stale=True) == "WATCH"


def test_decide_asset_market_watch_no_entry_is_watch():
    hint = _decide(asset_class="graded", trade_type="graded_market_watch",
                   entry_price=None, expected_net=None, expected_roi_pct=None,
                   verdict_tier="n/a")
    assert hint == "WATCH"


def test_decide_non_arbitrage_with_comp_is_watch():
    assert _decide(trade_type="sealed_momentum_watch", entry_price=None,
                   expected_net=None, expected_roi_pct=None, verdict_tier="n/a") == "WATCH"


def test_live_eligible_edge_set_is_exactly_the_three_arbitrage_types():
    assert edge.LIVE_ELIGIBLE_EDGE == {
        "sealed_retail_arbitrage", "raw_verified_arbitrage", "graded_verified_arbitrage"}


# ---------------------------------------------------------------- EdgePacket (A)

def _comp(estimate, confidence="high", sources=None, stale=False, checked="2026-07-04"):
    return {"estimate": estimate, "confidence": confidence,
            "sources": sources if sources is not None else [{"source": "tcgplayer"},
                                                            {"source": "pricecharting"}],
            "stale": stale, "checkedAt": checked, "compBasis": "ledger latest"}


def _mom(status="ok", delta=1.0, stale=False):
    return {"status": status, "delta_pct": delta, "stale": stale,
            "first_seen": "2026-07-01", "last_seen": "2026-07-04"}


SEALED_PRODUCT = {"name": "Journey Together Booster Bundle", "set": "Journey Together",
                  "msrp": "$26.94", "tcgplayer_id": "610953"}
RAW_ASSET = {"asset_class": "raw", "name": "Umbreon ex 161", "set": "Prismatic Evolutions",
             "card_number": "161", "condition": "NM", "tcgplayer_id": "610516"}


def _sealed_candidate(price=40.0):
    return {"verified_price": price, "retailer": "Target", "source": "manual_verified",
            "candidate_id": "cid-abc", "stock_evidence": "verified page", "url": "https://t/x",
            "stock_checked_at": "2026-07-05", "observed_at": "2026-07-05"}


def _asset_candidate(price=300.0):
    return {"verified_price": price, "retailer": "LGS", "source": "manual_verified",
            "candidate_id": "cid-raw", "stock_evidence": "verified page", "url": "https://l/x",
            "stock_checked_at": "2026-07-05", "observed_at": "2026-07-05",
            "asset_key": "umbreon_ex_161_raw_nm", "condition": "NM", "asset_class": "raw"}


def test_edge_packet_id_deterministic_and_unifies_with_opportunity_id():
    a = edge.build_sealed_packet("jt_bb", SEALED_PRODUCT, _comp(90.0), _mom(),
                                 _sealed_candidate(), _cfg(), as_of="2026-07-05")
    b = edge.build_sealed_packet("jt_bb", SEALED_PRODUCT, _comp(90.0), _mom(),
                                 _sealed_candidate(), _cfg(), as_of="2026-07-05")
    assert a["edge_packet_id"] == b["edge_packet_id"]
    assert a["edge_packet_id"] == opp.opportunity_id("jt_bb", a["trade_type"], "2026-07-05")
    assert a["opportunity_id"] == a["edge_packet_id"]      # unifies with the paper ledger


def test_sealed_packet_from_opportunity_is_live():
    p = edge.build_sealed_packet("jt_bb", SEALED_PRODUCT, _comp(90.0), _mom(),
                                 _sealed_candidate(40.0), _cfg(), as_of="2026-07-05")
    assert p["asset_class"] == "sealed"
    assert p["decision_hint"] == "LIVE_PACKET_ELIGIBLE"
    assert p["expected_net"] is not None and p["expected_roi_pct"] is not None
    assert p["entry_provenance"]["candidate_id"] == "cid-abc"
    assert p["comp_provenance"]["estimate"] == 90.0
    assert p["grading_ev"] is None                          # sealed carries no grading EV


def test_raw_packet_no_comp_is_data_needed_no_dollars():
    p = edge.build_asset_packet("umbreon_ex_161_raw_nm", RAW_ASSET,
                                _comp(None, "none", sources=[]), _mom("no_history", None),
                                None, _cfg(), as_of="2026-07-05")
    assert p["decision_hint"] == "DATA_NEEDED"
    assert p["expected_net"] is None
    assert p["comp_provenance"] is None
    assert "no comp" in " ".join(p["blockers"]).lower()


def test_raw_packet_ask_only_is_context_only():
    p = edge.build_asset_packet("umbreon_ex_161_raw_nm", RAW_ASSET,
                                _comp(None, "none", sources=[{"source": "ebay"}]),
                                _mom("single_observation", None), None, _cfg(), as_of="2026-07-05")
    assert "ask_only_context" in p["source_posture"]
    assert p["expected_net"] is None                        # ask is context, never a comp
    assert p["decision_hint"] in ("DATA_NEEDED", "WATCH")


def test_verified_raw_entry_makes_buy_shaped():
    p = edge.build_asset_packet(
        "umbreon_ex_161_raw_nm", RAW_ASSET,
        _comp(600.0, "high", [{"source": "ppt_cards"}, {"source": "tcgplayer"}]),
        _mom(), _asset_candidate(300.0), _cfg(), as_of="2026-07-05")
    assert p["trade_type"] == "raw_verified_arbitrage"
    assert p["decision_hint"] == "LIVE_PACKET_ELIGIBLE"
    assert p["entry_provenance"]["candidate_id"] == "cid-raw"
    assert p["expected_net"] > 0


def test_verified_graded_entry_makes_buy_shaped():
    graded = {"asset_class": "graded", "name": "Umbreon ex 161", "set": "Prismatic Evolutions",
              "card_number": "161", "grader": "PSA", "grade": "10", "grade_key": "psa10",
              "tcgplayer_id": "610516"}
    graded_cand = {"verified_price": 4000.0, "retailer": "LGS", "source": "manual_verified",
                   "candidate_id": "cid-psa10", "stock_evidence": "verified page",
                   "url": "https://l/x", "stock_checked_at": "2026-07-05",
                   "observed_at": "2026-07-05", "asset_key": "umbreon_psa10",
                   "grade_key": "psa10", "asset_class": "graded"}
    p = edge.build_asset_packet(
        "umbreon_psa10", graded,
        _comp(6900.0, "high", [{"source": "ppt_cards"}]), _mom(), graded_cand,
        _cfg(), as_of="2026-07-05")
    assert p["trade_type"] == "graded_verified_arbitrage"
    assert p["decision_hint"] == "LIVE_PACKET_ELIGIBLE"
    assert p["grading_ev"] is None                          # graded slabs carry no grading EV
    assert p["entry_provenance"]["candidate_id"] == "cid-psa10"


def test_unverified_raw_candidate_not_buy_shaped():
    # no verified asset candidate (asset_candidate_for returned None) => WATCH, no entry
    p = edge.build_asset_packet(
        "umbreon_ex_161_raw_nm", RAW_ASSET,
        _comp(600.0, "high", [{"source": "ppt_cards"}]), _mom(), None, _cfg(), as_of="2026-07-05")
    assert p["decision_hint"] == "WATCH"
    assert p["entry_provenance"] is None
    assert p["decision_hint"] not in ("PAPER_BUY", "LIVE_PACKET_ELIGIBLE")


def test_grading_ev_block_attached_for_raw_with_gem_rate():
    p = edge.build_asset_packet(
        "umbreon_ex_161_raw_nm", RAW_ASSET,
        _comp(500.0, "high", [{"source": "ppt_cards"}]), _mom(), _asset_candidate(400.0),
        _cfg(), as_of="2026-07-05", graded_sibling_comp=1000.0, target_grade="psa10",
        gem_rate=0.4, gem_rate_source="operator_assumption 2026-07-05")
    assert p["grading_ev"] is not None
    assert p["grading_ev"]["status"] != "blocked"
    assert p["grading_ev"]["expected_net"] is not None
    assert p["grading_ev"]["target_grade"] == "psa10"


def test_grading_ev_blocks_without_gem_rate():
    p = edge.build_asset_packet(
        "umbreon_ex_161_raw_nm", RAW_ASSET,
        _comp(500.0, "high", [{"source": "ppt_cards"}]), _mom(), _asset_candidate(400.0),
        _cfg(), as_of="2026-07-05", graded_sibling_comp=1000.0, target_grade="psa10")
    assert p["grading_ev"]["status"] == "blocked"
    assert any("gem rate" in b.lower() for b in p["grading_ev"]["blockers"])


def test_paper_ledger_view_carries_evidence_columns():
    """The audit row must round-trip the evidence, not just the id: a recorded edge
    decision keeps entry_price / market_comp / product_key / discount / confidence /
    stale under the Phase C ledger's legacy column names (the packet renamed them)."""
    from scanner.poke_api import paper_ledger
    p = edge.build_sealed_packet("jt_bb", SEALED_PRODUCT, _comp(90.0), _mom(),
                                 _sealed_candidate(40.0), _cfg(), as_of="2026-07-05")
    view = edge.paper_ledger_view(p)
    row = paper_ledger.build_decision_row(view, as_of="2026-07-05", recorded_at="2026-07-05")
    assert row["opportunity_id"] == p["edge_packet_id"]
    assert row["product_key"] == "jt_bb"
    assert row["entry_price"] == 40.0
    assert row["market_comp"] == 90.0
    assert row["discount_pct"] is not None
    assert row["latest_confidence"] == "high"
    assert row["stale"] is False
    assert row["verdict_tier"] == "BUY"
    assert row["expected_net"] is not None
    assert row["hypothesis"] == p["thesis"]
    assert row["input_snapshot"]                          # candidate provenance preserved


def test_packet_carries_momentum_for_the_audit_row():
    p = edge.build_sealed_packet("jt_bb", SEALED_PRODUCT, _comp(90.0), _mom("ok", 2.5),
                                 _sealed_candidate(40.0), _cfg(), as_of="2026-07-05")
    assert p["momentum_status"] == "ok"
    assert p["momentum_delta_pct"] == 2.5


def test_packet_serializes_to_plain_dict():
    p = edge.build_sealed_packet("jt_bb", SEALED_PRODUCT, _comp(90.0), _mom(),
                                 _sealed_candidate(), _cfg(), as_of="2026-07-05")
    import json
    json.dumps(p)                                           # must be JSON-serializable
    assert set(["edge_packet_id", "subject_key", "asset_class", "decision_hint",
                "source_posture", "provider_dependency", "input_snapshot"]).issubset(p)
