"""Phase C — append-only paper-trade ledger (decisions + outcomes) + signals fold."""
from __future__ import annotations

import json

import pytest

from scanner.poke_api import paper_ledger as pl


def _opp(oid="op1", trade_type="sealed_retail_arbitrage", decision_hint="PAPER_BUY",
         as_of="2026-07-05", **kw):
    base = {
        "opportunity_id": oid, "product_key": "jt_bb", "name": "JT Booster Bundle",
        "trade_type": trade_type, "hypothesis": "verified retail below comp",
        "decision_hint": decision_hint, "as_of": as_of,
        "entry_price": 58.0, "market_comp": 100.0, "msrp": 26.94, "discount_pct": 42.0,
        "expected_net": 16.29, "expected_roi_pct": 26.2, "verdict_tier": "BUY",
        "latest_confidence": "high", "momentum_delta_pct": 2.5, "momentum_status": "ok",
        "stale": False, "score": 71.0,
    }
    base.update(kw)
    return base


def test_missing_file_reads_empty(tmp_path):
    assert pl.read_rows(tmp_path / "nope.jsonl") == []


def test_record_decision_idempotent(tmp_path):
    path = tmp_path / "paper_decisions.jsonl"
    assert pl.record_decision(path, _opp(), recorded_at="2026-07-05T10:00") is True
    # same (opportunity_id, decision, as_of) is a no-op even from a later run
    assert pl.record_decision(path, _opp(), recorded_at="2026-07-05T23:59") is False
    rows = pl.read_rows(path)
    assert len(rows) == 1 and rows[0]["kind"] == "decision"
    assert rows[0]["decision"] == "PAPER_BUY"


def test_decision_correction_appends_new_line_keeps_first(tmp_path):
    path = tmp_path / "paper_decisions.jsonl"
    pl.record_decision(path, _opp(decision_hint="WATCH"), recorded_at="t1")
    # operator changes the call: a different decision is a CORRECTION (new line, not an edit)
    pl.record_decision(path, _opp(decision_hint="PAPER_BUY"), recorded_at="t2")
    rows = pl.read_rows(path)
    assert len(rows) == 2
    assert [r["decision"] for r in rows] == ["WATCH", "PAPER_BUY"]
    # current fold takes the latest; the original WATCH line still exists (immutability)
    cur = pl.current_by_id(rows)
    assert cur["op1"]["decision"]["decision"] == "PAPER_BUY"


def test_outcome_is_separate_row_keyed_by_opportunity(tmp_path):
    path = tmp_path / "paper_decisions.jsonl"
    pl.record_decision(path, _opp(), recorded_at="t1")
    assert pl.record_outcome(path, "op1", "SOLD", "2026-08-20",
                             realized_price=95.0, realized_net=20.0, note="ebay sale") is True
    rows = pl.read_rows(path)
    assert len(rows) == 2
    cur = pl.current_by_id(rows)
    # the outcome does NOT erase or edit the decision row
    assert cur["op1"]["decision"]["decision"] == "PAPER_BUY"
    assert cur["op1"]["outcome"]["status"] == "SOLD"
    assert cur["op1"]["outcome"]["realized_net"] == 20.0


def test_outcome_idempotent_but_latest_wins(tmp_path):
    path = tmp_path / "paper_decisions.jsonl"
    pl.record_decision(path, _opp(), recorded_at="t1")
    assert pl.record_outcome(path, "op1", "HELD", "2026-08-01", realized_net=None) is True
    assert pl.record_outcome(path, "op1", "HELD", "2026-08-01", realized_net=None) is False  # dupe
    assert pl.record_outcome(path, "op1", "SOLD", "2026-08-20", realized_net=20.0) is True
    cur = pl.current_by_id(pl.read_rows(path))
    assert cur["op1"]["outcome"]["status"] == "SOLD"


def test_record_outcome_rejects_unknown_status(tmp_path):
    path = tmp_path / "paper_decisions.jsonl"
    with pytest.raises(ValueError):
        pl.record_outcome(path, "op1", "MOONED", "2026-08-20")


def test_signals_report_hit_rate_and_realized_net(tmp_path):
    path = tmp_path / "paper_decisions.jsonl"
    pl.record_decision(path, _opp(oid="a", trade_type="sealed_retail_arbitrage",
                                  decision_hint="PAPER_BUY"), recorded_at="t1")
    pl.record_decision(path, _opp(oid="b", trade_type="sealed_retail_arbitrage",
                                  decision_hint="PAPER_BUY"), recorded_at="t2")
    pl.record_decision(path, _opp(oid="c", trade_type="sealed_momentum_watch",
                                  decision_hint="WATCH"), recorded_at="t3")
    pl.record_outcome(path, "a", "SOLD", "2026-08-20", realized_net=20.0)   # win
    pl.record_outcome(path, "b", "SOLD", "2026-08-20", realized_net=-5.0)   # loss
    rep = pl.signals_report(pl.read_rows(path))
    assert rep["opportunities"] == 3
    assert rep["decisions_recorded"] == 3
    assert rep["outcomes_recorded"] == 2
    assert rep["by_decision"]["PAPER_BUY"] == 2
    arb = rep["by_trade_type"]["sealed_retail_arbitrage"]
    assert arb["count"] == 2 and arb["with_outcome"] == 2
    assert arb["hit_rate"] == 0.5
    assert arb["mean_realized_net"] == 7.5
    # a trade type with no realized outcome reports None, never a fabricated number
    watch = rep["by_trade_type"]["sealed_momentum_watch"]
    assert watch["hit_rate"] is None and watch["mean_realized_net"] is None


def test_rows_are_valid_json_lines(tmp_path):
    path = tmp_path / "paper_decisions.jsonl"
    pl.record_decision(path, _opp(), recorded_at="t1")
    pl.record_outcome(path, "op1", "SOLD", "2026-08-20", realized_net=20.0)
    for line in path.read_text(encoding="utf-8").splitlines():
        obj = json.loads(line)
        assert "entry_id" in obj and "kind" in obj and "opportunity_id" in obj
