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
    assert deal.buy_url == BUY_URL and deal.verified_price == 50.0
    assert deal.comp == 100.0 and deal.comp_confidence == "high"
    assert deal.source_adapter == "slickdeals" and deal.listing_id == "c1"
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
    # wrap window (start > end): exercise BOTH disjuncts
    assert pipeline._in_quiet_hours(NIGHT, "23:00-08:00") is True             # 02:00 (cur < end)
    assert pipeline._in_quiet_hours(datetime(2026, 7, 3, 23, 30), "23:00-08:00") is True  # 23:30 (cur >= start)
    assert pipeline._in_quiet_hours(datetime(2026, 7, 3, 8, 0), "23:00-08:00") is False   # 08:00 boundary (exclusive)
    assert pipeline._in_quiet_hours(NOON, "23:00-08:00") is False            # 12:00 outside
    # normal window (start <= end)
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

def _network_spy(monkeypatch):
    """Count every call to the lowest network primitives (module-level AND the
    Session instance methods the resale clients use). Returns the call log so a
    test can assert it stayed empty -- a non-vacuous zero-network proof."""
    from scanner.retailers import http as retailer_http
    import requests as requests_mod

    calls: list[str] = []

    def _spy(name):
        def f(*a, **k):
            calls.append(name)
            raise RuntimeError(f"network via {name} in --dry-run")
        return f

    monkeypatch.setattr(retailer_http, "get", _spy("http.get"))
    monkeypatch.setattr(requests_mod, "get", _spy("requests.get"))
    monkeypatch.setattr(requests_mod, "post", _spy("requests.post"))
    monkeypatch.setattr(requests_mod.Session, "get", _spy("session.get"), raising=False)
    monkeypatch.setattr(requests_mod.Session, "post", _spy("session.post"), raising=False)
    return calls


def test_dry_run_makes_zero_network_calls(tmp_path, monkeypatch):
    """A dry run with REAL default adapters must touch NO network primitive.
    Proven by call-counting spies, not by a swallowable raise."""
    calls = _network_spy(monkeypatch)
    st = State(db_path=tmp_path / "s.db")
    m = pipeline.run_once(_cfg(), source_slugs=["slickdeals", "ebay_browse"],
                          state=st, now_ts=1000, dry_run=True)
    assert calls == []                          # THE invariant: zero network
    assert m["dry_run"] is True
    assert m["candidates"] == 0
    assert st.get_last_run("slickdeals") is None
    assert st.listing_history("slickdeals", "anything") is None


def test_dry_run_default_comp_lookup_makes_no_network(tmp_path, monkeypatch):
    """Even when a candidate reaches the COMP stage in --dry-run (fake verifier
    -> VERIFIED_BUYABLE, DEFAULT comp lookup), zero network is structural: the
    comp is skipped, candidate ends no_comp."""
    calls = _network_spy(monkeypatch)
    st = State(db_path=tmp_path / "s.db")
    m = pipeline.run_once(
        _cfg(), sources=[FakeSource("s", [_candidate()])],
        verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
        comp_lookup=None, state=st, catalog=dict(CATALOG),
        now_ts=1000, now_dt=NOON, dry_run=True)
    assert calls == []
    assert m["counts"]["no_comp"] == 1


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
    calls = _network_spy(monkeypatch)
    out = tmp_path / "out"
    rc = pipeline.main(["--dry-run", "--out", str(out)], cfg=_cfg(),
                       state=State(db_path=tmp_path / "s.db"))
    assert rc == 0
    assert calls == []                            # zero network on a CLI dry run
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


def test_cli_once_writes_dashboard_with_buyable_now(tmp_path):
    import glob
    out = tmp_path / "out"
    rc = pipeline.main(
        ["--once", "--out", str(out)], cfg=_cfg(),
        state=State(db_path=tmp_path / "s.db"),
        sources=[FakeSource("s", [_candidate()])],
        verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
        comp_lookup=lambda c, p: _comp_row(), notifier=FakeNotifier())
    assert rc == 0
    dashes = glob.glob(str(out / "dashboards" / "*-discovery.html"))
    assert len(dashes) == 1                       # the pipeline renders a dashboard
    html = open(dashes[0], encoding="utf-8").read()
    assert 'id="buyable-now"' in html
    from scanner.discovery.render import section_html
    assert "Fake ETB" in section_html(html, "buyable-now")   # verified row is Buyable now


