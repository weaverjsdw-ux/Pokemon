"""Slice 6A - degraded source matrix.

Take each major source DOWN in turn and prove the pipeline tells the truth:
it completes, every candidate lands in an honest terminal bucket, the manifest
counts reconcile (``sum(counts) == candidates == outcomes``), and NO alert
fires off degraded or unverifiable evidence.

The six scenarios the operator named:
  1. eBay key missing        -> ebay_browse adapter NEEDS_API_KEY, 0 candidates
  2. adapter blocked         -> slickdeals HTTP 403 -> BLOCKED, 0 candidates
  3. parser suspect          -> (a) adapter drift (slickdeals) surfaced honestly
                                (b) verify PARSER_SUSPECT -> unverifiable bucket
  4. page unavailable        -> verify PAGE_UNAVAILABLE -> unverifiable bucket
  5. comp unavailable        -> comp error/no_match/raise -> no_comp bucket
  6. notifier unavailable    -> (a) real Notifier w/ dead channels completes
                                (b) a raising notifier never aborts the run

Piecewise coverage exists in test_poke_pipeline.py (adapter-exception,
non-alert-state suppression, comp-exception) and the adapter unit suites; this
module is the single consolidated matrix the runbook points at, and it adds the
two pipeline-level gaps: eBay-key-missing and notifier-unavailable.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
import requests

from scanner import config as cfg_mod
from scanner import notify as notify_mod
from scanner.discovery import pipeline, verify as verify_mod
from scanner.discovery.adapters.base import DiscoverySource
from scanner.discovery.adapters.ebay_browse import EbayBrowse
from scanner.discovery.adapters.slickdeals import Slickdeals
from scanner.discovery.candidates import CandidateDeal
from scanner.state import State

CATALOG = {"fake_etb": {"name": "Fake ETB", "set": "FakeSet", "type": "ETB", "msrp": "$49.99"}}
BUY_URL = "https://slickdeals.net/f/1-fake-etb"
COMP_URL = "https://www.pricecharting.com/game/pokemon-fake/fake-etb"
CHECKED = "2026-07-03T12:00:00+00:00"
NOON = datetime(2026, 7, 3, 12, 0, 0)


def _cfg():
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    cfg.products = dict(CATALOG)
    cfg.products_filter = None
    return cfg


def _candidate(listing_id="c1"):
    return CandidateDeal(
        source="slickdeals", listing_id=listing_id, item_name="Fake ETB sealed",
        price=50.0, shipping=None, url=BUY_URL, retailer="SomeStore",
        seen_at=CHECKED, evidence_excerpt="Fake ETB | $50.00",
        matched_product_key="fake_etb", matched_set="FakeSet")


def _verification(state, *, price=50.0):
    buyable = state == verify_mod.VERIFIED_BUYABLE
    return verify_mod.StockVerification(
        state=state, stock_status="in_stock" if buyable else "unverifiable",
        verified_price=price if buyable else None, expected_price=None,
        price_matches=None, buy_url=BUY_URL if buyable else "",
        checked_at=CHECKED, source="slickdeals", method="page_fetch",
        evidence="in stock $50" if buyable else "", degraded_reason="" if buyable else state)


def _comp_row():
    return {"status": "ok", "estimate": "$100.00", "confidence": "high",
            "source": "PriceCharting", "basis": "ungraded market",
            "compBasis": "pricecharting sold-derived", "sourceUrl": COMP_URL, "url": COMP_URL}


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def send_deal(self, deal, *, push):
        self.calls.append((deal, push))


class FakeSource(DiscoverySource):
    def __init__(self, slug, candidates):
        super().__init__()
        self.slug = slug
        self.min_interval_seconds = 0
        self._candidates = candidates

    def discover(self, cfg, catalog, set_watch, **kwargs):
        self._set_state("WORKING", f"{len(self._candidates)} candidates")
        return list(self._candidates)


def _reconciles(m):
    counts = m["counts"]
    return sum(counts.values()) == m["candidates"] == len(m["outcomes"])


def _run(sources, *, verifier, comp_lookup=None, notifier=None, state,
         http_get=None, now_dt=NOON):
    notifier = notifier or FakeNotifier()
    m = pipeline.run_once(
        _cfg(), sources=sources, verifier=verifier,
        comp_lookup=comp_lookup or (lambda c, p: _comp_row()),
        notifier=notifier, state=state, catalog=dict(CATALOG),
        now_ts=1_000_000, now_dt=now_dt, http_get=http_get)
    return m, notifier


# ------------------------------------------------------- 1. eBay key missing

def test_ebay_key_missing_degrades_to_needs_api_key(tmp_path):
    st = State(db_path=tmp_path / "s.db")
    # real adapter, no keyset in cfg -> NEEDS_API_KEY, zero candidates, no network
    m, notifier = _run([EbayBrowse()], verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
                       state=st)
    assert m["candidates"] == 0 and _reconciles(m)
    report = next(s for s in m["sources"] if s["slug"] == "ebay_browse")
    assert report["state"] == "NEEDS_API_KEY"
    assert notifier.calls == []                     # nothing to alert; nothing pushed


# ------------------------------------------------------- 2. adapter blocked

def test_adapter_blocked_is_honest_and_alertless(tmp_path):
    st = State(db_path=tmp_path / "s.db")
    blocked = lambda url, **kw: SimpleNamespace(status_code=403, text="")
    m, notifier = _run([Slickdeals()], verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
                       state=st, http_get=blocked)
    assert m["candidates"] == 0 and _reconciles(m)
    report = next(s for s in m["sources"] if s["slug"] == "slickdeals")
    assert report["state"] == "BLOCKED"
    assert notifier.calls == []


# ------------------------------------------------------- 3. parser suspect

def test_adapter_parser_suspect_surfaced_not_hidden(tmp_path):
    """Slickdeals inner-markup drift (cards present, no title parsed) must reach
    the manifest as PARSER_SUSPECT, never a silent WORKING/empty."""
    st = State(db_path=tmp_path / "s.db")
    from pathlib import Path
    populated = Path("tests/fixtures/discovery/slickdeals_search_populated.html").read_text(
        encoding="utf-8")
    gutted = populated.replace("dealCardListView__title", "dealCardListView__headline")
    m, notifier = _run([Slickdeals()], verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
                       state=st, http_get=lambda url, **kw: SimpleNamespace(status_code=200, text=gutted))
    assert m["candidates"] == 0 and _reconciles(m)
    report = next(s for s in m["sources"] if s["slug"] == "slickdeals")
    assert report["state"] == "PARSER_SUSPECT"
    assert notifier.calls == []


def test_verify_parser_suspect_lands_unverifiable(tmp_path):
    st = State(db_path=tmp_path / "s.db")
    m, notifier = _run([FakeSource("s", [_candidate()])],
                       verifier=lambda c: _verification(verify_mod.PARSER_SUSPECT), state=st)
    assert m["counts"]["unverifiable"] == 1 and m["counts"]["alerted"] == 0
    assert _reconciles(m) and notifier.calls == []


# ------------------------------------------------------- 4. page unavailable

def test_page_unavailable_lands_unverifiable(tmp_path):
    st = State(db_path=tmp_path / "s.db")
    m, notifier = _run([FakeSource("s", [_candidate()])],
                       verifier=lambda c: _verification(verify_mod.PAGE_UNAVAILABLE), state=st)
    assert m["counts"]["unverifiable"] == 1 and m["counts"]["alerted"] == 0
    assert _reconciles(m) and notifier.calls == []


# ------------------------------------------------------- 5. comp unavailable

@pytest.mark.parametrize("comp_lookup", [
    lambda c, p: {"status": "no_match"},
    lambda c, p: {"status": "error", "detail": "all comp sources down"},
    pytest.param(lambda c, p: (_ for _ in ()).throw(RuntimeError("comp boom")),
                 id="comp-raises"),
])
def test_comp_unavailable_is_no_comp_never_alert(tmp_path, comp_lookup):
    st = State(db_path=tmp_path / "s.db")
    m, notifier = _run([FakeSource("s", [_candidate()])],
                       verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
                       comp_lookup=comp_lookup, state=st)
    assert m["counts"]["no_comp"] == 1 and m["counts"]["alerted"] == 0
    assert _reconciles(m) and notifier.calls == []


# ------------------------------------------------------- 6. notifier unavailable

def test_notifier_dead_channels_still_completes(tmp_path, monkeypatch):
    """The realistic failure: Discord/ntfy are configured but the network is
    down. The real Notifier swallows RequestException per channel, so the run
    completes, the board is built, and the alert still counts."""
    st = State(db_path=tmp_path / "s.db")

    def dead_post(*a, **k):
        raise requests.ConnectionError("channel down")

    monkeypatch.setattr(notify_mod.requests, "post", dead_post)
    real = notify_mod.Notifier("https://discord.test/hook", "topic")
    m, _ = _run([FakeSource("s", [_candidate()])],
                verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
                notifier=real, state=st)
    assert m["counts"]["alerted"] == 1 and _reconciles(m)
    assert len(m["board"]["deals"]) == 1              # board built despite dead channels


def test_raising_notifier_never_aborts_the_run(tmp_path):
    """Belt hardening: even a notifier that raises an unexpected (non-Request)
    exception must not crash the pipeline or lose the board. The candidate still
    counts as alerted, the run reconciles, and the dedupe baseline is NOT written
    so the next run re-attempts delivery (no permanent silent loss)."""
    st = State(db_path=tmp_path / "s.db")

    class BoomNotifier:
        def send_deal(self, deal, *, push):
            raise RuntimeError("notifier exploded")

    m, _ = _run([FakeSource("s", [_candidate()])],
                verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
                notifier=BoomNotifier(), state=st)
    assert m["counts"]["alerted"] == 1 and _reconciles(m)
    assert len(m["board"]["deals"]) == 1
    # not recorded -> re-fires next run
    assert st.db.execute("SELECT COUNT(*) FROM deal_alerts").fetchone()[0] == 0
    outcome = m["outcomes"][0]
    assert outcome["terminal"] == "alerted" and "notify" in outcome["reason"].lower()
