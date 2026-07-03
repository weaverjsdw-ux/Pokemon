"""Slice-4 discovery pipeline: DISCOVER -> VERIFY -> COMP -> DEDUPE -> ALERT.

All stages injected (fake adapters/verifier/comp/notifier); no live network.
The load-bearing invariant: no alert without a fresh same-run StockVerification
passing verify.assert_alertable, and no silent candidate drops (counts
reconcile).
"""
from __future__ import annotations

from datetime import datetime

import pytest

from scanner import config as cfg_mod
from scanner.discovery import pipeline, verify as verify_mod
from scanner.discovery.adapters.base import DiscoverySource
from scanner.discovery.candidates import CandidateDeal
from scanner.state import State

CATALOG = {"fake_etb": {"name": "Fake ETB", "set": "FakeSet", "type": "ETB",
                        "msrp": "$49.99"}}
COMP_URL = "https://www.pricecharting.com/game/pokemon-fake/fake-etb"
BUY_URL = "https://slickdeals.net/f/1-fake-etb"
CHECKED = "2026-07-03T12:00:00+00:00"
NOON = datetime(2026, 7, 3, 12, 0, 0)     # outside default quiet hours
NIGHT = datetime(2026, 7, 3, 2, 0, 0)     # inside 23:00-08:00


def _cfg(**disc):
    raw = {"locations": {"home": "A", "work": "B"}}
    if disc:
        raw["discovery"] = disc
    cfg = cfg_mod.from_mapping(raw)
    cfg.products = dict(CATALOG)
    cfg.products_filter = None
    return cfg


def _candidate(listing_id="c1", *, ring1=True, price=50.0, source="slickdeals"):
    return CandidateDeal(
        source=source, listing_id=listing_id, item_name="Fake ETB sealed",
        price=price, shipping=None, url=BUY_URL, retailer="SomeStore",
        seen_at=CHECKED, evidence_excerpt="Fake ETB | $50.00",
        matched_product_key="fake_etb" if ring1 else None,
        matched_set="FakeSet" if ring1 else "")


def _verification(state, *, price=50.0, buy_url=BUY_URL, evidence="in stock $50",
                  stock_status=None):
    if stock_status is None:
        stock_status = ("in_stock" if state == verify_mod.VERIFIED_BUYABLE
                        else "out_of_stock" if state == verify_mod.OUT_OF_STOCK
                        else "unverifiable")
    return verify_mod.StockVerification(
        state=state, stock_status=stock_status,
        verified_price=price if state == verify_mod.VERIFIED_BUYABLE else None,
        expected_price=None,
        price_matches=None, buy_url=buy_url if state == verify_mod.VERIFIED_BUYABLE else "",
        checked_at=CHECKED, source=source_for(state), method="page_fetch",
        evidence=evidence, degraded_reason="" if state == verify_mod.VERIFIED_BUYABLE else state)


def source_for(state):
    return "slickdeals"


def _comp_row(estimate="$100.00", confidence="high"):
    return {"status": "ok", "estimate": estimate, "confidence": confidence,
            "source": "PriceCharting", "basis": "ungraded market",
            "compBasis": "pricecharting sold-derived",
            "sourceUrl": COMP_URL, "url": COMP_URL}


class FakeSource(DiscoverySource):
    def __init__(self, slug, candidates=None, *, raises=None, min_interval=0):
        super().__init__()
        self.slug = slug
        self.min_interval_seconds = min_interval
        self._candidates = candidates or []
        self._raises = raises
        self.calls = 0

    def discover(self, cfg, catalog, set_watch, **kwargs):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        self._set_state("WORKING", f"{len(self._candidates)} candidates")
        return list(self._candidates)


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def send_deal(self, deal, *, push):
        self.calls.append((deal, push))


def _run(cfg, state, sources, *, verifier, comp_lookup=None, notifier=None,
         now_ts=1_000_000, now_dt=NOON, dry_run=False):
    notifier = notifier or FakeNotifier()
    return pipeline.run_once(
        cfg, sources=sources, verifier=verifier,
        comp_lookup=comp_lookup or (lambda c, p: _comp_row()),
        notifier=notifier, state=state, catalog=dict(CATALOG),
        now_ts=now_ts, now_dt=now_dt, dry_run=dry_run), notifier


