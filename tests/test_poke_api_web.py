"""Owned sealed API routes (Track A) — router dispatch with injected fakes.

No network, no live comp sources: refresh=false must never call estimate."""
from __future__ import annotations

from scanner.poke_api import router


PRODUCTS = {
    "prismatic_evolutions_etb": {
        "name": "Prismatic Evolutions Elite Trainer Box",
        "set": "Prismatic Evolutions", "type": "ETB",
        "msrp": "$49.99", "ppt_id": "593355",
    },
    "journey_together_booster_bundle": {
        "name": "Journey Together Booster Bundle",
        "set": "Journey Together", "type": "Booster Bundle",
        "msrp": "$26.94", "ppt_id": "610953",
    },
}

IKEY = "prismatic evolutions|prismatic evolutions elite trainer box|||"

OBS = [
    {"item_key": IKEY, "kind": "market_comp", "comp": 40.0,
     "capture_date": "2026-07-01", "source": "tcgplayer", "comp_confidence": "medium"},
    {"item_key": IKEY, "kind": "market_comp", "comp": 50.0,
     "capture_date": "2026-07-03", "source": "tcgplayer", "comp_confidence": "high"},
    {"item_key": IKEY, "kind": "deal", "deal_price": 26.94,
     "capture_date": "2026-07-03", "source_url": "https://x", "pct_off": 46},
]


class FakeProvider:
    def __init__(self, cached_row=None):
        self.cached_row = cached_row
        self.cached_calls = 0
        self.estimate_calls = 0

    def cached(self, key, product):
        self.cached_calls += 1
        return self.cached_row

    def estimate(self, key, product):
        self.estimate_calls += 1
        return {
            "productKey": key, "status": "ok", "estimate": "$77.00",
            "confidence": "high", "confidenceReason": "fresh fetch",
            "compBasis": "min(tcgplayer,pricecharting)", "sources": [],
            "sourceUrl": "https://tcg/x", "url": "https://tcg/x", "checkedAt": 999,
        }


def _deps(provider=None, observations=None, today="2026-07-04"):
    return router.PokeApiDeps(
        products=PRODUCTS,
        read_observations=lambda: (OBS if observations is None else observations),
        comp_provider=provider or FakeProvider(),
        today=today,
    )


def _status(payload):
    return payload.get("httpStatus", 200)


# --- routing / non-match ------------------------------------------------------

def test_non_poke_path_returns_none():
    assert router.handle_get("/api/status", {}, _deps()) is None
    assert router.handle_get("/", {}, _deps()) is None


def test_unknown_poke_subpath_is_404():
    payload = router.handle_get("/api/poke/nope", {}, _deps())
    assert _status(payload) == 404


# --- /api/poke/products -------------------------------------------------------

def test_products_lists_catalog():
    payload = router.handle_get("/api/poke/products", {}, _deps())
    assert _status(payload) == 200
    keys = {p["product_key"] for p in payload["products"]}
    assert keys == set(PRODUCTS)
    etb = next(p for p in payload["products"] if p["product_key"] == "prismatic_evolutions_etb")
    assert etb["tcgPlayerId"] == "593355"
    assert etb["msrp"] == 49.99


# --- /api/poke/products/{key}/comp -------------------------------------------

def test_comp_uses_cached_row_without_estimate():
    provider = FakeProvider(cached_row={
        "productKey": "prismatic_evolutions_etb", "status": "ok",
        "estimate": "$44.00", "confidence": "high",
        "confidenceReason": "two sources agree", "compBasis": "min(...)",
        "sources": [], "sourceUrl": "https://tcg/x", "url": "https://tcg/x",
        "checkedAt": 100, "cacheHit": True,
    })
    payload = router.handle_get(
        "/api/poke/products/prismatic_evolutions_etb/comp", {}, _deps(provider))
    assert _status(payload) == 200
    assert payload["estimate"] == 44.0
    assert payload["confidence"] == "high"
    assert provider.estimate_calls == 0          # read-only: no network comp


def test_comp_refresh_false_never_calls_estimate():
    provider = FakeProvider(cached_row=None)     # nothing cached
    payload = router.handle_get(
        "/api/poke/products/prismatic_evolutions_etb/comp",
        {"refresh": "false"}, _deps(provider))
    assert provider.estimate_calls == 0
    # falls back to the latest ledger comp (offline)
    assert payload["estimate"] == 50.0
    assert payload["status"] == "ok"