def test_cli_golden_failure_halts_dashboard_but_keeps_json_evidence(tmp_path, monkeypatch):
    """Belt-3 HALT behavior on the discovery lane: if a golden check fails, the
    dashboard is withheld (rc 1) but the board + manifest JSON evidence is kept.
    The STOP gate precedes golden so a real bad row can't reach it - inject a
    golden failure to prove the halt path is wired and truthful."""
    import glob
    monkeypatch.setattr(pipeline.golden_mod, "golden_check",
                        lambda html, min_rows: ["injected golden failure"])
    out = tmp_path / "out"
    rc = pipeline.main(
        ["--once", "--out", str(out)], cfg=_cfg(),
        state=State(db_path=tmp_path / "s.db"),
        sources=[FakeSource("s", [_candidate()])],
        verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
        comp_lookup=lambda c, p: _comp_row(), notifier=FakeNotifier())
    assert rc == 1                                             # halted
    poke = out / "data" / "poke"
    assert glob.glob(str(poke / "*-discovery.json"))          # JSON evidence kept
    assert glob.glob(str(poke / "*-discovery.manifest.json"))
    assert glob.glob(str(out / "dashboards" / "*.html")) == []  # dashboard withheld


def test_manifest_records_per_candidate_outcomes(tmp_path):
    st = State(db_path=tmp_path / "s.db")
    cands = [_candidate("a1"), _candidate("b2"), _candidate("c3"), _candidate("d4")]
    verdicts = {
        "a1": _verification(verify_mod.VERIFIED_BUYABLE),
        "b2": _verification(verify_mod.OUT_OF_STOCK),
        "c3": _verification(verify_mod.PARSER_SUSPECT),
        "d4": _verification(verify_mod.VERIFIED_BUYABLE),
    }
    m, _ = _run(cfg=_cfg(), state=st, sources=[FakeSource("s", cands)],
                verifier=lambda c: verdicts[c.listing_id],
                comp_lookup=lambda c, p: {"status": "no_match"} if c.listing_id == "d4"
                else _comp_row())
    outcomes = m["outcomes"]
    assert len(outcomes) == m["candidates"] == 4          # one disposition per candidate
    assert {o["listing_id"] for o in outcomes} == {"a1", "b2", "c3", "d4"}
    assert all(o["terminal"] and o.get("reason") for o in outcomes)   # every one has a reason


# --- comp lookup: PPT-free + never errors the run ----------------------------

def test_default_comp_lookup_is_ppt_free(monkeypatch):
    """The default (legacy) comp path must use the resale fallback, never the
    PPT-billing MarketFallbackClient."""
    from scanner import resale as resale_mod, market as market_mod

    used = {}

    class FakeResale:
        def estimate(self, key, product, checked_at):
            used["resale"] = True
            return _comp_row()

    monkeypatch.setattr(resale_mod, "resale_client_from_config", lambda cfg: FakeResale())

    def _no_ppt(*a, **k):
        raise AssertionError("PPT MarketFallbackClient used in pipeline comp path")

    monkeypatch.setattr(market_mod, "MarketFallbackClient", _no_ppt)

    lookup = pipeline.default_comp_lookup(_cfg())          # engine == 'legacy' default
    row = lookup(_candidate(), CATALOG["fake_etb"])
    assert used.get("resale") is True and row["status"] == "ok"


def test_comp_lookup_exception_becomes_no_comp(tmp_path):
    """A comp source that raises must not crash the run (sweep doctrine)."""
    st = State(db_path=tmp_path / "s.db")

    def boom(c, p):
        raise RuntimeError("comp source down")

    m, notifier = _run(cfg=_cfg(), state=st, sources=[FakeSource("s", [_candidate()])],
                       verifier=lambda c: _verification(verify_mod.VERIFIED_BUYABLE),
                       comp_lookup=boom)
    assert m["counts"]["no_comp"] == 1
    assert notifier.calls == []


