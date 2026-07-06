"""Session E Slice G — edge CLI (list / show / record / outcome / divergence-audit).

Deps injected; record/outcome append to a tmp paper-decisions ledger (idempotent);
divergence-audit --local spends 0 credits and external refuses without --yes."""
from __future__ import annotations

import json

from scanner import config as cfg_mod
from scanner.poke_api import candidates as cand
from scanner.poke_api import edge_cli, gem_rates, paper_ledger, router


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


# ------------------------------------------ record-asset-comp --refresh-independent
#
# 0-PPT-credit live fetch from the independent (PriceCharting/TCGplayer) sources,
# gated on poke.independent_sources; persisted with the ACTUAL source slug (never
# ppt_cards). ``_deps_indep`` mirrors ``_deps`` above but injects the raw/graded
# asset catalog + a tmp ledger + the independent-sources gate, matching the style of
# tests/test_poke_asset_comp_record.py's direct ``router.PokeApiDeps(...)`` builder.

class _FailingCardClient:
    """Any billed method is a test failure — proves _record_independent never touches
    the PPT client (0-PPT-credit invariant), even when one happens to be configured."""

    def raw_quote(self, asset, checked_at):
        raise AssertionError("--refresh-independent must not call the PPT card client")

    def graded_smart(self, asset, checked_at):
        raise AssertionError("--refresh-independent must not call the PPT card client")


def _deps_indep(*, assets, ledger_path, today="2026-07-06", independent_sources):
    cfg = cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "poke": {"independent_sources": independent_sources},
    })
    return router.PokeApiDeps(
        products={}, assets=assets, read_observations=lambda: [],
        comp_provider=FakeProvider({}), today=today, cfg=cfg, ledger_path=ledger_path,
        card_client=_FailingCardClient())


_RAW_ASSET = {"asset_class": "raw", "name": "Umbreon ex 161", "set": "Prismatic Evolutions",
              "condition": "NM",
              "pricecharting_slug": "pokemon-prismatic-evolutions/umbreon-ex-161"}


def test_refresh_independent_persists_pricecharting_slug(tmp_path, monkeypatch):
    from scanner.poke_api import sources as sources_mod

    ledger = tmp_path / "price_history.jsonl"
    deps = _deps_indep(assets={"umb": _RAW_ASSET}, ledger_path=ledger, independent_sources=True)

    # Stub the resolver so the test never hits the network. Mirrors the RAW-path shape:
    # sources[] lists the blocked tcgplayer quote FIRST, pricecharting (the actual
    # comp source) second — proving _record_independent uses _row_ok_source, not the
    # naive first-listed-source picker.
    monkeypatch.setattr(
        sources_mod, "resolve_independent_asset_row",
        lambda a, **k: {
            "estimate": "1425.00", "confidence": "low",
            "sources": [{"source": "tcgplayer", "status": "blocked", "price": None},
                       {"source": "pricecharting", "status": "ok", "price": 1425.00}],
            "sourceUrl": "https://www.pricecharting.com/game/x",
            "compBasis": "PriceCharting Ungraded"})

    rc = edge_cli.main(
        ["record-asset-comp", "--asset-key", "umb", "--refresh-independent"], deps=deps)
    assert rc == 0
    rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    assert rows and rows[0]["source"] == "pricecharting"      # never ppt_cards/tcgplayer
    assert rows[0]["comp"] == 1425.00 and rows[0]["comp_confidence"] == "low"


def test_refresh_independent_refuses_when_gate_off(tmp_path):
    ledger = tmp_path / "price_history.jsonl"
    deps = _deps_indep(assets={"umb": _RAW_ASSET}, ledger_path=ledger, independent_sources=False)
    rc = edge_cli.main(
        ["record-asset-comp", "--asset-key", "umb", "--refresh-independent"], deps=deps)
    assert rc == 2                                            # refused: gate off
    assert not ledger.exists()


def test_refresh_independent_no_usable_comp_records_nothing(tmp_path, monkeypatch):
    from scanner.poke_api import sources as sources_mod

    ledger = tmp_path / "price_history.jsonl"
    deps = _deps_indep(assets={"umb": _RAW_ASSET}, ledger_path=ledger, independent_sources=True)
    monkeypatch.setattr(
        sources_mod, "resolve_independent_asset_row",
        lambda a, **k: {"estimate": "", "confidence": "none", "sources": []})

    rc = edge_cli.main(
        ["record-asset-comp", "--asset-key", "umb", "--refresh-independent"], deps=deps)
    assert rc == 1
    assert not ledger.exists()


