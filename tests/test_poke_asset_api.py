"""Track D2 — owned asset endpoints + /cards compat via router dispatch.

Injected fakes; refresh=false must never call the card client (read-first, 0
credits). Proves per-identity history/momentum (#6), honest none, and that the
sealed routes are untouched (#1)."""
from __future__ import annotations

from scanner import config as cfg_mod
from scanner.poke_api import history, router, sources


ASSETS = {
    "umbreon_raw_nm": {"asset_class": "raw", "name": "Umbreon ex",
                       "set": "Prismatic Evolutions", "card_number": "161",
                       "condition": "NM", "tcgplayer_id": "999001"},
    "umbreon_raw_lp": {"asset_class": "raw", "name": "Umbreon ex",
                       "set": "Prismatic Evolutions", "card_number": "161",
                       "condition": "LP", "tcgplayer_id": "999001"},
    "umbreon_psa10": {"asset_class": "graded", "name": "Umbreon ex",
                      "set": "Prismatic Evolutions", "card_number": "161",
                      "grader": "PSA", "grade": "10", "grade_key": "psa10",
                      "tcgplayer_id": "999001"},
}

PRODUCTS = {
    "prismatic_evolutions_etb": {"name": "Prismatic Evolutions Elite Trainer Box",
                                 "set": "Prismatic Evolutions", "type": "ETB",
                                 "msrp": "$49.99", "ppt_id": "593355"},
}

IK_NM = history.item_key_for_asset(ASSETS["umbreon_raw_nm"])
IK_PSA10 = history.item_key_for_asset(ASSETS["umbreon_psa10"])

OBS = [
    {"item_key": IK_NM, "kind": "market_comp", "comp": 40.0, "capture_date": "2026-07-01",
     "source": "tcgplayer", "comp_confidence": "low"},
    {"item_key": IK_NM, "kind": "market_comp", "comp": 45.0, "capture_date": "2026-07-03",
     "source": "tcgplayer", "comp_confidence": "low"},
    {"item_key": IK_PSA10, "kind": "market_comp", "comp": 250.0, "capture_date": "2026-07-02",
     "source": "ppt_cards", "comp_confidence": "high"},
    {"item_key": IK_PSA10, "kind": "market_comp", "comp": 260.0, "capture_date": "2026-07-04",
     "source": "ppt_cards", "comp_confidence": "high"},
]


class _StubProvider:
    """Read-first comp provider stub for the sealed path (no cache -> ledger)."""
    def cached(self, key, product):
        return None

    def estimate(self, key, product):
        return {}


class FakeCardClient:
    def __init__(self):
        self.raw_calls = 0
        self.graded_calls = 0

    def raw_quote(self, asset, checked_at):
        self.raw_calls += 1
        from scanner.comps.model import SOLD_DERIVED, CompSourceQuote
        return CompSourceQuote("ppt_cards", SOLD_DERIVED, "ok", 120.0, "https://tcg/x",
                               "2026-07-05")

    def graded_smart(self, asset, checked_at):
        self.graded_calls += 1
        return sources.GradedSmartPrice(300.0, "high", "https://tcg/x", "psa10")


def _cfg():
    return cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})


def _deps(*, observations=None, card_client=None, products=None, today="2026-07-05"):
    return router.PokeApiDeps(
        products=products if products is not None else {},
        assets=ASSETS,
        read_observations=lambda: list(OBS if observations is None else observations),
        comp_provider=_StubProvider(),
        card_client=card_client,
        today=today,
        cfg=_cfg(),
    )


def _status(payload):
    return payload.get("httpStatus", 200)


# --- /api/poke/assets ---------------------------------------------------------

def test_assets_lists_catalog():
    payload = router.handle_get("/api/poke/assets", {}, _deps())
    assert _status(payload) == 200
    keys = {a["asset_key"] for a in payload["assets"]}
    assert keys == set(ASSETS)
    psa = next(a for a in payload["assets"] if a["asset_key"] == "umbreon_psa10")
    assert psa["asset_class"] == "graded" and psa["grade_key"] == "psa10"


