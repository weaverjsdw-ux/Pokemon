"""PokemonPriceTracker market source (API v2), behind the resale.py client contract.

Optional-preferred, never required: a missing key, rate-limit (429), quota, or any
HTTP error all fall through to the existing resale/scrape client. Scanning never
depends on it.

v2 contract (see docs/poke/reference/ppt-v2-notes.md):
- Sealed comp: GET /sealed-products?tcgPlayerId=<ppt_id> -> data.unopenedPrice
  (TCGplayer market price). Resolution is by EXACT id only: a bare name search returns
  the wrong variant (bundles / cases / store exclusives), so a product without a mapped
  `ppt_id` is skipped (0 credits) and falls back to resale. Map ppt_id per product
  (a data task, like the Costco/PC id seeding).
- The TCGplayer market price is treated as a medium-confidence single-source market
  summary (resale.annotate_quote, same class as the PriceCharting fallback).
Singles + graded (/cards with includeEbay) are the /poke follow-on, not wired here.
"""
from __future__ import annotations

from typing import Any

import requests

from . import resale

PPT_BASE_URL = "https://www.pokemonpricetracker.com/api/v2"
SOURCE_LABEL = resale.POKEMONPRICETRACKER_SOURCE_LABEL
SEALED_BASIS = "TCGplayer sealed market"


class PokemonPriceTrackerClient:
    def __init__(self, api_key: str, session: requests.Session | None = None) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()

    @classmethod
    def from_config(cls, cfg: Any) -> "PokemonPriceTrackerClient":
        return cls(api_key=str(getattr(cfg, "market_api_key", "") or ""))

    def estimate(self, product_key: str, product: dict[str, Any], checked_at: int) -> dict[str, Any]:
        # Resolve by exact TCGplayer id only. A bare name search returns the wrong
        # variant (bundles / cases / store exclusives), so without a mapped ppt_id we
        # skip the API entirely (0 credits) and let the caller fall back to resale.
        ppt_id = str(product.get("ppt_id") or product.get("ppt_query") or "").strip()
        if not ppt_id:
            return _no_match(product_key, product, checked_at,
                             "No ppt_id mapped; skipped to avoid a wrong-variant search.")
        response = self.session.get(
            f"{PPT_BASE_URL}/sealed-products",
            params={"tcgPlayerId": ppt_id},  # exact single product, 1 credit
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=20,
        )
        response.raise_for_status()  # 401/429/5xx -> RequestException -> fallback
        return _quote_from_ppt(product_key, product, response.json(), checked_at)


def _first_unopened_price(payload: dict[str, Any]) -> float | None:
    data = payload.get("data")
    items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    for item in items:
        if isinstance(item, dict):
            price = resale._amount(item.get("unopenedPrice"))
            if price is not None:
                return price
    return None


def _no_match(
    product_key: str, product: dict[str, Any], checked_at: int, detail: str
) -> dict[str, Any]:
    return resale.annotate_quote(product, {
        "productKey": product_key, "source": SOURCE_LABEL, "basis": SEALED_BASIS,
        "query": resale.product_query(product), "checkedAt": checked_at,
        "status": "no_matches", "estimate": "", "low": "", "high": "",
        "sampleSize": 0, "detail": detail,
    })


def _quote_from_ppt(
    product_key: str, product: dict[str, Any], payload: dict[str, Any], checked_at: int
) -> dict[str, Any]:
    price = _first_unopened_price(payload)
    base = {
        "productKey": product_key,
        "source": SOURCE_LABEL,
        "basis": SEALED_BASIS,
        "query": resale.product_query(product),
        "checkedAt": checked_at,
    }
    if price is None:
        return _no_match(product_key, product, checked_at,
                         "No PokemonPriceTracker sealed match for that id.")
    money = resale._money(price)
    return resale.annotate_quote(product, base | {
        "status": "ok",
        "estimate": money,
        "low": money,
        "high": money,
        "sampleSize": 0,  # single market price, not a sold-comp sample
        "detail": "PokemonPriceTracker TCGplayer sealed market price.",
    })


class MarketFallbackClient:
    def __init__(self, primary: Any, fallback: Any) -> None:
        self.primary = primary
        self.fallback = fallback

    def estimate(self, product_key: str, product: dict[str, Any], checked_at: int) -> dict[str, Any]:
        try:
            row = self.primary.estimate(product_key, product, checked_at)
            if row.get("status") == "ok":
                return row
        except requests.RequestException:
            pass
        except Exception:
            pass
        return self.fallback.estimate(product_key, product, checked_at)


def market_client_from_config(cfg: Any) -> Any:
    resale_client = resale.resale_client_from_config(cfg)
    if getattr(cfg, "market_preferred", False) and getattr(cfg, "market_api_key", ""):
        return MarketFallbackClient(PokemonPriceTrackerClient.from_config(cfg), resale_client)
    return resale_client


def comp_from_row(row: dict[str, Any]) -> tuple[float | None, str]:
    """Numeric comp + confidence from a cached quote row."""
    if not row or row.get("status") != "ok":
        return None, "none"
    return resale._amount(row.get("estimate")), str(row.get("confidence") or "none")
