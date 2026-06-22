"""Costco adapter.

Uses Costco's first-party warehouse locator, product-summary, distribution
center, and inventory availability endpoints. Product catalog entries use the
public Costco parent item number from the product URL (``costco_item_id``);
the adapter resolves child item numbers before asking the inventory endpoint.
"""
from __future__ import annotations

import datetime as dt
import html
import re
import time
import unicodedata
from typing import Any, Iterable

import requests

from . import http
from .base import Retailer, StockResult, Store

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

WAREHOUSE_URL = "https://ecom-api.costco.com/core/warehouse-locator/v1/warehouses.json"
GDX_SUMMARY_URL = "https://gdx-api.costco.com/catalog/product/product-api/v1/products/summary"
DIST_CENTERS_URL = (
    "https://ecom-api.costco.com/ebusiness/inventory/v1/location/distributioncenters"
)
INVENTORY_URL = (
    "https://ecom-api.costco.com/ebusiness/inventory/v1/inventorylevels/availability/batch"
)

WAREHOUSE_CLIENT_ID = "7c71124c-7bf1-44db-bc9d-498584cd66e5"
GDX_CLIENT_ID = "4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf"
GDX_CLIENT_IDENTIFIER = "b1be4e95-8696-4d93-8f50-5b5632922209"
INVENTORY_CLIENT_ID = "481b1aec-aa3b-454b-b81b-48187e28f205"

IN_STOCK_VALUES = {"INSTOCK", "AVAILABLE", "INVENTORYAVAILABLE"}
LIMITED_VALUES = {"LOWSTOCK", "LIMITEDSTOCK"}
OUT_VALUES = {"NOSTOCK", "OUTOFSTOCK", "UNAVAILABLE"}


def _as_text(value: Any) -> str:
    if isinstance(value, dict):
        return _as_text(value.get("value"))
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and str(item.get("localeCode") or "").lower() == "en-us":
                return _as_text(item)
        return _as_text(value[0]) if value else ""
    if value is None:
        return ""
    return str(value).strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _as_text(value)
        if text:
            return text
    return ""


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", html.unescape(text or "")).strip()


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _normalize_availability(value: Any) -> str:
    return re.sub(r"[^A-Z]", "", str(value or "").upper())


def _slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value[:90].strip("-")


