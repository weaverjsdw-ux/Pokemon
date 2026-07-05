"""Phase C activation — discovery-manifest replay + candidate-backed lab flow.

Replay imports ONLY verified-buyable rows as candidates; parser_suspect /
unverifiable / out_of_stock rows are summarized as blocked evidence, never
promoted to buys. The real on-disk sealed board is the dormant proof: rows scanned,
zero verified-buyable, per-row reasons — not a failure.
"""
from __future__ import annotations

import json
from pathlib import Path

from types import SimpleNamespace

from scanner import config as cfg_mod
from scanner.poke_api import candidates as cand
from scanner.poke_api import lab
from scanner.poke_api import paper_ledger as pl
from scanner.poke_api import router


CATALOG = {
    "pe_etb": {"name": "Prismatic Evolutions Elite Trainer Box",
               "set": "Prismatic Evolutions", "msrp": 49.99, "ppt_id": "593355"},
    "jt_bb": {"name": "Journey Together Booster Bundle", "set": "Journey Together",
              "msrp": 26.94, "ppt_id": "610953"},
}


class FakeComp:
    def __init__(self, rows):
        self._rows = rows

    def cached(self, key, product):
        return self._rows.get(key)


def _arb_comp_row():
    return {"status": "ok", "estimate": 176.17, "confidence": "medium",
            "sources": [{"source": "tcgplayer"}, {"source": "pricecharting"}],
            "checkedAt": "2026-07-05"}


def _lab_deps(tmp_path, *, cached=None, today="2026-07-05"):
    """Lab deps over a real cfg (fees/policy) but a hermetic tmp candidate ledger.
    ``candidate_for`` reads the ledger live so a candidate-add is visible to a
    later record-candidates in the same test."""
    cfg = cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "opportunity": {"max_hold_days": {"sealed_retail_arbitrage": 45},
                        "exit_venue": {"sealed_retail_arbitrage": "ebay"}},
    })
    cpath = tmp_path / "verified_candidates.jsonl"
    dpath = tmp_path / "paper_decisions.jsonl"
    return SimpleNamespace(
        products=CATALOG,
        read_observations=lambda: [],
        comp_provider=FakeComp(cached or {}),
        today=today,
        cfg=cfg,
        candidate_for=lambda k, p: cand.candidate_for_provider(cand.read_rows(cpath))(k, p),
        decisions_path=dpath,
        read_decisions=lambda: pl.read_rows(dpath),
        candidates_path=cpath,
        read_candidates=lambda: cand.read_rows(cpath),
    )


def _buyable_deal(item, price, url="https://shop.example/buy"):
    return {"item": item, "deal_price": price, "market_comp": 176.17, "pct_off": 72,
            "retailer": "Example", "source_url": "https://www.tcgplayer.com/product/593355",
            "comp_confidence": "medium", "stock_status": "in_stock",
            "stock_evidence": "availability=InStock price=49.99 :: <schema.org>",
            "buy_url": url, "stock_checked_at": "2026-07-05T20:00:00+00:00",
            "stock_method": "page_fetch", "captured_at": "2026-07-05", "set": "Prismatic Evolutions"}


def _blocked_deal(item, stock_status, evidence):
    return {"item": item, "deal_price": 49.99, "market_comp": 100.0, "retailer": "MSRP",
            "source_url": "https://www.pricecharting.com/x", "comp_confidence": "low",
            "stock_status": stock_status, "stock_evidence": evidence, "buy_url": "",
            "stock_checked_at": "2026-07-05T20:00:00+00:00", "stock_method": "none",
            "captured_at": "2026-07-05"}


# ---------------------------------------------------------------- replay: deals

def test_replay_imports_only_verified_buyable_rows(tmp_path):
    """Required test 4 — only verified-buyable rows become candidates."""
    board = {"deals": [
        _buyable_deal("Prismatic Evolutions Elite Trainer Box", 49.99),
        _blocked_deal("Crown Zenith Elite Trainer Box", "unverifiable",
                      "no online-capable retailer adapter holds an id"),
    ]}
    path = tmp_path / "2026-07-05-discovery.json"
    path.write_text(json.dumps(board), encoding="utf-8")
    result = cand.load_and_replay(path, CATALOG)
    assert result.scanned == 2
    assert len(result.candidates) == 1
    c = result.candidates[0]
    assert c.entry_verified is True
    assert c.product_key == "pe_etb"
    assert c.entry_price == 49.99
    assert len(result.blocked) == 1


