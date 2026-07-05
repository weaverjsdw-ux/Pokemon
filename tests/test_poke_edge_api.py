"""Session E Slice F — read-only, 0-credit edge endpoints via router dispatch.

Injected fakes; a counting/failing card client proves no billed provider call ever
happens on an edge read path (same belt as /opportunities)."""
from __future__ import annotations

from scanner import config as cfg_mod
from scanner.poke_api import candidates as cand
from scanner.poke_api import history, router


PRODUCTS = {
    "jt_bb": {"name": "Journey Together Booster Bundle", "set": "Journey Together",
              "type": "Booster Bundle", "msrp": "$26.94", "tcgplayer_id": "610953"},
}
ASSETS = {
    "umbreon_raw_nm": {"asset_class": "raw", "name": "Umbreon ex 161",
                       "set": "Prismatic Evolutions", "card_number": "161",
                       "condition": "NM", "tcgplayer_id": "610516"},
    "umbreon_psa10": {"asset_class": "graded", "name": "Umbreon ex 161",
                      "set": "Prismatic Evolutions", "card_number": "161",
                      "grader": "PSA", "grade": "10", "grade_key": "psa10",
                      "tcgplayer_id": "610516"},
}
IK_PSA10 = history.item_key_for_asset(ASSETS["umbreon_psa10"])
OBS = [{"item_key": IK_PSA10, "kind": "market_comp", "comp": 6900.0,
        "capture_date": "2026-07-04", "source": "ppt_cards", "comp_confidence": "high"}]


class FakeProvider:
    def __init__(self, rows):
        self.rows = rows
        self.estimate_calls = 0

    def cached(self, key, product):
        return self.rows.get(key)

    def estimate(self, key, product):
        self.estimate_calls += 1
        return {}


class _FailingCardClient:
    """Any billed lookup is a test failure — edge reads must never reach it."""
    def raw_quote(self, asset, checked_at):
        raise AssertionError("edge read path must not make a billed raw call")

    def graded_smart(self, asset, checked_at):
        raise AssertionError("edge read path must not make a billed graded call")


def _cfg():
    return cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "opportunity": {"live_min_expected_net": 25.0, "live_min_roi_pct": 30.0,
                        "live_min_confidence": "medium",
                        "max_hold_days": {"sealed_retail_arbitrage": 45},
                        "exit_venue": {"sealed_retail_arbitrage": "ebay"}}})


def _deps(*, cached=None, candidate_rows=None, today="2026-07-05"):
    rows = list(candidate_rows or [])
    return router.PokeApiDeps(
        products=PRODUCTS,
        assets=ASSETS,
        read_observations=lambda: list(OBS),
        comp_provider=FakeProvider(cached or {}),
        today=today,
        cfg=_cfg(),
        candidate_for=cand.candidate_for_provider(rows),
        asset_candidate_for=cand.asset_candidate_for_provider(rows),
        read_candidates=lambda: rows,
        card_client=_FailingCardClient(),
    )


def _arb_row():
    return {"status": "ok", "estimate": 90.0, "confidence": "high",
            "sources": [{"source": "tcgplayer"}, {"source": "pricecharting"}],
            "checkedAt": "2026-07-04"}


def _sealed_verified_row():
    return cand.build_record(cand.make_candidate(
        source="manual_verified", product_key="jt_bb", entry_price=40.0,
        buy_url="https://shop/x", stock_status="verified_buyable", stock_evidence="e",
        stock_checked_at="2026-07-05", observed_at="2026-07-05", retailer="Target"))


def _status(payload):
    return payload.get("httpStatus", 200)


def test_edge_packets_lists_sealed_and_assets():
    deps = _deps(cached={"jt_bb": _arb_row()}, candidate_rows=[_sealed_verified_row()])
    payload = router.handle_get("/api/poke/edge-packets", {}, deps)
    assert payload["ok"] is True
    keys = {p["subject_key"] for p in payload["edge_packets"]}
    assert keys == {"jt_bb", "umbreon_raw_nm", "umbreon_psa10"}
    jt = next(p for p in payload["edge_packets"] if p["subject_key"] == "jt_bb")
    assert jt["decision_hint"] == "LIVE_PACKET_ELIGIBLE"       # verified sealed entry + confident comp
    psa = next(p for p in payload["edge_packets"] if p["subject_key"] == "umbreon_psa10")
    assert psa["decision_hint"] == "WATCH"                     # comp but no verified asset entry