def test_refresh_independent_refuses_ebay_only_source(tmp_path, monkeypatch):
    """An ask-only ebay slug is never a sold comp; the independent path has no
    ppt_cards fallback to fall back to, so it must refuse rather than mislabel it."""
    from scanner.poke_api import sources as sources_mod

    ledger = tmp_path / "price_history.jsonl"
    deps = _deps_indep(assets={"umb": _RAW_ASSET}, ledger_path=ledger, independent_sources=True)
    monkeypatch.setattr(
        sources_mod, "resolve_independent_asset_row",
        lambda a, **k: {"estimate": "12.00", "confidence": "low",
                        "sources": [{"source": "ebay", "status": "ok", "price": 12.00}]})

    rc = edge_cli.main(
        ["record-asset-comp", "--asset-key", "umb", "--refresh-independent"], deps=deps)
    assert rc == 1
    assert not ledger.exists()


# ------------------------------------------ gem-rate ledger CLI (Phase G)
#
# `gem-rate record` captures a SOURCED gem rate from PriceCharting population (0 PPT
# credits — the pop path never constructs a PPT client), gated on
# poke.independent_sources + --yes. `record-assumption`/`list`/`show` are network-free.

_UMBREON_PSA = [1, 2, 4, 15, 43, 161, 428, 2654, 9195, 5487]
_POP_OK = {"status": "ok",
           "pop": {"psa": _UMBREON_PSA, "cgc": [0, 0, 0, 1, 0, 2, 16, 122, 259, 366]},
           "graders": ["psa", "cgc"],
           "url": "https://www.pricecharting.com/game/x/umbreon-ex-161",
           "number": "161", "detail": "", "fetched_at": "2026-07-06T00:00:00"}

_GEM_ASSET = {"asset_class": "raw", "name": "Umbreon ex 161", "set": "Prismatic Evolutions",
              "condition": "NM", "card_number": "161",
              "pricecharting_slug": "pokemon-prismatic-evolutions/umbreon-ex-161"}


def _deps_gem(*, assets, gem_rates_path, independent_sources, today="2026-07-06"):
    cfg = cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "poke": {"independent_sources": independent_sources}})
    return router.PokeApiDeps(
        products={}, assets=assets, read_observations=lambda: [],
        comp_provider=FakeProvider({}), today=today, cfg=cfg,
        gem_rates_path=gem_rates_path, card_client=_FailingCardClient())


def _stub_pop(monkeypatch, result):
    from scanner.poke_api import independent_sources as indep
    monkeypatch.setattr(indep.PriceChartingPopSource, "fetch_pop",
                        lambda self, a, ts: dict(result))


def test_gem_rate_record_gate_off_refuses(tmp_path):
    path = tmp_path / "gem_rates.jsonl"
    deps = _deps_gem(assets={"umb": _GEM_ASSET}, gem_rates_path=path, independent_sources=False)
    rc = edge_cli.main(["gem-rate", "record", "--asset-key", "umb",
                        "--source", "pricecharting", "--yes"], deps=deps)
    assert rc == 2
    assert not path.exists()


def test_gem_rate_record_without_yes_refuses(tmp_path):
    path = tmp_path / "gem_rates.jsonl"
    deps = _deps_gem(assets={"umb": _GEM_ASSET}, gem_rates_path=path, independent_sources=True)
    rc = edge_cli.main(["gem-rate", "record", "--asset-key", "umb",
                        "--source", "pricecharting"], deps=deps)
    assert rc == 2
    assert not path.exists()


def test_gem_rate_record_sourced_writes_row_zero_credits(tmp_path, monkeypatch, capsys):
    path = tmp_path / "gem_rates.jsonl"
    deps = _deps_gem(assets={"umb": _GEM_ASSET}, gem_rates_path=path, independent_sources=True)
    _stub_pop(monkeypatch, _POP_OK)
    rc = edge_cli.main(["gem-rate", "record", "--asset-key", "umb",
                        "--source", "pricecharting", "--yes"], deps=deps)
    assert rc == 0
    assert "credits_spent=0" in capsys.readouterr().out
    rows = gem_rates.read_rows(path)
    assert len(rows) == 1
    assert rows[0]["label"] == "sourced" and rows[0]["grader"] == "PSA"
    assert rows[0]["source"] == "pricecharting_pop"
    assert rows[0]["sample_size"] == 17990


