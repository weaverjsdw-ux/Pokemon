"""Track D lab integration — raw/graded assets as WATCH-grade evidence rows.

Conservative by design: the only asset trade types are catalog_gap / market_watch,
none are live-eligible, and no asset opportunity can ever be LIVE_PACKET_ELIGIBLE —
even with a fabricated high comp (#9, #10). Sealed opportunity / activation math is
untouched (#1)."""
from __future__ import annotations

from scanner import config as cfg_mod
from scanner.poke_api import history, opportunities as opp, router


RAW_NM = {"asset_class": "raw", "name": "Umbreon ex", "set": "Prismatic Evolutions",
          "card_number": "161", "condition": "NM", "tcgplayer_id": "999001"}
PSA10 = {"asset_class": "graded", "name": "Umbreon ex", "set": "Prismatic Evolutions",
         "card_number": "161", "grader": "PSA", "grade": "10", "grade_key": "psa10",
         "tcgplayer_id": "999001"}


def _cfg():
    return cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "opportunity": {"max_hold_days": {"sealed_retail_arbitrage": 45},
                        "exit_venue": {"sealed_retail_arbitrage": "ebay"}}})


def _comp(estimate, confidence="low", sources=None):
    return {"estimate": estimate, "confidence": confidence, "sources": sources or [],
            "stale": False, "checkedAt": "2026-07-04", "compBasis": "ledger latest"}


def _mom(status="no_history", delta=None):
    return {"status": status, "delta_pct": delta, "stale": False}


# --- classification + WATCH-only (#10) ----------------------------------------

def test_raw_no_comp_is_catalog_gap_watch():
    o = opp.build_asset_opportunity("umbreon_raw_nm", RAW_NM, _comp(None, "none"),
                                    _mom("no_history"), _cfg(), as_of="2026-07-05")
    assert o.trade_type == "raw_catalog_gap"
    assert o.decision_hint == "WATCH"
    assert o.live_eligible is False


def test_graded_with_comp_is_market_watch():
    o = opp.build_asset_opportunity(
        "umbreon_psa10", PSA10, _comp(250.0, "high", [{"source": "ppt_cards"}]),
        _mom("ok", 4.0), _cfg(), as_of="2026-07-05")
    assert o.trade_type == "graded_market_watch"
    assert o.decision_hint == "WATCH"
    assert o.asset_class == "graded" and o.grader == "PSA" and o.grade == "10"


def test_asset_trade_types_are_never_live_eligible():
    for tt in ("raw_catalog_gap", "raw_market_watch",
               "graded_catalog_gap", "graded_market_watch"):
        assert tt in opp.TRADE_TYPES
        assert tt not in opp.LIVE_ELIGIBLE


def test_asset_never_live_even_with_fabricated_high_comp():
    o = opp.build_asset_opportunity(
        "umbreon_psa10", PSA10,
        _comp(9999.0, "high", [{"source": "ppt_cards"}, {"source": "pricecharting"}]),
        _mom("ok", 50.0), _cfg(), as_of="2026-07-05")
    assert o.decision_hint == "WATCH"
    assert o.decision_hint != "LIVE_PACKET_ELIGIBLE"
    assert o.trade_type not in opp.LIVE_ELIGIBLE


def test_asset_opportunity_carries_no_entry_or_money():
    o = opp.build_asset_opportunity(
        "umbreon_raw_nm", RAW_NM, _comp(50.0, "low", [{"source": "tcgplayer"}]),
        _mom("ok", 2.0), _cfg(), as_of="2026-07-05")
    assert o.entry_price is None
    assert o.expected_net is None and o.expected_roi_pct is None
    assert o.condition == "NM" and o.card_number == "161"


# --- ask-only cannot mint live (#9, opportunity layer) ------------------------

def test_ask_only_low_confidence_graded_stays_watch():
    # a low-confidence comp (ask-derived context) never becomes a buy
    o = opp.build_asset_opportunity(
        "umbreon_psa10", PSA10, _comp(200.0, "low", [{"source": "ebay"}]),
        _mom("single_observation"), _cfg(), as_of="2026-07-05")
    assert o.decision_hint == "WATCH"
    assert o.live_eligible is False


# --- endpoint integration -----------------------------------------------------

ASSETS = {"umbreon_raw_nm": RAW_NM, "umbreon_psa10": PSA10}
IK_PSA10 = history.item_key_for_asset(PSA10)
OBS = [{"item_key": IK_PSA10, "kind": "market_comp", "comp": 250.0,
        "capture_date": "2026-07-04", "source": "ppt_cards", "comp_confidence": "high"}]
SEALED = {"pe_etb": {"name": "Prismatic Evolutions ETB", "set": "Prismatic Evolutions",
                     "type": "ETB", "msrp": "$49.99", "ppt_id": "593355"}}


class _Stub:
    def cached(self, k, p):
        return None

    def estimate(self, k, p):
        return {}


def _deps(*, products=None, assets=None, observations=None):
    return router.PokeApiDeps(
        products=products if products is not None else {},
        assets=ASSETS if assets is None else assets,
        read_observations=lambda: list(OBS if observations is None else observations),
        comp_provider=_Stub(), today="2026-07-05", cfg=_cfg())


def test_opportunities_endpoint_includes_asset_watch_rows():
    payload = router.handle_get("/api/poke/opportunities", {}, _deps())
    rows = {o["product_key"]: o for o in payload["opportunities"]}
    assert rows["umbreon_psa10"]["decision_hint"] == "WATCH"
    assert rows["umbreon_psa10"]["trade_type"] == "graded_market_watch"
    assert rows["umbreon_raw_nm"]["trade_type"] == "raw_catalog_gap"
    assert payload["summary"]["live_packet_eligible"] == 0


def test_opportunities_without_assets_is_unchanged():
    payload = router.handle_get("/api/poke/opportunities", {}, _deps(assets={}))
    assert payload["count"] == 0          # no products, no assets -> nothing


def test_signals_activation_stays_sealed_scoped():
    # assets are present, but the dormancy report counts sealed products only
    payload = router.handle_get("/api/poke/signals", {}, _deps(products=SEALED))
    assert payload["activation"]["products_seen"] == 1


# --- #5 /opportunities performs NO live/billed source calls -------------------

class _CountingCardClient:
    """A card client that records (and refuses) any lookup — proves /opportunities
    never reaches a billable source (it is read-first, 0 credits)."""
    def __init__(self):
        self.calls = 0

    def raw_quote(self, asset, checked_at):
        self.calls += 1
        raise AssertionError("/opportunities must not make a billed raw call")

    def graded_smart(self, asset, checked_at):
        self.calls += 1
        raise AssertionError("/opportunities must not make a billed graded call")


def test_opportunities_never_calls_a_billed_source():
    client = _CountingCardClient()
    deps = router.PokeApiDeps(
        products=SEALED, assets=ASSETS, read_observations=lambda: list(OBS),
        comp_provider=_Stub(), today="2026-07-05", cfg=_cfg(), card_client=client)
    payload = router.handle_get("/api/poke/opportunities", {}, deps)
    assert client.calls == 0                                  # 0 external calls, 0 credits
    assert payload["summary"]["live_packet_eligible"] == 0    # and still dormant
