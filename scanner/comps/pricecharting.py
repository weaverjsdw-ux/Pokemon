"""PriceCharting sold-derived summary as a CompSourceQuote (wraps scanner.resale)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from .. import resale
from .model import SOLD_DERIVED, CompSourceQuote


class PriceChartingSource:
    def __init__(self, cfg: Any, client: Any = None) -> None:
        self.client = client or resale.PriceChartingSearchClient()

    def fetch(self, product_key: str, product: dict, checked_at: int) -> CompSourceQuote:
        fetched_at = datetime.fromtimestamp(checked_at).isoformat(timespec="seconds")
        fallback_url = resale._pricecharting_search_url(resale.product_query(product))
        try:
            row = self.client.estimate(product_key, product, checked_at)
        except requests.RequestException as exc:
            detail = resale._safe_detail(str(exc))
            status = "blocked" if ("403" in detail or "429" in detail) else "error"
            return CompSourceQuote("pricecharting", SOLD_DERIVED, status, None,
                                   fallback_url, fetched_at, detail=detail)
        url = str(row.get("url") or fallback_url)
        if row.get("status") == "ok":
            return CompSourceQuote(
                "pricecharting", SOLD_DERIVED, "ok", resale._amount(row.get("estimate")),
                url, fetched_at,
                raw_excerpt=str(row.get("detail") or "")[:200])
        return CompSourceQuote("pricecharting", SOLD_DERIVED, "no_match", None, url,
                               fetched_at, detail=str(row.get("detail") or row.get("status") or ""))
