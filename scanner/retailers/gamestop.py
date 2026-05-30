"""GameStop adapter.

GameStop's site has a per-product BOPIS (buy online, pickup in store)
endpoint that returns store-level inventory. Like Walmart, this isn't a
documented API — surface area is small and changes infrequently.
"""
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


class GameStop(Retailer):
    name = "GameStop"
    product_id_fields = ("gamestop_pid",)

    @staticmethod
    def _inventory_text_in_stock(text: str) -> bool:
        if re.search(r"out[\s-]*of[\s-]*stock|not\s+available|unavailable", text, re.I):
            return False
        return bool(re.search(r"\bin[\s-]*stock\b", text, re.I))

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        try:
            resp = requests.get(
                "https://www.gamestop.com/on/demandware.store/Sites-gamestop-Site/default/Stores-FindStores",
                params={
                    "latitude": lat,
                    "longitude": lng,
                    "radius": int(radius_miles) + 5,
                    "showMap": "false",
                },
                headers={"User-Agent": UA, "Accept": "application/json"},
                timeout=15,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
        except (requests.RequestException, ValueError):
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
            pid = (prod.get("gamestop_pid") or "").strip()
            if not pid:
                continue
            url = f"https://www.gamestop.com/p/{pid}"
            for store in stores:
                try:
                    resp = requests.get(
                        "https://www.gamestop.com/on/demandware.store/Sites-gamestop-Site/default/Stores-InventorySearch",
                        params={"pid": pid, "storeId": store.store_id},
                        headers={"User-Agent": UA, "Accept": "application/json"},
                        timeout=15,
                    )
                except requests.RequestException:
                    continue
                if resp.status_code != 200:
                    continue
                # GameStop returns HTML fragment with availability text; fall
                # back to a regex on the response body.
                text = resp.text or ""
                if self._inventory_text_in_stock(text):
                    yield StockResult(
                        store=store,
                        product_key=key,
                        product_name=prod.get("name", key),
                        status="IN_STOCK",
                        url=url,
                    )
                time.sleep(0.4)