# --- slug validation ----------------------------------------------------------

def test_unknown_configured_slug_raises(tmp_path):
    cfg = _cfg()
    with pytest.raises(pipeline.PipelineConfigError, match="bogus"):
        pipeline.run_once(cfg, source_slugs=["bogus", "slickdeals"],
                          state=State(db_path=tmp_path / "s.db"),
                          verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE))


def test_known_slugs_build_from_registry(tmp_path):
    cfg = _cfg()
    # real slugs, but adapters are network-guarded in dry-run -> no fetch, no crash
    m = pipeline.run_once(cfg, source_slugs=["slickdeals"],
                          state=State(db_path=tmp_path / "s.db"), dry_run=True)
    assert m["candidates"] == 0
    assert any(s["slug"] == "slickdeals" for s in m["sources"])


# --- resilience ---------------------------------------------------------------

def test_adapter_exception_does_not_crash(tmp_path):
    state = State(db_path=tmp_path / "s.db")
    bad = FakeSource("badsrc", raises=RuntimeError("boom"))
    good = FakeSource("goodsrc", [_candidate()])
    m, notifier = _run(cfg=_cfg(), state=state, sources=[bad, good],
                       verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE))
    assert m["candidates"] == 1                       # good source's candidate survived
    assert len(notifier.calls) == 1
    states = {s["slug"]: s["state"] for s in m["sources"]}
    assert states["badsrc"] in ("DEGRADED", "BLOCKED")   # honest degradation, not a crash


# --- the alert gate (load-bearing) --------------------------------------------

def test_verified_buyable_alerts_and_gate_runs_on_fresh_object(tmp_path, monkeypatch):
    seen = {}
    real_gate = verify_mod.assert_alertable

    def spy_gate(v):
        seen["v"] = v
        return real_gate(v)

    monkeypatch.setattr(pipeline.verify_mod, "assert_alertable", spy_gate)
    state = State(db_path=tmp_path / "s.db")
    m, notifier = _run(cfg=_cfg(), state=state, sources=[FakeSource("s", [_candidate()])],
                       verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE))
    assert len(notifier.calls) == 1
    deal, push = notifier.calls[0]
    assert push is True                              # NOON is outside quiet hours
    assert deal["buy_url"] == BUY_URL and deal["verified_price"] == 50.0
    assert deal["comp"] == 100.0 and deal["comp_confidence"] == "high"
    assert seen["v"].state == verify_mod.VERIFIED_BUYABLE   # gate saw the fresh object
    assert m["counts"]["alerted"] == 1


def test_fabricated_verified_without_evidence_never_alerts(tmp_path):
    """A verifier that lies (state VERIFIED_BUYABLE but no buy_url/evidence) must
    be caught by assert_alertable re-checking evidence, not the label."""
    state = State(db_path=tmp_path / "s.db")
    liar = verify_mod.StockVerification(
        state=verify_mod.VERIFIED_BUYABLE, stock_status="in_stock",
        verified_price=None, expected_price=None, price_matches=None,
        buy_url="", checked_at="", source="x", method="none", evidence="")
    m, notifier = _run(cfg=_cfg(), state=state, sources=[FakeSource("s", [_candidate()])],
                       verifier=lambda c: liar)
    assert notifier.calls == []
    assert m["counts"]["alerted"] == 0
    assert m["counts"]["unverifiable"] == 1


# --- non-alert terminal states suppress the notifier --------------------------

