"""TCGPlayer (online-only).

TCGPlayer is the dominant marketplace for sealed and singles. Their
public product pages embed a `__NEXT_DATA__` JSON blob with availability
+ price. We surface only sealed products marked as in-stock from TCGPlayer
*Direct* (their first-party fulfillment) when possible; third-party
marketplace listings are usually scalper-tier and excluded by the price
filter anyway.

ID field: `tcgplayer_product_id` — numeric, visible in the URL like
    https://www.tcgplayer.com/product/<productId>/<slug>
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Iterable

from .base import Retailer, StockResult, Store, variant_ids

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class TCGPlayer(Retailer):
    name = "TCGPlayer"
    slug = "tcgplayer"
    online_only = True

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        return []

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        for key, prod in products.items():
            for pid in variant_ids(prod, "tcgplayer_product_id"):
                url = f"https://www.tcgplayer.com/product/{pid}"
                resp = self.http_get(
                    url,
                    headers={
                        "User-Agent": UA,
                        "Accept": "text/html",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                    timeout=20,
                )
                if resp is None or resp.status_code != 200:
                    continue
                text = resp.text or ""
                m = re.search(
                    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                    text, re.S,
                )
                if not m:
                    continue
                try:
                    data = json.loads(m.group(1))
                except ValueError:
                    continue
                listings = _walk_listings(data)
                direct = _first_direct(listings)
                if direct is None:
                    continue
                price = ""
                if "price" in direct:
                    try:
                        price = f"${float(direct['price']):.2f}"
                    except (TypeError, ValueError):
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


def _walk_listings(obj: Any) -> list[dict]:
    """TCGPlayer's __NEXT_DATA__ buries listings deep in the props tree.
    Pull every dict that looks like a listing (has 'price' + a 'sellerName'
    or similar marker) via a generic walk."""
    out: list[dict] = []
    stack: list[Any] = [obj]
    while stack:
        v = stack.pop()
        if isinstance(v, dict):
            if "price" in v and ("sellerName" in v or "shippingPrice" in v or "directProduct" in v):
                out.append(v)
            stack.extend(v.values())
        elif isinstance(v, list):
            stack.extend(v)
    return out


def _first_direct(listings: list[dict]) -> dict | None:
    """Prefer a TCGPlayer Direct listing (first-party, ships-from-TCGP)."""
    for l in listings:
        if l.get("directProduct") or "Direct" in str(l.get("sellerName", "")):
            return l
    # Fall back to any in-stock listing if no Direct one.
    return listings[0] if listings else None
