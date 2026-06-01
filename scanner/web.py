"""Local web UI and JSON API for the scanner.

Run with:

  python -m scanner.web
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import mimetypes
import re
import sys
import threading
import time
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from . import config as cfg_mod
from . import coverage as coverage_mod
from . import health
from .identifiers import extract_id, field_for_slug, set_product_id
from .main import (
    build_corridor,
    check_config,
    config_errors,
    discover_stores,
    enabled_retailer_slugs,
    run_pass,
    safe_demo_results,
    safe_demo_stores,
)
from .notify import Notifier, StockAlert
from .priority import product_priority
from .retailers import ALL as RETAILER_REGISTRY
from .retailers.base import StockResult, Store
from .state import State

ASSETS_DIR = Path(__file__).resolve().parent / "web_assets"
EXAMPLE_CONFIG_PATH = cfg_mod.ROOT / "config.example.yaml"
POSITIVE_STATUSES = {"IN_STOCK", "LIMITED", "ONLINE_IN_STOCK"}
LAST_STORE_DIAGNOSTICS: list[dict[str, Any]] = []


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_current_config() -> tuple[cfg_mod.Config, bool]:
    config_missing = not cfg_mod.CONFIG_PATH.exists()
    path = EXAMPLE_CONFIG_PATH if config_missing else cfg_mod.CONFIG_PATH
    return cfg_mod.load(path), config_missing


def _selected_products_or_empty(cfg: cfg_mod.Config) -> dict[str, dict[str, Any]]:
    try:
        return cfg_mod.selected_products(cfg)
    except SystemExit:
        return {}


def _api_key_missing(cls: type, rcfg: cfg_mod.RetailerCfg) -> bool:
    return bool(getattr(cls, "api_key_required", False) and not rcfg.api_key.strip())


def _query_ready(cls: type, rcfg: cfg_mod.RetailerCfg, product_ids: int) -> bool:
    return (
        bool(rcfg.enabled)
        and bool(getattr(cls, "supported", True))
        and product_ids > 0
        and not _api_key_missing(cls, rcfg)
    )


def _retailer_payload(cfg: cfg_mod.Config) -> list[dict[str, Any]]:
    selected = _selected_products_or_empty(cfg)
    retailers = []
    for slug, cls in RETAILER_REGISTRY.items():
        rcfg = cfg.retailers.get(slug, cfg_mod.RetailerCfg())
        fields = getattr(cls, "product_id_fields", ())
        product_ids = sum(
            1
            for product in selected.values()
            if any(str(product.get(field) or "").strip() for field in fields)
        )
        missing_api_key = _api_key_missing(cls, rcfg)
        retailers.append(
            {
                "slug": slug,
                "name": cls.name,
                "enabled": bool(rcfg.enabled),
                "supported": bool(getattr(cls, "supported", True)),
                "unsupportedReason": getattr(cls, "unsupported_reason", ""),
                "onlineOnly": bool(getattr(cls, "online_only", False)),
                "productIdFields": list(fields),
                "selectedProductIds": product_ids,
                "apiKeySet": bool(rcfg.api_key),
                "apiKeyRequired": bool(getattr(cls, "api_key_required", False)),
                "missingApiKey": missing_api_key,
                "queryReady": _query_ready(cls, rcfg, product_ids),
            }
        )
    return retailers


def _product_payload(cfg: cfg_mod.Config) -> list[dict[str, Any]]:
    selected = _selected_products_or_empty(cfg)
    selected_keys = set(selected)
    products: list[dict[str, Any]] = []
    for key, product in cfg.products.items():
        priority, priority_score = product_priority(product)
        selected_for_scan = key in selected_keys
        retailer_entries = []
        for slug, cls in RETAILER_REGISTRY.items():
            fields = getattr(cls, "product_id_fields", ())
            ids = {
                field: str(product.get(field) or "").strip()
                for field in fields
                if str(product.get(field) or "").strip()
            }
            rcfg = cfg.retailers.get(slug, cfg_mod.RetailerCfg())
            supported = bool(getattr(cls, "supported", True))
            missing_api_key = _api_key_missing(cls, rcfg)
            active = (
                selected_for_scan
                and bool(rcfg.enabled)
                and supported
                and bool(ids)
                and not missing_api_key
            )
            if not supported:
                blocked_reason = getattr(cls, "unsupported_reason", "") or "unsupported"
            elif missing_api_key and ids:
                blocked_reason = "missing API key"
            elif bool(rcfg.enabled) and selected_for_scan and not ids:
                blocked_reason = "missing product ID"
            elif not rcfg.enabled:
                blocked_reason = "retailer disabled"
            elif not selected_for_scan:
                blocked_reason = "product not selected"
            else:
                blocked_reason = ""
            retailer_entries.append(
                {
                    "slug": slug,
                    "name": cls.name,
                    "enabled": bool(rcfg.enabled),
                    "supported": supported,
                    "onlineOnly": bool(getattr(cls, "online_only", False)),
                    "ids": ids,
                    "active": active,
                    "missingApiKey": missing_api_key,
                    "blockedReason": blocked_reason,
                }
            )

        active_retailers = [
            entry["slug"] for entry in retailer_entries if entry["active"]
        ]
        products.append(
            {
                "key": key,
                "name": product.get("name", key),
                "set": product.get("set", ""),
                "type": product.get("type", ""),
                "selected": selected_for_scan,
                "scanned": bool(active_retailers),
                "priority": priority,
                "priorityScore": priority_score,
                "activeRetailers": active_retailers,
                "retailers": retailer_entries,
            }
        )
    return products


def _config_summary(cfg: cfg_mod.Config, config_missing: bool) -> dict[str, Any]:
    selected = _selected_products_or_empty(cfg)
    return {
        "configMissing": config_missing,
        "homeAddress": cfg.home_address,
        "workAddress": cfg.work_address,
        "routeRadiusMiles": cfg.route_radius_miles,
        "routingEngine": cfg.routing_engine,
        "googleApiKeySet": bool(cfg.google_api_key),
        "pollIntervalSeconds": cfg.poll_interval_seconds,
        "discordWebhookSet": bool(cfg.discord_webhook),
        "ntfyTopicSet": bool(cfg.ntfy_topic),
        "productsFilter": cfg.products_filter,
        "productsSelected": len(selected),
        "productsTotal": len(cfg.products),
    }


def _recent_restocks_payload(cfg: cfg_mod.Config, limit: int = 10) -> list[dict[str, Any]]:
    """Last few products seen in stock (restock memory), labelled for display."""
    try:
        rows = State().recent_restocks(limit)
    except Exception:
        return []
    product_names = {k: v.get("name", k) for k, v in cfg.products.items()}
    retailer_names = {slug: cls.name for slug, cls in RETAILER_REGISTRY.items()}
    for r in rows:
        r["productName"] = product_names.get(r["productKey"], r["productKey"])
        r["retailerName"] = retailer_names.get(r["retailer"], r["retailer"])
    return rows


def _health_payload() -> list[dict[str, Any]]:
    rows = health.snapshot()
    if rows:
        return rows
    try:
        return State().source_health_snapshot()
    except Exception:
        return []


def _summary_payload(
    cfg: cfg_mod.Config,
    coverage: dict[str, Any],
    retailers: list[dict[str, Any]],
    products: list[dict[str, Any]],
    health_rows: list[dict[str, Any]],
    recent_restocks: list[dict[str, Any]],
    runner: dict[str, Any],
) -> dict[str, Any]:
    """Compact dashboard summary derived from the detailed API payloads."""
    health_by_slug = {row.get("slug"): row for row in health_rows}
    health_counts = {"healthy": 0, "degraded": 0, "down": 0, "unknown": 0}
    for retailer in retailers:
        if not (retailer.get("enabled") and retailer.get("supported")):
            continue
        state = str(health_by_slug.get(retailer["slug"], {}).get("state") or "unknown")
        if state not in health_counts:
            state = "unknown"
        health_counts[state] += 1

    stock_hits = 0
    for retailer in runner.get("stockBoard") or []:
        for location in retailer.get("locations") or []:
            stock_hits += int(location.get("inStockCount") or 0)

    return {
        "coverageScore": int(coverage.get("score") or 0),
        "actionableProducts": int(coverage.get("actionableProducts") or 0),
        "totalProducts": int(coverage.get("totalProducts") or 0),
        "selectedProducts": int(coverage.get("totalProducts") or 0),
        "scannedProducts": sum(1 for product in products if product.get("scanned")),
        "enabledSources": sum(
            1 for retailer in retailers if retailer.get("enabled") and retailer.get("supported")
        ),
        "activeSources": sum(
            1
            for retailer in retailers
            if retailer.get("queryReady")
        ),
        "sourceHealth": health_counts,
        "stockHits": stock_hits,
        "recentRestocks": len(recent_restocks),
        "lastScanAt": runner.get("lastScanAt"),
        "nextScanAt": runner.get("nextScanAt"),
        "scanCount": int(runner.get("scanCount") or 0),
        "running": bool(runner.get("running")),
        "phase": runner.get("phase") or "idle",
        "pollIntervalSeconds": cfg.poll_interval_seconds,
    }


def status_payload() -> dict[str, Any]:
    try:
        cfg, config_missing = _load_current_config()
        errors = config_errors(cfg)
        coverage = coverage_mod.coverage_report(cfg)
        retailers = _retailer_payload(cfg)
        products = _product_payload(cfg)
        health_rows = _health_payload()
        recent_restocks = _recent_restocks_payload(cfg)
        runner = RUNNER.snapshot()
        status = HTTPStatus.OK
        payload: dict[str, Any] = {
            "ok": not errors and not config_missing,
            "config": _config_summary(cfg, config_missing),
            "coverage": coverage,
            "retailers": retailers,
            "products": products,
            "health": health_rows,
            "recentRestocks": recent_restocks,
            "summary": _summary_payload(
                cfg, coverage, retailers, products, health_rows, recent_restocks, runner
            ),
            "errors": errors,
            "runner": runner,
        }
    except SystemExit as exc:
        status = HTTPStatus.BAD_REQUEST
        payload = {
            "ok": False,
            "errors": [str(exc)],
            "runner": RUNNER.snapshot(),
        }
    payload["httpStatus"] = status.value
    return payload


def _normalize_config(raw: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    locations = raw.setdefault("locations", {})
    locations["home"] = str(payload.get("homeAddress", locations.get("home", ""))).strip()
    locations["work"] = str(payload.get("workAddress", locations.get("work", ""))).strip()

    if "routeRadiusMiles" in payload:
        raw["route_radius_miles"] = float(payload["routeRadiusMiles"])
    if "pollIntervalSeconds" in payload:
        raw["poll_interval_seconds"] = int(payload["pollIntervalSeconds"])

    routing = raw.setdefault("routing", {})
    if "routingEngine" in payload:
        engine = str(payload["routingEngine"]).lower().strip()
        if engine not in {"osrm", "google"}:
            raise ValueError("routingEngine must be osrm or google")
        routing["engine"] = engine
    if payload.get("googleApiKey"):
        routing["google_api_key"] = str(payload["googleApiKey"]).strip()

    discord_webhook = str(payload.get("discordWebhook", "")).strip()
    if discord_webhook:
        raw["discord_webhook"] = discord_webhook
    if "ntfyTopic" in payload:
        raw["ntfy_topic"] = str(payload["ntfyTopic"]).strip()

    retailers_raw = raw.setdefault("retailers", {})
    for slug, cls in RETAILER_REGISTRY.items():
        current = retailers_raw.setdefault(slug, {})
        if not isinstance(current, dict):
            current = {}
            retailers_raw[slug] = current
        incoming = (payload.get("retailers") or {}).get(slug)
        if incoming is None:
            continue
        current["enabled"] = bool(incoming.get("enabled", False))
        api_key = str(incoming.get("apiKey", "")).strip()
        if api_key:
            current["api_key"] = api_key
        elif "api_key" not in current and "apiKey" in incoming:
            current["api_key"] = ""
        if not getattr(cls, "supported", True):
            current["enabled"] = False

    products = payload.get("products")
    if products == "all_sealed" or products is None:
        raw["products"] = raw.get("products", "all_sealed")
    elif isinstance(products, list):
        raw["products"] = products
    else:
        raise ValueError("products must be all_sealed or a list of product keys")

    return raw


def save_config_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source = cfg_mod.CONFIG_PATH if cfg_mod.CONFIG_PATH.exists() else EXAMPLE_CONFIG_PATH
    raw = _read_yaml(source)
    raw = _normalize_config(raw, payload)

    cfg = cfg_mod.from_mapping(raw)
    errors = config_errors(cfg)
    if errors:
        return {"ok": False, "errors": errors, "config": _config_summary(cfg, False)}

    cfg_mod.CONFIG_PATH.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    return {"ok": True, "message": "config.yaml saved", "currentStatus": status_payload()}


def save_product_id_payload(payload: dict[str, Any]) -> dict[str, Any]:
    slug = str(payload.get("retailer") or "").strip().lower()
    product_key = str(payload.get("productKey") or "").strip()
    url_or_id = str(payload.get("urlOrId") or "").strip()

    if slug not in RETAILER_REGISTRY:
        return {"ok": False, "errors": [f"Unknown retailer: {slug or '(blank)'}"]}
    field = field_for_slug(slug)
    if not field:
        return {"ok": False, "errors": [f"{slug} does not have a supported catalog ID field."]}
    value = extract_id(slug, url_or_id)
    if not value:
        return {
            "ok": False,
            "errors": [f"Could not extract a {slug} ID from the provided value."],
        }

    try:
        text = cfg_mod.PRODUCTS_PATH.read_text(encoding="utf-8")
        updated = set_product_id(text, product_key, field, value)
        cfg_mod.PRODUCTS_PATH.write_text(updated, encoding="utf-8")
    except KeyError as exc:
        return {"ok": False, "errors": [str(exc).strip('"')]}
    except OSError as exc:
        return {"ok": False, "errors": [_safe_error_text(str(exc))]}

    return {
        "ok": True,
        "message": f"Saved {product_key}.{field}",
        "field": field,
        "value": value,
        "currentStatus": status_payload(),
    }


def _capture_output(fn):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        result = fn()
    return result, out.getvalue(), err.getvalue()


def _friendly_warning(line: str) -> str:
    raw = line.lstrip("! ").strip()
    lower = raw.lower()

    if "target store search failed" in lower and "403" in lower:
        return (
            "Target store discovery is blocked by Target (HTTP 403). "
            "Route-store Target checks are unavailable right now; online checks continue."
        )
    if "target store search failed" in lower:
        return (
            "Target store discovery failed. Route-store Target checks are unavailable "
            "for this scan; the scanner will retry."
        )
    if "store search failed" in lower:
        slug = raw.split(" store search failed", 1)[0].strip()
        retailer_name = RETAILER_REGISTRY.get(slug, type("_Unknown", (), {"name": slug})).name
        return (
            f"{retailer_name} store discovery failed. Route-store checks for this "
            "retailer are unavailable for this scan; the scanner will retry."
        )
    if "discord webhook failed" in lower:
        return "Discord notification failed. The stock alert was still logged locally."
    if "ntfy failed" in lower:
        return "ntfy notification failed. The stock alert was still logged locally."
    if "check raised" in lower:
        slug = raw.split(" check raised", 1)[0].strip()
        retailer_name = RETAILER_REGISTRY.get(slug, type("_Unknown", (), {"name": slug})).name
        return f"{retailer_name} stock check failed for this scan; the scanner will retry."
    return raw


def _warning_lines(text: str) -> list[str]:
    warnings: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("!"):
            continue
        warning = _friendly_warning(line)
        if warning in seen:
            continue
        seen.add(warning)
        warnings.append(warning)
    return warnings


def _safe_log_text(text: str) -> str:
    """Redact coordinates and query strings before logs reach the browser."""
    text = re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?...", text)
    return re.sub(
        r"\b(home|work): \([-+]?\d+(?:\.\d+)?,\s*[-+]?\d+(?:\.\d+)?\)",
        r"\1: (redacted)",
        text,
    )


def _safe_error_text(text: str) -> str:
    return _safe_log_text(str(text))


def _stores_payload(stores_by_retailer: dict[str, list[Store]]) -> dict[str, list[dict[str, Any]]]:
    return {
        slug: [
            {
                "storeId": store.store_id,
                "name": store.name,
                "distanceMiles": store.distance_miles,
            }
            for store in stores
        ]
        for slug, stores in stores_by_retailer.items()
    }


def _result_payload(result: StockResult, checked_at: int | None = None) -> dict[str, Any]:
    store = result.store
    return {
        "retailerSlug": result.retailer_slug,
        "retailer": store.retailer if store else result.retailer_slug,
        "storeId": store.store_id if store else "_online_",
        "storeLabel": store.label() if store else "Online",
        "distanceMiles": store.distance_miles if store else None,
        "productKey": result.product_key,
        "productName": result.product_name,
        "status": result.status,
        "price": result.price,
        "url": result.url,
        "checkedAt": checked_at,
    }


def _stock_board_payload(
    cfg: cfg_mod.Config,
    stores_by_retailer: dict[str, list[Store]],
    results: list[StockResult],
    checked_at: int | None = None,
) -> list[dict[str, Any]]:
    products = {product["key"]: product for product in _product_payload(cfg)}
    result_map = {
        (
            result.retailer_slug,
            result.store.store_id if result.store else "_online_",
            result.product_key,
        ): result
        for result in results
    }

    def missing_status(slug: str) -> tuple[str, str]:
        row = health.get(slug) or {}
        last_status = row.get("last_status") or ""
        detail = str(row.get("last_detail") or "")
        if last_status == "BLOCKED":
            return "BLOCKED", detail or "Retailer blocked or rate-limited this check."
        if last_status == "ERROR":
            return "SOURCE_ERROR", detail or "Retailer check failed."
        if last_status == "NO_DATA":
            return "NO_DATA", detail or "Retailer returned no parseable inventory rows."
        if last_status == "DISCOVERY_FAILED":
            return "DISCOVERY_FAILED", detail or "Store discovery failed."
        return "NOT_CHECKED", "No inventory row returned for this product on the last scan."

    board: list[dict[str, Any]] = []
    for slug, RClass in RETAILER_REGISTRY.items():
        rcfg = cfg.retailers.get(slug)
        if not rcfg or not rcfg.enabled or not getattr(RClass, "supported", True):
            continue

        active_products = [
            product
            for product in products.values()
            if product["selected"] and any(
                retailer["slug"] == slug and retailer["active"]
                for retailer in product["retailers"]
            )
        ]
        active_products.sort(
            key=lambda product: (
                -int(product["priorityScore"]),
                product["name"],
            )
        )
        stores = stores_by_retailer.get(slug, [])
        locations: list[Store | None]
        if getattr(RClass, "online_only", False):
            locations = [None]
        else:
            locations = list(stores)

        retailer_rows = []
        if not locations:
            retailer_rows.append(
                {
                    "storeId": "",
                    "storeLabel": "No route stores found",
                    "distanceMiles": None,
                    "inStockCount": 0,
                    "products": [],
                }
            )

        for store in locations:
            store_id = store.store_id if store else "_online_"
            statuses = []
            for product in active_products:
                result = result_map.get((slug, store_id, product["key"]))
                if result is None:
                    status, status_reason = missing_status(slug)
                    price = ""
                    url = ""
                else:
                    status = result.status
                    status_reason = ""
                    price = result.price
                    url = result.url
                statuses.append(
                    {
                        "productKey": product["key"],
                        "productName": product["name"],
                        "priority": product["priority"],
                        "priorityScore": product["priorityScore"],
                        "status": status,
                        "statusReason": status_reason,
                        "price": price,
                        "url": url,
                    }
                )
            retailer_rows.append(
                {
                    "storeId": store_id,
                    "storeLabel": store.label() if store else "Online",
                    "distanceMiles": store.distance_miles if store else None,
                    "inStockCount": sum(
                        1 for item in statuses if item["status"] in POSITIVE_STATUSES
                    ),
                    "products": statuses,
                }
            )
        retailer_rows.sort(
            key=lambda row: (
                -int(row["inStockCount"]),
                9999 if row["distanceMiles"] is None else float(row["distanceMiles"]),
                row["storeLabel"],
            )
        )
        board.append(
            {
                "retailerSlug": slug,
                "retailerName": RClass.name,
                "onlineOnly": bool(getattr(RClass, "online_only", False)),
                "activeProductCount": len(active_products),
                "locations": retailer_rows,
                "checkedAt": checked_at,
            }
        )
    return board


def _online_only_diagnostic(cfg: cfg_mod.Config, slug: str) -> dict[str, Any]:
    RClass = RETAILER_REGISTRY[slug]
    return {
        "slug": slug,
        "name": RClass.name,
        "onlineOnly": True,
        "corridorRadiusMiles": cfg.route_radius_miles,
        "candidateSearchRadiusMiles": 0,
        "centersPlanned": 0,
        "centersQueried": 0,
        "candidateStores": 0,
        "uniqueCandidateStores": 0,
        "keptStores": 0,
        "filteredOutStores": 0,
        "status": "skipped",
        "skippedReason": "online_only",
        "errors": [],
    }


def _set_store_diagnostics(rows: list[dict[str, Any]]) -> None:
    global LAST_STORE_DIAGNOSTICS
    LAST_STORE_DIAGNOSTICS = [dict(row) for row in rows]


def _get_store_diagnostics() -> list[dict[str, Any]]:
    return [dict(row) for row in LAST_STORE_DIAGNOSTICS]


def _prepare_scan_capture(cfg: cfg_mod.Config) -> tuple[dict[str, list[Store]], list[dict[str, Any]]]:
    _set_store_diagnostics([])
    stores = _prepare_scan(cfg)
    return stores, _get_store_diagnostics()


def _prepare_scan(cfg: cfg_mod.Config) -> dict[str, list[Store]]:
    errors = config_errors(cfg)
    if errors:
        raise ValueError("\n".join(errors))
    enabled_slugs = enabled_retailer_slugs(cfg)
    needs_route = any(not RETAILER_REGISTRY[slug].online_only for slug in enabled_slugs)
    if not needs_route:
        _set_store_diagnostics([_online_only_diagnostic(cfg, slug) for slug in enabled_slugs])
        return {slug: [] for slug in enabled_slugs}
    home, work, polyline = build_corridor(cfg)
    diagnostics: list[dict[str, Any]] = []
    stores = discover_stores(cfg, home, work, polyline, diagnostics=diagnostics)
    _set_store_diagnostics(diagnostics)
    return stores


def dry_run_payload() -> dict[str, Any]:
    cfg, config_missing = _load_current_config()
    if config_missing:
        return {"ok": False, "errors": ["Save config.yaml before running scanners."]}

    try:
        (stores, store_diagnostics), stdout, stderr = _capture_output(
            lambda: _prepare_scan_capture(cfg)
        )
    except Exception as exc:
        return {"ok": False, "errors": [_safe_error_text(str(exc))]}
    warnings = _warning_lines(stderr)
    safe_stdout = _safe_log_text(stdout)
    safe_stderr = _safe_log_text(stderr)
    stores_payload = _stores_payload(stores)
    RUNNER._update(
        stores=stores_payload,
        warnings=warnings,
        stdout=safe_stdout,
        stderr=safe_stderr,
        stockBoard=[],
        lastResults=[],
        lastAlerts=[],
        storeDiagnostics=store_diagnostics,
        phase="idle",
    )
    coverage = coverage_mod.coverage_report(cfg)
    retailers = _retailer_payload(cfg)
    products = _product_payload(cfg)
    health_rows = _health_payload()
    recent_restocks = _recent_restocks_payload(cfg)
    runner = RUNNER.snapshot()
    return {
        "ok": True,
        "coverage": coverage,
        "health": health_rows,
        "recentRestocks": recent_restocks,
        "summary": _summary_payload(
            cfg, coverage, retailers, products, health_rows, recent_restocks, runner
        ),
        "retailers": retailers,
        "stores": stores_payload,
        "storeDiagnostics": store_diagnostics,
        "warnings": warnings,
        "stdout": safe_stdout,
        "stderr": safe_stderr,
    }


def safe_demo_payload() -> dict[str, Any]:
    cfg, config_missing = _load_current_config()
    if config_missing:
        return {"ok": False, "errors": ["Save config.yaml before running scanners."]}
    errors = config_errors(cfg)
    if errors:
        return {"ok": False, "errors": errors}

    try:
        stores, store_diagnostics = safe_demo_stores(cfg)
        results = safe_demo_results(cfg, stores)
        checked_at = int(time.time())
    except Exception as exc:
        return {"ok": False, "errors": [_safe_error_text(str(exc))]}

    stores_payload = _stores_payload(stores)
    stock_board = _stock_board_payload(cfg, stores, results, checked_at)
    last_results = [_result_payload(result, checked_at) for result in results]
    warnings = [
        "Safe demo only: synthetic stores and out-of-stock rows; no geocoding, routing, retailer, or alert network calls were made."
    ]
    RUNNER._update(
        phase="idle",
        running=False,
        lastScanAt=checked_at,
        nextScanAt=None,
        lastAlerts=[],
        lastResults=last_results,
        stockBoard=stock_board,
        warnings=warnings,
        stores=stores_payload,
        storeDiagnostics=store_diagnostics,
        stdout="safe demo: local-only synthetic scanner state\n",
        stderr="",
    )
    coverage = coverage_mod.coverage_report(cfg)
    retailers = _retailer_payload(cfg)
    products = _product_payload(cfg)
    health_rows = _health_payload()
    recent_restocks = _recent_restocks_payload(cfg)
    runner = RUNNER.snapshot()
    return {
        "ok": True,
        "coverage": coverage,
        "health": health_rows,
        "recentRestocks": recent_restocks,
        "summary": _summary_payload(
            cfg, coverage, retailers, products, health_rows, recent_restocks, runner
        ),
        "retailers": retailers,
        "stores": stores_payload,
        "storeDiagnostics": store_diagnostics,
        "stockBoard": stock_board,
        "lastResults": last_results,
        "alerts": [],
        "warnings": warnings,
        "stdout": "safe demo: local-only synthetic scanner state\n",
        "stderr": "",
    }


def _alert_payload(alert: StockAlert) -> dict[str, Any]:
    return asdict(alert) | {"line": alert.line()}


class CapturingNotifier:
    def __init__(self, cfg: cfg_mod.Config, forward: bool = False):
        self.alerts: list[StockAlert] = []
        self.forward = Notifier(cfg.discord_webhook, cfg.ntfy_topic) if forward else None

    def send(self, alert: StockAlert) -> None:
        self.alerts.append(alert)
        if self.forward:
            self.forward.send(alert)
        else:
            print(alert.line(), flush=True)


def scan_once_payload(notify: bool = False) -> dict[str, Any]:
    cfg, config_missing = _load_current_config()
    if config_missing:
        return {"ok": False, "errors": ["Save config.yaml before running scanners."]}

    try:
        (stores, store_diagnostics), setup_stdout, setup_stderr = _capture_output(
            lambda: _prepare_scan_capture(cfg)
        )
        notifier = CapturingNotifier(cfg, forward=notify)
        state = State()
        results, scan_stdout, scan_stderr = _capture_output(
            lambda: run_pass(cfg, stores, state, notifier)
        )
        checked_at = int(time.time())
    except Exception as exc:
        return {"ok": False, "errors": [_safe_error_text(str(exc))]}

    stores_payload = _stores_payload(stores)
    stock_board = _stock_board_payload(cfg, stores, results, checked_at)
    last_results = [_result_payload(result, checked_at) for result in results]
    alerts = [_alert_payload(alert) for alert in notifier.alerts]
    warnings = _warning_lines(setup_stderr + scan_stderr)
    safe_stdout = _safe_log_text(setup_stdout + scan_stdout)
    safe_stderr = _safe_log_text(setup_stderr + scan_stderr)
    RUNNER._update(
        phase="idle",
        running=False,
        lastScanAt=checked_at,
        nextScanAt=None,
        scanCount=int(RUNNER.snapshot().get("scanCount") or 0) + 1,
        lastAlerts=alerts[-25:],
        lastResults=last_results,
        stockBoard=stock_board,
        warnings=warnings,
        stores=stores_payload,
        storeDiagnostics=store_diagnostics,
        stdout=safe_stdout,
        stderr=safe_stderr,
    )
    coverage = coverage_mod.coverage_report(cfg)
    retailers = _retailer_payload(cfg)
    products = _product_payload(cfg)
    health_rows = _health_payload()
    recent_restocks = _recent_restocks_payload(cfg)
    runner = RUNNER.snapshot()

    return {
        "ok": True,
        "coverage": coverage,
        "health": health_rows,
        "recentRestocks": recent_restocks,
        "summary": _summary_payload(
            cfg, coverage, retailers, products, health_rows, recent_restocks, runner
        ),
        "retailers": retailers,
        "stores": stores_payload,
        "storeDiagnostics": store_diagnostics,
        "stockBoard": stock_board,
        "lastResults": last_results,
        "alerts": alerts,
        "warnings": warnings,
        "stdout": safe_stdout,
        "stderr": safe_stderr,
    }


class ScannerRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state: dict[str, Any] = {
            "running": False,
            "phase": "idle",
            "lastError": "",
            "lastStartedAt": None,
            "lastScanAt": None,
            "nextScanAt": None,
            "scanCount": 0,
            "intervalSeconds": None,
            "lastAlerts": [],
            "lastResults": [],
            "stockBoard": [],
            "storeDiagnostics": [],
            "warnings": [],
            "stores": {},
            "stdout": "",
            "stderr": "",
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            data = dict(self._state)
            thread = self._thread
        data["running"] = bool(thread and thread.is_alive() and data["running"])
        return data

    def _update(self, **kwargs: Any) -> None:
        with self._lock:
            self._state.update(kwargs)

    def start(self, notify: bool = True) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {"ok": True, "message": "scanner already running", "runner": dict(self._state)}
            self._stop.clear()
            self._state.update(
                {
                    "running": True,
                    "phase": "starting",
                    "lastError": "",
                    "lastStartedAt": int(time.time()),
                    "lastScanAt": None,
                    "nextScanAt": None,
                    "scanCount": 0,
                    "intervalSeconds": None,
                    "lastAlerts": [],
                    "lastResults": [],
                    "stockBoard": [],
                    "storeDiagnostics": [],
                    "warnings": [],
                    "stdout": "",
                    "stderr": "",
                }
            )
            self._thread = threading.Thread(
                target=self._run,
                args=(notify,),
                name="pokemon-scanner",
                daemon=True,
            )
            self._thread.start()
        return {"ok": True, "message": "scanner started", "runner": self.snapshot()}

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        self._update(running=False, phase="stopping")
        return {"ok": True, "message": "scanner stopping", "runner": self.snapshot()}

    def _run(self, notify: bool) -> None:
        try:
            cfg, config_missing = _load_current_config()
            if config_missing:
                raise RuntimeError("Save config.yaml before starting the scanner.")
            interval = max(60, cfg.poll_interval_seconds)
            self._update(intervalSeconds=interval)
            self._update(phase="discovering")
            (stores, store_diagnostics), setup_stdout, setup_stderr = _capture_output(
                lambda: _prepare_scan_capture(cfg)
            )
            self._update(
                stores=_stores_payload(stores),
                storeDiagnostics=store_diagnostics,
                stdout=_safe_log_text(setup_stdout),
                stderr=_safe_log_text(setup_stderr),
                warnings=_warning_lines(setup_stderr),
                phase="scanning",
            )
            notifier = CapturingNotifier(cfg, forward=notify)
            state = State()
            scan_count = 0
            while not self._stop.is_set():
                self._update(phase="scanning", nextScanAt=None)
                results, scan_stdout, scan_stderr = _capture_output(
                    lambda: run_pass(cfg, stores, state, notifier)
                )
                scan_count += 1
                now = int(time.time())
                self._update(
                    lastScanAt=now,
                    nextScanAt=now + interval,
                    scanCount=scan_count,
                    lastAlerts=[_alert_payload(alert) for alert in notifier.alerts[-25:]],
                    lastResults=[
                        _result_payload(result, now) for result in results
                    ],
                    stockBoard=_stock_board_payload(cfg, stores, results, now),
                    warnings=_warning_lines(setup_stderr + scan_stderr),
                    stdout=_safe_log_text(setup_stdout + scan_stdout),
                    stderr=_safe_log_text(setup_stderr + scan_stderr),
                    phase="sleeping",
                )
                if self._stop.wait(interval):
                    break
                self._update(phase="scanning")
        except Exception as exc:
            self._update(
                lastError=_safe_error_text(str(exc)),
                phase="error",
                running=False,
                nextScanAt=None,
            )
            return
        self._update(phase="idle", running=False, nextScanAt=None)


RUNNER = ScannerRunner()


def _should_autostart() -> bool:
    try:
        cfg, config_missing = _load_current_config()
        return (
            not config_missing
            and not config_errors(cfg)
            and bool(enabled_retailer_slugs(cfg))
        )
    except Exception:
        return False


class WebHandler(BaseHTTPRequestHandler):
    server_version = "PokemonScannerUI/1.0"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/status":
            self._send_json(status_payload())
            return
        if path == "/" or path == "/index.html":
            self._send_file(ASSETS_DIR / "index.html")
            return
        if path.startswith("/static/"):
            rel = path.removeprefix("/static/").lstrip("/")
            target = (ASSETS_DIR / rel).resolve()
            if ASSETS_DIR.resolve() not in target.parents:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._send_file(target)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        payload = self._read_json()
        if path == "/api/config":
            self._send_json(save_config_payload(payload))
            return
        if path == "/api/product-id":
            self._send_json(save_product_id_payload(payload))
            return
        if path == "/api/dry-run":
            self._send_json(dry_run_payload())
            return
        if path == "/api/safe-demo":
            self._send_json(safe_demo_payload())
            return
        if path == "/api/scan-once":
            self._send_json(scan_once_payload(notify=bool(payload.get("notify", False))))
            return
        if path == "/api/start":
            self._send_json(RUNNER.start(notify=bool(payload.get("notify", True))))
            return
        if path == "/api/stop":
            self._send_json(RUNNER.stop())
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _send_json(self, payload: dict[str, Any]) -> None:
        status = int(
            payload.get(
                "httpStatus",
                HTTPStatus.OK if payload.get("ok", True) else HTTPStatus.BAD_REQUEST,
            )
        )
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[ui] {self.address_string()} - {fmt % args}", file=sys.__stderr__)


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    autostart: bool = True,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), WebHandler)
    print(f"Pokemon scanner UI: http://{host}:{server.server_port}", flush=True)
    if autostart and _should_autostart():
        RUNNER.start(notify=True)
        print("Interval scanner: started", flush=True)
    server.serve_forever()
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local Pokemon scanner UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--no-autostart",
        action="store_true",
        help="serve the UI without starting the interval scanner",
    )
    args = parser.parse_args()
    serve(args.host, args.port, autostart=not args.no_autostart)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