def test_replay_summarizes_blocked_without_converting(tmp_path):
    """Required test 5 — parser_suspect / unverifiable rows are evidence, not buys."""
    board = {"deals": [
        _blocked_deal("A", "parser_suspect", "no schema.org availability signal parsed"),
        _blocked_deal("B", "unverifiable", "walmart returned no inventory row"),
        _blocked_deal("C", "out_of_stock", "affirmatively out of stock"),
    ]}
    path = tmp_path / "b.json"
    path.write_text(json.dumps(board), encoding="utf-8")
    result = cand.load_and_replay(path, CATALOG)
    assert result.scanned == 3
    assert result.candidates == []                       # nothing promoted to a buy
    assert len(result.blocked) == 3
    reasons = " ".join(b["reason"] for b in result.blocked).lower()
    assert "not verified-buyable" in reasons
    # blocker rows carry the stock_status so the report can bucket them
    assert {b["stock_status"] for b in result.blocked} == {"parser_suspect", "unverifiable", "out_of_stock"}


def test_replay_reports_unmatched_buyable_not_dropped(tmp_path):
    """A verified-buyable row that maps to no catalog product is reported, not dropped."""
    board = {"deals": [_buyable_deal("Totally Unknown Mystery Box 9000", 12.0)]}
    path = tmp_path / "u.json"
    path.write_text(json.dumps(board), encoding="utf-8")
    result = cand.load_and_replay(path, CATALOG)
    assert result.candidates == []
    assert len(result.unmatched) == 1
    assert "product_key" in result.unmatched[0]["reason"].lower()


def test_replay_reads_embedded_pipeline_board(tmp_path):
    """A pipeline manifest carries deals under board.deals."""
    manifest = {"sweep_id": "2026-07-05-discovery", "candidates": 1,
                "board": {"deals": [_buyable_deal("Prismatic Evolutions Elite Trainer Box", 44.5)]}}
    path = tmp_path / "2026-07-05-discovery.manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = cand.load_and_replay(path, CATALOG)
    assert result.input_kind == "manifest_embedded_board"
    assert len(result.candidates) == 1 and result.candidates[0].entry_price == 44.5


# ---------------------------------------------------------------- replay: wrong file

def test_replay_manifest_without_deals_is_distinguished(tmp_path):
    """A bare sealed manifest has no deals array — must NOT read as '0 buyable'."""
    manifest = {"sweep_id": "2026-07-05-sealed", "counts": {"scanned": 5}}
    path = tmp_path / "2026-07-05-sealed.manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = cand.load_and_replay(path, CATALOG)
    assert result.input_kind == "manifest_no_deals"
    assert result.scanned == 0
    assert "sibling" in result.note.lower() or "board" in result.note.lower()


def test_replay_resolves_sibling_board(tmp_path):
    """Pointed at a sealed manifest, replay resolves the sibling <sweep_id>.json board."""
    sweep = "2026-07-05-sealed"
    (tmp_path / f"{sweep}.json").write_text(
        json.dumps({"deals": [_buyable_deal("Prismatic Evolutions Elite Trainer Box", 49.99)]}),
        encoding="utf-8")
    mpath = tmp_path / f"{sweep}.manifest.json"
    mpath.write_text(json.dumps({"sweep_id": sweep, "counts": {"scanned": 1}}), encoding="utf-8")
    result = cand.load_and_replay(mpath, CATALOG)
    assert result.input_kind == "manifest_sibling_board"
    assert len(result.candidates) == 1


# ---------------------------------------------------------------- real dormant proof

# ---------------------------------------------------------------- build_deps wire

def test_build_deps_defaults_candidate_for_from_ledger(tmp_path):
    """The live API wire: build_deps reads verified_candidates.jsonl and exposes a
    candidate_for that lights up matching products (dormant when the ledger empty)."""
    cpath = tmp_path / "verified_candidates.jsonl"
    cand.append_candidate(cpath, cand.make_candidate(
        source="manual_verified", product_key="pe_etb", entry_price=49.99,
        buy_url="https://shop/x", stock_status="verified_buyable", stock_evidence="e",
        stock_checked_at="2026-07-05", observed_at="2026-07-05", retailer="Example"))
    cfg = SimpleNamespace(products=CATALOG)
    deps = router.build_deps(cfg, candidates_path=cpath, ledger_path=tmp_path / "h.jsonl",
                             decisions_path=tmp_path / "d.jsonl", today="2026-07-05")
    got = deps.candidate_for("pe_etb", CATALOG["pe_etb"])
    assert got is not None and got["verified_price"] == 49.99
    assert deps.candidate_for("jt_bb", CATALOG["jt_bb"]) is None    # no candidate => dormant


