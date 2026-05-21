"""Meijer (online + store).

Midwest-only chain that carries sealed TCG. Their public product page
exposes both online availability and a store-level inventory blob if
you POST a zip. For simplicity we surface only online availability;
contributions for store-level lookup are welcome.

ID field: `meijer_product_id` — numeric, visible in the URL like
    https://www.meijer.com/shopping/product/<slug>/<id>.html
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

_PRICE = re.compile(r'"price"\s*:\s*"?\$?([\d.]+)"?')


class Meijer(Retailer):
    name = "Meijer"
    slug = "meijer"
    online_only = True

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        return []

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        for key, prod in products.items():
            for pid in variant_ids(prod, "meijer_product_id"):
                url = f"https://www.meijer.com/shopping/product/-/{pid}.html"
                resp = self.http_get(
                    url,
                    headers={"User-Agent": UA, "Accept": "text/html"},
                    timeout=20,
                )
                if resp is None or resp.status_code != 200:
                    continue
                text = resp.text or ""
                if re.search(r'"available"\s*:\s*false', text) or "Out of Stock" in text:
                    continue
                if '"available":true' not in text and "Add to Cart" not in text:
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
