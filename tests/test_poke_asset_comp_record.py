"""Post-Session-E gate — persisted raw/graded asset comps for the edge audit.

The D.5 refresh path computes a raw/graded comp row but never persists it, so the
read-first ledger (and the divergence audit's ``ours``) had nothing to serve —
raw/graded rows came back ``ours: null``. This suite drives the fix: a
provenance-honest ``market_comp`` writer (``sources.record_asset_comp`` +
``build_asset_comp_observation``) and a ``record-asset-comp`` edge CLI command
(0-credit from-value default; operator-gated billed ``--refresh``).

STOP-class invariants under test:
* the persisted observation's ``item_key`` byte-matches ``item_key_for_asset`` (else
  read-first silently keeps returning null — the whole fix fails without an error);
* read endpoints serve the persisted comp at **0 credits** (never a billed call);
* a fabricated/ask-only/no-price comp is refused, never recorded;
* after persisting, the edge packet carries ``comp_provenance`` (not ``missing_comp``)
  and the external divergence audit compares numeric ``ours`` vs external.

No live calls: the billed ``--refresh`` path is exercised with injected fake clients.
"""
from __future__ import annotations

import pytest

from scanner import config as cfg_mod
from scanner.poke_api import (
    divergence as dv,
    edge as edge_mod,
    edge_cli,
    history,
    router,
    sources,
)

# Normalized loaded-asset shapes (graded carries the derived grade_key, exactly as
# catalog.load_assets emits) so item_key construction matches the served catalog.
RAW_NM = {"asset_class": "raw", "name": "Umbreon ex 161", "set": "Prismatic Evolutions",
          "card_number": "161", "condition": "NM", "tcgplayer_id": "610516"}
PSA10 = {"asset_class": "graded", "name": "Umbreon ex 161", "set": "Prismatic Evolutions",
         "card_number": "161", "grader": "PSA", "grade": "10", "grade_key": "psa10",
         "tcgplayer_id": "610516"}
ASSETS = {"umbreon_ex_161_raw_nm": RAW_NM, "umbreon_ex_161_psa10": PSA10}


def _cfg():
    return cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})


class _StubProvider:
    def cached(self, key, product):
        return None

    def estimate(self, key, product):
        return {}


class _FailingCardClient:
    """Any billed method is a test failure — proves read paths never touch a provider."""
    def raw_quote(self, asset, checked_at):
        raise AssertionError("read path must not call the external card client")

    def graded_smart(self, asset, checked_at):
        raise AssertionError("read path must not call the external card client")


def _deps(ledger_path, *, card_client=None, today="2026-07-05"):
    return router.PokeApiDeps(
        products={}, assets=ASSETS,
        read_observations=lambda: history.read_ledger(ledger_path).observations,
        comp_provider=_StubProvider(), today=today, cfg=_cfg(),
        card_client=card_client, ledger_path=ledger_path)


# ---------------------------------------------------------------- builder / writer

def test_build_observation_item_key_matches_raw(tmp_path):
    ledger = tmp_path / "price_history.jsonl"
    sources.record_asset_comp(ledger, RAW_NM, comp=1528.09, confidence="low",
                              source="ppt_cards", capture_date="2026-07-05",
                              asset_key="umbreon_ex_161_raw_nm")
    rec = history.read_ledger(ledger).observations[-1]
    assert rec["item_key"] == history.item_key_for_asset(RAW_NM)


def test_build_observation_item_key_matches_graded(tmp_path):
    ledger = tmp_path / "price_history.jsonl"
    sources.record_asset_comp(ledger, PSA10, comp=6925.5, confidence="high",
                              source="ppt_cards", capture_date="2026-07-05",
                              asset_key="umbreon_ex_161_psa10")
    rec = history.read_ledger(ledger).observations[-1]
    assert rec["item_key"] == history.item_key_for_asset(PSA10)
    assert "psa10" in rec["item_key"]        # grade slot filled (not a sealed-shaped key)