def test_gem_rate_record_never_constructs_ppt_client(tmp_path, monkeypatch):
    # _FailingCardClient raises on any billed call; a green run proves the pop path
    # never touched the PPT client (0-PPT-credit invariant).
    path = tmp_path / "gem_rates.jsonl"
    deps = _deps_gem(assets={"umb": _GEM_ASSET}, gem_rates_path=path, independent_sources=True)
    _stub_pop(monkeypatch, _POP_OK)
    assert edge_cli.main(["gem-rate", "record", "--asset-key", "umb",
                          "--source", "pricecharting", "--yes"], deps=deps) == 0


def test_gem_rate_record_below_floor_blocks_no_write(tmp_path, monkeypatch, capsys):
    small = {**_POP_OK, "pop": {"psa": [0, 0, 0, 0, 0, 0, 1, 2, 40, 30]}}  # total 73 < 300
    path = tmp_path / "gem_rates.jsonl"
    deps = _deps_gem(assets={"umb": _GEM_ASSET}, gem_rates_path=path, independent_sources=True)
    _stub_pop(monkeypatch, small)
    rc = edge_cli.main(["gem-rate", "record", "--asset-key", "umb",
                        "--source", "pricecharting", "--yes"], deps=deps)
    assert rc == 1
    assert "credits_spent=0" in capsys.readouterr().out
    assert gem_rates.read_rows(path) == []                    # never a guessed sourced row


def test_gem_rate_record_grader_absent_blocks(tmp_path, monkeypatch, capsys):
    only_psa = {**_POP_OK, "pop": {"psa": _UMBREON_PSA}, "graders": ["psa"]}
    path = tmp_path / "gem_rates.jsonl"
    deps = _deps_gem(assets={"umb": _GEM_ASSET}, gem_rates_path=path, independent_sources=True)
    _stub_pop(monkeypatch, only_psa)
    rc = edge_cli.main(["gem-rate", "record", "--asset-key", "umb", "--grader", "CGC",
                        "--source", "pricecharting", "--yes"], deps=deps)
    assert rc == 1
    assert "credits_spent=0" in capsys.readouterr().out
    assert gem_rates.read_rows(path) == []


def test_gem_rate_record_rejects_non_pricecharting_source(tmp_path):
    path = tmp_path / "gem_rates.jsonl"
    deps = _deps_gem(assets={"umb": _GEM_ASSET}, gem_rates_path=path, independent_sources=True)
    rc = edge_cli.main(["gem-rate", "record", "--asset-key", "umb",
                        "--source", "ppt", "--yes"], deps=deps)
    assert rc == 1
    assert not path.exists()


def test_gem_rate_record_assumption_no_network(tmp_path):
    path = tmp_path / "gem_rates.jsonl"
    # gate OFF: an operator assumption never fetches, so it records regardless of the gate.
    deps = _deps_gem(assets={"umb": _GEM_ASSET}, gem_rates_path=path, independent_sources=False)
    rc = edge_cli.main(["gem-rate", "record-assumption", "--asset-key", "umb", "--grader", "PSA",
                        "--gem-rate", "0.30", "--basis", "operator base rate for modern SIR"],
                       deps=deps)
    assert rc == 0
    rows = gem_rates.read_rows(path)
    assert rows and rows[0]["label"] == "operator_assumption" and rows[0]["gem_rate"] == 0.30


def test_gem_rate_list_and_show_are_ledger_only(tmp_path, capsys):
    path = tmp_path / "gem_rates.jsonl"
    gem_rates.record_assumption(path, asset_key="umb", grader="PSA", gem_rate=0.30,
                                basis="x", capture_date="2026-07-06")
    gem_rates.record_assumption(path, asset_key="other", grader="PSA", gem_rate=0.25,
                                basis="y", capture_date="2026-07-06")
    # _FailingCardClient in deps: a green run proves list/show never reach a billed source.
    deps = _deps_gem(assets={"umb": _GEM_ASSET}, gem_rates_path=path, independent_sources=True)
    assert edge_cli.main(["gem-rate", "list"], deps=deps) == 0
    out = capsys.readouterr().out
    assert "umb" in out and "other" in out
    assert edge_cli.main(["gem-rate", "show", "--asset-key", "umb"], deps=deps) == 0
    out2 = capsys.readouterr().out
    assert "umb" in out2 and "other" not in out2