def test_comp_read_only_no_cache_no_ledger_is_honest():
    provider = FakeProvider(cached_row=None)
    payload = router.handle_get(
        "/api/poke/products/journey_together_booster_bundle/comp", {},
        _deps(provider, observations=[]))
    assert provider.estimate_calls == 0
    assert payload["estimate"] is None
    assert payload["status"] == "no_history"


def test_comp_refresh_true_calls_estimate():
    provider = FakeProvider()
    payload = router.handle_get(
        "/api/poke/products/prismatic_evolutions_etb/comp",
        {"refresh": "true"}, _deps(provider))
    assert provider.estimate_calls == 1
    assert payload["estimate"] == 77.0
    assert payload["confidenceReason"] == "fresh fetch"


def test_comp_unknown_product_is_404():
    payload = router.handle_get("/api/poke/products/nope/comp", {}, _deps())
    assert _status(payload) == 404
    assert payload["ok"] is False


# --- /api/poke/products/{key}/history ----------------------------------------

def test_history_grouped_by_source_and_kind():
    payload = router.handle_get(
        "/api/poke/products/prismatic_evolutions_etb/history", {}, _deps())
    assert _status(payload) == 200
    assert "tcgplayer" in payload["bySource"]
    assert payload["byKind"]["market_comp"] == 2
    assert payload["byKind"]["deal"] == 1
    assert [pt["price"] for pt in payload["priceHistory"]] == [40.0, 50.0]


# --- /api/poke/products/{key}/momentum ---------------------------------------

def test_momentum_summary():
    payload = router.handle_get(
        "/api/poke/products/prismatic_evolutions_etb/momentum", {}, _deps())
    assert _status(payload) == 200
    m = payload["momentum"]
    assert m["status"] == "ok"
    assert m["latest"] == 50.0
    assert m["previous"] == 40.0
    assert m["delta_abs"] == 10.0


def test_momentum_unknown_product_is_404():
    payload = router.handle_get("/api/poke/products/nope/momentum", {}, _deps())
    assert _status(payload) == 404


# --- /api/poke/sealed-products (PPT facade) ----------------------------------

def test_sealed_facade_for_mapped_id():
    provider = FakeProvider(cached_row={
        "status": "ok", "estimate": "$44.00", "confidence": "high",
        "confidenceReason": "agree", "sources": [], "sourceUrl": "https://tcg/x",
        "url": "https://tcg/x",
    })
    payload = router.handle_get(
        "/api/poke/sealed-products", {"tcgPlayerId": "593355"}, _deps(provider))
    assert payload["data"]["tcgPlayerId"] == "593355"
    assert payload["data"]["name"] == "Prismatic Evolutions Elite Trainer Box"
    assert payload["data"]["unopenedPrice"] == 44.0
    assert payload["data"]["priceHistory"]                       # populated from ledger
    assert payload["metadata"] == {"source": "local", "apiCallsConsumed": {"total": 0}}


def test_sealed_facade_unknown_id_is_no_match_not_error():
    payload = router.handle_get(
        "/api/poke/sealed-products", {"tcgPlayerId": "000000"}, _deps())
    assert _status(payload) == 200
    assert payload["data"]["status"] == "no_match"
    assert payload["data"]["unopenedPrice"] is None
    assert payload["metadata"]["apiCallsConsumed"]["total"] == 0


def test_sealed_facade_missing_id_is_400():
    payload = router.handle_get("/api/poke/sealed-products", {}, _deps())
    assert _status(payload) == 400


# --- web.py dispatch (config -> deps -> router), no socket -------------------

class _Cfg:
    products = PRODUCTS


def test_web_dispatch_builds_deps_and_routes(monkeypatch):
    from scanner import web
    monkeypatch.setattr(web, "_load_current_config", lambda: (_Cfg(), False))
    payload = web.handle_poke_get("/api/poke/products", {})
    assert {p["product_key"] for p in payload["products"]} == set(PRODUCTS)


def test_web_dispatch_non_poke_path_returns_none(monkeypatch):
    from scanner import web
    monkeypatch.setattr(web, "_load_current_config", lambda: (_Cfg(), False))
    assert web.handle_poke_get("/api/status", {}) is None
