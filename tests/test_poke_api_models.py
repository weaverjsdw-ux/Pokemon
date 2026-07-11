"""Owned API response shaping + PPT-compatible facade (Track A). Pure."""
from __future__ import annotations

from scanner.poke_api import model


PRODUCT = {
    "name": "Prismatic Evolutions Elite Trainer Box",
    "set": "Prismatic Evolutions",
    "type": "ETB",
    "msrp": "$49.99",
    "ppt_id": "593355",
}

# A legacy comp row, shaped like comps/model.to_legacy_row output.
OK_ROW = {
    "productKey": "prismatic_evolutions_etb",
    "source": "InHouse comp engine",
    "basis": "min(tcgplayer,pricecharting) agree@20%",
    "compBasis": "min(tcgplayer,pricecharting) agree@20%",
    "checkedAt": 1720051200,
    "status": "ok",
    "estimate": "$44.00",
    "confidence": "high",
    "confidenceReason": "two sold-derived sources agree within 20%",
    "sources": [
        {"source": "tcgplayer", "kind": "sold_derived", "status": "ok",
         "price": 44.0, "url": "https://www.tcgplayer.com/product/593355"},
        {"source": "pricecharting", "kind": "sold_derived", "status": "ok",
         "price": 45.5, "url": "https://www.pricecharting.com/game/x/etb"},
    ],
    "sourceUrl": "https://www.tcgplayer.com/product/593355",
    "url": "https://www.tcgplayer.com/product/593355",
}

NO_MATCH_ROW = {
    "productKey": "prismatic_evolutions_etb",
    "status": "no_matches",
    "estimate": "",
    "confidence": "none",
    "confidenceReason": "no usable source; no comp invented",
    "compBasis": "none",
    "sources": [],
    "detail": "no usable comp from any source",
    "checkedAt": 1720051200,
}


# --- product_summary ----------------------------------------------------------

def test_product_summary_exposes_catalog_fields():
    s = model.product_summary("prismatic_evolutions_etb", PRODUCT)
    assert s["product_key"] == "prismatic_evolutions_etb"
    assert s["name"] == "Prismatic Evolutions Elite Trainer Box"
    assert s["set"] == "Prismatic Evolutions"
    assert s["type"] == "ETB"
    assert s["msrp"] == 49.99
    assert s["tcgPlayerId"] == "593355"
    assert s["ppt_id"] == "593355"


def test_product_summary_null_ids_when_unmapped():
    s = model.product_summary("x", {"name": "X", "set": "S", "type": "T", "msrp": ""})
    assert s["tcgPlayerId"] is None
    assert s["msrp"] is None


# --- comp_response ------------------------------------------------------------

def test_comp_response_adapts_ok_row():
    r = model.comp_response("prismatic_evolutions_etb", PRODUCT, OK_ROW, cache_hit=True)
    assert r["product_key"] == "prismatic_evolutions_etb"
    assert r["name"] == PRODUCT["name"]
    assert r["tcgPlayerId"] == "593355"
    assert r["status"] == "ok"
    assert r["estimate"] == 44.0
    assert r["unopenedPrice"] == 44.0
    assert r["confidence"] == "high"
    assert r["confidenceReason"] == "two sold-derived sources agree within 20%"
    assert r["compBasis"] == "min(tcgplayer,pricecharting) agree@20%"
    assert r["sourceUrl"] == "https://www.tcgplayer.com/product/593355"
    assert r["checkedAt"] == 1720051200
    assert r["cacheHit"] is True
    assert [s["source"] for s in r["sources"]] == ["tcgplayer", "pricecharting"]


def test_comp_response_honest_on_no_match():
    r = model.comp_response("prismatic_evolutions_etb", PRODUCT, NO_MATCH_ROW)
    assert r["status"] == "no_matches"
    assert r["estimate"] is None
    assert r["unopenedPrice"] is None
    assert r["confidence"] == "none"
    assert r["detail"] == "no usable comp from any source"


