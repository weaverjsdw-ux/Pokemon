"""Best Buy adapter.

Uses the official Best Buy Products API for online availability checks.
Requires `retailers.bestbuy.api_key` in config.yaml and `bestbuy_sku`
values in data/products.yaml.
"""
from __future__ import annotations

import time
from typing import Any, Iterable

import requests

from . import http
from .base import Retailer, StockResult, Store


class BestBuy(Retailer):
    name = "Best Buy"
    online_only = True
    product_id_fields = ("bestbuy_sku",)
    api_key_required = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.api_key = str(kwargs.get("api_key") or "").strip()

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        return []

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        yield from self._iter_products(products, include_out=False)

    def inventory(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        yield from self._iter_products(products, include_out=True)

    def _iter_products(
        self, products: dict[str, dict[str, Any]], include_out: bool
    ) -> Iterable[StockResult]:
        if not self.api_key:
            return
        for key, prod in products.items():
            sku = str(prod.get("bestbuy_sku") or "").strip()
            if not sku:
                continue
            result = self._check_one(sku, prod, key, include_out=include_out)
            if result is not None:
                yield result
            time.sleep(0.4)

    def _check_one(
        self, sku: str, prod: dict[str, Any], key: str, include_out: bool = False
    ) -> StockResult | None:
        try:
            resp = http.get(
                f"https://api.bestbuy.com/v1/products/{sku}.json",
                retailer="bestbuy",
                params={
                    "apiKey": self.api_key,
                    # Official, stable fields per the Best Buy Products API.
                    "show": (
                        "sku,name,salePrice,regularPrice,onlineAvailability,"
                        "inStoreAvailability,inStorePickup,url,addToCartUrl"
                    ),
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

        online = bool(data.get("onlineAvailability"))
        in_store = bool(data.get("inStoreAvailability"))
        available = online or in_store
        if not available and not include_out:
            return None

        sale = data.get("salePrice")
        regular = data.get("regularPrice")
        price = f"${sale:.2f}" if isinstance(sale, (int, float)) else (
            f"${regular:.2f}" if isinstance(regular, (int, float)) else ""
        )
        url = data.get("url") or data.get("addToCartUrl") or f"https://www.bestbuy.com/site/{sku}.p"
        return StockResult(
            store=None,
            product_key=key,
            product_name=prod.get("name", data.get("name") or key),
            status="ONLINE_IN_STOCK" if available else "ONLINE_OUT",
            url=url,
            price=price,
        )