@pytest.mark.parametrize("state,bucket", [
    (verify_mod.OUT_OF_STOCK, "out_of_stock"),
    (verify_mod.PRICE_MISMATCH, "price_mismatch"),
    (verify_mod.PAGE_UNAVAILABLE, "unverifiable"),
    (verify_mod.PARSER_SUSPECT, "unverifiable"),
    (verify_mod.SOURCE_BLOCKED, "unverifiable"),
    (verify_mod.UNKNOWN_NO_ALERT, "unverifiable"),
])
def test_nonalert_state_suppresses_notifier(tmp_path, state, bucket):
    st = State(db_path=tmp_path / "s.db")
    m, notifier = _run(cfg=_cfg(), state=st, sources=[FakeSource("s", [_candidate()])],
                       verifier=lambda c: _verification(state))
    assert notifier.calls == []
    assert m["counts"][bucket] == 1
    assert m["counts"]["alerted"] == 0


def test_no_comp_bucket_no_alert(tmp_path):
    st = State(db_path=tmp_path / "s.db")
    m, notifier = _run(cfg=_cfg(), state=st, sources=[FakeSource("s", [_candidate()])],
                       verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
                       comp_lookup=lambda c, p: {"status": "no_match"})
    assert notifier.calls == []
    assert m["counts"]["no_comp"] == 1


def test_below_min_discount_bucket_no_alert(tmp_path):
    st = State(db_path=tmp_path / "s.db")
    # verified 99 vs comp 100 -> 1% off, below default min_discount_pct 5
    m, notifier = _run(cfg=_cfg(), state=st,
                       sources=[FakeSource("s", [_candidate(price=99.0)])],
                       verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE, price=99.0),
                       comp_lookup=lambda c, p: _comp_row("$100.00"))
    assert notifier.calls == []
    assert m["counts"]["below_min_discount"] == 1


def test_ring3_below_confidence_no_alert(tmp_path):
    st = State(db_path=tmp_path / "s.db")
    m, notifier = _run(cfg=_cfg(min_alert_confidence="medium"), state=st,
                       sources=[FakeSource("s", [_candidate("c1", ring1=False)])],
                       verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
                       comp_lookup=lambda c, p: _comp_row(confidence="low"))
    assert notifier.calls == []
    assert m["counts"]["below_confidence"] == 1


def test_ring3_high_confidence_alerts(tmp_path):
    st = State(db_path=tmp_path / "s.db")
    m, notifier = _run(cfg=_cfg(min_alert_confidence="medium"), state=st,
                       sources=[FakeSource("s", [_candidate("c1", ring1=False)])],
                       verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
                       comp_lookup=lambda c, p: _comp_row(confidence="high"))
    assert len(notifier.calls) == 1
    assert m["counts"]["alerted"] == 1


# --- dedupe matrix (end-to-end through the pipeline) --------------------------

def _one(cfg, state, verification, *, now_ts, price=50.0, now_dt=NOON):
    return _run(cfg=cfg, state=state,
                sources=[FakeSource("s", [_candidate(price=price)])],
                verifier=lambda c: verification, now_ts=now_ts, now_dt=now_dt)


def test_dedupe_matrix(tmp_path):
    cfg = _cfg()
    st = State(db_path=tmp_path / "s.db")
    hour = 3600
    v = _verification(verify_mod.VERIFIED_BUYABLE, price=50.0)
    # 1) new -> alert
    _, n1 = _one(cfg, st, v, now_ts=1000)
    assert len(n1.calls) == 1
    # 2) same price+status within cooldown -> suppress
    m2, n2 = _one(cfg, st, v, now_ts=1000 + hour)
    assert n2.calls == [] and m2["counts"]["suppressed_dupe"] == 1
    # 3) price drop >= 5% -> re-alert
    v_drop = _verification(verify_mod.VERIFIED_BUYABLE, price=47.0)
    _, n3 = _one(cfg, st, v_drop, now_ts=1000 + 2 * hour, price=47.0)
    assert len(n3.calls) == 1
    # 4) status flip -> re-alert (limited)
    v_flip = _verification(verify_mod.VERIFIED_BUYABLE, price=47.0, stock_status="limited")
    _, n4 = _one(cfg, st, v_flip, now_ts=1000 + 3 * hour, price=47.0)
    assert len(n4.calls) == 1
    # 5) cooldown expiry -> re-alert
    _, n5 = _one(cfg, st, v_flip, now_ts=1000 + 3 * hour + 25 * hour, price=47.0)
    assert len(n5.calls) == 1


