"""Local game stores on Shopify — generic adapter.

A large fraction of LGS run on Shopify. Every Shopify storefront exposes
`<domain>/products/<slug>.js` returning a JSON document with `variants[]`
that each have `available` and `price` fields — the same shape Pokémon
Center uses. One adapter therefore covers many stores.

Config (in config.yaml):

    retailers:
      lgs_shopify:
        enabled: true
        stores:
          - { name: "Bob's TCG",   domain: "bobs-tcg.myshopify.com" }
          - { name: "Card Castle", domain: "cardcastle.com" }

Per-product (in data/products.yaml), one entry per store the product is
sold at:

    prismatic_evolutions_etb:
      lgs_shopify_slugs:
        "bobs-tcg.myshopify.com":  "pokemon-prismatic-evolutions-etb"
        "cardcastle.com":          "prismatic-elite-trainer-box"

Online-only — LGS rarely expose per-store inventory anyway. Pickup-in-
store at LGS is usually negotiated by DM, not surfaced via the site."""
from __future__ import annotations

import time
from typing import Any, Iterable

from .base import Retailer, StockResult, Store

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class LGSShopify(Retailer):
    name = "LGS (Shopify)"
    slug = "lgs_shopify"
    online_only = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # `stores: [{name, domain}, ...]` injected from RetailerCfg.extra
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
            slugs_by_domain = prod.get("lgs_shopify_slugs") or {}
            if not isinstance(slugs_by_domain, dict):
                continue
            for shop in self.stores:
                slug = (slugs_by_domain.get(shop["domain"]) or "").strip()
                if not slug:
                    continue
                product_url = f"https://{shop['domain']}/products/{slug}"
                resp = self.http_get(
                    f"https://{shop['domain']}/products/{slug}.js",
                    headers={"User-Agent": UA, "Accept": "application/json"},
                )
                if resp is None or resp.status_code != 200:
                    continue
                try:
                    data = resp.json()
                except ValueError:
                    continue
                variants = data.get("variants") or []
                available = any(v.get("available") for v in variants)
                if not available:
                    continue
                price_cents = data.get("price")
                price = f"${price_cents/100:.2f}" if isinstance(price_cents, (int, float)) else ""
                yield StockResult(
                    store=None,
                    product_key=key,
                    product_name=f"{prod.get('name', key)} ({shop['name']})",
                    status="ONLINE_IN_STOCK",
                    url=product_url,
                    price=price,
                )
                time.sleep(0.4)