def _price_text(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"${value:.2f}"
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("$"):
        return text
    try:
        return f"${float(text):.2f}"
    except ValueError:
        return text


def _flatten_programs(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if any(
            key in value
            for key in (
                "availability",
                "availabilityStatus",
                "inventoryStatus",
                "availableQuantity",
                "quantityAvailable",
            )
        ):
            yield value
            return
        for child in value.values():
            yield from _flatten_programs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _flatten_programs(child)


def _localized_object_field(data: dict[str, Any], list_key: str, field: str) -> str:
    rows = data.get(list_key) or []
    if not isinstance(rows, list):
        return ""
    first_value = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        obj = row.get("object")
        if not isinstance(obj, dict):
            continue
        value = _first_text(obj.get(field))
        if not value:
            continue
        if not first_value:
            first_value = value
        if str(row.get("languageKey") or "").lower() == "en-us":
            return value
    return first_value


class Costco(Retailer):
    name = "Costco"
    online_only = False
    supported = True
    product_id_fields = ("costco_item_id",)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._distribution_cache: dict[tuple[str, str], list[str]] = {}
        self._summary_cache: dict[tuple[str, str], dict[str, Any] | None] = {}

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        try:
            resp = http.get(
                WAREHOUSE_URL,
                retailer="costco",
                params={
                    "latitude": lat,
                    "longitude": lng,
                    "limit": 50,
                    "openingDate": dt.date.today().isoformat(),
                },
                headers={
                    "User-Agent": UA,
                    "Accept": "application/json",
                    "Accept-Language": "en-us",
                    "client-identifier": WAREHOUSE_CLIENT_ID,
                },
                timeout=20,
            )
            if resp.status_code != 200:
                return []
            payload = resp.json()
        except (requests.RequestException, ValueError):
            return []

        out: list[Store] = []
        for raw in payload.get("warehouses") or []:
            store = self._store_from_payload(raw)
            if store is not None:
                out.append(store)
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
            item_id = str(prod.get("costco_item_id") or "").strip()
            if not item_id:
                continue
            for store in stores:
                result = self._check_one(item_id, store, prod, key, include_out=include_out)
                if result is not None:
                    yield result
                time.sleep(0.4)

    def _check_one(
        self,
        item_id: str,
        store: Store,
        prod: dict[str, Any],
        key: str,
        include_out: bool,
    ) -> StockResult | None:
        summary = self._summary_for_item(item_id, store.store_id)
        if summary is None:
            return None

        child_ids = self._child_item_ids(summary) or [item_id]
        centers = self._distribution_centers_for_store(store)
        if not centers:
            return None

        data = self._inventory_for_items(child_ids, centers, store.store_id)
        if data is None:
            return None

        status = self._status_from_inventory(data, child_ids)
        if status == "OUT" and not include_out:
            return None

        return StockResult(
            store=store,
            product_key=key,
            product_name=self._product_name(summary, prod, key),
            status=status,
            url=self._product_url(item_id, summary),
            price=self._product_price(summary),
        )

    @staticmethod
    def _store_from_payload(raw: dict[str, Any]) -> Store | None:
        address_raw = raw.get("address")
        geo_raw = raw.get("geoPoint") or raw.get("geo")
        address = address_raw if isinstance(address_raw, dict) else {}
        geo = geo_raw if isinstance(geo_raw, dict) else {}
        store_id = _first_text(raw.get("warehouseId"), raw.get("id"), raw.get("warehouseNumber"))
        if not store_id:
            return None
        try:
            lat = float(
                _first_text(raw.get("latitude"), geo.get("latitude"), address.get("latitude"))
            )
            lng = float(
                _first_text(raw.get("longitude"), geo.get("longitude"), address.get("longitude"))
            )
        except ValueError:
            return None

        name = _first_text(raw.get("name"), raw.get("displayName"), f"#{store_id}")
        address_line = _first_text(
            raw.get("addressLine1"),
            raw.get("address1"),
            address.get("line1"),
            address.get("addressLine1"),
            address.get("streetAddress"),
        )
        city = _first_text(raw.get("city"), address.get("city")).upper()
        state = _first_text(
            raw.get("state"),
            raw.get("stateCode"),
            address.get("state"),
            address.get("stateCode"),
            address.get("territory"),
        ).upper()
        postal = _first_text(
            raw.get("postalCode"),
            raw.get("zipCode"),
            address.get("postalCode"),
            address.get("zipCode"),
        )
        suffix = ", ".join(part for part in (city, state) if part)
        label = f"Costco {name} #{store_id}"
        if suffix:
            label = f"{label} - {suffix}"
        return Store(
            retailer="Costco",
            store_id=store_id,
            name=label,
            lat=lat,
            lng=lng,
            address=address_line,
            city=city,
            state=state,
            postal_code=postal,
        )

    def _summary_for_item(self, item_id: str, warehouse_id: str) -> dict[str, Any] | None:
        cache_key = (item_id, warehouse_id)
        if cache_key in self._summary_cache:
            return self._summary_cache[cache_key]
        try:
            resp = http.get(
                GDX_SUMMARY_URL,
                retailer="costco",
                params={
                    "clientId": GDX_CLIENT_ID,
                    "items": item_id,
                    "whsNumber": warehouse_id,
                    "locales": "en-US",
                },
                headers={
                    "User-Agent": UA,
                    "Accept": "application/json",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.costco.com/",
                    "client-identifier": GDX_CLIENT_IDENTIFIER,
                    "costco-env": "prd",
                },
                timeout=20,
            )
            if resp.status_code != 200:
                self._summary_cache[cache_key] = None
                return None
            payload = resp.json()
        except (requests.RequestException, ValueError):
            self._summary_cache[cache_key] = None
            return None

        product_rows = payload.get("productData") or payload.get("products") or []
        summary = product_rows[0] if product_rows and isinstance(product_rows[0], dict) else None
        self._summary_cache[cache_key] = summary
        return summary

    @staticmethod
    def _child_item_ids(summary: dict[str, Any]) -> list[str]:
        children = summary.get("childCatalogData") or summary.get("children") or []
        out: list[str] = []
        for child in children:
            if not isinstance(child, dict):
                continue
            child_id = _first_text(child.get("id"), child.get("itemNumber"), child.get("sku"))
            if child_id:
                out.append(child_id)
        return out

    def _distribution_centers_for_store(self, store: Store) -> list[str]:
        postal = _digits(store.postal_code)[:5]
        state = (store.state or "").strip().upper()
        if not postal or not state:
            return []
        cache_key = (postal, state)
        if cache_key in self._distribution_cache:
            return self._distribution_cache[cache_key]
        try:
            resp = http.get(
                DIST_CENTERS_URL,
                retailer="costco",
                params={"destinationPostalCode": postal, "stateCode": state},
                headers={
                    "User-Agent": UA,
                    "Accept": "application/json",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.costco.com/",
                    "client-identifier": INVENTORY_CLIENT_ID,
                    "costco.service": "restInventory",
                },
                timeout=20,
            )
            if resp.status_code != 200:
                self._distribution_cache[cache_key] = []
                return []
            payload = resp.json()
        except (requests.RequestException, ValueError):
            self._distribution_cache[cache_key] = []
            return []

        centers = [
            str(value)
            for value in (
                list(payload.get("distributionCenters") or [])
                + list(payload.get("groceryCenters") or [])
            )
            if str(value).strip()
        ]
        self._distribution_cache[cache_key] = centers
        return centers

    def _inventory_for_items(
        self, item_ids: list[str], centers: list[str], warehouse_id: str
    ) -> dict[str, Any] | None:
        try:
            resp = http.post(
                INVENTORY_URL,
                retailer="costco",
                json={
                    "distributionCenters": centers,
                    "itemNumbers": item_ids,
                    "selectedWarehouse": warehouse_id,
                },
                headers={
                    "User-Agent": UA,
                    "Accept": "application/json",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Content-Type": "application/json",
                    "Origin": "https://www.costco.com",
                    "Referer": "https://www.costco.com/",
                    "client-identifier": INVENTORY_CLIENT_ID,
                    "costco.env": "PROD",
                    "costco.service": "restInventory",
                },
                timeout=20,
            )
            if resp.status_code != 200:
                return None
            return resp.json()
        except (requests.RequestException, ValueError):
            return None

    @staticmethod
    def _inventory_rows(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if not isinstance(data, dict):
            return []
        for key in ("inventoryLevels", "inventory", "items", "availability"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        if "programTypes" in data or "itemNumber" in data:
            return [data]
        rows: list[dict[str, Any]] = []
        for value in data.values():
            if isinstance(value, list):
                rows.extend(row for row in value if isinstance(row, dict))
        return rows

    @classmethod
    def _status_from_inventory(cls, data: Any, item_ids: list[str]) -> str:
        wanted = {str(item_id) for item_id in item_ids}
        limited = False
        for row in cls._inventory_rows(data):
            row_item = _first_text(row.get("itemNumber"), row.get("itemNo"), row.get("itemId"))
            if row_item and wanted and row_item not in wanted:
                continue
            programs = list(_flatten_programs(row.get("programTypes") or row))
            for program in programs:
                raw_status = _first_text(
                    program.get("availability"),
                    program.get("availabilityStatus"),
                    program.get("inventoryStatus"),
                    program.get("status"),
                )
                status = _normalize_availability(raw_status)
                if status in IN_STOCK_VALUES:
                    return "IN_STOCK"
                if status in LIMITED_VALUES:
                    limited = True
                quantity = program.get("availableQuantity", program.get("quantityAvailable"))
                if quantity is not None:
                    try:
                        if float(quantity) > 0:
                            return "IN_STOCK"
                    except (TypeError, ValueError):
                        pass
                if status in OUT_VALUES:
                    continue
        return "LIMITED" if limited else "OUT"

    @staticmethod
    def _product_name(summary: dict[str, Any], prod: dict[str, Any], key: str) -> str:
        return _strip_html(
            _first_text(
                summary.get("shortDescription"),
                summary.get("description"),
                summary.get("name"),
                _localized_object_field(summary, "descriptions", "shortDescription"),
                prod.get("name"),
                key,
            )
        )

    @staticmethod
    def _product_url(item_id: str, summary: dict[str, Any]) -> str:
        name = Costco._product_name(summary, {}, item_id)
        slug = _slugify(name)
        if slug and slug != item_id:
            return f"https://www.costco.com/{slug}.product.{item_id}.html"
        return f"https://www.costco.com/.product.{item_id}.html"

    @staticmethod
    def _product_price(summary: dict[str, Any]) -> str:
        price_data = summary.get("priceData") or {}
        return _price_text(
            _first_text(
                summary.get("displayPrice"),
                summary.get("price"),
                price_data.get("displayPrice"),
                price_data.get("salePrice"),
                price_data.get("listPrice"),
            )
        )