# --- quiet hours --------------------------------------------------------------

def test_quiet_hours_suppresses_push_but_writes_board(tmp_path):
    st = State(db_path=tmp_path / "s.db")
    m, notifier = _run(cfg=_cfg(), state=st, sources=[FakeSource("s", [_candidate()])],
                       verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
                       now_dt=NIGHT)
    assert len(notifier.calls) == 1
    _, push = notifier.calls[0]
    assert push is False                      # ntfy suppressed in quiet hours
    assert m["counts"]["alerted"] == 1        # still counts as alerted
    assert m["quiet_hours"] is True
    assert len(m["board"]["deals"]) == 1      # board still built


def test_in_quiet_hours_wraps_midnight():
    assert pipeline._in_quiet_hours(NIGHT, "23:00-08:00") is True     # 02:00 inside
    assert pipeline._in_quiet_hours(NOON, "23:00-08:00") is False     # 12:00 outside
    assert pipeline._in_quiet_hours(datetime(2026, 7, 3, 10, 0), "09:00-17:00") is True
    assert pipeline._in_quiet_hours(datetime(2026, 7, 3, 20, 0), "09:00-17:00") is False


# --- manifest reconciliation --------------------------------------------------

def test_manifest_counts_reconcile(tmp_path):
    st = State(db_path=tmp_path / "s.db")
    cands = [_candidate("a1"), _candidate("b2"), _candidate("c3"), _candidate("d4")]
    verdicts = {
        "a1": _verification(verify_mod.VERIFIED_BUYABLE),      # -> alerted
        "b2": _verification(verify_mod.OUT_OF_STOCK),          # -> out_of_stock
        "c3": _verification(verify_mod.PARSER_SUSPECT),        # -> unverifiable
        "d4": _verification(verify_mod.VERIFIED_BUYABLE),      # -> no_comp
    }

    def verifier(c):
        return verdicts[c.listing_id]

    def comp_lookup(c, p):
        return {"status": "no_match"} if c.listing_id == "d4" else _comp_row()

    m, _ = _run(cfg=_cfg(), state=st, sources=[FakeSource("s", cands)],
                verifier=verifier, comp_lookup=comp_lookup)
    counts = m["counts"]
    assert m["candidates"] == 4
    assert sum(counts.values()) == 4                # no silent drops
    assert counts["alerted"] == 1 and counts["out_of_stock"] == 1
    assert counts["unverifiable"] == 1 and counts["no_comp"] == 1


def test_within_run_duplicate_candidates_collapse(tmp_path):
    st = State(db_path=tmp_path / "s.db")
    dupes = [_candidate("same"), _candidate("same")]
    m, notifier = _run(cfg=_cfg(), state=st, sources=[FakeSource("s", dupes)],
                       verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE))
    assert m["candidates"] == 1
    assert len(notifier.calls) == 1


# --- min_interval throttle ----------------------------------------------------

def test_recent_source_is_throttled(tmp_path):
    st = State(db_path=tmp_path / "s.db")
    st.set_last_run("s", 1000)
    src = FakeSource("s", [_candidate()], min_interval=900)
    m, notifier = _run(cfg=_cfg(), state=st, sources=[src],
                       verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
                       now_ts=1000 + 100)      # only 100s since last run < 900
    assert src.calls == 0                      # discover skipped
    assert m["candidates"] == 0
    assert any(s["slug"] == "s" and "throttl" in s.get("detail", "").lower()
               for s in m["sources"])


def test_interval_elapsed_source_runs_and_records(tmp_path):
    st = State(db_path=tmp_path / "s.db")
    st.set_last_run("s", 1000)
    src = FakeSource("s", [_candidate()], min_interval=900)
    _run(cfg=_cfg(), state=st, sources=[src],
         verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
         now_ts=1000 + 1000)
    assert src.calls == 1
    assert st.get_last_run("s") == 1000 + 1000   # last_run advanced


