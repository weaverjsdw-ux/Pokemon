"""Retailer adapter interface."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class Store:
    retailer: str
    store_id: str          # retailer-specific (e.g. Target store number)
    name: str              # human-readable, "Target Springfield IL"
    lat: float
    lng: float
    distance_miles: float | None = None  # filled in after route filter
    address: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""

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
    retailer_slug: str = ""


class Retailer:
    name: str = ""
    online_only: bool = False
    supported: bool = True
    unsupported_reason: str = ""
    product_id_fields: tuple[str, ...] = ()
    api_key_required: bool = False

    def __init__(self, **kwargs: Any) -> None:
        self.opts = kwargs

    def find_stores(self, center_lat: float, center_lng: float, radius_miles: float) -> list[Store]:
        """Return candidate stores near (lat, lng). Online-only retailers return []."""
        return []

    def check(self, products: dict[str, dict[str, Any]], stores: list[Store]) -> Iterable[StockResult]:
        """Yield StockResult for each (product, store) combination this adapter handles."""
        return []

    def inventory(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        """Yield all known stock states for UI inventory views.

        Adapters that can distinguish OUT from unknown should override this.
        The default preserves legacy behavior by returning alertable positives.
        """
        yield from self.check(products, stores)
