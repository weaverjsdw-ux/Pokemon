"""Session E Slice H — off-hot-path API-vs-external divergence audit.

The classifier is pure. The engine's dry/local mode spends 0 network/credits; the
external mode is money-class (refuses without a key + operator --yes, prints the
estimated spend, hard-stops on a remaining-credit floor). Material UNEXPLAINED
divergence fails the audit. Clients are injected — no live calls in tests."""
from __future__ import annotations

from scanner import config as cfg_mod
from scanner.poke_api import divergence as dv
from scanner.poke_api import history, router


# ---------------------------------------------------------------- classifier (pure)

def test_classify_agree_within_tolerance():
    r = dv.classify_divergence({"estimate": 100.0, "confidence": "high"},
                               {"estimate": 105.0, "confidence": "high"}, tolerance_pct=20.0)
    assert r["category"] == "agree"
    assert r["material"] is False and r["blocking"] is False


def test_classify_no_external_reference():
    r = dv.classify_divergence({"estimate": 100.0}, None, tolerance_pct=20.0)
    assert r["category"] == "no_external_reference"
    assert r["blocking"] is False


def test_classify_provider_payload_issue():
    r = dv.classify_divergence({"estimate": 100.0}, {"estimate": None, "error": True})
    assert r["category"] == "provider_payload_issue"


def test_classify_ask_only_missing_local():
    r = dv.classify_divergence({"estimate": None, "ask_only": True},
                               {"estimate": 250.0, "confidence": "high"})
    assert r["category"] == "ask_vs_sold_difference"
    assert "ask" in r["note"].lower()


def test_classify_source_policy_missing_local():
    r = dv.classify_divergence({"estimate": None, "ask_only": False},
                               {"estimate": 250.0, "confidence": "high"})
    assert r["category"] == "source_policy_difference"


def test_classify_stale_local_explains_material_gap():
    r = dv.classify_divergence({"estimate": 100.0, "stale": True},
                               {"estimate": 200.0, "confidence": "high"}, tolerance_pct=20.0)
    assert r["category"] == "stale_local"
    assert r["material"] is True and r["blocking"] is False   # explained -> not blocking


def test_classify_unexplained_material_is_blocking():
    r = dv.classify_divergence({"estimate": 100.0, "confidence": "high"},
                               {"estimate": 160.0, "confidence": "high"}, tolerance_pct=20.0)
    assert r["category"] == "unexplained_material_divergence"
    assert r["material"] is True and r["blocking"] is True


def test_classify_huge_gap_is_mapping_error_not_blocking():
    r = dv.classify_divergence({"estimate": 50.0, "confidence": "high"},
                               {"estimate": 5000.0, "confidence": "high"}, tolerance_pct=20.0)
    assert r["category"] == "mapping_error"
    assert r["blocking"] is False                              # a known-defect category, flagged not fatal


# ---------------------------------------------------------------- local/dry engine

ASSETS = {
    "umbreon_psa10": {"asset_class": "graded", "name": "Umbreon ex 161",
                      "set": "Prismatic Evolutions", "card_number": "161",
                      "grader": "PSA", "grade": "10", "grade_key": "psa10",
                      "tcgplayer_id": "610516"},
}
IK = history.item_key_for_asset(ASSETS["umbreon_psa10"])


class _NoProvider:
    def cached(self, k, p):
        return None

    def estimate(self, k, p):
        raise AssertionError("local audit must not estimate")


class _FailingClient:
    def raw_quote(self, a, c):
        raise AssertionError("local audit must not call external")

    def graded_smart(self, a, c):
        raise AssertionError("local audit must not call external")


def _cfg(**over):
    raw = {"locations": {"home": "A", "work": "B"}}
    raw.update(over)
    return cfg_mod.from_mapping(raw)


def _deps(observations, *, market_api_key=""):
    cfg = _cfg()
    cfg.market_api_key = market_api_key
    return router.PokeApiDeps(
        products={}, assets=ASSETS, read_observations=lambda: list(observations),
        comp_provider=_NoProvider(), today="2026-07-06", cfg=cfg,
        card_client=_FailingClient())


