"""Owned response shaping for raw/graded assets (Track D2).

Adapts an asset comp row (from ``sources`` or the ledger) into a stable owned
shape, and emits a drop-in-compatible ``/cards`` card facade. Pure: no network, no
external provider call, always 0 credits. Numeric ``estimate`` comes from ``market.comp_from_row``
so a no-source/degraded row honestly reports ``None`` — never an invented number.
"""
from __future__ import annotations

from typing import Any

from .. import market as market_mod


def _tcg_player_id(asset: dict) -> str | None:
    raw = str(asset.get("tcgplayer_id") or "").strip()
    return raw or None


def _identity(asset_key: str, asset: dict) -> dict[str, Any]:
    return {
        "asset_key": asset_key,
        "asset_class": str(asset.get("asset_class") or ""),
        "name": asset.get("name") or asset_key,
        "set": asset.get("set", ""),
        "card_number": asset.get("card_number"),
        "condition": asset.get("condition"),
        "grader": asset.get("grader"),
        "grade": asset.get("grade"),
        "grade_key": asset.get("grade_key"),
        "tcgPlayerId": _tcg_player_id(asset),
    }


def _api_meta(api_calls: int = 0, *, estimated: bool = False,
              source: str | None = None) -> dict[str, Any]:
    """Billable-surface accounting block. ``source`` is ``"external"`` iff a billable
    request was issued (else ``"local"``); ``apiCallsConsumed.total`` is the credit
    spend (0 on every read path). ``estimated`` marks a deterministic bound."""
    total = int(api_calls or 0)
    return {
        "source": source or ("external" if total > 0 else "local"),
        "apiCallsConsumed": {"total": total, "estimated": bool(estimated)},
    }


def asset_comp_response(asset_key: str, asset: dict, comp_row: dict, *,
                        cache_hit: bool | None = None, api_calls: int = 0,
                        api_calls_estimated: bool = False,
                        source: str | None = None) -> dict[str, Any]:
    """Adapt an asset comp row into owned shape. ``estimate`` honestly ``None`` when
    the row is not an ``ok`` sold/graded source. ``metadata.apiCallsConsumed.total``
    reports credits spent — 0 on every read path; a bounded spend on a configured
    ``refresh=true`` external lookup (never 0 on a path that made a billable request)."""
    row = comp_row or {}
    comp, _conf = market_mod.comp_from_row(row)
    resolved_cache_hit = bool(row.get("cacheHit")) if cache_hit is None else cache_hit
    return {
        **_identity(asset_key, asset),
        "status": str(row.get("status") or "no_match"),
        "estimate": comp,
        "confidence": str(row.get("confidence") or "none"),
        "confidenceReason": str(row.get("confidenceReason") or row.get("detail") or ""),
        "compBasis": str(row.get("compBasis") or row.get("basis") or ""),
        "sources": list(row.get("sources") or []),
        "sourceUrl": str(row.get("sourceUrl") or row.get("url") or ""),
        "checkedAt": row.get("checkedAt"),
        "cacheHit": resolved_cache_hit,
        "stale": bool(row.get("stale")),
        "detail": str(row.get("detail") or ""),
        "metadata": _api_meta(api_calls, estimated=api_calls_estimated, source=source),
    }


def asset_no_comp_response(asset_key: str, asset: dict, *, status: str,
                           detail: str, api_calls: int = 0,
                           api_calls_estimated: bool = False,
                           source: str | None = None) -> dict[str, Any]:
    """Honest empty asset comp (no ledger, refresh not requested / no exact source).
    Never a number — STOP-class: no source -> no comp. Reports 0 credits by default."""
    return {
        **_identity(asset_key, asset),
        "status": status,
        "estimate": None,
        "confidence": "none",
        "confidenceReason": detail,
        "compBasis": "",
        "sources": [],
        "sourceUrl": "",
        "checkedAt": None,
        "cacheHit": False,
        "stale": False,
        "detail": detail,
        "metadata": _api_meta(api_calls, estimated=api_calls_estimated, source=source),
    }


# ---------------------------------------------------------------- /cards facade

def _facade(data: dict) -> dict[str, Any]:
    return {"data": data, "metadata": {"source": "local", "apiCallsConsumed": {"total": 0}}}


def card_facade(asset_key: str, asset: dict, comp_row: dict | None, *,
                price_history: list | None = None,
                momentum: dict | None = None) -> dict[str, Any]:
    """Drop-in-compatible ``/cards`` payload for one resolved asset, built entirely
    from local data. Structurally 0 credits — never calls any external price provider."""
    data = dict(asset_comp_response(asset_key, asset, comp_row or {}))
    data.pop("metadata", None)          # the facade carries the single outer credit block
    data["priceHistory"] = list(price_history or [])
    if momentum is not None:
        data["momentum"] = momentum
    return _facade(data)


def card_no_match(tcg_player_id: str, *, detail: str = "") -> dict[str, Any]:
    """Well-formed empty facade for an unmapped/unknown tcgPlayerId. 200, not error."""
    return _facade({
        "tcgPlayerId": tcg_player_id,
        "status": "no_match",
        "estimate": None,
        "confidence": "none",
        "confidenceReason": detail or "no local asset mapped to that tcgPlayerId",
        "priceHistory": [],
    })


def card_ambiguous(tcg_player_id: str, matches: list[tuple[str, dict]]) -> dict[str, Any]:
    """One tcgPlayerId maps to several assets (raw NM/LP, PSA10, PSA9…) and no
    condition/grade discriminator was given. Return the candidates — never guess a
    wrong variant (STOP-class: a wrong pick is a wrong number)."""
    candidates = [{
        "asset_key": key,
        "asset_class": asset.get("asset_class"),
        "condition": asset.get("condition"),
        "grade_key": asset.get("grade_key"),
        "grade": asset.get("grade"),
    } for key, asset in matches]
    return _facade({
        "tcgPlayerId": tcg_player_id,
        "status": "ambiguous",
        "estimate": None,
        "confidence": "none",
        "confidenceReason": ("multiple assets map to this tcgPlayerId; pass condition= "
                             "(raw) or grade= / grade_key= (graded) to disambiguate"),
        "candidates": candidates,
        "priceHistory": [],
    })