def test_build_deps_empty_ledger_is_dormant(tmp_path):
    cfg = SimpleNamespace(products=CATALOG)
    deps = router.build_deps(cfg, candidates_path=tmp_path / "absent.jsonl",
                             ledger_path=tmp_path / "h.jsonl",
                             decisions_path=tmp_path / "d.jsonl", today="2026-07-05")
    assert deps.candidate_for("pe_etb", CATALOG["pe_etb"]) is None


def test_replay_real_sealed_board_is_dormant():
    """The actual 2026-07-03 sealed board: rows scanned, ZERO verified-buyable,
    every row blocked with a reason. This is the dormant state, not a failure."""
    board_path = Path("data/poke/2026-07-03-sealed.json")
    if not board_path.exists():
        import pytest
        pytest.skip("sealed board artifact not present")
    result = cand.load_and_replay(board_path, CATALOG)
    assert result.scanned >= 10                          # ~13 comped rows
    assert result.candidates == []                       # none buyable (buy_url empty)
    assert len(result.blocked) == result.scanned         # no silent drops
    reasons = " ".join(b["reason"] for b in result.blocked).lower()
    assert "buy_url" in reasons or "not verified-buyable" in reasons


# ---------------------------------------------------------------- CLI: candidate-add

def test_cli_candidate_add_writes_ledger(tmp_path, capsys):
    deps = _lab_deps(tmp_path)
    rc = lab.main(["candidate-add", "--product-key", "pe_etb", "--entry-price", "49.99",
                   "--buy-url", "https://shop.example/pe", "--stock-status", "verified_buyable",
                   "--evidence", "operator verified page price + stock",
                   "--source", "manual_verified", "--observed-at", "2026-07-05"], deps=deps)
    assert rc == 0
    capsys.readouterr()
    rows = cand.read_rows(deps.candidates_path)
    assert len(rows) == 1
    assert rows[0]["entry_verified"] is True and rows[0]["entry_price"] == 49.99


def test_cli_candidate_add_rejects_unknown_product(tmp_path, capsys):
    deps = _lab_deps(tmp_path)
    rc = lab.main(["candidate-add", "--product-key", "not_in_catalog", "--entry-price", "10",
                   "--buy-url", "u", "--stock-status", "verified_buyable",
                   "--evidence", "e"], deps=deps)
    assert rc == 1                                        # unmatched product reported, not written
    assert cand.read_rows(deps.candidates_path) == []


def test_cli_candidate_add_missing_evidence_is_non_entry(tmp_path, capsys):
    deps = _lab_deps(tmp_path)
    rc = lab.main(["candidate-add", "--product-key", "pe_etb", "--entry-price", "49.99",
                   "--stock-status", "unverifiable", "--source", "manual_verified"], deps=deps)
    assert rc == 0                                        # kept as an evidence row
    rows = cand.read_rows(deps.candidates_path)
    assert len(rows) == 1 and rows[0]["entry_verified"] is False and rows[0]["entry_price"] is None


# ---------------------------------------------------------------- CLI: from-manifest

def test_cli_candidates_from_manifest_appends(tmp_path, capsys):
    board = {"deals": [_buyable_deal("Prismatic Evolutions Elite Trainer Box", 49.99),
                       _blocked_deal("X", "unverifiable", "no adapter")]}
    mpath = tmp_path / "2026-07-05-discovery.json"
    mpath.write_text(json.dumps(board), encoding="utf-8")
    deps = _lab_deps(tmp_path)
    rc = lab.main(["candidates-from-manifest", "--manifest", str(mpath)], deps=deps)
    assert rc == 0
    out = capsys.readouterr().out
    assert "scanned" in out.lower()
    rows = cand.read_rows(deps.candidates_path)
    assert len(rows) == 1 and rows[0]["product_key"] == "pe_etb"


# ---------------------------------------------------------------- C.6 build_opportunities + record

