import json
from datetime import date

import pytest

from scanner import config as cfg_mod
from scanner import main as main_mod
from scanner.discovery import score, sweep
from scanner.discovery.schema import row_from_dict

PPT_URL = "https://www.tcgplayer.com/product/593355"
EBAY_URL = "https://www.ebay.com/sch/i.html?_nkw=fake+etb+sealed"

CATALOG = {
    "fake_etb": {"name": "Fake ETB", "set": "FakeSet", "type": "ETB", "msrp": "$49.99"},
    "fake_bundle": {"name": "Fake Bundle", "set": "FakeSet", "type": "Booster Bundle", "msrp": "$26.94"},
    "fake_box": {"name": "Fake Box", "set": "FakeSet", "type": "Surprise Box", "msrp": "$22.99"},
}


def _cfg(catalog=CATALOG, **poke):
    raw = {"locations": {"home": "A", "work": "B"}}
    if poke:
        raw["poke"] = poke
    cfg = cfg_mod.from_mapping(raw)
    cfg.products = dict(catalog)
    cfg.products_filter = None
    return cfg


def _verified_row(estimate="$199.14", confidence="medium"):
    return {"status": "ok", "estimate": estimate, "confidence": confidence,
            "source": "PokemonPriceTracker", "basis": "TCGplayer sealed market",
            "sourceUrl": PPT_URL, "url": PPT_URL}


def _est_row(estimate="$60.00"):
    return {"status": "ok", "estimate": estimate, "confidence": "medium",
            "source": "eBay Browse API", "basis": "active fixed-price asking median",
            "url": EBAY_URL}


def _build(cfg, lookup):
    return sweep.build_sealed_sweep(cfg, lookup, event="sealed",
                                    sweep_id="2026-07-01-sealed",
                                    captured_at="2026-07-01")


def test_verified_comp_maps_to_verified_row():
    swp = _build(_cfg(), lambda k, p: _verified_row())
    assert len(swp["deals"]) == 3
    for d in swp["deals"]:
        assert d["asset_class"] == "sealed"
        assert d["retailer"] == "MSRP"
        assert d["price_confidence"] == "verified"
        assert d["source_url"] == PPT_URL
        assert d["captured_at"] == "2026-07-01"
        assert "EST" not in d["badges"]
    by_item = {d["item"]: d for d in swp["deals"]}
    assert by_item["Fake ETB"]["category"] == "sealed-etb"
    assert by_item["Fake Bundle"]["category"] == "sealed-bundle"
    assert by_item["Fake Box"]["category"] == "sealed-other"
    assert swp["counts"] == {"scanned": 3, "comped": 3, "no_comp": 0,
                             "no_msrp": 0, "no_source": 0}


def test_fallback_comp_maps_to_est_with_attribution():
    swp = _build(_cfg(), lambda k, p: _est_row())
    for d in swp["deals"]:
        assert d["price_confidence"] == "est"
        assert "EST" in d["badges"]
        assert d["source_url"] == EBAY_URL       # search-page attribution
        assert "eBay Browse API" in d["derivation_method"]
        assert "STEAL" not in d["badges"]        # est never a confirmed STEAL


def test_low_confidence_ppt_comp_is_est_even_with_source_url():
    swp = _build(_cfg(), lambda k, p: _verified_row(confidence="low"))
    for d in swp["deals"]:
        assert d["price_confidence"] == "est"
        assert "EST" in d["badges"]


def test_no_comp_product_is_skipped_and_counted():
    def lookup(key, product):
        if key == "fake_etb":
            return {"status": "no_matches"}
        return _verified_row()
    swp = _build(_cfg(), lookup)
    assert len(swp["deals"]) == 2
    assert swp["counts"]["no_comp"] == 1
    assert all(d["item"] != "Fake ETB" for d in swp["deals"])


def test_missing_msrp_is_skipped_and_counted():
    catalog = dict(CATALOG)
    catalog["no_msrp"] = {"name": "No MSRP", "set": "FakeSet", "type": "ETB"}
    swp = _build(_cfg(catalog), lambda k, p: _verified_row())
    assert swp["counts"]["no_msrp"] == 1
    assert len(swp["deals"]) == 3


