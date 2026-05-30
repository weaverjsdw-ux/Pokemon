"""Best Buy adapter.

Uses the official Best Buy Products API for online availability checks.
Requires `retailers.bestbuy.api_key` in config.yaml and `bestbuy_sku`
values in data/products.yaml.
"""
from __future__ import annotations

import time
from typing import Any, Iterable

import requests

from .base import Retailer, StockResult, Store


class BestBuy(Retailer):
    name = "Best Buy"
    online_only = True
    product_id_fields = ("bestbuy_sku",)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.api_key = str(kwargs.get("api_key") or "").strip()

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        return []

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        if not self.api_key:
            return []

        for key, prod in products.items():
            sku = str(prod.get("bestbuy_sku") or "").strip()
            if not sku:
                continue
            result = self._check_one(sku, prod, key)
            if result is not None:
                yield result
            time.sleep(0.4)

    def _check_one(self, sku: str, prod: dict[str, Any], key: str) -> StockResult | None:
        try:
            resp = requests.get(
                f"https://api.bestbuy.com/v1/products/{sku}.json",
                params={
                    "apiKey": self.api_key,
                    "show": "sku,name,salePrice,onlineAvailability,url,addToCartUrl",
                },
                timeout=15,
            )
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None

        try:
            data = resp.json()
        except ValueError:
            return None

        if not data.get("onlineAvailability"):
            return None

        price_raw = data.get("salePrice")
        price = f"${price_raw:.2f}" if isinstance(price_raw, (int, float)) else ""
        url = data.get("url") or data.get("addToCartUrl") or f"https://www.bestbuy.com/site/{sku}.p"
        return StockResult(
            store=None,
            product_key=key,
            product_name=prod.get("name", data.get("name") or key),
            status="ONLINE_IN_STOCK",
            url=url,
            price=price,
        )
