"""Best Buy adapter.

Uses the official Best Buy developer API:
    https://developer.bestbuy.com

Free key, generous quota (50k req/day, 5 req/sec), documented endpoints,
and — crucially — explicit ToS that permits this kind of inventory
polling. That makes Best Buy the cleanest retailer to wire up; it's also
the most likely to remain reliable long-term.

Configure with:
    retailers:
      bestbuy: { enabled: true, api_key: "${BESTBUY_API_KEY}" }
    # per-product:
    data/products.yaml:
      surging_sparks_etb:
        bestbuy_sku: "6566943"
"""
from __future__ import annotations

import time
from typing import Any, Iterable

from .base import Retailer, Store, StockResult, variant_ids
from ..log import get_logger

log = get_logger(__name__)


class BestBuy(Retailer):
    name = "Best Buy"
    slug = "bestbuy"

    BASE = "https://api.bestbuy.com/v1"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.api_key = (kwargs.get("api_key") or "").strip()

    # --- store discovery ---

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        if not self.api_key:
            log.warning("bestbuy enabled but api_key is empty; skipping store discovery")
            return []
        resp = self.http_get(
            f"{self.BASE}/stores(area({lat},{lng},{int(radius_miles)+5}))",
            params={
                "format": "json",
                "show": "storeId,name,city,region,lat,lng",
                "pageSize": 50,
                "apiKey": self.api_key,
            },
            headers={"Accept": "application/json"},
        )
        if resp is None or resp.status_code != 200:
            return []
        try:
            payload = resp.json()
        except ValueError:
            return []
        out: list[Store] = []
        for s in payload.get("stores") or []:
            try:
                slat = float(s.get("lat"))
                slng = float(s.get("lng"))
            except (TypeError, ValueError):
                continue
            store_id = str(s.get("storeId") or "")
            if not store_id:
                continue
            out.append(
                Store(
                    retailer="Best Buy",
                    store_id=store_id,
                    name=f"Best Buy {s.get('name','')} — {s.get('city','')}, {s.get('region','')}",
                    lat=slat,
                    lng=slng,
                )
            )
        return out

    # --- stock check ---

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        if not self.api_key:
            return
        for key, prod in products.items():
            for sku in variant_ids(prod, "bestbuy_sku"):
                url = f"https://www.bestbuy.com/site/-/{sku}.p"
                for store in stores:
                    result = self._check_one(sku, store, prod, key, url)
                    if result is not None:
                        yield result
                    time.sleep(0.25)  # well under the 5 req/sec limit

    def _check_one(
        self, sku: str, store: Store, prod: dict[str, Any], key: str, url: str
    ) -> StockResult | None:
        # The /stores endpoint with a productId filter returns inventory rows
        # only for stores that actually have it. Querying per (sku, store)
        # is straightforward and stays well within the rate limit.
        resp = self.http_get(
            f"{self.BASE}/stores(storeId={store.store_id})+products(sku={sku})",
            params={
                "format": "json",
                "show": "products.sku,products.name,products.salePrice,products.regularPrice",
                "apiKey": self.api_key,
            },
            headers={"Accept": "application/json"},
        )
        if resp is None or resp.status_code != 200:
            return None
        try:
            payload = resp.json()
        except ValueError:
            return None
        stores_block = payload.get("stores") or []
        if not stores_block:
            return None
        products_block = (stores_block[0].get("products") or [])
        if not products_block:
            return None
        item = products_block[0]
        # Best Buy's per-store products endpoint only returns the product
        # when it's in-stock at that store, so presence is enough.
        sale = item.get("salePrice")
        price = f"${sale:.2f}" if isinstance(sale, (int, float)) else ""
        return StockResult(
            store=store,
            product_key=key,
            product_name=prod.get("name", key) or item.get("name", key),
            status="IN_STOCK",
            url=url,
            price=price,
        )