# --- Slice 6B: default verifier routes slickdeals through the resolver --------

from types import SimpleNamespace  # noqa: E402

from scanner.discovery import verify as _verify_real  # noqa: E402

SD_THREAD = "https://slickdeals.net/f/19710354-mega"
SD_MERCHANT = "https://www.walmart.com/ip/pokemon-mega-ex-box/123456789"


def _sd_thread_html():
    enc = "https%3A%2F%2Fwww.walmart.com%2Fip%2Fpokemon-mega-ex-box%2F123456789"
    return (f'<a class="dealButton" data-role="seeDealButton" '
            f'href="https://slickdeals.net/?u2={enc}&amp;pv=1">See Deal</a>')


def _sd_merchant_html(price="49.99"):
    return ('<html><body><script type="application/ld+json">'
            f'{{"offers":{{"price":"{price}",'
            f'"availability":"https://schema.org/InStock"}}}}</script></body></html>')


def _sd_get():
    def _get(url, **kwargs):
        if url == SD_THREAD:
            return SimpleNamespace(status_code=200, text=_sd_thread_html(), headers={}, url=url)
        if url == SD_MERCHANT:
            return SimpleNamespace(status_code=200, text=_sd_merchant_html(), headers={}, url=url)
        raise AssertionError(f"unexpected GET {url}")
    return _get


def _sd_candidate(listing_id="19710354", *, ring1=True, price=49.99):
    return CandidateDeal(
        source="slickdeals", listing_id=listing_id, item_name="Fake ETB sealed",
        price=price, shipping=None, url=SD_THREAD, retailer="Walmart", seen_at=CHECKED,
        evidence_excerpt="Fake ETB | $49.99",
        matched_product_key="fake_etb" if ring1 else None,
        matched_set="FakeSet" if ring1 else "")


def test_default_verifier_routes_slickdeals_to_resolver(monkeypatch):
    seen = {}

    def fake_sd(candidate, **kwargs):
        seen["c"] = candidate
        return _verification(verify_mod.VERIFIED_BUYABLE)

    monkeypatch.setattr(pipeline.verify_mod, "verify_slickdeals_candidate", fake_sd)
    verifier = pipeline.default_verifier(_cfg())
    sd = _candidate(source="slickdeals")
    v = verifier(sd)
    assert seen["c"] is sd                       # slickdeals candidate went to the resolver
    assert v.state == verify_mod.VERIFIED_BUYABLE


def test_default_verifier_leaves_other_sources_unverifiable(monkeypatch):
    def fake_sd(candidate, **kwargs):
        raise AssertionError("resolver called for a non-slickdeals source")

    monkeypatch.setattr(pipeline.verify_mod, "verify_slickdeals_candidate", fake_sd)
    verifier = pipeline.default_verifier(_cfg())
    v = verifier(_candidate("e1", source="ebay_browse"))
    assert v.state == verify_mod.UNKNOWN_NO_ALERT
    assert v.stock_status == "unverifiable"


def test_dry_run_default_verifier_slickdeals_is_zero_network(tmp_path, monkeypatch):
    """The REAL default verifier must touch NO network in --dry-run even with a
    slickdeals candidate present (structural, not incidental on zero candidates)."""
    calls = _network_spy(monkeypatch)
    st = State(db_path=tmp_path / "s.db")
    m = pipeline.run_once(
        _cfg(), sources=[FakeSource("slickdeals", [_sd_candidate()])],
        verifier=None, comp_lookup=None, state=st, catalog=dict(CATALOG),
        now_ts=1000, now_dt=NOON, dry_run=True)
    assert calls == []                           # resolver did not fetch
    assert m["counts"]["unverifiable"] == 1


