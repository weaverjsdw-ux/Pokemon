"""Costco (online-only).

Costco.com surfaces availability through their product-detail JSON
endpoint. Per docs/retailer-tos.md, this adapter is disabled by default
because Costco's ToS prohibits scraping; enabling it is the user's call.

ID field: `costco_item_id` — numeric, visible in the product URL like
    https://www.costco.com/.product.<itemId>.html
"""
from __future__ import annotations

import re
import time
from typing import Any, Iterable

from .base import Retailer, StockResult, Store, variant_ids

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class Costco(Retailer):
    name = "Costco"
    slug = "costco"
    online_only = True

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        return []

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        for key, prod in products.items():
            for item_id in variant_ids(prod, "costco_item_id"):
                url = f"https://www.costco.com/.product.{item_id}.html"
                resp = self.http_get(
                    url,
                    headers={"User-Agent": UA, "Accept": "text/html"},
                    timeout=20,
                )
                if resp is None or resp.status_code != 200:
                    continue
                text = resp.text or ""
                # Costco product pages embed an "inventory" JSON-LD field; the
                # cheapest reliable signal is the "Add to Cart" button or the
                # 'OutOfStockMessage' marker.
                if 'OutOfStockMessage' in text or 'out of stock' in text.lower():
                    continue
                if 'Add to Cart' not in text and 'addToCart' not in text:
                    continue
                # Extract price if we can find it; tolerant on failure.
                price = ""
                m = re.search(r'"price"\s*:\s*"?\$?([\d.,]+)"?', text)
                if m:
                    try:
                        price = f"${float(m.group(1).replace(',', '')):.2f}"
                    except ValueError:
                        pass
                yield StockResult(
                    store=None,
                    product_key=key,
                    product_name=prod.get("name", key),
                    status="ONLINE_IN_STOCK",
                    url=url,
                    price=price,
                )
                time.sleep(0.6)
