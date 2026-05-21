"""Pokémon Center (online-only).

The official storefront is Shopify-based. The cleanest signal is the
product-variant JSON exposed at /products/<slug>.js — gives availability
without parsing HTML."""
from __future__ import annotations

import time
from typing import Any, Iterable

from .base import Retailer, StockResult, Store, variant_ids

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class PokemonCenter(Retailer):
    name = "Pokemon Center"
    slug = "pokemoncenter"
    online_only = True

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        return []

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        for key, prod in products.items():
            for slug in variant_ids(prod, "pokemoncenter_slug"):
                url = f"https://www.pokemoncenter.com/product/{slug}"
                resp = self.http_get(
                    f"https://www.pokemoncenter.com/products/{slug}.js",
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
                    product_name=prod.get("name", key),
                    status="ONLINE_IN_STOCK",
                    url=url,
                    price=price,
                )
                time.sleep(0.4)