# --- /api/poke/assets/{key}/comp ----------------------------------------------

def test_asset_comp_read_first_serves_ledger_no_client_call():
    client = FakeCardClient()
    payload = router.handle_get(
        "/api/poke/assets/umbreon_raw_nm/comp", {}, _deps(card_client=client))
    assert _status(payload) == 200
    assert payload["estimate"] == 45.0          # latest ledger comp
    assert payload["status"] == "ok"
    assert client.raw_calls == 0                # read-first: never a network source


def test_asset_comp_no_ledger_is_honest_none():
    client = FakeCardClient()
    payload = router.handle_get(
        "/api/poke/assets/umbreon_raw_lp/comp", {}, _deps(card_client=client))
    assert payload["estimate"] is None
    assert payload["confidence"] == "none"
    assert client.raw_calls == 0


def test_asset_comp_refresh_true_calls_source():
    client = FakeCardClient()
    payload = router.handle_get(
        "/api/poke/assets/umbreon_raw_nm/comp", {"refresh": "true"}, _deps(card_client=client))
    assert client.raw_calls == 1
    assert payload["estimate"] == 120.0
    assert payload["confidence"] == "low"       # single sold-derived, uncorroborated


def test_asset_comp_unknown_key_404():
    assert _status(router.handle_get("/api/poke/assets/nope/comp", {}, _deps())) == 404


# --- /api/poke/assets/{key}/history + /momentum (#6 per-identity) -------------

def test_asset_history_is_per_identity():
    nm = router.handle_get("/api/poke/assets/umbreon_raw_nm/history", {}, _deps())
    psa = router.handle_get("/api/poke/assets/umbreon_psa10/history", {}, _deps())
    assert [pt["price"] for pt in nm["priceHistory"]] == [40.0, 45.0]
    assert [pt["price"] for pt in psa["priceHistory"]] == [250.0, 260.0]
    assert nm["item_key"] != psa["item_key"]


def test_asset_momentum_is_per_identity():
    nm = router.handle_get("/api/poke/assets/umbreon_raw_nm/momentum", {}, _deps())["momentum"]
    psa = router.handle_get("/api/poke/assets/umbreon_psa10/momentum", {}, _deps())["momentum"]
    assert nm["latest"] == 45.0 and nm["previous"] == 40.0 and nm["delta_abs"] == 5.0
    assert psa["latest"] == 260.0 and psa["previous"] == 250.0 and psa["delta_abs"] == 10.0


def test_asset_history_momentum_unknown_key_404():
    assert _status(router.handle_get("/api/poke/assets/nope/history", {}, _deps())) == 404
    assert _status(router.handle_get("/api/poke/assets/nope/momentum", {}, _deps())) == 404


# --- /api/poke/cards (compat; explicit raw condition + graded grade) ----------

def test_cards_missing_id_is_400():
    assert _status(router.handle_get("/api/poke/cards", {}, _deps())) == 400


def test_cards_raw_by_condition():
    payload = router.handle_get(
        "/api/poke/cards", {"tcgPlayerId": "999001", "condition": "NM"}, _deps())
    assert payload["data"]["asset_key"] == "umbreon_raw_nm"
    assert payload["data"]["condition"] == "NM"
    assert payload["data"]["estimate"] == 45.0
    assert payload["metadata"]["apiCallsConsumed"]["total"] == 0


def test_cards_graded_by_grade():
    payload = router.handle_get(
        "/api/poke/cards", {"tcgPlayerId": "999001", "grade": "psa10"}, _deps())
    assert payload["data"]["asset_key"] == "umbreon_psa10"
    assert payload["data"]["grade_key"] == "psa10"
    assert payload["data"]["estimate"] == 260.0


def test_cards_ambiguous_without_discriminator():
    payload = router.handle_get("/api/poke/cards", {"tcgPlayerId": "999001"}, _deps())
    assert payload["data"]["status"] == "ambiguous"
    assert payload["data"]["estimate"] is None        # never a wrong pick
    assert {c["asset_key"] for c in payload["data"]["candidates"]} == set(ASSETS)


