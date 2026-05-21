"""Sam's Club (online-only).

Like Costco, Sam's surfaces inventory through its public product pages.
Per docs/retailer-tos.md, disabled by default since their terms prohibit
scraping.

ID field: `samsclub_product_id` — numeric, visible in the URL like
    https://www.samsclub.com/p/<slug>/<productId>
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


class SamsClub(Retailer):
    name = "Sam's Club"
    slug = "samsclub"
    online_only = True

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        return []

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        for key, prod in products.items():
            for pid in variant_ids(prod, "samsclub_product_id"):
                url = f"https://www.samsclub.com/p/-/{pid}"
                resp = self.http_get(
                    url,
                    headers={"User-Agent": UA, "Accept": "text/html",
                             "Accept-Language": "en-US,en;q=0.9"},
                    timeout=20,
                )
                if resp is None or resp.status_code != 200:
                    continue
                text = resp.text or ""
                # Sam's surfaces an inventory status in their __NEXT_DATA__
                # blob; AVAILABLE / OUT_OF_STOCK are the two stable values.
                if re.search(r'"onlineInventory"\s*:\s*\{[^}]*"status"\s*:\s*"OUT_OF_STOCK"', text):
                    continue
                if not re.search(r'"onlineInventory"\s*:\s*\{[^}]*"status"\s*:\s*"AVAILABLE"', text):
                    continue
                price = ""
                m = re.search(r'"finalPrice"\s*:\s*"?\$?([\d.,]+)"?', text)
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
