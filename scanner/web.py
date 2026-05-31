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
from .main import (
    build_corridor,
    check_config,
    config_errors,
    discover_stores,
    enabled_retailer_slugs,
    run_pass,
)
from .notify import Notifier, StockAlert
from .retailers import ALL as RETAILER_REGISTRY
from .retailers.base import StockResult, Store
from .state import State

ASSETS_DIR = Path(__file__).resolve().parent / "web_assets"
EXAMPLE_CONFIG_PATH = cfg_mod.ROOT / "config.example.yaml"
PRIORITY_KEYWORDS = (
    "prismatic",
    "151",
    "surging sparks",
    "journey together",
    "evolving skies",
    "booster bundle",
    "booster box",
    "elite trainer box",
    "ultra-premium",
    "premium collection",
    "special collection",
)
POSITIVE_STATUSES = {"IN_STOCK", "LIMITED", "ONLINE_IN_STOCK"}


def _product_priority(product: dict[str, Any]) -> tuple[str, int]:
    text = " ".join(
        str(product.get(field, ""))
        for field in ("name", "set", "type")
    ).lower()
    if any(keyword in text for keyword in PRIORITY_KEYWORDS):
        return "High priority", 100
    return "Standard", 10


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
            }
        )
    return retailers


def _product_payload(cfg: cfg_mod.Config) -> list[dict[str, Any]]:
    selected = _selected_products_or_empty(cfg)
    selected_keys = set(selected)
    products: list[dict[str, Any]] = []
    for key, product in cfg.products.items():
        priority, priority_score = _product_priority(product)
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
            active = selected_for_scan and bool(rcfg.enabled) and supported and bool(ids)
            retailer_entries.append(
                {
                    "slug": slug,
                    "name": cls.name,
                    "enabled": bool(rcfg.enabled),
                    "supported": supported,
                    "onlineOnly": bool(getattr(cls, "online_only", False)),
                    "ids": ids,
                    "active": active,
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


def status_payload() -> dict[str, Any]:
    try:
        cfg, config_missing = _load_current_config()
        errors = config_errors(cfg)
        status = HTTPStatus.OK
        payload: dict[str, Any] = {
            "ok": not errors and not config_missing,
            "config": _config_summary(cfg, config_missing),
            "retailers": _retailer_payload(cfg),
            "products": _product_payload(cfg),
            "errors": errors,
            "runner": RUNNER.snapshot(),
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


def _stores_payload(stores_by_retailer: dict[str, list[Store]]) -> dict[str, list[dict[str, Any]]]:
    return {
        slug: [
            {
                "storeId": store.store_id,
                "name": store.name,
                "lat": store.lat,
                "lng": store.lng,
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
                    status = "UNKNOWN"
                    price = ""
                    url = ""
                else:
                    status = result.status
                    price = result.price
                    url = result.url
                statuses.append(
                    {
                        "productKey": product["key"],
                        "productName": product["name"],
                        "priority": product["priority"],
                        "priorityScore": product["priorityScore"],
                        "status": status,
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


def _prepare_scan(cfg: cfg_mod.Config) -> dict[str, list[Store]]:
    errors = config_errors(cfg)
    if errors:
        raise ValueError("\n".join(errors))
    enabled_slugs = enabled_retailer_slugs(cfg)
    needs_route = any(not RETAILER_REGISTRY[slug].online_only for slug in enabled_slugs)
    if not needs_route:
        return {slug: [] for slug in enabled_slugs}
    home, work, polyline = build_corridor(cfg)
    return discover_stores(cfg, home, work, polyline)


def dry_run_payload() -> dict[str, Any]:
    cfg, config_missing = _load_current_config()
    if config_missing:
        return {"ok": False, "errors": ["Save config.yaml before running scanners."]}

    try:
        stores, stdout, stderr = _capture_output(lambda: _prepare_scan(cfg))
    except Exception as exc:
        return {"ok": False, "errors": [str(exc)]}
    return {
        "ok": True,
        "stores": _stores_payload(stores),
        "warnings": _warning_lines(stderr),
        "stdout": stdout,
        "stderr": stderr,
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
        stores, setup_stdout, setup_stderr = _capture_output(lambda: _prepare_scan(cfg))
        notifier = CapturingNotifier(cfg, forward=notify)
        state = State()
        results, scan_stdout, scan_stderr = _capture_output(
            lambda: run_pass(cfg, stores, state, notifier)
        )
        checked_at = int(time.time())
    except Exception as exc:
        return {"ok": False, "errors": [str(exc)]}

    return {
        "ok": True,
        "stores": _stores_payload(stores),
        "stockBoard": _stock_board_payload(cfg, stores, results, checked_at),
        "lastResults": [_result_payload(result, checked_at) for result in results],
        "alerts": [_alert_payload(alert) for alert in notifier.alerts],
        "warnings": _warning_lines(setup_stderr + scan_stderr),
        "stdout": setup_stdout + scan_stdout,
        "stderr": setup_stderr + scan_stderr,
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
            stores, setup_stdout, setup_stderr = _capture_output(lambda: _prepare_scan(cfg))
            self._update(
                stores=_stores_payload(stores),
                stdout=setup_stdout,
                stderr=setup_stderr,
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
                    stdout=setup_stdout + scan_stdout,
                    stderr=setup_stderr + scan_stderr,
                    phase="sleeping",
                )
                if self._stop.wait(interval):
                    break
                self._update(phase="scanning")
        except Exception as exc:
            self._update(lastError=str(exc), phase="error", running=False, nextScanAt=None)
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
        if path == "/api/dry-run":
            self._send_json(dry_run_payload())
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
