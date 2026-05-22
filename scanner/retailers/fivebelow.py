"""Five Below (online + store, online surfaced here).

5B carries blister packs and tins for under-MSRP price. Highly desirable
for cost-conscious tracking; also extremely volatile inventory.

ID field: `fivebelow_product_id` — alphanumeric slug, visible in URL like
    https://www.fivebelow.com/p/<product-slug>
"""
from __future__ import annotations

import re
import time
from typing import Any, Iterable

from .base import Retailer, StockResult, Store, variant_ids

from ..useragents import UA

_PRICE = re.compile(r'"price"\s*:\s*"?\$?([\d.]+)"?')


class FiveBelow(Retailer):
    name = "Five Below"
    slug = "fivebelow"
    online_only = True

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        return []

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        for key, prod in products.items():
            for slug in variant_ids(prod, "fivebelow_product_id"):
                url = f"https://www.fivebelow.com/p/{slug}"
                resp = self.http_get(
                    url,
                    headers={"User-Agent": UA, "Accept": "text/html"},
                    timeout=20,
                )
                if resp is None or resp.status_code != 200:
                    continue
                text = resp.text or ""
                if 'inventoryStatus":"out_of_stock' in text or 'Sold Out' in text:
                    continue
                if 'inventoryStatus":"in_stock' not in text and 'Add to Cart' not in text:
                    continue
                price = ""
                m = _PRICE.search(text)
                if m:
                    try:
                        price = f"${float(m.group(1)):.2f}"
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
                time.sleep(0.5)
