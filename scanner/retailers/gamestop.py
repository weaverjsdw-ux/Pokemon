"""GameStop adapter.

GameStop's site has a per-product BOPIS (buy online, pickup in store)
endpoint that returns store-level inventory. Like Walmart, this isn't a
documented API — surface area is small and changes infrequently.
"""
from __future__ import annotations

import re
import time
from typing import Any, Iterable

from .base import Retailer, Store, StockResult, variant_ids

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class GameStop(Retailer):
    name = "GameStop"
    slug = "gamestop"

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        resp = self.http_get(
            "https://www.gamestop.com/on/demandware.store/Sites-gamestop-Site/default/Stores-FindStores",
            params={
                "latitude": lat,
                "longitude": lng,
                "radius": int(radius_miles) + 5,
                "showMap": "false",
            },
            headers={"User-Agent": UA, "Accept": "application/json"},
        )
        if resp is None or resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except ValueError:
            return []
        out: list[Store] = []
        for s in data.get("stores") or []:
            try:
                slat = float(s.get("latitude"))
                slng = float(s.get("longitude"))
            except (TypeError, ValueError):
                continue
            store_id = str(s.get("ID") or s.get("storeId") or "")
            if not store_id:
                continue
            out.append(
                Store(
                    retailer="GameStop",
                    store_id=store_id,
                    name=f"GameStop {s.get('name','')} — {s.get('city','')}, {s.get('stateCode','')}",
                    lat=slat,
                    lng=slng,
                )
            )
        return out

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        for key, prod in products.items():
            for pid in variant_ids(prod, "gamestop_pid"):
                url = f"https://www.gamestop.com/p/{pid}"
                for store in stores:
                    result = self._check_one(pid, store, prod, key, url)
                    if result is not None:
                        yield result
                    time.sleep(0.4)

    def _check_one(
        self, pid: str, store: Store, prod: dict[str, Any], key: str, url: str,
    ) -> StockResult | None:
        resp = self.http_get(
            "https://www.gamestop.com/on/demandware.store/Sites-gamestop-Site/default/Stores-InventorySearch",
            params={"pid": pid, "storeId": store.store_id},
            headers={"User-Agent": UA, "Accept": "application/json"},
        )
        if resp is None or resp.status_code != 200:
            return None
        # GameStop returns an HTML fragment whose availability is encoded in
        # text; the regex check is intentionally permissive.
        text = resp.text or ""
        if re.search(r"in[\s-]*stock", text, re.I) and not re.search(
            r"out[\s-]*of[\s-]*stock", text, re.I
        ):
            return StockResult(
                store=store,
                product_key=key,
                product_name=prod.get("name", key),
                status="IN_STOCK",
                url=url,
            )
        return None
