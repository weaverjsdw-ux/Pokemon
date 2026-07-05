"""Phase C — lab orchestrator (build opportunities from deps) + CLI round-trip."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scanner import config as cfg_mod
from scanner.poke_api import lab
from scanner.poke_api import paper_ledger as pl


class FakeComp:
    """Minimal comp provider: returns a cached legacy row per key, no network."""
    def __init__(self, rows):
        self._rows = rows

    def cached(self, key, product):
        return self._rows.get(key)


PRODUCTS = {
    "jt_bb": {"name": "Journey Together Booster Bundle", "set": "Journey Together",
              "msrp": 26.94, "ppt_id": "610953"},
    "pe_etb": {"name": "Prismatic Evolutions ETB", "set": "Prismatic Evolutions",
               "msrp": 49.99, "ppt_id": "999"},
}


def make_deps(tmp_path, *, cached=None, observations=None, candidates=None,
              today="2026-07-05"):
    cfg = cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "opportunity": {
            "max_hold_days": {"sealed_retail_arbitrage": 45},
            "exit_venue": {"sealed_retail_arbitrage": "ebay"},
        },
    })
    decisions_path = tmp_path / "paper_decisions.jsonl"
    return SimpleNamespace(
        products=PRODUCTS,
        read_observations=lambda: list(observations or []),
        comp_provider=FakeComp(cached or {}),
        today=today,
        cfg=cfg,
        candidate_for=lambda k, p: (candidates or {}).get(k),
        decisions_path=decisions_path,
        read_decisions=lambda: pl.read_rows(decisions_path),
    )


def _arb_comp_row():
    # legacy cached comp row (status ok + estimate) that model.comp_response adapts
    return {"status": "ok", "estimate": 90.0, "confidence": "high",
            "sources": [{"source": "tcgplayer"}, {"source": "pricecharting"}],
            "checkedAt": "2026-07-03"}


def test_build_opportunities_one_per_product_no_network(tmp_path):
    deps = make_deps(
        tmp_path,
        cached={"jt_bb": _arb_comp_row()},
        candidates={"jt_bb": {"verified_price": 40.0, "retailer": "Target",
                              "source": "target_search"}},
    )
    opps = lab.build_opportunities(deps, as_of="2026-07-05")
    assert len(opps) == 2
    by_key = {o["product_key"]: o for o in opps}
    # jt_bb: verified deal + confident comp => arbitrage, clears live floor
    assert by_key["jt_bb"]["trade_type"] == "sealed_retail_arbitrage"
    assert by_key["jt_bb"]["decision_hint"] == "LIVE_PACKET_ELIGIBLE"
    # pe_etb: no comp, no candidate => catalog gap / watch (STOP-class None numbers)
    assert by_key["pe_etb"]["market_comp"] is None
    assert by_key["pe_etb"]["expected_net"] is None
    assert by_key["pe_etb"]["decision_hint"] == "WATCH"


def test_summary_counts(tmp_path):
    deps = make_deps(
        tmp_path,
        cached={"jt_bb": _arb_comp_row()},
        candidates={"jt_bb": {"verified_price": 40.0, "retailer": "Target"}},
    )
    opps = lab.build_opportunities(deps, as_of="2026-07-05")
    s = lab.summary(opps)
    assert s["count"] == 2
    assert s["live_packet_eligible"] == 1
    assert s["by_decision"].get("LIVE_PACKET_ELIGIBLE") == 1
    assert sum(s["by_trade_type"].values()) == 2


def test_cli_list_json(tmp_path, capsys):
    deps = make_deps(tmp_path, cached={"jt_bb": _arb_comp_row()},
                     candidates={"jt_bb": {"verified_price": 40.0}})
    rc = lab.main(["list", "--json"], deps=deps)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["count"] == 2
    assert len(out["opportunities"]) == 2


def test_cli_record_then_outcome_then_report(tmp_path, capsys):
    deps = make_deps(tmp_path, cached={"jt_bb": _arb_comp_row()},
                     candidates={"jt_bb": {"verified_price": 40.0}})
    # record the decision hint for jt_bb
    assert lab.main(["record", "--product", "jt_bb"], deps=deps) == 0
    capsys.readouterr()
    rows = pl.read_rows(deps.decisions_path)
    assert len(rows) == 1 and rows[0]["kind"] == "decision"
    oid = rows[0]["opportunity_id"]

    # mark an outcome later
    assert lab.main(["outcome", "--opportunity", oid, "--status", "SOLD",
                     "--net", "22.5", "--observed-at", "2026-08-20"], deps=deps) == 0
    capsys.readouterr()

    # report reflects the realized outcome
    assert lab.main(["report", "--json"], deps=deps) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["signals"]["outcomes_recorded"] == 1
    arb = rep["signals"]["by_trade_type"]["sealed_retail_arbitrage"]
    assert arb["with_outcome"] == 1 and arb["hit_rate"] == 1.0


def test_cli_record_all(tmp_path, capsys):
    deps = make_deps(tmp_path, cached={"jt_bb": _arb_comp_row()},
                     candidates={"jt_bb": {"verified_price": 40.0}})
    assert lab.main(["record-all"], deps=deps) == 0
    capsys.readouterr()
    rows = pl.decisions(pl.read_rows(deps.decisions_path))
    assert len(rows) == 2  # one decision per opportunity


def test_cli_record_unknown_product_errors(tmp_path, capsys):
    deps = make_deps(tmp_path)
    rc = lab.main(["record", "--product", "nope"], deps=deps)
    assert rc == 1
