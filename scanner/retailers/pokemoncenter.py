"""Pokémon Center (online-only, multi-region).

The official storefront is Shopify-based. The cleanest signal is the
product-variant JSON exposed at /products/<slug>.js — gives availability
without parsing HTML.

Region support: by default we poll the US storefront. Users who watch
multiple regions can add them to config:

    retailers:
      pokemoncenter:
        enabled: true
        regions:
          - { code: us, base: "https://www.pokemoncenter.com",        currency: "$"  }
          - { code: gb, base: "https://www.pokemoncenter.com/en-gb",  currency: "£"  }
          - { code: ca, base: "https://www.pokemoncenter.com/en-ca",  currency: "C$" }

Each enabled region polls the same per-product `pokemoncenter_slug`.
URL structure occasionally changes — `base` is overrideable so the user
can adapt without code changes."""
from __future__ import annotations

import time
from typing import Any, Iterable

from .base import Retailer, StockResult, Store, variant_ids

from ..useragents import UA


_DEFAULT_REGIONS = [
    {"code": "us", "base": "https://www.pokemoncenter.com", "currency": "$"},
]


class PokemonCenter(Retailer):
    name = "Pokemon Center"
    slug = "pokemoncenter"
    online_only = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        raw_regions = kwargs.get("regions") or _DEFAULT_REGIONS
        self.regions = []
        for r in raw_regions:
            if not isinstance(r, dict):
                continue
            base = str(r.get("base") or "").strip().rstrip("/")
            if not base:
                continue
            self.regions.append({
                "code": str(r.get("code") or "us").strip().lower(),
                "base": base,
                "currency": str(r.get("currency") or "$"),
            })
        if not self.regions:
            self.regions = list(_DEFAULT_REGIONS)

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        return []

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        for key, prod in products.items():
            for slug in variant_ids(prod, "pokemoncenter_slug"):
                for region in self.regions:
                    yield from self._check_region(key, prod, slug, region)

    def _check_region(self, key, prod, slug, region):
        url = f"{region['base']}/product/{slug}"
        resp = self.http_get(
            f"{region['base']}/products/{slug}.js",
            headers={"User-Agent": UA, "Accept": "application/json"},
        )
        if resp is None or resp.status_code != 200:
            return
        try:
            data = resp.json()
        except ValueError:
            return
        variants = data.get("variants") or []
        available = any(v.get("available") for v in variants)
        if not available:
            return
        price_cents = data.get("price")
        cur = region["currency"]
        price = f"{cur}{price_cents/100:.2f}" if isinstance(price_cents, (int, float)) else ""
        region_tag = f" [{region['code'].upper()}]" if region["code"] != "us" else ""
        yield StockResult(
            store=None,
            product_key=key,
            product_name=f"{prod.get('name', key)}{region_tag}",
            status="ONLINE_IN_STOCK",
            url=url,
            price=price,
        )
        time.sleep(0.4)
