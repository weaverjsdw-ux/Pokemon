"""Phase G — read-only grading-EV endpoint (/api/poke/grading-ev/<asset_key>).

Ledger-only: the raw comp, graded-sibling comp, and gem rate all come from recorded
rows — the read path never fetches PriceCharting live, never spends a PPT credit, and
is capped at PAPER_BUY (a gem rate is a population proxy, never LIVE)."""
from __future__ import annotations

from scanner import config as cfg_mod
from scanner.poke_api import candidates as cand
from scanner.poke_api import gem_rates, history, router


RAW_KEY = "umbreon_ex_161_raw_nm"
ASSETS = {
    RAW_KEY: {"asset_class": "raw", "name": "Umbreon ex 161", "set": "Prismatic Evolutions",
              "card_number": "161", "condition": "NM", "tcgplayer_id": "610516"},
    "umbreon_ex_161_psa10": {"asset_class": "graded", "name": "Umbreon ex 161",
                             "set": "Prismatic Evolutions", "card_number": "161",
                             "grader": "PSA", "grade": "10", "grade_key": "psa10",
                             "tcgplayer_id": "610516"},
}
IK_RAW = history.item_key_for_asset(ASSETS[RAW_KEY])
IK_PSA10 = history.item_key_for_asset(ASSETS["umbreon_ex_161_psa10"])
OBS = [
    {"item_key": IK_RAW, "kind": "market_comp", "comp": 400.0, "capture_date": "2026-07-06",
     "source": "pricecharting", "comp_confidence": "low"},
    {"item_key": IK_PSA10, "kind": "market_comp", "comp": 1575.0, "capture_date": "2026-07-06",
     "source": "pricecharting", "comp_confidence": "low"},
]


class _FailingCardClient:
    def raw_quote(self, asset, checked_at):
        raise AssertionError("grading-ev read must not make a billed raw call")

    def graded_smart(self, asset, checked_at):
        raise AssertionError("grading-ev read must not make a billed graded call")


def _cfg():
    return cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "opportunity": {"live_min_expected_net": 25.0, "live_min_roi_pct": 30.0,
                        "live_min_confidence": "medium",
                        "max_hold_days": {"raw_grading_ev": 45},
                        "exit_venue": {"raw_grading_ev": "ebay"}}})


def _verified_entry():
    return cand.build_record(cand.make_candidate(
        source="manual_verified", product_key=RAW_KEY, entry_price=300.0,
        buy_url="https://shop/x", stock_status="verified_buyable", stock_evidence="e",
        stock_checked_at="2026-07-06", observed_at="2026-07-06", retailer="LGS",
        asset_class="raw", asset_key=RAW_KEY, condition="NM"))


def _deps(*, gem_rows=None, candidate_rows=None, today="2026-07-06"):
    crows = list(candidate_rows or [])
    grows = list(gem_rows or [])
    return router.PokeApiDeps(
        products={}, assets=ASSETS, read_observations=lambda: list(OBS),
        comp_provider=type("P", (), {"cached": lambda s, k, p: None,
                                     "estimate": lambda s, k, p: {}})(),
        today=today, cfg=_cfg(),
        candidate_for=cand.candidate_for_provider(crows),
        asset_candidate_for=cand.asset_candidate_for_provider(crows),
        read_candidates=lambda: crows,
        read_gem_rates=lambda: grows,
        card_client=_FailingCardClient())


def _get(deps, asset_key):
    return router.handle_get(f"/api/poke/grading-ev/{asset_key}", {}, deps)


# ---------------------------------------------------------------- computed number

def _sourced_gem_rows():
    path_rows: list[dict] = []
    row = gem_rates.build_sourced_row(
        asset_key=RAW_KEY, grader="PSA",
        counts=[1, 2, 4, 15, 43, 161, 428, 2654, 9195, 5487],
        source_url="https://www.pricecharting.com/game/x/umbreon-ex-161",
        capture_date="2026-07-06")
    path_rows.append(row)
    return path_rows


