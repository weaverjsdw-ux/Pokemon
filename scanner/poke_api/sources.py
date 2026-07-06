"""Raw + graded comp source adapters (Track D1).

A small, strategy-free interface over the exact card sources. External sources are
*pluggable adapters*; the dollar number is produced by the *same* in-house
confidence ladder the sealed/discovery paths use (``comps.model.resolve`` ->
``to_legacy_row``) for raw, and by the configured external card source's graded
smart price (pass-through confidence) for graded. Nothing here decides a trade —
that is the Lab's job.

STOP-class rules baked in structurally:
* No exact source -> ``estimate`` None, confidence ``none`` (never an invented
  number, never MSRP/title/fallback text as a comp).
* Raw: sold-derived quotes (TCGplayer / PriceCharting / the configured external
  card source's market price) plus an optional eBay active ask. An ask alone is
  *context, never a comp* (D.5) — with no sold-derived source the raw estimate is
  ``None``/confidence ``none``; the ask stays in ``sources`` as context only.
* Graded: ``estimate`` may come ONLY from the external source's graded smart price
  or a PriceCharting graded page. The eBay ask is validator/context — it can lift
  the confidence of a real sold source but can NEVER become the graded comp.

The external card price client is dormant by default: it is built only when
``cfg.market_preferred and cfg.market_api_key`` are set, always requests
``limit=1`` (the provider bills on requested limit), and degrades to no-price on
401 / 429 / transport / decode error rather than crashing a lookup. (Provider-
branded tokens like the ``ppt_cards`` source slug and ``smartMarketPrice`` /
``salesByGrade`` response keys are retained only as honest source provenance /
upstream wire-format — see ``docs/poke/private-price-api.md``.)
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
from ..discovery import ledger as disc_ledger
from . import catalog as catalog_mod
from . import history as history_mod


# ---------------------------------------------------------------- small types

@dataclass(frozen=True)
class GradedSmartPrice:
    """One graded smart-price reading (the external card source's ``/cards``
    ``salesByGrade`` -> ``smartMarketPrice`` upstream wire fields)."""
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


# ------------------------------------------------- external card price client (/cards)

class ExternalCardPriceClient:
    """Dormant external card price client (raw market price + graded smart price).

    A pluggable adapter over the configured external card-price source (today a
    PokemonPriceTracker ``/cards`` endpoint — an implementation detail, not the
    program's identity). Every request pins ``limit=1`` (single by-id lookup; the
    provider bills on the requested limit, not results). Any HTTP/transport/decode
    failure degrades to a no-price quote / ``None`` — it never raises into a comp
    lookup."""

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
            return resp.json()           # a malformed 200 body -> ValueError -> degrade
        except (requests.RequestException, ValueError):
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
                                   fetched, detail="external /cards request failed (401/429/transport/decode)")
        price, url = _card_market(payload)
        if price is None:
            return CompSourceQuote("ppt_cards", SOLD_DERIVED, "no_match", None, url,
                                   fetched, detail="no /cards market price for that id")
        return CompSourceQuote("ppt_cards", SOLD_DERIVED, "ok", price, url, fetched,
                               detail="external card source /cards TCGplayer market price")

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


def _card_market(payload: Any) -> tuple[float | None, str]:
    """(prices.market, tcgPlayerUrl) from the first usable ``/cards`` data item.

    Fully type-defensive: a malformed provider payload (``data``/``prices`` of the
    wrong type, non-dict items) yields ``(None, "")`` — an honest no-match, never a
    crash. ``resale._amount`` already tolerates non-numeric price values."""
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    for item in items:
        if not isinstance(item, dict):
            continue
        prices = item.get("prices")
        if not isinstance(prices, dict):
            continue
        price = resale._amount(prices.get("market"))
        if price is not None:
            return price, str(item.get("tcgPlayerUrl") or "")
    return None, ""


def _graded_smart_from(payload: Any, grade_key: str) -> GradedSmartPrice | None:
    """Graded ``smartMarketPrice`` for ``grade_key`` from a ``/cards`` payload.

    Fully type-defensive at every level (``data``/``ebay``/``salesByGrade``/the grade
    entry/``smartMarketPrice`` may each be the wrong type) — a malformed payload
    returns ``None`` (honest no-source), never an ``AttributeError``."""
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    for item in items:
        if not isinstance(item, dict):
            continue
        ebay = item.get("ebay")
        by_grade = ebay.get("salesByGrade") if isinstance(ebay, dict) else None
        entry = by_grade.get(grade_key) if isinstance(by_grade, dict) else None
        smart = entry.get("smartMarketPrice") if isinstance(entry, dict) else None
        if not isinstance(smart, dict):
            continue
        price = resale._amount(smart.get("price"))
        if price is not None:
            conf = str(smart.get("confidence") or "medium").lower()
            if conf not in {"high", "medium", "low"}:
                conf = "medium"
            return GradedSmartPrice(price=price, confidence=conf,
                                    url=str(item.get("tcgPlayerUrl") or ""),
                                    grade_key=grade_key)
    return None


def card_client_from_config(cfg: Any) -> "ExternalCardPriceClient | None":
    """Build the dormant external card price client only when configured
    (``market_preferred`` + a key). Otherwise ``None`` -> raw/graded resolve to
    honest ``none`` with 0 network."""
    if getattr(cfg, "market_preferred", False) and getattr(cfg, "market_api_key", ""):
        return ExternalCardPriceClient(str(cfg.market_api_key))
    return None


# Deprecated compat alias: this client was historically ``PptCardClient``. Retained so
# existing imports/tests keep working; the provider-neutral ``ExternalCardPriceClient``
# is the public name.
PptCardClient = ExternalCardPriceClient


# ---------------------------------------------------------------- credit accounting

@dataclass(frozen=True)
class CreditAccount:
    """The credit cost of one asset comp resolution. ``source`` is ``"external"`` iff
    a billable provider request is/was issued, else ``"local"``. ``estimated`` marks a
    deterministic bound (vs a provider-reported actual)."""
    total: int
    estimated: bool
    source: str


def expected_asset_credits(asset: dict, *, card_client: Any) -> CreditAccount:
    """Deterministic, stateless UPPER BOUND on the external credits a ``refresh=true``
    asset comp will spend — never under-reporting a billable request.

    A configured client issues at most ONE ``/cards`` by-id lookup (``limit=1``):
    raw bills 1 credit; graded adds ``includeEbay=true`` (+1) for 2 (see
    ``docs/poke/reference/ppt-v2-notes.md``). Zero credits whenever no billable
    request is issued — no client, an unmapped ``tcgplayer_id``, or a graded asset
    missing its ``grade_key`` (``graded_smart`` skips the call). ``estimated=True``:
    this is the deterministic bound; no provider actual-credit header is consumed on
    this path today (the sealed client reads ``X-API-Calls-Consumed`` — preferring it
    here is a documented follow-up). Because it is an upper bound it stays money-honest
    even when the request degrades (401/429): the credit was still billable."""
    if card_client is None:
        return CreditAccount(0, False, "local")
    if not str(asset.get("tcgplayer_id") or "").strip():
        return CreditAccount(0, False, "local")        # no id -> no request issued
    asset_class = str(asset.get("asset_class") or "").strip().lower()
    if asset_class == catalog_mod.RAW:
        return CreditAccount(1, True, "external")
    if asset_class == catalog_mod.GRADED and str(asset.get("grade_key") or "").strip():
        return CreditAccount(2, True, "external")
    return CreditAccount(0, False, "local")             # graded w/o grade_key -> no call


# ---------------------------------------------------------------- ledger writer (persist)

# Sources whose number is an active ASK, never a sold comp — refused by the writer.
# Recording an ask as a market_comp would launder context into sold-comp truth (D.5).
_ASK_SOURCES = frozenset({"ebay"})


def build_asset_comp_observation(asset: dict, *, comp, confidence: str, source: str,
                                 capture_date: str, source_url: str = "", basis: str = "",
                                 asset_key: str = "") -> dict:
    """Shape a sold-derived raw/graded comp into a ``market_comp`` ledger observation
    whose identity slots come straight from ``history.asset_identity`` — so the persisted
    ``item_key`` byte-matches what read-first looks up. STOP-class: a missing/<=0 comp or
    an ask-only source is refused (``ValueError``); the writer never fabricates a sold
    number and never launders an active ask into sold-comp truth."""
    price = resale._amount(comp)
    if price is None or price <= 0:
        raise ValueError(f"refusing to record a non-positive/absent asset comp: {comp!r}")
    slug = str(source or "").strip().lower()
    if not slug:
        raise ValueError("refusing to record an asset comp with no source "
                         "(provenance is STOP-class)")
    if slug in _ASK_SOURCES:
        raise ValueError(f"refusing to record source {slug!r}: an active ask is context, "
                         "never a sold comp")
    obs = dict(history_mod.asset_identity(asset, asset_key))
    obs.update({
        "kind": history_mod.MARKET_COMP,
        "comp": round(float(price), 2),
        "comp_confidence": str(confidence or "none").strip().lower() or "none",
        "source": slug,
        "source_url": str(source_url or ""),
        "capture_date": str(capture_date or ""),
        # provenance for later audit (identity already lives in the item_key slots)
        "asset_key": str(asset_key or ""),
        "asset_class": str(asset.get("asset_class") or ""),
        "basis": str(basis or ""),
        "recorded_via": "record_asset_comp",
    })
    return obs


def record_asset_comp(ledger_path, asset: dict, *, comp, confidence: str, source: str,
                      capture_date: str, source_url: str = "", basis: str = "",
                      asset_key: str = "") -> bool:
    """Append a sold-derived raw/graded ``market_comp`` to the append-only price-history
    ledger (idempotent by kind+identity+source_url+capture_date). True on a fresh write,
    False if already recorded. Refuses to fabricate (see ``build_asset_comp_observation``).
    No network, 0 credits — any billed provider fetch happens upstream and passes the
    resolved number in here."""
    obs = build_asset_comp_observation(
        asset, comp=comp, confidence=confidence, source=source,
        capture_date=capture_date, source_url=source_url, basis=basis, asset_key=asset_key)
    return disc_ledger.append_observation(ledger_path, obs)


def resolve_asset_source_row(asset: dict, *, card_client: Any, checked_at: int,
                             tolerance_pct: float = 20.0, floor_sanity_pct: float = 50.0) -> dict:
    """Dispatch a raw/graded asset to its source resolver (the billed refresh path,
    shared by the router refresh route and the ``record-asset-comp --refresh`` CLI).
    Returns the legacy comp row; with no configured client it is an honest ``none``
    row touching no network. Callers wrap this so a resolver bug degrades to no-price,
    never a persisted number."""
    if str(asset.get("asset_class")) == catalog_mod.RAW:
        return resolve_raw_comp(asset, checked_at=checked_at, ppt_client=card_client,
                                tolerance_pct=tolerance_pct, floor_sanity_pct=floor_sanity_pct)
    return resolve_graded_comp(asset, checked_at=checked_at, ppt_client=card_client)


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

    Sold-derived quotes (the external card source's ``/cards`` market when configured, plus any injected
    TCGplayer / PriceCharting card adapters) and an optional eBay active ask are
    handed to ``comps.model.resolve`` with ``allow_ask_only=False``; the result goes
    through ``to_legacy_row`` so the no-source case honestly reports confidence
    ``none``. An ask alone is context, never a comp — it can never mint an estimate."""
    asset_key = str(asset.get("asset_key") or asset.get("name") or "asset")
    ikey = history_mod.item_key_for_asset(asset)

    sold: list[CompSourceQuote] = []
    if ppt_client is not None:
        try:
            sold.append(ppt_client.raw_quote(asset, checked_at))
        except Exception as exc:  # noqa: BLE001 - a client bug degrades, never crashes
            sold.append(CompSourceQuote("ppt_cards", SOLD_DERIVED, "error", None, "",
                                        _iso(checked_at),
                                        detail=f"card client raised: {str(exc)[:150]}"))
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
        tolerance_pct=tolerance_pct, floor_sanity_pct=floor_sanity_pct,
        allow_ask_only=False)   # D.5: a raw single is never priced off active asks alone
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
    """Resolve a graded slab's comp. ``estimate`` comes ONLY from the external card
    source's graded smart price (confidence passed through 1:1) or a PriceCharting
    graded page (single sold-derived source -> medium if an ask corroborates, else
    low). The eBay ask is validator/context — structurally it can never be the comp."""
    asset_key = str(asset.get("asset_key") or asset.get("name") or "asset")

    smart = None
    if ppt_client is not None:
        try:
            smart = ppt_client.graded_smart(asset, checked_at)
        except Exception:  # noqa: BLE001 - a client bug degrades to honest no-source
            smart = None
    if smart is not None:
        return _legacy_row(
            asset_key, asset, status="ok", estimate=smart.price,
            confidence=smart.confidence, basis="external card source graded smart price",
            source=smart.source, url=smart.url, checked_at=checked_at,
            detail=f"external smart price for {smart.grade_key} (confidence passed through)")

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
                       detail="no exact graded source (external smart price / PriceCharting) mapped")