def test_audit_local_zero_credits_agree():
    obs = [
        {"item_key": IK, "kind": "market_comp", "comp": 6900.0, "capture_date": "2026-07-05",
         "source": "pricecharting", "comp_confidence": "medium"},   # our local comp
        {"item_key": IK, "kind": "market_comp", "comp": 6925.5, "capture_date": "2026-07-05",
         "source": "ppt_cards", "comp_confidence": "high"},         # external reference
    ]
    result = dv.audit_local(_deps(obs), asset_keys=["umbreon_psa10"], tolerance_pct=20.0)
    assert result["failed"] is False
    row = result["rows"][0]
    assert row["category"] == "agree"
    assert result["credits_spent"] == 0


def test_audit_local_flags_unexplained_material():
    obs = [
        {"item_key": IK, "kind": "market_comp", "comp": 3000.0, "capture_date": "2026-07-05",
         "source": "pricecharting", "comp_confidence": "high"},
        {"item_key": IK, "kind": "market_comp", "comp": 6925.5, "capture_date": "2026-07-05",
         "source": "ppt_cards", "comp_confidence": "high"},
    ]
    result = dv.audit_local(_deps(obs), asset_keys=["umbreon_psa10"], tolerance_pct=20.0)
    assert result["rows"][0]["category"] == "mapping_error"       # >150% gap
    # a moderate unexplained gap is blocking:
    obs2 = [
        {"item_key": IK, "kind": "market_comp", "comp": 5000.0, "capture_date": "2026-07-05",
         "source": "pricecharting", "comp_confidence": "high"},
        {"item_key": IK, "kind": "market_comp", "comp": 6925.5, "capture_date": "2026-07-05",
         "source": "ppt_cards", "comp_confidence": "high"},
    ]
    r2 = dv.audit_local(_deps(obs2), asset_keys=["umbreon_psa10"], tolerance_pct=20.0)
    assert r2["rows"][0]["category"] == "unexplained_material_divergence"
    assert r2["failed"] is True


# ---------------------------------------------------------------- external (guarded)

class _FakeSealedClient:
    def __init__(self, rows):
        self.rows, self.calls = rows, 0

    def estimate(self, key, product, checked_at):
        row = self.rows[self.calls]
        self.calls += 1
        return row


def _sealed_deps(market_api_key="k"):
    cfg = _cfg()
    cfg.market_api_key = market_api_key
    cfg.products = {"a": {"name": "A", "tcgplayer_id": "1", "msrp": "$50"},
                    "b": {"name": "B", "tcgplayer_id": "2", "msrp": "$30"}}
    return router.PokeApiDeps(
        products=cfg.products, assets={}, read_observations=lambda: [],
        comp_provider=_NoProvider(), today="2026-07-06", cfg=cfg)


def test_run_audit_external_refuses_without_key():
    deps = _sealed_deps(market_api_key="")
    result = dv.run_audit(deps, product_keys=["a"], local=False, yes=True)
    assert result["refused"] is True
    assert "market.api_key" in result["message"]


def test_run_audit_external_refuses_without_yes():
    deps = _sealed_deps()
    result = dv.run_audit(deps, product_keys=["a"], local=False, yes=False)
    assert result["refused"] is True
    assert "--yes" in result["message"]
    assert result["spend_estimate"]["credits"] == 1               # surfaced before refusal


def test_run_audit_external_hard_stops_below_floor():
    client = _FakeSealedClient([
        {"status": "ok", "estimate": "$99.00", "confidence": "high", "dailyRemaining": 9}])
    deps = _sealed_deps()
    result = dv.run_audit(deps, product_keys=["a", "b"], local=False, yes=True,
                          client_sealed=client)
    assert result["hard_stopped"] is True
    assert client.calls == 1                                       # never touched product b


def test_run_audit_external_material_unexplained_fails():
    client = _FakeSealedClient([
        {"status": "ok", "estimate": "$160.00", "confidence": "high", "dailyRemaining": 80}])
    deps = _sealed_deps()
    # our served comp is $100 (cached), theirs $160 -> unexplained material -> fail
    deps.comp_provider = type("P", (), {
        "cached": lambda self, k, p: {"status": "ok", "estimate": "$100.00",
                                      "confidence": "high", "sources": [{"source": "pricecharting"}]},
        "estimate": lambda self, k, p: {}})()
    result = dv.run_audit(deps, product_keys=["a"], local=False, yes=True, client_sealed=client)
    assert result["failed"] is True
    assert any(r["category"] == "unexplained_material_divergence" for r in result["rows"])