def test_unattributable_comp_is_skipped_and_counted():
    row = {"status": "ok", "estimate": "$60.00", "confidence": "medium",
           "source": "X", "basis": "y"}  # no sourceUrl, no url
    swp = _build(_cfg(), lambda k, p: row)
    assert len(swp["deals"]) == 0
    assert swp["counts"]["no_source"] == 3


def test_badges_lenses_and_verdict_pin_to_backbone():
    cfg = _cfg()
    comp_rows = {k: _verified_row() for k in CATALOG}
    swp = _build(cfg, lambda k, p: comp_rows[k])
    key_by_item = {p["name"]: k for k, p in CATALOG.items()}
    for d in swp["deals"]:
        row = row_from_dict(d)
        row.badges, row.lens_tags = [], []
        assert score.assign_badges(row, cfg) == d["badges"]
        assert score.lens_tags(row, cfg) == d["lens_tags"]
        key = key_by_item[d["item"]]
        expected = main_mod.verdict_for_alert(
            cfg, CATALOG[key], f"${d['deal_price']:.2f}", comp_rows[key])
        assert d["scanner_verdict"] == expected


def test_deals_sorted_by_pct_off_desc():
    def lookup(key, product):
        return {"fake_etb": _verified_row("$199.14"),      # ~75% off
                "fake_bundle": _verified_row("$30.00"),    # ~10% off
                "fake_box": _verified_row("$100.00")}[key]  # ~77% off
    swp = _build(_cfg(), lookup)
    pcts = [d["pct_off"] for d in swp["deals"]]
    assert pcts == sorted(pcts, reverse=True)


def test_sweep_dict_shape():
    swp = _build(_cfg(), lambda k, p: _verified_row())
    for key in ("event", "sweep_id", "captured_window", "notes", "deals",
                "promo_codes", "bundled_offers", "watchlist_results",
                "sources", "counts"):
        assert key in swp
    assert swp["promo_codes"] == []
    assert swp["bundled_offers"] == []
    assert swp["watchlist_results"] == []
    assert any(s["name"] == "PokemonPriceTracker" for s in swp["sources"])


# ---------------------------------------------------------------- CLI + guard


class _StubEstimator:
    def __init__(self, row):
        self.row = row
        self.calls = 0

    def estimate(self, key, product, checked_at):
        self.calls += 1
        return dict(self.row)


def test_live_lookup_degrades_to_fallback_when_cap_hit():
    cfg = _cfg(daily_credit_cap=2)
    market = _StubEstimator(_verified_row() | {"creditsConsumed": 1, "dailyRemaining": 50})
    fallback = _StubEstimator(_est_row())
    lookup = sweep.LiveCompLookup(cfg, market_client=market, resale_client=fallback)
    for key, product in CATALOG.items():
        lookup(key, product)
    assert market.calls == 2          # cap=2 -> third product skips the market path
    assert fallback.calls == 1
    assert lookup.credits_used == 2


def test_live_lookup_stops_market_calls_when_daily_remaining_zero():
    cfg = _cfg()
    market = _StubEstimator(_verified_row() | {"creditsConsumed": 1, "dailyRemaining": 0})
    fallback = _StubEstimator(_est_row())
    lookup = sweep.LiveCompLookup(cfg, market_client=market, resale_client=fallback)
    for key, product in CATALOG.items():
        lookup(key, product)
    assert market.calls == 1
    assert lookup.exhausted is True
    assert fallback.calls == 2


def test_live_lookup_turns_exceptions_into_error_rows():
    cfg = _cfg()

    class _Boom:
        def estimate(self, key, product, checked_at):
            raise ValueError("boom")

    lookup = sweep.LiveCompLookup(cfg, market_client=_Boom(), resale_client=_Boom())
    row = lookup("fake_etb", CATALOG["fake_etb"])
    assert row["status"] == "error"   # comp_from_row -> (None, "none") -> counted no_comp


