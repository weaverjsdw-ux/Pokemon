"""PokemonPriceTracker market source, behind the resale.py client contract.

Optional-preferred, never required: a missing key, rate-limit, or quota all
fall through to the existing resale/scrape client. Scanning never depends on it.
"""
from __future__ import annotations

from typing import Any

import requests

from . import resale

PPT_SEARCH_URL = "https://www.pokemonpricetracker.com/api/v1/prices"
SOURCE_LABEL = "PokemonPriceTracker"
BASIS = "sold comp median"


class PokemonPriceTrackerClient:
    def __init__(self, api_key: str, session: requests.Session | None = None) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()

    @classmethod
    def from_config(cls, cfg: Any) -> "PokemonPriceTrackerClient":
        return cls(api_key=str(getattr(cfg, "market_api_key", "") or ""))

    def estimate(self, product_key: str, product: dict[str, Any], checked_at: int) -> dict[str, Any]:
        query = resale.product_query(product)
        response = self.session.get(
            PPT_SEARCH_URL,
            params={"q": query, "condition": "sealed"},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=20,
        )
        response.raise_for_status()  # 401/429/5xx -> RequestException -> fallback
        return _quote_from_ppt(product_key, product, response.json(), checked_at)


def _quote_from_ppt(
    product_key: str, product: dict[str, Any], payload: dict[str, Any], checked_at: int
) -> dict[str, Any]:
    results = payload.get("results") or payload.get("data") or []
    prices = [
        p for item in results
        if isinstance(item, dict)
        for p in [resale._amount(item.get("marketPrice") or item.get("price"))]
        if p is not None
    ]
    base = {
        "productKey": product_key,
        "source": SOURCE_LABEL,
        "basis": BASIS,
        "query": resale.product_query(product),
        "checkedAt": checked_at,
    }
    if not prices:
        return resale.annotate_quote(product, base | {
            "status": "no_matches", "estimate": "", "low": "", "high": "",
            "sampleSize": 0, "detail": "No PokemonPriceTracker comps matched.",
        })
    prices.sort()
    median = prices[len(prices) // 2]
    return resale.annotate_quote(product, base | {
        "status": "ok",
        "estimate": resale._money(median),
        "low": resale._money(prices[0]),
        "high": resale._money(prices[-1]),
        "sampleSize": len(prices),
        "detail": f"Median of {len(prices)} PokemonPriceTracker sold comps.",
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
