"""Retailer adapter interface."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import requests

from ..http import HTTPClient, default_client


@dataclass
class Store:
    retailer: str
    store_id: str          # retailer-specific (e.g. Target store number)
    name: str              # human-readable, "Target Springfield IL"
    lat: float
    lng: float
    distance_miles: float | None = None  # filled in after route filter

    def label(self) -> str:
        return self.name


@dataclass
class StockResult:
    store: Store | None    # None for online-only retailers
    product_key: str
    product_name: str
    status: str            # "IN_STOCK" | "LIMITED" | "OUT" | "ONLINE_IN_STOCK" | "ONLINE_OUT"
    url: str
    price: str = ""
    cart_url: str = ""     # Direct add-to-cart deep link when retailer supports it
    image_url: str = ""    # Hero image, surfaced in Discord embed thumbnail


class Retailer:
    name: str = ""
    slug: str = ""           # short stable id used for health/budget tracking
    online_only: bool = False

    def __init__(self, http: HTTPClient | None = None, **kwargs: Any) -> None:
        self.opts = kwargs
        self.http = http or default_client

    def find_stores(self, center_lat: float, center_lng: float, radius_miles: float) -> list[Store]:
        """Return candidate stores near (lat, lng). Online-only retailers return []."""
        return []

    def check(self, products: dict[str, dict[str, Any]], stores: list[Store]) -> Iterable[StockResult]:
        """Yield StockResult for each (product, store) combination this adapter handles."""
        return []

    def http_get(
        self, url: str, *, params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None, timeout: float = 15.0,
    ) -> requests.Response | None:
        """Shared GET that returns None on terminal failure.

        Bubbles BudgetExceeded / RetailerDisabled so the outer loop can log
        the throttle clearly; swallows ordinary RequestException after retries
        so adapters can keep their "missing data == skip product" semantics.
        """
        try:
            return self.http.request(
                self.slug or self.name.lower(),
                "GET",
                url,
                params=params,
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException:
            return None
