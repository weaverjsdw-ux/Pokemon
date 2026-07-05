"""Raw + graded comp source adapters (Track D1).

A small, strategy-free interface over the exact card sources. The dollar number
is produced by the *same* in-house confidence ladder the sealed/discovery paths
use (``comps.model.resolve`` -> ``to_legacy_row``) for raw, and by PPT's
``smartMarketPrice`` (pass-through confidence) for graded. Nothing here decides a
trade — that is the Lab's job.

STOP-class rules baked in structurally:
* No exact source -> ``estimate`` None, confidence ``none`` (never an invented
  number, never MSRP/title/fallback text as a comp).
* Raw: sold-derived quotes (TCGplayer / PriceCharting / PPT ``/cards`` market)
  plus an optional eBay active ask; an ask alone can only ever be a *low*-
  confidence surface, never high.
* Graded: ``estimate`` may come ONLY from a PPT ``smartMarketPrice`` or a
  PriceCharting graded page. The eBay ask is validator/context — it can lift the
  confidence of a real sold source but can NEVER become the graded comp.

The PPT ``/cards`` client is dormant by default: it is built only when
``cfg.market_preferred and cfg.market_api_key`` are set, always requests
``limit=1`` (PPT bills on requested limit), and degrades to no-price on 401 / 429
/ transport error rather than crashing a lookup.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import requests

from .. import market as market_mod
from .. import resale
from ..comps import model as comps_model
from ..comps.model import SOLD_DERIVED, CompSourceQuote
from . import history as history_mod


# ---------------------------------------------------------------- small types

@dataclass(frozen=True)
class GradedSmartPrice:
    """One graded ``smartMarketPrice`` reading (PPT ``/cards`` ``salesByGrade``)."""
    price: float
    confidence: str          # high | medium | low (passed through 1:1)
    url: str
    grade_key: str
    source: str = "ppt_cards"


# ---------------------------------------------------------------- time helpers

def _iso(checked_at: int) -> str:
    return datetime.fromtimestamp(int(checked_at)).isoformat(timespec="seconds")


def _iso_date(checked_at: int) -> str:
    return date.fromtimestamp(int(checked_at)).isoformat()


# ---------------------------------------------------------------- PPT /cards client

class PptCardClient:
    """Dormant PPT ``/cards`` client for raw market price + graded smart price.

    Every request pins ``limit=1`` (single by-id lookup; PPT bills on the
    requested limit, not results). Any HTTP/transport failure degrades to a
    no-price quote / ``None`` — it never raises into a comp lookup."""

    def __init__(self, api_key: str, session: Any = None) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()

    def _get(self, params: dict) -> dict | None:
        try:
            resp = self.session.get(
                f"{market_mod.PPT_BASE_URL}/cards",
                params=params,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=20,
            )
            resp.raise_for_status()      # 401/429/5xx -> HTTPError -> degrade
            return resp.json()
        except requests.RequestException:
            return None

    def raw_quote(self, asset: dict, checked_at: int) -> CompSourceQuote:
        """Raw single market price as a sold-derived quote (``data.prices.market``).
        No ``tcgplayer_id`` -> skipped (0 network). Failure -> error quote."""
        fetched = _iso(checked_at)
        tcg_id = str(asset.get("tcgplayer_id") or "").strip()
        if not tcg_id:
            return CompSourceQuote("ppt_cards", SOLD_DERIVED, "skipped", None, "",
                                   fetched, detail="no tcgplayer_id mapped")
        payload = self._get({"tcgPlayerId": tcg_id, "limit": 1})
        if payload is None:
            return CompSourceQuote("ppt_cards", SOLD_DERIVED, "error", None, "",
                                   fetched, detail="PPT /cards request failed (401/429/transport)")
        price, url = _card_market(payload)
        if price is None:
            return CompSourceQuote("ppt_cards", SOLD_DERIVED, "no_match", None, url,
                                   fetched, detail="no /cards market price for that id")
        return CompSourceQuote("ppt_cards", SOLD_DERIVED, "ok", price, url, fetched,
                               detail="PPT /cards TCGplayer market price")

    def graded_smart(self, asset: dict, checked_at: int) -> GradedSmartPrice | None:
        """Graded ``smartMarketPrice`` for the asset's ``grade_key`` via
        ``includeEbay=true`` (+1 credit). Missing id/grade_key or any failure ->
        ``None`` (honest no-source)."""
        tcg_id = str(asset.get("tcgplayer_id") or "").strip()
        grade_key = str(asset.get("grade_key") or "").strip()
        if not tcg_id or not grade_key:
            return None
        payload = self._get({"tcgPlayerId": tcg_id, "includeEbay": "true", "limit": 1})
        if payload is None:
            return None
        return _graded_smart_from(payload, grade_key)


def _card_market(payload: dict) -> tuple[float | None, str]:
    """(prices.market, tcgPlayerUrl) from the first usable ``/cards`` data item."""
    data = payload.get("data")
    items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    for item in items:
        if isinstance(item, dict):
            prices = item.get("prices") or {}
            price = resale._amount(prices.get("market"))
            if price is not None:
                return price, str(item.get("tcgPlayerUrl") or "")
    return None, ""


def _graded_smart_from(payload: dict, grade_key: str) -> GradedSmartPrice | None:
    data = payload.get("data")
    items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    for item in items:
        if not isinstance(item, dict):
            continue
        by_grade = ((item.get("ebay") or {}).get("salesByGrade") or {})
        smart = (by_grade.get(grade_key) or {}).get("smartMarketPrice") or {}
        price = resale._amount(smart.get("price"))
        if price is not None:
            conf = str(smart.get("confidence") or "medium").lower()
            if conf not in {"high", "medium", "low"}:
                conf = "medium"
            return GradedSmartPrice(price=price, confidence=conf,
                                    url=str(item.get("tcgPlayerUrl") or ""),
                                    grade_key=grade_key)
    return None


def card_client_from_config(cfg: Any) -> PptCardClient | None:
    """Build the dormant PPT ``/cards`` client only when configured
    (``market_preferred`` + a key). Otherwise ``None`` -> raw/graded resolve to
    honest ``none`` with 0 network."""
    if getattr(cfg, "market_preferred", False) and getattr(cfg, "market_api_key", ""):
        return PptCardClient(str(cfg.market_api_key))
    return None


# ---------------------------------------------------------------- adapter plumbing

def _safe_fetch(source: Any, asset: dict, checked_at: int, slug: str) -> CompSourceQuote | None:
    """A source adapter bug never fails a comp lookup."""
    if source is None:
        return None
    try:
        return source.fetch(asset, checked_at)
    except Exception as exc:  # noqa: BLE001 - honest degrade, never crash
        return CompSourceQuote(slug, SOLD_DERIVED, "error", None, "",
                               _iso(checked_at), detail=str(exc)[:200])


def _legacy_row(asset_key: str, asset: dict, *, status: str, estimate: float | None,
                confidence: str, basis: str, source: str, url: str,
                checked_at: int, detail: str) -> dict:
    """A comp-row in the legacy quote-dict shape (superset of resale.annotate_quote)
    so ``asset_model``/``market.comp_from_row`` read it exactly like a sealed row."""
    money = resale._money(estimate) if estimate is not None else ""
    return {
        "productKey": asset_key,
        "status": status,
        "estimate": money,
        "confidence": confidence,
        "confidenceReason": detail,
        "compBasis": basis,
        "basis": basis,
        "sources": ([{"source": source, "status": "ok", "price": estimate, "url": url}]
                    if estimate is not None else []),
        "sourceUrl": url,
        "url": url,
        "checkedAt": _iso_date(checked_at),
        "cacheHit": False,
        "detail": detail,
    }


# ---------------------------------------------------------------- raw resolver

def resolve_raw_comp(asset: dict, *, checked_at: int, ppt_client: Any = None,
                     tcg_source: Any = None, pc_source: Any = None,
                     ebay_source: Any = None, tolerance_pct: float = 20.0,
                     floor_sanity_pct: float = 50.0) -> dict:
    """Resolve a raw single's comp through the in-house confidence ladder.

    Sold-derived quotes (PPT ``/cards`` market when configured, plus any injected
    TCGplayer / PriceCharting card adapters) and an optional eBay active ask are
    handed to ``comps.model.resolve``; the result goes through ``to_legacy_row`` so
    the no-source case honestly reports confidence ``none`` (not ``unknown``). An
    ask alone can only surface at ``low``, never high."""
    asset_key = str(asset.get("asset_key") or asset.get("name") or "asset")
    ikey = history_mod.item_key_for_asset(asset)

    sold: list[CompSourceQuote] = []
    if ppt_client is not None:
        sold.append(ppt_client.raw_quote(asset, checked_at))
    for src, slug in ((tcg_source, "tcgplayer"), (pc_source, "pricecharting")):
        q = _safe_fetch(src, asset, checked_at, slug)
        if q is not None:
            sold.append(q)

    ebay = None
    if ebay_source is not None:
        try:
            ebay = ebay_source.fetch(asset, checked_at)
        except Exception:  # noqa: BLE001
            ebay = None

    tcg_slot = sold[0] if len(sold) >= 1 else None
    pc_slot = sold[1] if len(sold) >= 2 else None
    normalized = comps_model.resolve(
        ikey, None, tcg_slot, pc_slot, ebay, _iso_date(checked_at),
        tolerance_pct=tolerance_pct, floor_sanity_pct=floor_sanity_pct)
    return comps_model.to_legacy_row(normalized, asset_key, asset, int(checked_at))


# ---------------------------------------------------------------- graded resolver

def _ask_ok(ebay: Any) -> bool:
    return bool(ebay and getattr(ebay, "quote", None)
                and ebay.quote.status == "ok" and ebay.quote.price and ebay.quote.price > 0)


def _within(a: float, b: float, tolerance_pct: float) -> bool:
    lo = min(a, b)
    return lo > 0 and abs(a - b) / lo * 100.0 <= tolerance_pct


def resolve_graded_comp(asset: dict, *, checked_at: int, ppt_client: Any = None,
                        pc_source: Any = None, ebay_source: Any = None) -> dict:
    """Resolve a graded slab's comp. ``estimate`` comes ONLY from a PPT
    ``smartMarketPrice`` (confidence passed through 1:1) or a PriceCharting graded
    page (single sold-derived source -> medium if an ask corroborates, else low).
    The eBay ask is validator/context — structurally it can never be the comp."""
    asset_key = str(asset.get("asset_key") or asset.get("name") or "asset")

    smart = ppt_client.graded_smart(asset, checked_at) if ppt_client is not None else None
    if smart is not None:
        return _legacy_row(
            asset_key, asset, status="ok", estimate=smart.price,
            confidence=smart.confidence, basis="PPT /cards smartMarketPrice",
            source=smart.source, url=smart.url, checked_at=checked_at,
            detail=f"PPT smartMarketPrice for {smart.grade_key} (confidence passed through)")

    pc = _safe_fetch(pc_source, asset, checked_at, "pricecharting") if pc_source is not None else None
    ebay = None
    if ebay_source is not None:
        try:
            ebay = ebay_source.fetch(asset, checked_at)
        except Exception:  # noqa: BLE001
            ebay = None

    if pc is not None and pc.status == "ok" and pc.price and pc.price > 0:
        corroborated = _ask_ok(ebay) and _within(pc.price, ebay.quote.price, 20.0)
        conf = "medium" if corroborated else "low"
        detail = ("single sold-derived graded source"
                  + (", ask corroborated" if corroborated else ", uncorroborated"))
        return _legacy_row(asset_key, asset, status="ok", estimate=pc.price,
                           confidence=conf, basis="pricecharting graded page",
                           source="pricecharting", url=pc.url, checked_at=checked_at,
                           detail=detail)

    return _legacy_row(asset_key, asset, status="no_match", estimate=None,
                       confidence="none", basis="", source="", url="",
                       checked_at=checked_at,
                       detail="no exact graded source (PPT smart price / PriceCharting) mapped")