def test_recorded_observation_carries_full_provenance(tmp_path):
    ledger = tmp_path / "price_history.jsonl"
    sources.record_asset_comp(ledger, RAW_NM, comp=1528.09, confidence="low",
                              source="ppt_cards", capture_date="2026-07-05",
                              source_url="https://tcg/x", basis="external smart price",
                              asset_key="umbreon_ex_161_raw_nm")
    rec = history.read_ledger(ledger).observations[-1]
    assert rec["kind"] == "market_comp"
    assert rec["comp"] == 1528.09
    assert rec["comp_confidence"] == "low"
    assert rec["source"] == "ppt_cards"
    assert rec["capture_date"] == "2026-07-05"
    assert rec["asset_key"] == "umbreon_ex_161_raw_nm"
    assert rec["asset_class"] == "raw"
    assert rec["source_url"] == "https://tcg/x"


def test_record_refuses_missing_or_nonpositive_comp(tmp_path):
    ledger = tmp_path / "price_history.jsonl"
    for bad in (None, 0, -5, "", "n/a"):
        with pytest.raises(ValueError):
            sources.record_asset_comp(ledger, RAW_NM, comp=bad, confidence="low",
                                      source="ppt_cards", capture_date="2026-07-05")
    assert not ledger.exists()               # nothing fabricated to disk


def test_record_refuses_ask_only_source(tmp_path):
    """An active eBay ask is context, never sold-comp truth — must be refused."""
    ledger = tmp_path / "price_history.jsonl"
    with pytest.raises(ValueError):
        sources.record_asset_comp(ledger, RAW_NM, comp=1500.0, confidence="low",
                                  source="ebay", capture_date="2026-07-05")


def test_record_is_idempotent_same_source_and_date(tmp_path):
    ledger = tmp_path / "price_history.jsonl"
    first = sources.record_asset_comp(ledger, RAW_NM, comp=1528.09, confidence="low",
                                      source="ppt_cards", capture_date="2026-07-05")
    again = sources.record_asset_comp(ledger, RAW_NM, comp=1528.09, confidence="low",
                                      source="ppt_cards", capture_date="2026-07-05")
    assert first is True and again is False
    assert len(history.read_ledger(ledger).observations) == 1


# ---------------------------------------------------------------- read path (0 credits)

def test_read_path_serves_persisted_raw_comp_zero_credits(tmp_path):
    ledger = tmp_path / "price_history.jsonl"
    sources.record_asset_comp(ledger, RAW_NM, comp=1528.09, confidence="low",
                              source="ppt_cards", capture_date="2026-07-05",
                              asset_key="umbreon_ex_161_raw_nm")
    payload = router.handle_get("/api/poke/assets/umbreon_ex_161_raw_nm/comp", {},
                                _deps(ledger, card_client=_FailingCardClient()))
    assert payload["estimate"] == 1528.09
    assert payload["status"] == "ok"
    assert payload["metadata"]["apiCallsConsumed"]["total"] == 0
    assert payload["metadata"]["source"] == "local"


def test_read_path_serves_persisted_graded_comp_zero_credits(tmp_path):
    ledger = tmp_path / "price_history.jsonl"
    sources.record_asset_comp(ledger, PSA10, comp=6925.5, confidence="high",
                              source="ppt_cards", capture_date="2026-07-05",
                              asset_key="umbreon_ex_161_psa10")
    payload = router.handle_get("/api/poke/assets/umbreon_ex_161_psa10/comp", {},
                                _deps(ledger, card_client=_FailingCardClient()))
    assert payload["estimate"] == 6925.5
    assert payload["metadata"]["apiCallsConsumed"]["total"] == 0


