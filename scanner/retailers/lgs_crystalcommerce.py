"""Local game stores on Crystal Commerce — generic adapter.

Crystal Commerce is the dominant POS for TCG-focused LGS in the US.
Their stores typically live at `<storename>.crystalcommerce.com` or a
custom domain pointed at it. Product pages render server-side HTML with
a `data-add-variant` / `add-to-cart` form when the item is in stock.

Same configuration model as lgs_shopify:

    retailers:
      lgs_crystalcommerce:
        enabled: true
        stores:
          - { name: "City Cards", domain: "citycards.crystalcommerce.com" }
          - { name: "Card Coalition", domain: "cardcoalition.com" }

Per-product (in data/products.yaml):

    prismatic_evolutions_etb:
      lgs_crystalcommerce_paths:
        "citycards.crystalcommerce.com": "products/pokemon-prismatic-etb"
        "cardcoalition.com":             "products/pokemon-tcg-prismatic-evolutions-etb"

Each value is the *path*, not the full URL, so the same path can be
reused across stores when the slugs happen to match.

Square and BinderPOS LGS storefronts follow this same shape (stores +
per-product path map) — contributing equivalent adapters is a copy +
swap-the-in-stock-marker job."""
from __future__ import annotations

import re
import time
from typing import Any, Iterable

from .base import Retailer, StockResult, Store

from ..useragents import UA

# Crystal Commerce shows an "Add to Cart" button only when in stock; the
# form action is consistently /cart/add for in-stock items.
_OUT = re.compile(r"out\s*of\s*stock|sold\s*out", re.I)
_IN = re.compile(r"add\s*to\s*cart|/cart/add", re.I)
_PRICE = re.compile(r'\$\s*([0-9]+(?:\.[0-9]{2})?)')


class LGSCrystalCommerce(Retailer):
    name = "LGS (Crystal Commerce)"
    slug = "lgs_crystalcommerce"
    online_only = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        raw_stores = kwargs.get("stores") or []
        self.stores = [
            {
                "name": str(s.get("name") or s.get("domain") or "").strip(),
                "domain": str(s.get("domain") or "").strip().rstrip("/"),
            }
            for s in raw_stores
            if isinstance(s, dict) and s.get("domain")
        ]

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        return []

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        if not self.stores:
            return
        for key, prod in products.items():
            paths = prod.get("lgs_crystalcommerce_paths") or {}
            if not isinstance(paths, dict):
                continue
            for shop in self.stores:
                path = (paths.get(shop["domain"]) or "").strip().lstrip("/")
                if not path:
                    continue
                url = f"https://{shop['domain']}/{path}"
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
                if not _IN.search(text):
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
                    product_name=f"{prod.get('name', key)} ({shop['name']})",
                    status="ONLINE_IN_STOCK",
                    url=url,
                    price=price,
                )
                time.sleep(0.4)