def test_cards_unknown_id_is_no_match_not_error():
    payload = router.handle_get("/api/poke/cards", {"tcgPlayerId": "000000"}, _deps())
    assert _status(payload) == 200
    assert payload["data"]["status"] == "no_match"
    assert payload["data"]["estimate"] is None


# --- #1 sealed routes untouched ----------------------------------------------

def test_products_endpoint_excludes_assets():
    payload = router.handle_get("/api/poke/products", {}, _deps(products=PRODUCTS))
    keys = {p["product_key"] for p in payload["products"]}
    assert keys == set(PRODUCTS)                # assets never leak into /products


def test_sealed_products_facade_still_works():
    payload = router.handle_get(
        "/api/poke/sealed-products", {"tcgPlayerId": "593355"}, _deps(products=PRODUCTS))
    assert payload["data"]["tcgPlayerId"] == "593355"
    assert payload["metadata"]["apiCallsConsumed"]["total"] == 0


def test_malformed_asset_catalog_does_not_break_sealed(tmp_path):
    """A bad assets.yaml must NOT take the sealed catalog offline (proof #1); the
    failure is contained + surfaced honestly on the asset routes (no silent empty)."""
    bad = tmp_path / "assets.yaml"
    bad.write_text("bad_raw:\n  asset_class: raw\n  name: X\n  set: S\n",  # raw missing condition
                   encoding="utf-8")
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    deps = router.build_deps(cfg, assets_path=bad, today="2026-07-05")

    prod = router.handle_get("/api/poke/products", {}, deps)
    assert prod["ok"] is True and prod["count"] == len(cfg.products)   # sealed unaffected

    assets = router.handle_get("/api/poke/assets", {}, deps)           # honest error, not empty
    assert assets["ok"] is False and "asset catalog" in assets["error"].lower()
    assert _status(assets) == 500


def test_syntactically_malformed_yaml_does_not_break_sealed(tmp_path):
    """A genuinely unparseable assets.yaml (YAML scanner error, not just a missing
    field) must ALSO stay contained — build_deps must not raise, sealed routes stay
    up, and the asset routes surface the failure honestly (regression guard)."""
    bad = tmp_path / "assets.yaml"
    bad.write_text("umbreon_psa10:\n  asset_class: graded\n\tname: bad tab indent\n",
                   encoding="utf-8")
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    deps = router.build_deps(cfg, assets_path=bad, today="2026-07-05")  # must not raise

    prod = router.handle_get("/api/poke/products", {}, deps)
    assert prod["ok"] is True and prod["count"] == len(cfg.products)   # sealed unaffected

    assets = router.handle_get("/api/poke/assets", {}, deps)
    assert assets["ok"] is False and _status(assets) == 500           # honest error, not empty
    cards = router.handle_get("/api/poke/cards", {"tcgPlayerId": "999001"}, deps)
    assert _status(cards) == 500                                      # asset routes guarded too


def test_invalid_encoding_asset_catalog_does_not_break_sealed(tmp_path):
    """Containment must hold for a non-UnicodeDecodeError-clean catalog too (invalid
    UTF-8 bytes / unreadable file are NOT AssetCatalogError/YAMLError): build_deps
    still must not raise, and sealed routes stay up (regression guard for dim. 2)."""
    bad = tmp_path / "assets.yaml"
    bad.write_bytes(b"umbreon:\n  asset_class: raw\n  name: caf\xe9 bad byte\n  set: s\n"
                    b"  condition: NM\n")  # lone 0xe9 is invalid UTF-8
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    deps = router.build_deps(cfg, assets_path=bad, today="2026-07-05")  # must not raise

    prod = router.handle_get("/api/poke/products", {}, deps)
    assert prod["ok"] is True and prod["count"] == len(cfg.products)   # sealed unaffected
    assets = router.handle_get("/api/poke/assets", {}, deps)
    assert assets["ok"] is False and _status(assets) == 500           # honest error, not empty