def test_slickdeals_resolved_candidate_alerts_end_to_end(tmp_path):
    """A slickdeals thread candidate, resolved to a verified in-stock merchant
    page, alerts through the pipeline with the RESOLVED merchant URL as buy_url —
    and only because the fresh StockVerification passed assert_alertable."""
    st = State(db_path=tmp_path / "s.db")
    sd_get = _sd_get()

    def verifier(c):
        return _verify_real.verify_slickdeals_candidate(c, http_get=sd_get, checked_at=CHECKED)

    m, notifier = _run(cfg=_cfg(), state=st, sources=[FakeSource("s", [_sd_candidate()])],
                       verifier=verifier, comp_lookup=lambda c, p: _comp_row())
    assert len(notifier.calls) == 1
    deal, _push = notifier.calls[0]
    assert deal.buy_url == SD_MERCHANT           # the merchant URL, not the thread
    assert deal.verified_price == 49.99
    assert m["counts"]["alerted"] == 1


def test_slickdeals_unresolvable_candidate_does_not_alert(tmp_path):
    """A slickdeals thread with no See-Deal outbound structure (drift) never
    alerts — it lands unverifiable with an honest reason."""
    st = State(db_path=tmp_path / "s.db")

    def drift_get(url, **kwargs):
        return SimpleNamespace(status_code=200, text="<html>discussion only</html>",
                               headers={}, url=url)

    def verifier(c):
        return _verify_real.verify_slickdeals_candidate(c, http_get=drift_get, checked_at=CHECKED)

    m, notifier = _run(cfg=_cfg(), state=st, sources=[FakeSource("s", [_sd_candidate()])],
                       verifier=verifier, comp_lookup=lambda c, p: _comp_row())
    assert notifier.calls == []
    assert m["counts"]["unverifiable"] == 1


def test_default_verifier_threads_injected_http_get(tmp_path, monkeypatch):
    """A non-dry-run run_once given an http_get stub must NOT reach real network
    through the default verifier's slickdeals branch — the injected stage
    contract covers the verifier, not just DISCOVER."""
    calls = _network_spy(monkeypatch)
    st = State(db_path=tmp_path / "s.db")

    def stub_get(url, **kwargs):
        return SimpleNamespace(status_code=200, text="<html>no cta</html>",
                               headers={}, url=url)

    m = pipeline.run_once(
        _cfg(), sources=[FakeSource("slickdeals", [_sd_candidate()])],
        verifier=None, state=st, catalog=dict(CATALOG),
        now_ts=1000, now_dt=NOON, http_get=stub_get)
    assert calls == []                           # default verifier used the stub
    assert m["counts"]["unverifiable"] == 1      # thread had no CTA -> drift


def test_slickdeals_mixed_batch_manifest_reconciles(tmp_path):
    """A batch of slickdeals candidates with different resolution outcomes routed
    through the REAL resolver: one alerts, one is drift (unverifiable), one is a
    dead redirect (unverifiable). Counts must reconcile with no silent drops."""
    st = State(db_path=tmp_path / "s.db")
    good = _sd_candidate("19710354")
    drift = _sd_candidate("19710357")
    dead = _sd_candidate("19710358")

    # all three share SD_THREAD as their thread URL; disambiguate by listing_id
    def per_candidate_get(listing_id):
        if listing_id == "19710354":
            return _sd_get()
        if listing_id == "19710357":
            return lambda url, **k: SimpleNamespace(status_code=200,
                                                    text="<html>no cta</html>", headers={}, url=url)
        return lambda url, **k: SimpleNamespace(status_code=404, text="", headers={}, url=url)

    def verifier(c):
        return _verify_real.verify_slickdeals_candidate(
            c, http_get=per_candidate_get(c.listing_id), checked_at=CHECKED)

    m, notifier = _run(cfg=_cfg(), state=st,
                       sources=[FakeSource("s", [good, drift, dead])],
                       verifier=verifier, comp_lookup=lambda c, p: _comp_row())
    counts = m["counts"]
    assert m["candidates"] == 3
    assert sum(counts.values()) == 3                 # no silent drops
    assert counts["alerted"] == 1
    assert counts["unverifiable"] == 2               # drift + dead redirect
    assert len(notifier.calls) == 1
    assert notifier.calls[0][0].buy_url == SD_MERCHANT
