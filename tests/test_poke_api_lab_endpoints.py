"""Phase C — Lab GET endpoints (opportunities / paper-decisions / signals).

Injected fakes; no network, no PPT. refresh semantics of the read path unchanged."""
from __future__ import annotations

from scanner import config as cfg_mod
from scanner.poke_api import paper_ledger as pl
from scanner.poke_api import router


PRODUCTS = {
    "jt_bb": {"name": "Journey Together Booster Bundle", "set": "Journey Together",
              "type": "Booster Bundle", "msrp": "$26.94", "ppt_id": "610953"},
    "pe_etb": {"name": "Prismatic Evolutions ETB", "set": "Prismatic Evolutions",
               "type": "ETB", "msrp": "$49.99", "ppt_id": "593355"},
}


class FakeProvider:
    def __init__(self, rows):
        self.rows = rows
        self.estimate_calls = 0

    def cached(self, key, product):
        return self.rows.get(key)

    def estimate(self, key, product):
        self.estimate_calls += 1
        return {}


def _cfg():
    return cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "opportunity": {"max_hold_days": {"sealed_retail_arbitrage": 45},
                        "exit_venue": {"sealed_retail_arbitrage": "ebay"}},
    })


def _deps(*, cached=None, candidates=None, decisions=None, today="2026-07-05"):
    provider = FakeProvider(cached or {})
    return router.PokeApiDeps(
        products=PRODUCTS,
        read_observations=lambda: [],
        comp_provider=provider,
        today=today,
        cfg=_cfg(),
        candidate_for=lambda k, p: (candidates or {}).get(k),
        read_decisions=lambda: list(decisions or []),
    ), provider


def _arb_row():
    return {"status": "ok", "estimate": 90.0, "confidence": "high",
            "sources": [{"source": "tcgplayer"}, {"source": "pricecharting"}],
            "checkedAt": "2026-07-03"}


def _status(payload):
    return payload.get("httpStatus", 200)


def test_opportunities_endpoint_scores_catalog_no_network():
    deps, provider = _deps(cached={"jt_bb": _arb_row()},
                           candidates={"jt_bb": {"verified_price": 40.0, "retailer": "Target"}})
    payload = router.handle_get("/api/poke/opportunities", {}, deps)
    assert payload["ok"] is True
    assert payload["count"] == 2
    assert payload["summary"]["live_packet_eligible"] == 1
    keys = {o["product_key"]: o for o in payload["opportunities"]}
    assert keys["jt_bb"]["decision_hint"] == "LIVE_PACKET_ELIGIBLE"
    assert keys["pe_etb"]["market_comp"] is None      # STOP-class: no source, no number
    assert provider.estimate_calls == 0                # never a network comp on the read path


def test_single_opportunity_endpoint():
    deps, _ = _deps(cached={"jt_bb": _arb_row()},
                    candidates={"jt_bb": {"verified_price": 40.0}})
    payload = router.handle_get("/api/poke/opportunities/jt_bb", {}, deps)
    assert payload["ok"] is True
    assert payload["opportunity"]["product_key"] == "jt_bb"
    assert payload["opportunity"]["trade_type"] == "sealed_retail_arbitrage"


def test_single_opportunity_unknown_key_is_404():
    deps, _ = _deps()
    payload = router.handle_get("/api/poke/opportunities/nope", {}, deps)
    assert _status(payload) == 404
    assert payload["ok"] is False


def test_paper_decisions_replay_fold():
    oid = "op-jt"
    rows = [
        pl.build_decision_row({"opportunity_id": oid, "decision_hint": "PAPER_BUY",
                               "as_of": "2026-07-05", "trade_type": "sealed_retail_arbitrage"},
                              recorded_at="t1"),
        pl.build_outcome_row(oid, "SOLD", "2026-08-20", realized_net=20.0),
    ]
    deps, _ = _deps(decisions=rows)
    payload = router.handle_get("/api/poke/paper-decisions", {}, deps)
    assert payload["ok"] is True and payload["count"] == 1
    entry = payload["decisions"][0]
    assert entry["opportunity_id"] == oid
    assert entry["decision"]["decision"] == "PAPER_BUY"
    assert entry["outcome"]["status"] == "SOLD"


def test_signals_endpoint():
    oid = "op-jt"
    rows = [
        pl.build_decision_row({"opportunity_id": oid, "decision_hint": "PAPER_BUY",
                               "as_of": "2026-07-05", "trade_type": "sealed_retail_arbitrage"},
                              recorded_at="t1"),
        pl.build_outcome_row(oid, "SOLD", "2026-08-20", realized_net=20.0),
    ]
    deps, _ = _deps(decisions=rows)
    payload = router.handle_get("/api/poke/signals", {}, deps)
    assert payload["ok"] is True
    sig = payload["signals"]
    assert sig["outcomes_recorded"] == 1
    assert sig["by_trade_type"]["sealed_retail_arbitrage"]["hit_rate"] == 1.0


def test_empty_paper_decisions_and_signals():
    deps, _ = _deps()
    assert router.handle_get("/api/poke/paper-decisions", {}, deps)["count"] == 0
    assert router.handle_get("/api/poke/signals", {}, deps)["signals"]["opportunities"] == 0
