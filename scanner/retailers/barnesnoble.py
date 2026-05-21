"""Barnes & Noble (online-only).

B&N carries sealed Pokémon TCG product, especially ETBs around release
dates. Public product pages embed availability text we can read without
login. Disabled by default; enable to track.

ID field: `barnesnoble_id` — numeric, visible in the URL like
    https://www.barnesandnoble.com/w/<slug>/<barnesnoble_id>
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

_OUT = re.compile(r"(out of stock|currently unavailable|temporarily out)", re.I)
_PRICE = re.compile(r'"price"\s*:\s*"?\$?([\d.]+)"?')


class BarnesNoble(Retailer):
    name = "Barnes & Noble"
    slug = "barnesnoble"
    online_only = True

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        return []

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        for key, prod in products.items():
            for bnid in variant_ids(prod, "barnesnoble_id"):
                url = f"https://www.barnesandnoble.com/w/-/{bnid}"
                resp = self.http_get(
                    url,
                    headers={"User-Agent": UA, "Accept": "text/html"},
                    timeout=20,
                )
                if resp is None or resp.status_code != 200:
                    continue
                text = resp.text or ""
                if _OUT.search(text):
                    continue
                if "Add to Bag" not in text and "addToBag" not in text:
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