def test_read_endpoint_never_calls_billed_client_after_persist(tmp_path):
    """The read invariant end to end: a persisted comp is served from the ledger with
    a FailingCardClient injected — any billed call raises, so a green run proves 0."""
    ledger = tmp_path / "price_history.jsonl"
    sources.record_asset_comp(ledger, RAW_NM, comp=1528.09, confidence="low",
                              source="ppt_cards", capture_date="2026-07-05",
                              asset_key="umbreon_ex_161_raw_nm")
    deps = _deps(ledger, card_client=_FailingCardClient())
    # comp, history, momentum, /cards, edge-packets: all read-first, none billed
    router.handle_get("/api/poke/assets/umbreon_ex_161_raw_nm/comp", {}, deps)
    router.handle_get("/api/poke/cards", {"tcgPlayerId": "610516", "condition": "NM"}, deps)
    router.handle_get("/api/poke/edge-packets", {}, deps)   # would raise if it billed


# ---------------------------------------------------------------- edge provenance

def _packet(deps, subject_key):
    for p in edge_mod.build_edge_packets(deps, as_of=deps.today):
        if p["subject_key"] == subject_key:
            return p
    raise AssertionError(f"no packet for {subject_key}")


def test_edge_packet_shows_comp_provenance_after_record(tmp_path):
    ledger = tmp_path / "price_history.jsonl"
    deps = _deps(ledger, card_client=_FailingCardClient())
    before = _packet(deps, "umbreon_ex_161_psa10")
    assert before["comp_provenance"] is None
    assert "missing_comp" in (before["source_posture"] or [])

    sources.record_asset_comp(ledger, PSA10, comp=6925.5, confidence="high",
                              source="ppt_cards", capture_date="2026-07-05",
                              asset_key="umbreon_ex_161_psa10")
    after = _packet(deps, "umbreon_ex_161_psa10")
    assert after["comp_provenance"] is not None
    assert after["comp_provenance"]["estimate"] == 6925.5
    assert after["comp_provenance"]["primary_source"] == "ppt_cards"
    assert "missing_comp" not in (after["source_posture"] or [])
    assert "external_only" in (after["source_posture"] or [])


# --------------------------------------------- divergence: numeric ours vs external

class _FakeAssetClient:
    """Injected external client for divergence external mode (no live call)."""
    def raw_quote(self, asset, checked_at):
        from scanner.comps.model import SOLD_DERIVED, CompSourceQuote
        return CompSourceQuote("ppt_cards", SOLD_DERIVED, "ok", 1541.0, "https://tcg/x",
                               "2026-07-05")

    def graded_smart(self, asset, checked_at):
        return sources.GradedSmartPrice(6950.0, "high", "https://tcg/x", "psa10")


def test_external_divergence_compares_numeric_ours_vs_external(tmp_path):
    """After persisting, the external audit's ``ours`` is a number (not null): it
    compares the persisted comp against a fresh (injected) external call."""
    ledger = tmp_path / "price_history.jsonl"
    sources.record_asset_comp(ledger, RAW_NM, comp=1528.09, confidence="low",
                              source="ppt_cards", capture_date="2026-07-05",
                              asset_key="umbreon_ex_161_raw_nm")
    deps = _deps(ledger)
    deps.cfg.market_api_key = "k"
    result = dv.run_audit(deps, asset_keys=["umbreon_ex_161_raw_nm"], local=False,
                          yes=True, client_asset=_FakeAssetClient())
    row = result["rows"][0]
    assert row["ours"] == 1528.09            # numeric, not None
    assert row["theirs"] == 1541.0
    assert row["category"] == "agree"        # ~0.8% delta, within tolerance
    assert result["failed"] is False


# ---------------------------------------------------------------- CLI

class _FakeGradedClient:
    def raw_quote(self, asset, checked_at):
        raise AssertionError("graded path must not raw_quote")

    def graded_smart(self, asset, checked_at):
        return sources.GradedSmartPrice(6925.5, "high", "https://tcg/x", "psa10")