def test_build_opportunities_with_candidate_computes_money(tmp_path):
    """Required test 6 — a verified candidate yields entry_price / net / ROI."""
    cand.append_candidate(_lab_deps(tmp_path).candidates_path, cand.make_candidate(
        source="manual_verified", product_key="pe_etb", entry_price=49.99,
        buy_url="https://x", stock_status="verified_buyable", stock_evidence="e",
        stock_checked_at="2026-07-05", observed_at="2026-07-05", retailer="Example"))
    deps = _lab_deps(tmp_path, cached={"pe_etb": _arb_comp_row()})
    opps = {o["product_key"]: o for o in lab.build_opportunities(deps, as_of="2026-07-05")}
    pe = opps["pe_etb"]
    assert pe["entry_price"] == 49.99
    assert pe["market_comp"] == 176.17
    assert pe["expected_net"] is not None and pe["expected_roi_pct"] is not None
    assert pe["trade_type"] == "sealed_retail_arbitrage"


def test_no_entry_price_never_paper_buy(tmp_path):
    """Required test 7 — no verified entry => never PAPER_BUY/LIVE (WATCH only)."""
    deps = _lab_deps(tmp_path, cached={"pe_etb": _arb_comp_row()})    # comp but no candidate
    opps = {o["product_key"]: o for o in lab.build_opportunities(deps, as_of="2026-07-05")}
    pe = opps["pe_etb"]
    assert pe["entry_price"] is None
    assert pe["decision_hint"] not in ("PAPER_BUY", "LIVE_PACKET_ELIGIBLE")


def test_cli_record_candidates_writes_decisions_with_snapshot(tmp_path, capsys):
    """Required test 9 — record-candidates writes decisions carrying input_snapshot."""
    deps = _lab_deps(tmp_path, cached={"pe_etb": _arb_comp_row()})
    cand.append_candidate(deps.candidates_path, cand.make_candidate(
        source="manual_verified", product_key="pe_etb", entry_price=49.99,
        buy_url="https://x", stock_status="verified_buyable", stock_evidence="operator verified",
        stock_checked_at="2026-07-05", observed_at="2026-07-05", retailer="Example"))
    rc = lab.main(["record-candidates"], deps=deps)
    assert rc == 0
    capsys.readouterr()
    decisions = pl.decisions(pl.read_rows(deps.decisions_path))
    assert len(decisions) == 1                            # only the candidate-backed product
    assert decisions[0]["product_key"] == "pe_etb"
    assert decisions[0]["input_snapshot"]["source"] == "manual_verified"


# ---------------------------------------------------------------- C.5 activation report

def test_activation_report_dormant_when_no_verified_candidates(tmp_path, capsys):
    """Required test 10 — report shows the dormant state honestly."""
    deps = _lab_deps(tmp_path, cached={"pe_etb": _arb_comp_row()})   # comp, but no candidates
    rc = lab.main(["candidates-report", "--json"], deps=deps)
    assert rc == 0
    rep = json.loads(capsys.readouterr().out)["activation"]
    assert rep["verified_candidates"] == 0
    assert rep["live_packet_eligible_count"] == 0
    assert rep["paper_buy_count"] == 0
    assert rep["dormant"] is True
    assert rep["no_entry_price_count"] == rep["products_seen"]
    assert "verified" in rep["why_no_live_packets"].lower()


def test_activation_report_shows_top_blockers(tmp_path, capsys):
    """Required test 11 — top blockers are surfaced and ranked."""
    deps = _lab_deps(tmp_path)                            # no comps, no candidates
    # add a parser_suspect evidence row so a candidate-side blocker shows too
    cand.append_candidate(deps.candidates_path, cand.make_candidate(
        source="manifest_replay", product_key="pe_etb", stock_status="parser_suspect",
        stock_evidence="no availability parsed", observed_at="2026-07-05"))
    rc = lab.main(["candidates-report", "--json"], deps=deps)
    assert rc == 0
    rep = json.loads(capsys.readouterr().out)["activation"]
    assert rep["parser_suspect_count"] == 1
    blockers = {b["blocker"]: b["count"] for b in rep["top_blockers"]}
    assert any("no_comp" in b or "entry" in b for b in blockers)
    assert rep["top_blockers"] == sorted(rep["top_blockers"], key=lambda b: -b["count"])


def test_report_include_candidates_adds_activation(tmp_path, capsys):
    deps = _lab_deps(tmp_path, cached={"pe_etb": _arb_comp_row()})
    rc = lab.main(["report", "--include-candidates", "--json"], deps=deps)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "signals" in out and "activation" in out
    assert out["activation"]["dormant"] is True
