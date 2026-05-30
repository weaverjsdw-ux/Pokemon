"""Walmart adapter.

Walmart no longer exposes a publicly documented inventory API. The
adapter hits the same store finder + product-page JSON used by
walmart.com itself. These endpoints change occasionally; if you see
parse failures, check the Network tab on a Walmart product page and
update the URLs/fields here."""
from __future__ import annotations

import re
import time
from typing import Any, Iterable

import requests

from .base import Retailer, Store, StockResult

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class Walmart(Retailer):
    name = "Walmart"
    online_only = True
    product_id_fields = ("walmart_item_id",)

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        try:
            resp = requests.get(
                "https://www.walmart.com/store/finder/electrode/api/stores",
                params={"singleLineAddr": f"{lat},{lng}", "distance": int(radius_miles) + 5},
                headers={
                    "User-Agent": UA,
                    "Accept": "application/json",
                    "Referer": "https://www.walmart.com/store/finder",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                return []
            payload = resp.json()
        except (requests.RequestException, ValueError):
            return []

        stores_raw = payload.get("payload", {}).get("storesData", {}).get("stores", [])
        out: list[Store] = []
        for s in stores_raw:
            geo = s.get("geoPoint") or {}
            addr = s.get("address") or {}
            try:
                slat = float(geo.get("latitude"))
                slng = float(geo.get("longitude"))
            except (TypeError, ValueError):
                continue
            store_id = str(s.get("id") or s.get("storeId") or "")
            if not store_id:
                continue
            out.append(
                Store(
                    retailer="Walmart",
                    store_id=store_id,
                    name=f"Walmart #{store_id} — {addr.get('city','')}, {addr.get('state','')}",
                    lat=slat,
                    lng=slng,
                )
            )
        return out

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        for key, prod in products.items():
            item_id = (prod.get("walmart_item_id") or "").strip()
            if not item_id:
                continue
            url = f"https://www.walmart.com/ip/{item_id}"
            online = self._check_online(item_id, url, prod, key)
            if online is not None:
                yield online
            time.sleep(0.6)

    def _check_online(
        self, item_id: str, url: str, prod: dict[str, Any], key: str
    ) -> StockResult | None:
        """Parse the JSON-LD / __NEXT_DATA__ blob embedded in the product page
        to determine online availability. Store-level pickup status is in the
        same blob; we surface online as the primary signal because Walmart's
        store inventory feed is unreliable."""
        try:
            resp = requests.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "text/html",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=20,
            )
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        m = re.search(
            r'"availabilityStatus"\s*:\s*"(IN_STOCK|OUT_OF_STOCK|LIMITED_STOCK)"',
            resp.text,
        )
        if not m:
            return None
        status_raw = m.group(1)
        if status_raw == "OUT_OF_STOCK":
            return None
        status = "ONLINE_IN_STOCK" if status_raw == "IN_STOCK" else "LIMITED"
        return StockResult(
            store=None,
            product_key=key,
            product_name=prod.get("name", key),
            status=status,
            url=url,
        )
