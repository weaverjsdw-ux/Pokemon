"""Scanner entry point.

  python -m scanner                  # run scan loop forever
  python -m scanner --once           # single pass, then exit
  python -m scanner --dry-run        # print plan (route + stores) without polling
  python -m scanner --check-config   # validate config + catalog, no network
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import time
import traceback
from typing import Any

from . import config as cfg_mod
from . import coverage as coverage_mod
from . import health
from .geo import distance_to_polyline_miles, haversine_miles
from .geocode import geocode
from .notify import Notifier, StockAlert
from .priority import product_priority
from .retailers import ALL as RETAILER_REGISTRY
from .retailers.base import StockResult, Store
from .route import get_polyline
from .state import State


def config_errors(cfg: cfg_mod.Config) -> list[str]:
    errors: list[str] = []
    unknown = [s for s in cfg.retailers if s not in RETAILER_REGISTRY]
    if unknown:
        errors.append(f"config.yaml references unknown retailers: {', '.join(unknown)}")

    unsupported_enabled = []
    for slug, rcfg in cfg.retailers.items():
        if not rcfg.enabled or slug not in RETAILER_REGISTRY:
            continue
        RClass = RETAILER_REGISTRY[slug]
        if not getattr(RClass, "supported", True):
            reason = getattr(RClass, "unsupported_reason", "") or "not implemented"
            unsupported_enabled.append(f"{slug} ({reason})")
        if getattr(RClass, "api_key_required", False) and not rcfg.api_key.strip():
            errors.append(
                f"config.yaml enables {slug}, but retailers.{slug}.api_key is required"
            )
    if unsupported_enabled:
        errors.append(
            "config.yaml enables unsupported retailers: " + "; ".join(unsupported_enabled)
        )

    if cfg.routing_engine not in {"osrm", "google"}:
        errors.append("config.yaml: routing.engine must be 'osrm' or 'google'")
    if cfg.route_radius_miles <= 0:
        errors.append("config.yaml: route_radius_miles must be greater than 0")
    if cfg.poll_interval_seconds < 60:
        errors.append("config.yaml: poll_interval_seconds must be at least 60")

    try:
        selected = cfg_mod.selected_products(cfg)
    except SystemExit as exc:
        errors.append(str(exc))
        return errors

    for slug, rcfg in cfg.retailers.items():
        if not rcfg.enabled or slug not in RETAILER_REGISTRY:
            continue
        RClass = RETAILER_REGISTRY[slug]
        if not getattr(RClass, "supported", True):
            continue
        fields = getattr(RClass, "product_id_fields", ())
        if fields and not any(
            any(str(product.get(field) or "").strip() for field in fields)
            for product in selected.values()
        ):
            errors.append(
                f"config.yaml enables {slug}, but selected products have no "
                f"{'/'.join(fields)} values"
            )
    return errors


def build_corridor(cfg: cfg_mod.Config):
    print(f"Geocoding addresses...", flush=True)
    home = geocode(cfg.home_address)
    work = geocode(cfg.work_address)
    print(f"  home: {home}", flush=True)
    print(f"  work: {work}", flush=True)

    print(f"Computing route via {cfg.routing_engine}...", flush=True)
    forward = get_polyline(home, work, cfg.routing_engine, cfg.google_api_key)
    reverse = get_polyline(work, home, cfg.routing_engine, cfg.google_api_key)
    polyline = forward + reverse
    print(f"  route polyline points: {len(polyline)}", flush=True)
    return home, work, polyline


MAX_DISCOVERY_CENTERS = 8
MIN_DISCOVERY_SPACING_MILES = 8.0


def _route_discovery_centers(
    home: tuple[float, float],
    work: tuple[float, float],
    polyline: list[tuple[float, float]],
    radius_miles: float,
) -> list[tuple[float, float]]:
    """Home/work plus a bounded set of route sample points for store discovery."""
    centers: list[tuple[float, float]] = [home, work]
    if len(polyline) < 2:
        return centers

    spacing = max(radius_miles, MIN_DISCOVERY_SPACING_MILES)
    next_sample_at = spacing
    traveled = 0.0
    for start, end in zip(polyline, polyline[1:]):
        segment = haversine_miles(start, end)
        if segment <= 0:
            continue
        while traveled + segment >= next_sample_at and len(centers) < MAX_DISCOVERY_CENTERS:
            ratio = (next_sample_at - traveled) / segment
            centers.append(
                (
                    start[0] + (end[0] - start[0]) * ratio,
                    start[1] + (end[1] - start[1]) * ratio,
                )
            )
            next_sample_at += spacing
        traveled += segment
        if len(centers) >= MAX_DISCOVERY_CENTERS:
            break

    deduped: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for lat, lng in centers:
        key = (round(lat, 4), round(lng, 4))
        if key in seen:
            continue
        seen.add(key)
        deduped.append((lat, lng))
    return deduped


def safe_demo_stores(
    cfg: cfg_mod.Config,
) -> tuple[dict[str, list[Store]], list[dict[str, Any]]]:
    """Build a local-only scanner plan for UI/CLI verification.

    This deliberately avoids geocoding, routing, store-finder calls, and stock
    endpoints. It proves the dashboard and catalog wiring with synthetic stores
    only, so private addresses never leave the machine.
    """
    stores_by_retailer: dict[str, list[Store]] = {}
    diagnostics: list[dict[str, Any]] = []
    demo_distance = min(max(cfg.route_radius_miles / 2, 0.5), cfg.route_radius_miles)
    for slug, RClass in RETAILER_REGISTRY.items():
        rcfg = cfg.retailers.get(slug)
        if not rcfg or not rcfg.enabled or not getattr(RClass, "supported", True):
            continue
        online_only = bool(getattr(RClass, "online_only", False))
        stores: list[Store] = []
        if not online_only:
            stores = [
                Store(
                    retailer=RClass.name,
                    store_id="_demo_store_",
                    name=f"{RClass.name} demo store - local only",
                    lat=0.0,
                    lng=0.0,
                    distance_miles=demo_distance,
                )
            ]
        stores_by_retailer[slug] = stores
        diagnostics.append(
            {
                "slug": slug,
                "name": RClass.name,
                "onlineOnly": online_only,
                "corridorRadiusMiles": cfg.route_radius_miles,
                "candidateSearchRadiusMiles": 0,
                "centersPlanned": 0,
                "centersQueried": 0,
                "candidateStores": len(stores),
                "uniqueCandidateStores": len(stores),
                "keptStores": len(stores),
                "filteredOutStores": 0,
                "status": "skipped" if online_only else "ready",
                "skippedReason": "online_only" if online_only else "",
                "errors": [],
                "demo": True,
            }
        )
    return stores_by_retailer, diagnostics


def discover_stores(
    cfg: cfg_mod.Config,
    home,
    work,
    polyline,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, list[Store]]:
    """For each enabled retailer, find candidate stores near home + work,
    then keep only those within `route_radius_miles` of the route polyline."""
    out: dict[str, list[Store]] = {}
    for slug, RClass in RETAILER_REGISTRY.items():
        rcfg = cfg.retailers.get(slug)
        if not rcfg or not rcfg.enabled:
            continue
        diag: dict[str, Any] = {
            "slug": slug,
            "name": RClass.name,
            "onlineOnly": bool(getattr(RClass, "online_only", False)),
            "corridorRadiusMiles": cfg.route_radius_miles,
            "candidateSearchRadiusMiles": cfg.route_radius_miles + 5,
            "centersPlanned": 0,
            "centersQueried": 0,
            "candidateStores": 0,
            "uniqueCandidateStores": 0,
            "keptStores": 0,
            "filteredOutStores": 0,
            "status": "pending",
            "skippedReason": "",
            "errors": [],
        }
        retailer = RClass(api_key=rcfg.api_key)
        if retailer.online_only:
            out[slug] = []
            diag["status"] = "skipped"
            diag["skippedReason"] = "online_only"
            if diagnostics is not None:
                diagnostics.append(diag)
            continue
        seen: dict[str, Store] = {}
        discovery_error = ""
        centers = _route_discovery_centers(home, work, polyline, cfg.route_radius_miles)
        diag["centersPlanned"] = len(centers)
        for center in centers:
            diag["centersQueried"] += 1
            try:
                found = retailer.find_stores(center[0], center[1], cfg.route_radius_miles + 5)
            except Exception as exc:
                discovery_error = _safe_health_detail(str(exc) or exc.__class__.__name__)
                diag["errors"].append(discovery_error)
                print(f"  ! {slug} store search failed: {exc}", file=sys.stderr)
                if "403" in discovery_error or "429" in discovery_error:
                    break
                continue
            diag["candidateStores"] += len(found)
            for s in found:
                seen[s.store_id] = s
        if not seen and discovery_error:
            health.record_failure(slug, "DISCOVERY_FAILED", discovery_error)
        diag["uniqueCandidateStores"] = len(seen)
        kept: list[Store] = []
        for s in seen.values():
            d = distance_to_polyline_miles((s.lat, s.lng), polyline)
            if d <= cfg.route_radius_miles:
                s.distance_miles = d
                kept.append(s)
        kept.sort(key=lambda x: x.distance_miles or 0.0)
        diag["keptStores"] = len(kept)
        diag["filteredOutStores"] = max(0, len(seen) - len(kept))
        if diag["errors"] and not seen:
            diag["status"] = "blocked"
        elif kept:
            diag["status"] = "ready"
        elif seen:
            diag["status"] = "filtered_out"
        else:
            diag["status"] = "empty"
        if diagnostics is not None:
            diagnostics.append(diag)
        out[slug] = kept
        print(f"  {slug}: {len(kept)} stores in corridor", flush=True)
    return out


ALERTABLE_STATUSES = {"IN_STOCK", "LIMITED", "ONLINE_IN_STOCK"}


def _safe_health_detail(detail: str) -> str:
    """Keep health cards readable without leaking query-string tokens."""
    return re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?...", detail)


def _retailer_queryable(
    RClass: type, products: dict, stores: list[Store]
) -> bool:
    """True if this retailer *should* have produced inventory rows this pass:
    it's supported, has at least one selected product ID for its fields, and
    has somewhere to look. Used to tell "legitimately quiet" apart from
    "parser broke / returned nothing"."""
    if not getattr(RClass, "supported", True):
        return False
    fields = getattr(RClass, "product_id_fields", ())
    if not fields:
        return False
    has_ids = any(
        any(str(p.get(f) or "").strip() for f in fields) for p in products.values()
    )
    if not has_ids:
        return False
    return bool(getattr(RClass, "online_only", False) or stores)


def _record_empty_query_health(slug: str) -> None:
    """Turn an empty retailer result into a useful source-health reason."""
    current = health.get(slug) or {}
    if current.get("last_status") in {"BLOCKED", "ERROR"}:
        return

    http_status = current.get("last_http_status")
    if http_status in {403, 429}:
        health.record_failure(
            slug,
            "BLOCKED",
            f"last HTTP {http_status}; retailer endpoint blocked or rate-limited",
        )
    elif isinstance(http_status, int) and 500 <= http_status <= 599:
        health.record_failure(
            slug,
            "ERROR",
            f"last HTTP {http_status}; retailer endpoint unavailable",
        )
    else:
        health.record_failure(slug, "NO_DATA", "queried but returned no inventory rows")


def run_pass(
    cfg: cfg_mod.Config,
    stores_by_retailer: dict[str, list[Store]],
    state: State,
    notifier: Notifier,
) -> list[StockResult]:
    products = cfg_mod.selected_products(cfg)
    results: list[StockResult] = []
    for slug, RClass in RETAILER_REGISTRY.items():
        rcfg = cfg.retailers.get(slug)
        if not rcfg or not rcfg.enabled:
            continue
        retailer = RClass(api_key=rcfg.api_key)
        stores = stores_by_retailer.get(slug, [])
        health.record_check(slug)
        count = 0
        try:
            for result in retailer.inventory(products, stores):
                result.retailer_slug = slug
                results.append(result)
                count += 1
                store_id = result.store.store_id if result.store else "_online_"
                state.record_observation(slug, store_id, result.product_key, result.status)
                if result.status not in ALERTABLE_STATUSES:
                    continue
                if not state.should_alert(slug, store_id, result.product_key, result.status):
                    continue
                prod = products.get(result.product_key, {})
                hist = state.history_for(slug, store_id, result.product_key) or {}
                alert = StockAlert(
                    retailer=retailer.name,
                    product_name=result.product_name,
                    store_label=result.store.label() if result.store else "Online",
                    distance_miles=result.store.distance_miles if result.store else None,
                    status=result.status,
                    url=result.url,
                    price=result.price,
                    priority=product_priority(prod)[0],
                    msrp=str(prod.get("msrp") or ""),
                    image_url=str(prod.get("image") or ""),
                    first_seen=hist.get("firstSeen"),
                    seen_count=hist.get("inStockCount"),
                )
                notifier.send(alert)
        except Exception as exc:
            health.record_failure(
                slug,
                "ERROR",
                _safe_health_detail(str(exc) or exc.__class__.__name__),
            )
            print(f"  ! {slug} check raised:", file=sys.stderr)
            traceback.print_exc()
            continue
        if count == 0 and _retailer_queryable(RClass, products, stores):
            _record_empty_query_health(slug)
        else:
            current_health = health.get(slug)
            if not (
                count == 0
                and current_health
                and current_health.get("last_status") == "DISCOVERY_FAILED"
            ):
                health.record_success(slug, items=count)
    if hasattr(state, "record_source_health_snapshot"):
        state.record_source_health_snapshot(health.snapshot())
    return results


def enabled_retailer_slugs(cfg: cfg_mod.Config) -> list[str]:
    return [
        slug
        for slug, RClass in RETAILER_REGISTRY.items()
        if getattr(RClass, "supported", True)
        and (cfg.retailers.get(slug) and cfg.retailers[slug].enabled)
    ]


def safe_demo_results(
    cfg: cfg_mod.Config,
    stores_by_retailer: dict[str, list[Store]],
) -> list[StockResult]:
    """Synthetic OUT rows for each active product/source, with no network."""
    products = cfg_mod.selected_products(cfg)
    results: list[StockResult] = []
    for slug, RClass in RETAILER_REGISTRY.items():
        rcfg = cfg.retailers.get(slug)
        if not rcfg or not rcfg.enabled or not getattr(RClass, "supported", True):
            continue
        fields = getattr(RClass, "product_id_fields", ())
        active_products = [
            (key, product)
            for key, product in products.items()
            if any(str(product.get(field) or "").strip() for field in fields)
        ]
        if getattr(RClass, "online_only", False):
            locations: list[Store | None] = [None]
            status = "ONLINE_OUT"
        else:
            locations = list(stores_by_retailer.get(slug, []))
            status = "OUT"
        for store in locations:
            for key, product in active_products:
                results.append(
                    StockResult(
                        store=store,
                        product_key=key,
                        product_name=str(product.get("name") or key),
                        status=status,
                        url="",
                        retailer_slug=slug,
                    )
                )
    return results


def check_config(cfg: cfg_mod.Config) -> int:
    """Validate config + product catalog without making any network calls.

    Useful as a first sanity check after install - confirms config.yaml parses,
    addresses are set, retailers are wired, and the product catalog loads."""
    print("config.yaml: OK")
    print(f"  home:  {cfg.home_address}")
    print(f"  work:  {cfg.work_address}")
    print(f"  route_radius_miles: {cfg.route_radius_miles}")
    print(f"  routing engine: {cfg.routing_engine}")
    print(f"  poll_interval_seconds: {cfg.poll_interval_seconds}")
    print(f"  discord_webhook: {'set' if cfg.discord_webhook else 'not set (console-only)'}")
    print(f"  ntfy_topic: {'set' if cfg.ntfy_topic else 'not set'}")

    enabled = [s for s, r in cfg.retailers.items() if r.enabled]
    disabled = [s for s, r in cfg.retailers.items() if not r.enabled]
    print(f"\nretailers enabled ({len(enabled)}): {', '.join(enabled) or '(none)'}")
    print(f"retailers disabled ({len(disabled)}): {', '.join(disabled) or '(none)'}")

    errors = config_errors(cfg)
    if errors:
        print("\nconfiguration errors:")
        for error in errors:
            print(f"! {error}")

    try:
        selected = cfg_mod.selected_products(cfg)
    except SystemExit:
        return 1
    print(f"\nproducts: {len(selected)} selected / {len(cfg.products)} in catalog")

    report = coverage_mod.coverage_report(cfg)
    print(
        f"active coverage: {report['score']}% "
        f"({report['actionableProducts']}/{report['totalProducts']} products actionable)"
    )
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="single pass then exit")
    parser.add_argument("--dry-run", action="store_true", help="print plan only, no stock checks")
    parser.add_argument(
        "--safe-demo",
        action="store_true",
        help="local-only UI/CLI verification using synthetic stores; no network",
    )
    parser.add_argument("--check-config", action="store_true", help="validate config + catalog, no network")
    args = parser.parse_args()

    cfg = cfg_mod.load()

    if args.check_config:
        return check_config(cfg)

    errors = config_errors(cfg)
    if errors:
        raise SystemExit("\n".join(errors))

    if args.safe_demo:
        stores_by_retailer, diagnostics = safe_demo_stores(cfg)
        results = safe_demo_results(cfg, stores_by_retailer)
        report = coverage_mod.coverage_report(cfg)
        print("safe demo: no geocoding, routing, store, or stock network calls")
        print(
            f"active coverage: {report['score']}% "
            f"({report['actionableProducts']}/{report['totalProducts']} products actionable)"
        )
        for row in diagnostics:
            if row["onlineOnly"]:
                print(f"\n{row['slug']} (online-only demo)")
                continue
            stores = stores_by_retailer.get(row["slug"], [])
            print(f"\n{row['slug']} ({len(stores)} demo stores):")
            for store in stores:
                print(f"  {store.label()}  ({store.distance_miles:.2f} mi from route)")
        print(f"\nsynthetic inventory rows: {len(results)}")
        return 0

    enabled_slugs = enabled_retailer_slugs(cfg)
    needs_route = any(not RETAILER_REGISTRY[slug].online_only for slug in enabled_slugs)
    if needs_route:
        try:
            home, work, polyline = build_corridor(cfg)
        except Exception as exc:
            raise SystemExit(f"route setup failed: {exc}")
        stores_by_retailer = discover_stores(cfg, home, work, polyline)
    else:
        stores_by_retailer = {slug: [] for slug in enabled_slugs}

    if args.dry_run:
        for slug, stores in stores_by_retailer.items():
            RClass = RETAILER_REGISTRY[slug]
            if RClass.online_only:
                print(f"\n{slug} (online-only)")
                continue
            print(f"\n{slug} ({len(stores)} stores in corridor):")
            for s in stores:
                print(f"  {s.label()}  ({s.distance_miles:.2f} mi from route)")
        return 0

    notifier = Notifier(cfg.discord_webhook, cfg.ntfy_topic)
    state = State()

    if args.once:
        run_pass(cfg, stores_by_retailer, state, notifier)
        return 0

    print(f"\nScanning every {cfg.poll_interval_seconds}s (+jitter). Ctrl-C to stop.", flush=True)
    while True:
        run_pass(cfg, stores_by_retailer, state, notifier)
        jitter = random.uniform(0.8, 1.3)
        time.sleep(cfg.poll_interval_seconds * jitter)


if __name__ == "__main__":
    sys.exit(main())