# --- dry run: zero network, zero side effects ---------------------------------

def test_dry_run_makes_zero_network_calls(tmp_path, monkeypatch):
    """Patch the lowest network primitives; a dry run with REAL default adapters
    must complete without any of them being called."""
    from scanner.retailers import http as retailer_http
    import requests as requests_mod

    def _boom(*a, **k):
        raise AssertionError("network call in --dry-run")

    monkeypatch.setattr(retailer_http, "get", _boom)
    monkeypatch.setattr(requests_mod, "get", _boom)
    monkeypatch.setattr(requests_mod, "post", _boom)

    st = State(db_path=tmp_path / "s.db")
    m = pipeline.run_once(_cfg(), source_slugs=["slickdeals", "ebay_browse"],
                          state=st, now_ts=1000, dry_run=True)
    assert m["dry_run"] is True
    assert m["candidates"] == 0
    # no state writes
    assert st.get_last_run("slickdeals") is None
    assert st.listing_history("slickdeals", "anything") is None


def test_dry_run_with_fake_candidates_suppresses_side_effects(tmp_path):
    st = State(db_path=tmp_path / "s.db")
    m, notifier = _run(cfg=_cfg(), state=st, sources=[FakeSource("s", [_candidate()])],
                       verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
                       dry_run=True)
    # decision still computed + reported, but nothing sent or persisted
    assert notifier.calls == []
    assert st.listing_history("slickdeals", "c1") is None
    row = st.db.execute("SELECT COUNT(*) FROM deal_alerts").fetchone()[0]
    assert row == 0
    assert m["dry_run"] is True


# --- CLI ----------------------------------------------------------------------

def test_cli_requires_once_or_dry_run(tmp_path):
    assert pipeline.main([], cfg=_cfg(), state=State(db_path=tmp_path / "s.db")) == 2


def test_cli_unknown_source_returns_2(tmp_path):
    rc = pipeline.main(["--once", "--sources", "bogus"], cfg=_cfg(),
                       state=State(db_path=tmp_path / "s.db"))
    assert rc == 2


def test_cli_dry_run_writes_nothing_zero_network(tmp_path, monkeypatch):
    from scanner.retailers import http as retailer_http
    import requests as requests_mod

    def _boom(*a, **k):
        raise AssertionError("network in CLI --dry-run")

    monkeypatch.setattr(retailer_http, "get", _boom)
    monkeypatch.setattr(requests_mod, "get", _boom)
    monkeypatch.setattr(requests_mod, "post", _boom)

    out = tmp_path / "out"
    rc = pipeline.main(["--dry-run", "--out", str(out)], cfg=_cfg(),
                       state=State(db_path=tmp_path / "s.db"))
    assert rc == 0
    assert not (out / "data" / "poke").exists()   # nothing written on a dry run


def test_cli_once_writes_board_and_manifest(tmp_path):
    import glob

    out = tmp_path / "out"
    notifier = FakeNotifier()
    rc = pipeline.main(
        ["--once", "--out", str(out)], cfg=_cfg(),
        state=State(db_path=tmp_path / "s.db"),
        sources=[FakeSource("s", [_candidate()])],
        verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
        comp_lookup=lambda c, p: _comp_row(), notifier=notifier)
    assert rc == 0
    poke = out / "data" / "poke"
    boards = glob.glob(str(poke / "*-discovery.json"))
    manifests = glob.glob(str(poke / "*-discovery.manifest.json"))
    assert len(boards) == 1 and len(manifests) == 1

    import json as _json
    manifest = _json.loads(open(manifests[0], encoding="utf-8").read())
    assert manifest["candidates"] == 1
    assert manifest["counts"]["alerted"] == 1
    assert sum(manifest["counts"].values()) == manifest["candidates"]
    assert "board" not in manifest       # board lives in its own file
    board = _json.loads(open(boards[0], encoding="utf-8").read())
    assert len(board["deals"]) == 1
    assert len(notifier.calls) == 1
