"""Owned API response shaping + a drop-in-compatible sealed facade.

Adapts the existing legacy comp rows (comps/model.to_legacy_row, market.py,
cached rows) into a stable owned shape so callers never touch source internals,
and emits a payload close enough to a common external ``/sealed-products`` shape
for local drop-in compatibility. Pure: no network, no external provider call,
always 0 credits. (Retained provider-shaped field names — ``ppt_id``,
``unopenedPrice`` — are documented compat aliases, not the program's identity;
``tcgPlayerId`` is the preferred key.)
"""
from __future__ import annotations

from typing import Any

from .. import market as market_mod
from .. import resale
from . import history as history_mod


def _tcg_player_id(product: dict) -> str | None:
    # ``ppt_id`` / ``ppt_query`` are the sealed catalog's (products.yaml) legacy field
    # names for the TCGplayer product id — retained as config compat, read here only.
    raw = str(product.get("tcgplayer_id") or product.get("ppt_id")
              or product.get("ppt_query") or "").strip()
    return raw or None


def _tcg_player_url(comp_row: dict | None) -> str:
    row = comp_row or {}
    return str(row.get("sourceUrl") or row.get("url") or "")


def product_summary(product_key: str, product: dict) -> dict[str, Any]:
    """Catalog product -> owned summary for /api/poke/products."""
    ppt_id = _tcg_player_id(product)
    return {
        "product_key": product_key,
        "name": product.get("name") or product_key,
        "set": product.get("set", ""),
        "type": product.get("type", ""),
        "msrp": resale._amount(product.get("msrp")),
        "tcgPlayerId": ppt_id,
        "ppt_id": ppt_id,
    }


def comp_response(product_key: str, product: dict, comp_row: dict, *,
                  cache_hit: bool | None = None) -> dict[str, Any]:
    """Adapt a legacy comp row (CompEngine / market / cache) into owned shape.

    Numeric ``estimate`` (and its compat alias ``unopenedPrice``) come from
    market.comp_from_row so a no-match/degraded row honestly reports None,
    never an invented number."""
    row = comp_row or {}
    comp, _conf = market_mod.comp_from_row(row)
    resolved_cache_hit = bool(row.get("cacheHit")) if cache_hit is None else cache_hit
    return {
        "product_key": product_key,
        "name": product.get("name") or product_key,
        "set": product.get("set", ""),
        "tcgPlayerId": _tcg_player_id(product),
        "ppt_id": _tcg_player_id(product),
        "status": str(row.get("status") or "no_match"),
        "estimate": comp,
        "unopenedPrice": comp,
        "confidence": str(row.get("confidence") or "none"),
        "confidenceReason": str(row.get("confidenceReason") or row.get("detail") or ""),
        "compBasis": str(row.get("compBasis") or row.get("basis") or ""),
        "sources": list(row.get("sources") or []),
        "sourceUrl": str(row.get("sourceUrl") or row.get("url") or ""),
        "url": str(row.get("url") or row.get("sourceUrl") or ""),
        "checkedAt": row.get("checkedAt"),
        "cacheHit": resolved_cache_hit,
        "stale": bool(row.get("stale")),
        "detail": str(row.get("detail") or ""),
    }


def no_comp_response(product_key: str, product: dict, *, status: str,
                     detail: str) -> dict[str, Any]:
    """Honest empty comp (no cache, refresh not requested / no ledger). Never a
    number - price accuracy is STOP-class: no source -> no comp."""
    return {
        "product_key": product_key,
        "name": product.get("name") or product_key,
        "set": product.get("set", ""),
        "tcgPlayerId": _tcg_player_id(product),
        "ppt_id": _tcg_player_id(product),
        "status": status,
        "estimate": None,
        "unopenedPrice": None,
        "confidence": "none",
        "confidenceReason": detail,
        "compBasis": "",
        "sources": [],
        "sourceUrl": "",
        "url": "",
        "checkedAt": None,
        "cacheHit": False,
        "stale": False,
        "detail": detail,
    }


def price_points(observations, item_key: str, *,
                 kind: str = history_mod.MARKET_COMP) -> list[dict[str, Any]]:
    """Chronological {date, price, source, confidence} points for an item from
    the ledger observations - the common ``priceHistory`` array shape."""
    points = []
    for obs in history_mod.filter_observations(observations, item_key=item_key, kind=kind):
        price = history_mod._comp_value(obs)
        if price is None:
            continue
        points.append({
            "date": str(obs.get("capture_date") or ""),
            "price": price,
            "source": history_mod.source_of(obs),
            "confidence": str(obs.get("comp_confidence") or "") or None,
        })
    points.sort(key=lambda p: p["date"])
    return points


def sealed_facade(product_key: str, product: dict, comp_row: dict | None, *,
                  price_history: list | None = None, momentum: dict | None = None,
                  last_scraped_at: str | None = None,
                  updated_at: str | None = None) -> dict[str, Any]:
    """Drop-in-compatible ``/sealed-products`` payload built entirely from local data.

    ``{data: {...}, metadata: {source: 'local', apiCallsConsumed: {total: 0}}}``.
    Structurally 0 credits - this never calls any external price provider."""
    row = comp_row or {}
    comp, _conf = market_mod.comp_from_row(row)
    data = {
        "tcgPlayerId": _tcg_player_id(product),
        "tcgPlayerUrl": _tcg_player_url(comp_row),
        "name": product.get("name") or product_key,
        "setName": product.get("set", ""),
        "unopenedPrice": comp,
        "priceHistory": list(price_history or []),
        "lastScrapedAt": last_scraped_at,
        "updatedAt": updated_at,
        "confidence": str(row.get("confidence") or "none"),
        "confidenceReason": str(row.get("confidenceReason") or row.get("detail") or ""),
        "sources": list(row.get("sources") or []),
        "productKey": product_key,
        "status": str(row.get("status") or "no_match"),
    }
    if momentum is not None:
        data["momentum"] = momentum
    return {
        "data": data,
        "metadata": {"source": "local", "apiCallsConsumed": {"total": 0}},
    }


def no_match_facade(tcg_player_id: str) -> dict[str, Any]:
    """Empty-but-well-formed facade for an unmapped/unknown tcgPlayerId. Never
    raises - a miss is data, not an error."""
    return {
        "data": {
            "tcgPlayerId": tcg_player_id,
            "tcgPlayerUrl": "",
            "name": None,
            "setName": None,
            "unopenedPrice": None,
            "priceHistory": [],
            "lastScrapedAt": None,
            "updatedAt": None,
            "confidence": "none",
            "confidenceReason": "no local product mapped to that tcgPlayerId",
            "sources": [],
            "status": "no_match",
        },
        "metadata": {"source": "local", "apiCallsConsumed": {"total": 0}},
    }