def test_edge_packet_by_id():
    deps = _deps(cached={"jt_bb": _arb_row()}, candidate_rows=[_sealed_verified_row()])
    allp = router.handle_get("/api/poke/edge-packets", {}, deps)["edge_packets"]
    pid = allp[0]["edge_packet_id"]
    one = router.handle_get(f"/api/poke/edge-packets/{pid}", {}, deps)
    assert one["ok"] is True
    assert one["edge_packet"]["edge_packet_id"] == pid


def test_edge_packet_unknown_id_is_404():
    payload = router.handle_get("/api/poke/edge-packets/nope-nope", {}, _deps())
    assert _status(payload) == 404
    assert payload["ok"] is False


def test_edge_summary():
    deps = _deps(cached={"jt_bb": _arb_row()}, candidate_rows=[_sealed_verified_row()])
    payload = router.handle_get("/api/poke/edge-summary", {}, deps)
    assert payload["ok"] is True
    s = payload["summary"]
    assert s["count"] == 3
    assert s["by_decision"]["LIVE_PACKET_ELIGIBLE"] == 1
    assert s["live_packet_eligible"] == 1
    assert set(s["by_asset_class"]) == {"sealed", "raw", "graded"}


def test_edge_endpoints_spend_no_credits():
    """The core belt: every edge read route stays off the network (0 credits) — the
    counting card client is never called and the comp provider never estimates."""
    deps = _deps(cached={"jt_bb": _arb_row()}, candidate_rows=[_sealed_verified_row()])
    router.handle_get("/api/poke/edge-packets", {}, deps)
    router.handle_get("/api/poke/edge-summary", {}, deps)
    allp = router.handle_get("/api/poke/edge-packets", {}, deps)["edge_packets"]
    router.handle_get(f"/api/poke/edge-packets/{allp[0]['edge_packet_id']}", {}, deps)
    assert deps.comp_provider.estimate_calls == 0             # read-first, never a network comp


def test_verified_asset_entry_makes_asset_live_via_edge_route():
    """A verified RAW asset candidate is the ONLY way a raw single becomes buy-shaped;
    a psa10 with only a comp (no verified entry) stays WATCH (never live off a comp)."""
    raw_row = cand.build_record(cand.make_candidate(
        source="manual_verified", product_key="umbreon_raw_nm", asset_key="umbreon_raw_nm",
        asset_class="raw", condition="NM", entry_price=200.0, buy_url="https://l/x",
        stock_status="verified_buyable", stock_evidence="e", stock_checked_at="2026-07-05",
        observed_at="2026-07-05", retailer="LGS"))
    # ledger comp for the raw NM identity so there is a comp to value against
    ik_nm = history.item_key_for_asset(ASSETS["umbreon_raw_nm"])
    obs = OBS + [{"item_key": ik_nm, "kind": "market_comp", "comp": 1500.0,
                  "capture_date": "2026-07-04", "source": "ppt_cards", "comp_confidence": "high"}]
    deps = router.PokeApiDeps(
        products={}, assets=ASSETS, read_observations=lambda: list(obs),
        comp_provider=FakeProvider({}), today="2026-07-05", cfg=_cfg(),
        asset_candidate_for=cand.asset_candidate_for_provider([raw_row]),
        card_client=_FailingCardClient())
    packets = {p["subject_key"]: p for p in
               router.handle_get("/api/poke/edge-packets", {}, deps)["edge_packets"]}
    assert packets["umbreon_raw_nm"]["trade_type"] == "raw_verified_arbitrage"
    assert packets["umbreon_raw_nm"]["decision_hint"] == "LIVE_PACKET_ELIGIBLE"
    assert packets["umbreon_psa10"]["decision_hint"] == "WATCH"   # comp only, never live