def test_cli_record_from_value_zero_credits(tmp_path, capsys):
    ledger = tmp_path / "price_history.jsonl"
    deps = _deps(ledger, card_client=_FailingCardClient())
    rc = edge_cli.main(["record-asset-comp", "--asset-key", "umbreon_ex_161_raw_nm",
                        "--comp", "1528.09", "--source", "ppt_cards",
                        "--confidence", "low", "--capture-date", "2026-07-05"], deps=deps)
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "0 credit" in out
    rec = history.read_ledger(ledger).observations[-1]
    assert rec["comp"] == 1528.09 and rec["source"] == "ppt_cards"


def test_cli_record_unknown_asset_nonzero(tmp_path, capsys):
    deps = _deps(tmp_path / "price_history.jsonl")
    rc = edge_cli.main(["record-asset-comp", "--asset-key", "nope", "--comp", "1",
                        "--source", "ppt_cards"], deps=deps)
    assert rc == 1
    assert "nope" in capsys.readouterr().out


def test_cli_record_from_value_needs_comp_and_source(tmp_path, capsys):
    deps = _deps(tmp_path / "price_history.jsonl")
    rc = edge_cli.main(["record-asset-comp", "--asset-key", "umbreon_ex_161_raw_nm"],
                       deps=deps)
    assert rc == 1                            # missing --comp/--source, nothing billed


def test_cli_billed_refresh_refuses_without_yes(tmp_path, capsys):
    ledger = tmp_path / "price_history.jsonl"
    deps = _deps(ledger, card_client=_FakeGradedClient())
    rc = edge_cli.main(["record-asset-comp", "--asset-key", "umbreon_ex_161_psa10",
                        "--refresh"], deps=deps)
    assert rc == 2                            # money-class refusal
    out = capsys.readouterr().out
    assert "--yes" in out and "credit" in out.lower()
    assert not ledger.exists()                # refused before any write


def test_cli_billed_refresh_persists_and_reports_credits(tmp_path, capsys):
    ledger = tmp_path / "price_history.jsonl"
    deps = _deps(ledger, card_client=_FakeGradedClient())
    rc = edge_cli.main(["record-asset-comp", "--asset-key", "umbreon_ex_161_psa10",
                        "--refresh", "--yes"], deps=deps)
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "2 credit" in out                  # graded billed 2 (includeEbay +1)
    rec = history.read_ledger(ledger).observations[-1]
    assert rec["comp"] == 6925.5 and rec["source"] == "ppt_cards"
    assert rec["item_key"] == history.item_key_for_asset(PSA10)


class _DegradingClient:
    """A configured client whose billed lookup returns no usable price (honest degrade)."""
    def raw_quote(self, asset, checked_at):
        from scanner.comps.model import SOLD_DERIVED, CompSourceQuote
        return CompSourceQuote("ppt_cards", SOLD_DERIVED, "error", None, "",
                               "2026-07-05", detail="401")

    def graded_smart(self, asset, checked_at):
        return None


def test_cli_billed_refresh_no_price_records_nothing(tmp_path, capsys):
    """A billed refresh that yields no usable comp must NOT persist a null/fabricated
    row — it degrades honestly (read path stays a genuine none)."""
    ledger = tmp_path / "price_history.jsonl"
    deps = _deps(ledger, card_client=_DegradingClient())
    rc = edge_cli.main(["record-asset-comp", "--asset-key", "umbreon_ex_161_raw_nm",
                        "--refresh", "--yes"], deps=deps)
    assert rc == 1                            # nothing usable recorded
    assert not ledger.exists()
    read = router.handle_get("/api/poke/assets/umbreon_ex_161_raw_nm/comp", {},
                             _deps(ledger))
    assert read["estimate"] is None           # honest none, not a fabricated number


# ---------------------------------------------------------------- deps wiring

def test_build_deps_exposes_ledger_path():
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    deps = router.build_deps(cfg, today="2026-07-05")
    assert deps.ledger_path is not None
    assert str(deps.ledger_path).endswith("price_history.jsonl")