def test_cli_writes_sweep_manifest_dashboard_and_ledger(tmp_path):
    cfg = _cfg(min_rows=3)
    rc = sweep.main(["--out", str(tmp_path)],
                    comp_lookup=lambda k, p: _verified_row(), cfg=cfg)
    assert rc == 0
    today = date.today().isoformat()
    poke_dir = tmp_path / "data" / "poke"
    assert (poke_dir / f"{today}-sealed.json").exists()
    assert (poke_dir / f"{today}-sealed.manifest.json").exists()
    dash = tmp_path / "dashboards" / f"{today}-sealed.html"
    assert dash.exists()

    from scanner.discovery.golden import golden_check
    assert golden_check(dash.read_text(encoding="utf-8"), 3) == []

    manifest = json.loads((poke_dir / f"{today}-sealed.manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"] == {"scanned": 3, "comped": 3, "no_comp": 0,
                                  "no_msrp": 0, "no_source": 0}
    assert manifest["credits_consumed"] == 0
    assert manifest["golden_failures"] == []

    ledger_path = poke_dir / "price_history.jsonl"
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 6            # market_comp + deal line per comped product

    # idempotent re-run: same day, same comps -> nothing new appended
    rc2 = sweep.main(["--out", str(tmp_path)],
                     comp_lookup=lambda k, p: _verified_row(), cfg=cfg)
    assert rc2 == 0
    assert len(ledger_path.read_text(encoding="utf-8").splitlines()) == 6


def test_cli_halts_without_dashboard_on_golden_failure(tmp_path, capsys):
    cfg = _cfg(min_rows=99)          # impossible floor -> acquisition-failure canary
    rc = sweep.main(["--out", str(tmp_path)],
                    comp_lookup=lambda k, p: _verified_row(), cfg=cfg)
    assert rc == 1
    today = date.today().isoformat()
    assert not (tmp_path / "dashboards" / f"{today}-sealed.html").exists()
    # evidence still persisted for diagnosis
    assert (tmp_path / "data" / "poke" / f"{today}-sealed.json").exists()
    assert (tmp_path / "data" / "poke" / f"{today}-sealed.manifest.json").exists()
    ledger_path = tmp_path / "data" / "poke" / "price_history.jsonl"
    assert ledger_path.exists()
    assert len(ledger_path.read_text(encoding="utf-8").splitlines()) == 6
    out = capsys.readouterr().out
    assert "GOLDEN FAIL" in out


# ---------------------------------------------------------------- stock verify


def _fake_verification(expected, **kw):
    from scanner.discovery import verify as verify_mod
    base = dict(
        state=verify_mod.VERIFIED_BUYABLE, stock_status="in_stock",
        verified_price=expected, expected_price=expected, price_matches=True,
        buy_url="https://www.walmart.com/ip/123", checked_at="2026-07-01T09:00:00",
        source="walmart", method="retailer_adapter:walmart",
        evidence="walmart adapter: status=ONLINE_IN_STOCK price=$x",
        degraded_reason="")
    base.update(kw)
    return verify_mod.StockVerification(**base)


def test_build_without_verifier_leaves_stock_untouched():
    swp = _build(_cfg(), lambda k, p: _verified_row())
    assert "stock_states" not in swp
    for d in swp["deals"]:
        assert d["stock_status"] == "unknown"
        assert d["stock_evidence"] == "" and d["buy_url"] == ""
        assert d["stock_checked_at"] == "" and d["stock_method"] == ""


def test_rows_carry_comp_basis_passthrough():
    swp = _build(_cfg(), lambda k, p: _verified_row())
    for d in swp["deals"]:
        assert d["comp_basis"] == "TCGplayer sealed market"


def test_verify_stock_populates_evidence_and_retailer():
    swp = sweep.build_sealed_sweep(
        _cfg(), lambda k, p: _verified_row(), event="sealed",
        sweep_id="2026-07-01-sealed", captured_at="2026-07-01",
        stock_verifier=lambda k, p, expected: _fake_verification(expected))
    assert swp["stock_states"] == {"VERIFIED_BUYABLE": 3}
    for d in swp["deals"]:
        assert d["stock_status"] == "in_stock"
        assert d["stock_evidence"]
        assert d["buy_url"] == "https://www.walmart.com/ip/123"
        assert d["stock_checked_at"] == "2026-07-01T09:00:00"
        assert d["stock_method"] == "retailer_adapter:walmart"
        assert d["retailer"] == "Walmart"          # no longer the MSRP placeholder


def test_verify_stock_price_mismatch_recomputes_at_observed_price():
    from scanner.discovery import verify as verify_mod

    def verifier(key, product, expected):
        return _fake_verification(expected, state=verify_mod.PRICE_MISMATCH,
                                  verified_price=round(expected * 1.5, 2),
                                  price_matches=False)

    swp = sweep.build_sealed_sweep(
        _cfg(), lambda k, p: _verified_row(), event="sealed",
        sweep_id="2026-07-01-sealed", captured_at="2026-07-01",
        stock_verifier=verifier)
    assert swp["stock_states"] == {"PRICE_MISMATCH": 3}
    by_item = {d["item"]: d for d in swp["deals"]}
    etb = by_item["Fake ETB"]                      # MSRP 49.99 -> observed 1.5x
    observed = round(49.99 * 1.5, 2)
    assert etb["deal_price"] == observed           # verdict basis = verified price
    assert etb["pct_off"] == score.compute_pct_off(observed, etb["market_comp"])
    assert etb["warn_reason"].startswith("PRICE_CHANGED")
    assert "WARN" in etb["badges"]
    assert etb["stock_status"] == "in_stock"       # stock evidence intact


def test_verify_stock_unknown_stays_unknown_and_gate_clean():
    from scanner.discovery import verify as verify_mod

    def verifier(key, product, expected):
        return _fake_verification(expected, state=verify_mod.UNKNOWN_NO_ALERT,
                                  stock_status="unknown", verified_price=None,
                                  price_matches=None, buy_url="", source="",
                                  method="none", evidence="",
                                  degraded_reason="no online-capable adapter")

    swp = sweep.build_sealed_sweep(
        _cfg(), lambda k, p: _verified_row(), event="sealed",
        sweep_id="2026-07-01-sealed", captured_at="2026-07-01",
        stock_verifier=verifier)
    assert swp["stock_states"] == {"UNKNOWN_NO_ALERT": 3}
    for d in swp["deals"]:
        assert d["stock_status"] == "unknown"
        assert d["stock_evidence"] == "no online-capable adapter"  # honest reason
        assert d["retailer"] == "MSRP"             # no fake retailer claim


def test_cli_verify_stock_flag_writes_stock_states_to_manifest(tmp_path):
    # fake catalog has no retailer ids -> the real verifier runs entirely
    # offline and every product terminates UNKNOWN_NO_ALERT (no network).
    cfg = _cfg(min_rows=3)
    cfg.retailers = {}
    rc = sweep.main(["--out", str(tmp_path), "--verify-stock"],
                    comp_lookup=lambda k, p: _verified_row(), cfg=cfg)
    assert rc == 0
    today = date.today().isoformat()
    manifest = json.loads((tmp_path / "data" / "poke" / f"{today}-sealed.manifest.json")
                          .read_text(encoding="utf-8"))
    assert manifest["stock_states"] == {"UNKNOWN_NO_ALERT": 3}


# ---------------------------------------------------------------- CompEngine wiring


@pytest.fixture
def poke_cfg():
    return _cfg()


def test_livecomplookup_inhouse_engine_selected(poke_cfg):
    from scanner.comps.engine import CompEngine
    from scanner.discovery.sweep import LiveCompLookup
    poke_cfg.comps.engine = "inhouse"
    lookup = LiveCompLookup(poke_cfg)
    assert isinstance(lookup.market_client, CompEngine)


def test_livecomplookup_legacy_default_unchanged(poke_cfg):
    from scanner.comps.engine import CompEngine
    from scanner.discovery.sweep import LiveCompLookup
    poke_cfg.comps.engine = "legacy"
    lookup = LiveCompLookup(poke_cfg)
    assert not isinstance(lookup.market_client, CompEngine)
