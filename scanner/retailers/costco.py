"""Costco adapter placeholder.

Costco is registered so config.yaml can keep it disabled by default without
being reported as an unknown retailer. Live stock checks still need a dedicated
adapter once a reliable public signal is selected.
"""
from __future__ import annotations

from typing import Any, Iterable

from .base import Retailer, StockResult, Store


class Costco(Retailer):
    name = "Costco"
    online_only = True
    supported = False
    unsupported_reason = "Costco live stock checks need a dedicated adapter."
    product_id_fields = ("costco_item_id",)

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        return []

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        return []
