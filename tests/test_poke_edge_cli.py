"""Session E Slice G — edge CLI (list / show / record / outcome / divergence-audit).

Deps injected; record/outcome append to a tmp paper-decisions ledger (idempotent);
divergence-audit --local spends 0 credits and external refuses without --yes."""
from __future__ import annotations

import json

from scanner import config as cfg_mod
from scanner.poke_api import candidates as cand
from scanner.poke_api import edge_cli, paper_ledger, router


PRODUCTS = {"jt_bb": {"name": "Journey Together Booster Bundle", "set": "Journey Together",
                      "type": "Booster Bundle", "msrp": "$26.94", "tcgplayer_id": "610953"}}


class FakeProvider:
    def __init__(self, rows):
        self.rows = rows

    def cached(self, key, product):
        return self.rows.get(key)

    def estimate(self, key, product):
        return {}


def _cfg():
    return cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "opportunity": {"live_min_expected_net": 25.0, "live_min_roi_pct": 30.0,
                        "live_min_confidence": "medium",
                        "max_hold_days": {"sealed_retail_arbitrage": 45},
                        "exit_venue": {"sealed_retail_arbitrage": "ebay"}}})


def _arb_row():
    return {"status": "ok", "estimate": 90.0, "confidence": "high",
            "sources": [{"source": "tcgplayer"}, {"source": "pricecharting"}],
            "checkedAt": "2026-07-04"}


def _verified_row():
    return cand.build_record(cand.make_candidate(
        source="manual_verified", product_key="jt_bb", entry_price=40.0,
        buy_url="https://shop/x", stock_status="verified_buyable", stock_evidence="e",
        stock_checked_at="2026-07-05", observed_at="2026-07-05", retailer="Target"))


def _deps(tmp_path):
    rows = [_verified_row()]
    return router.PokeApiDeps(
        products=PRODUCTS, assets={}, read_observations=lambda: [],
        comp_provider=FakeProvider({"jt_bb": _arb_row()}), today="2026-07-05", cfg=_cfg(),
        candidate_for=cand.candidate_for_provider(rows),
        asset_candidate_for=cand.asset_candidate_for_provider(rows),
        read_candidates=lambda: rows, decisions_path=tmp_path / "paper_decisions.jsonl")


def _pid(deps):
    from scanner.poke_api import edge
    return edge.build_edge_packets(deps, as_of="2026-07-05")[0]["edge_packet_id"]


def test_list_prints_packets(tmp_path, capsys):
    rc = edge_cli.main(["list"], deps=_deps(tmp_path))
    assert rc == 0
    assert "jt_bb" in capsys.readouterr().out


def test_list_json(tmp_path, capsys):
    rc = edge_cli.main(["list", "--json"], deps=_deps(tmp_path))
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "edge_packets" in data and data["summary"]["count"] == 1


def test_show_by_id(tmp_path, capsys):
    deps = _deps(tmp_path)
    pid = _pid(deps)
    rc = edge_cli.main(["show", "--id", pid, "--json"], deps=deps)
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["edge_packet_id"] == pid


def test_show_unknown_id_nonzero(tmp_path, capsys):
    rc = edge_cli.main(["show", "--id", "nope"], deps=_deps(tmp_path))
    assert rc == 1
    assert "nope" in capsys.readouterr().out


def test_record_appends_decision_idempotent(tmp_path, capsys):
    deps = _deps(tmp_path)
    pid = _pid(deps)
    assert edge_cli.main(["record", "--id", pid], deps=deps) == 0
    rows = paper_ledger.read_rows(deps.decisions_path)
    assert len(paper_ledger.decisions(rows)) == 1
    assert rows[0]["opportunity_id"] == pid
    # STOP-class auditability: the durable row keeps the evidence, not just the id
    assert rows[0]["product_key"] == "jt_bb"
    assert rows[0]["entry_price"] == 40.0
    assert rows[0]["market_comp"] == 90.0
    # idempotent re-run
    assert edge_cli.main(["record", "--id", pid], deps=deps) == 0
    assert len(paper_ledger.decisions(paper_ledger.read_rows(deps.decisions_path))) == 1


def test_outcome_appends(tmp_path):
    deps = _deps(tmp_path)
    pid = _pid(deps)
    edge_cli.main(["record", "--id", pid], deps=deps)
    assert edge_cli.main(["outcome", "--id", pid, "--status", "SOLD", "--net", "20"],
                         deps=deps) == 0
    outs = paper_ledger.outcomes(paper_ledger.read_rows(deps.decisions_path))
    assert len(outs) == 1 and outs[0]["realized_net"] == 20.0


def test_divergence_audit_local_zero_credits(tmp_path, capsys):
    rc = edge_cli.main(["divergence-audit", "--local"], deps=_deps(tmp_path))
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "0 credit" in out or "local" in out


def test_divergence_audit_external_refuses_without_yes(tmp_path, capsys):
    deps = _deps(tmp_path)
    deps.cfg.market_api_key = "k"
    rc = edge_cli.main(["divergence-audit", "--products", "jt_bb"], deps=deps)
    assert rc == 2                                     # refused (money-class)
    assert "--yes" in capsys.readouterr().out