def test_no_comp_response_is_honest_placeholder():
    r = model.no_comp_response("prismatic_evolutions_etb", PRODUCT,
                               status="no_history",
                               detail="no cached comp and refresh not requested")
    assert r["status"] == "no_history"
    assert r["estimate"] is None
    assert r["tcgPlayerId"] == "593355"
    assert r["detail"] == "no cached comp and refresh not requested"


def test_sealed_comp_response_reports_zero_local_on_free_route():
    # a CompEngine-style row (structurally 0-credit) -> field PRESENT, 0/local, never dropped
    row = {"status": "ok", "estimate": "$50.00", "creditsConsumed": 0, "sources": []}
    resp = model.comp_response("pe_etb", {"name": "X", "set": "S"}, row)
    assert resp["apiCallsConsumed"]["total"] == 0
    assert resp["apiCallsConsumed"]["source"] == "local"


def test_sealed_comp_response_preserves_a_billing_rows_credits_never_zeroes_it():
    # a billing provider row (market.py-shaped) must NOT be silently dropped/zeroed
    row = {"status": "ok", "estimate": "$50.00", "creditsConsumed": 1,
           "dailyRemaining": 87, "sources": []}
    resp = model.comp_response("pe_etb", {"name": "X", "set": "S"}, row)
    assert resp["apiCallsConsumed"]["total"] == 1        # preserved, not 0
    assert resp["apiCallsConsumed"]["source"] == "external"
    assert resp.get("dailyRemaining") == 87


# --- price_points -------------------------------------------------------------

def test_price_points_chronological_from_observations():
    obs = [
        {"item_key": "k", "kind": "market_comp", "comp": 44.0,
         "capture_date": "2026-07-03", "source": "tcgplayer", "comp_confidence": "high"},
        {"item_key": "k", "kind": "market_comp", "comp": 40.0,
         "capture_date": "2026-07-01", "source": "pricecharting", "comp_confidence": "low"},
        {"item_key": "other", "kind": "market_comp", "comp": 9.0,
         "capture_date": "2026-07-02"},
    ]
    points = model.price_points(obs, "k")
    assert [p["date"] for p in points] == ["2026-07-01", "2026-07-03"]
    assert points[0] == {"date": "2026-07-01", "price": 40.0,
                         "source": "pricecharting", "confidence": "low"}


# --- sealed_facade (PPT-compatible) -------------------------------------------

def test_sealed_facade_ppt_shape():
    points = [{"date": "2026-07-01", "price": 40.0, "source": "tcgplayer",
               "confidence": "high"}]
    facade = model.sealed_facade(
        "prismatic_evolutions_etb", PRODUCT, OK_ROW,
        price_history=points, last_scraped_at="2026-07-03", updated_at="2026-07-03",
    )
    data = facade["data"]
    assert data["tcgPlayerId"] == "593355"
    assert data["name"] == PRODUCT["name"]
    assert data["setName"] == "Prismatic Evolutions"
    assert data["unopenedPrice"] == 44.0
    assert data["priceHistory"] == points
    assert data["lastScrapedAt"] == "2026-07-03"
    assert data["updatedAt"] == "2026-07-03"
    assert data["confidence"] == "high"
    assert data["confidenceReason"] == "two sold-derived sources agree within 20%"
    assert data["tcgPlayerUrl"] == "https://www.tcgplayer.com/product/593355"
    assert facade["metadata"] == {"source": "local", "apiCallsConsumed": {"total": 0}}


def test_sealed_facade_null_price_when_no_comp():
    facade = model.sealed_facade("prismatic_evolutions_etb", PRODUCT, NO_MATCH_ROW,
                                 price_history=[])
    assert facade["data"]["unopenedPrice"] is None
    assert facade["metadata"]["apiCallsConsumed"]["total"] == 0


def test_no_match_facade_is_empty_but_well_formed():
    facade = model.no_match_facade("999999")
    assert facade["data"]["tcgPlayerId"] == "999999"
    assert facade["data"]["unopenedPrice"] is None
    assert facade["data"]["priceHistory"] == []
    assert facade["data"]["status"] == "no_match"
    assert facade["metadata"] == {"source": "local", "apiCallsConsumed": {"total": 0}}
