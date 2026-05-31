"""Target adapter.

Uses Target's RedSky aggregator (the same endpoints target.com itself
calls from the browser). The "key" is a long-lived public token embedded
in target.com's front-end JavaScript; it can be overridden via
TARGET_API_KEY env var if Target rotates it."""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Iterable

import requests

from ..geocode import geocode
from .base import Retailer, Store, StockResult

REDSKY_KEY = os.getenv("TARGET_API_KEY", "9f36aeafbe60771e321a7cc95a78140772ab3e96")
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class Target(Retailer):
    name = "Target"
    product_id_fields = ("target_tcin",)

    @staticmethod
    def _status_from_store_option(opt: dict[str, Any]) -> str:
        statuses = [
            (opt.get("order_pickup") or {}).get("availability_status", ""),
            (opt.get("in_store_only") or {}).get("availability_status", ""),
        ]
        if "IN_STOCK" in statuses:
            return "IN_STOCK"
        if "LIMITED_STOCK" in statuses:
            return "LIMITED"
        return "OUT"

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        resp = requests.get(
            "https://redsky.target.com/redsky_aggregations/v1/web/nearby_stores_v1",
            params={
                "key": REDSKY_KEY,
                "limit": 20,
                "within": max(int(radius_miles) + 5, 25),  # generous; we re-filter ourselves
                "place": f"{lat},{lng}",
                "visitor_id": uuid.uuid4().hex.upper(),
            },
            headers={"User-Agent": UA, "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        stores_raw = (
            resp.json()
            .get("data", {})
            .get("nearby_stores", {})
            .get("stores", [])
        )
        out: list[Store] = []
        for s in stores_raw:
            geo = s.get("geographic_specifications") or {}
            addr = s.get("mailing_address") or {}
            slat = geo.get("latitude")
            slng = geo.get("longitude")
            city = addr.get("city", "")
            state = addr.get("state") or addr.get("region", "")
            if slat is None or slng is None:
                address = ", ".join(
                    part
                    for part in (
                        addr.get("address_line1", ""),
                        city,
                        state,
                        addr.get("postal_code", ""),
                    )
                    if part
                )
                if not address:
                    continue
                try:
                    slat, slng = geocode(address)
                except Exception:
                    continue
            out.append(
                Store(
                    retailer="Target",
                    store_id=str(s.get("store_id")),
                    name=f"Target #{s.get('store_id')} — {city}, {state}".strip(", "),
                    lat=float(slat),
                    lng=float(slng),
                )
            )
        return out

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        yield from self._iter_products(products, stores, include_out=False)

    def inventory(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        yield from self._iter_products(products, stores, include_out=True)

    def _iter_products(
        self,
        products: dict[str, dict[str, Any]],
        stores: list[Store],
        include_out: bool,
    ) -> Iterable[StockResult]:
        for key, prod in products.items():
            tcin = (prod.get("target_tcin") or "").strip()
            if not tcin:
                continue
            url = f"https://www.target.com/p/A-{tcin}"
            for store in stores:
                result = self._check_one(tcin, store, prod, key, url, include_out=include_out)
                if result is not None:
                    yield result
                time.sleep(0.4)  # be polite

    def _check_one(
        self,
        tcin: str,
        store: Store,
        prod: dict[str, Any],
        key: str,
        url: str,
        include_out: bool = False,
    ) -> StockResult | None:
        try:
            resp = requests.get(
                "https://redsky.target.com/redsky_aggregations/v1/web/product_fulfillment_v1",
                params={
                    "key": REDSKY_KEY,
                    "tcin": tcin,
                    "store_id": store.store_id,
                    "pricing_store_id": store.store_id,
                    "latitude": store.lat,
                    "longitude": store.lng,
                    "has_pricing_store_id": "true",
                    "channel": "WEB",
                    "page": f"/p/A-{tcin}",
                },
                headers={"User-Agent": UA, "Accept": "application/json"},
                timeout=15,
            )
            if resp.status_code != 200:
                return None
            data = resp.json().get("data", {}).get("product", {}).get("fulfillment", {})
        except (requests.RequestException, ValueError):
            return None

        store_options = data.get("store_options") or []
        for opt in store_options:
            opt_store = (opt.get("store") or {}).get("store_id")
            if str(opt_store) != store.store_id:
                continue
            status = self._status_from_store_option(opt)
            if status == "OUT" and not include_out:
                return None
            return StockResult(
                store=store,
                product_key=key,
                product_name=prod.get("name", key),
                status=status,
                url=url,
            )
        return None