def test_endpoint_computes_paper_number_with_provenance():
    deps = _deps(gem_rows=_sourced_gem_rows(), candidate_rows=[_verified_entry()])
    r = _get(deps, RAW_KEY)
    assert r["ok"] is True
    ev = r["grading_ev"]
    assert ev["status"] in ("actionable", "watch")          # a number, never blocked
    assert ev["expected_net"] is not None
    assert ev["breakeven_gem_rate"] is not None
    assert ev["sensitivity"]                                  # band present
    assert r["capped_at"] == "PAPER_BUY"                     # never LIVE
    prov = r["gem_rate_provenance"]
    assert prov["label"] == "sourced"
    assert prov["sample_size"] == 17990
    assert prov["sample_status"] == "sufficient"


def test_endpoint_blocks_with_named_inputs_when_no_gem_rate():
    deps = _deps(gem_rows=[], candidate_rows=[_verified_entry()])
    r = _get(deps, RAW_KEY)
    ev = r["grading_ev"]
    assert ev["status"] == "blocked"
    assert any("gem rate" in b.lower() for b in ev["blockers"])
    assert ev["expected_net"] is None                        # no dollar output when blocked
    assert r["gem_rate_provenance"]["sample_status"] == "no_gem_rate"


def test_endpoint_gem_rate_only_no_entry_stays_blocked_never_buy():
    """The no-gem-rate-only-promotion guard: a gem rate + comps but NO verified entry
    never yields a dollar buy — grading EV blocks on the missing entry (WATCH, not BUY)."""
    deps = _deps(gem_rows=_sourced_gem_rows(), candidate_rows=[])   # no verified entry
    r = _get(deps, RAW_KEY)
    ev = r["grading_ev"]
    assert ev["status"] == "blocked"
    assert any("raw entry" in b.lower() for b in ev["blockers"])
    assert ev["expected_net"] is None


def test_endpoint_sample_status_uses_recorded_floor_not_default():
    """A sourced row recorded against a custom floor (200) with n=250 reads back as
    `sufficient` — provenance judges against the RECORDED floor, not the default 300."""
    row = gem_rates.build_sourced_row(
        asset_key=RAW_KEY, grader="PSA",
        counts=[0, 0, 0, 0, 0, 0, 0, 50, 150, 50],   # total 250 (>= 200, < 300)
        source_url="https://www.pricecharting.com/game/x/umbreon-ex-161",
        capture_date="2026-07-06", sample_floor=200)
    deps = _deps(gem_rows=[row], candidate_rows=[_verified_entry()])
    prov = _get(deps, RAW_KEY)["gem_rate_provenance"]
    assert prov["sample_size"] == 250
    assert prov["sample_floor"] == 200
    assert prov["sample_status"] == "sufficient"          # not "below_floor"


def test_endpoint_operator_assumption_labeled():
    asm = gem_rates.build_assumption_row(
        asset_key=RAW_KEY, grader="PSA", gem_rate=0.30,
        basis="operator base rate", capture_date="2026-07-06")
    deps = _deps(gem_rows=[asm], candidate_rows=[_verified_entry()])
    prov = _get(deps, RAW_KEY)["gem_rate_provenance"]
    assert prov["label"] == "operator_assumption"
    assert prov["sample_status"] == "operator_assumption"


def test_endpoint_is_ledger_only_never_network():
    # _FailingCardClient + no live pop source: a green read proves 0 network, 0 credits.
    deps = _deps(gem_rows=_sourced_gem_rows(), candidate_rows=[_verified_entry()])
    r = _get(deps, RAW_KEY)
    assert r["ok"] is True                                    # no AssertionError from failing client


def test_endpoint_unknown_asset_404():
    r = _get(_deps(), "nope")
    assert r["ok"] is False and r["httpStatus"] == 404


def test_endpoint_non_raw_rejected():
    r = _get(_deps(), "umbreon_ex_161_psa10")
    assert r["ok"] is False and r["httpStatus"] == 400
