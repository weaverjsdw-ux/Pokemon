"""Scanner entry point.

  python -m scanner                  # run scan loop forever
  python -m scanner --once           # single pass, then exit
  python -m scanner --dry-run        # print plan (route + stores) without polling
  python -m scanner --check-config   # validate config + catalog, no network
"""
from __future__ import annotations

import argparse
import random
import sys
import time
import traceback

from . import config as cfg_mod
from .geo import distance_to_polyline_miles
from .geocode import geocode
from .notify import Notifier, StockAlert
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


def discover_stores(cfg: cfg_mod.Config, home, work, polyline) -> dict[str, list[Store]]:
    """For each enabled retailer, find candidate stores near home + work,
    then keep only those within `route_radius_miles` of the route polyline."""
    out: dict[str, list[Store]] = {}
    for slug, RClass in RETAILER_REGISTRY.items():
        rcfg = cfg.retailers.get(slug)
        if not rcfg or not rcfg.enabled:
            continue
        retailer = RClass(api_key=rcfg.api_key)
        if retailer.online_only:
            out[slug] = []
            continue
        seen: dict[str, Store] = {}
        for center in (home, work):
            try:
                found = retailer.find_stores(center[0], center[1], cfg.route_radius_miles + 5)
            except Exception as exc:
                print(f"  ! {slug} store search failed: {exc}", file=sys.stderr)
                continue
            for s in found:
                seen[s.store_id] = s
        kept: list[Store] = []
        for s in seen.values():
            d = distance_to_polyline_miles((s.lat, s.lng), polyline)
            if d <= cfg.route_radius_miles:
                s.distance_miles = d
                kept.append(s)
        kept.sort(key=lambda x: x.distance_miles or 0.0)
        out[slug] = kept
        print(f"  {slug}: {len(kept)} stores in corridor", flush=True)
    return out


ALERTABLE_STATUSES = {"IN_STOCK", "LIMITED", "ONLINE_IN_STOCK"}


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
        try:
            for result in retailer.inventory(products, stores):
                result.retailer_slug = slug
                results.append(result)
                if result.status not in ALERTABLE_STATUSES:
                    continue
                store_id = result.store.store_id if result.store else "_online_"
                if not state.should_alert(slug, store_id, result.product_key, result.status):
                    continue
                alert = StockAlert(
                    retailer=retailer.name,
                    product_name=result.product_name,
                    store_label=result.store.label() if result.store else "Online",
                    distance_miles=result.store.distance_miles if result.store else None,
                    status=result.status,
                    url=result.url,
                    price=result.price,
                )
                notifier.send(alert)
        except Exception:
            print(f"  ! {slug} check raised:", file=sys.stderr)
            traceback.print_exc()
    return results


def enabled_retailer_slugs(cfg: cfg_mod.Config) -> list[str]:
    return [
        slug
        for slug, RClass in RETAILER_REGISTRY.items()
        if getattr(RClass, "supported", True)
        and (cfg.retailers.get(slug) and cfg.retailers[slug].enabled)
    ]


def check_config(cfg: cfg_mod.Config) -> int:
    """Validate config + product catalog without making any network calls.

    Useful as a first sanity check after install — confirms config.yaml parses,
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
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="single pass then exit")
    parser.add_argument("--dry-run", action="store_true", help="print plan only, no stock checks")
    parser.add_argument("--check-config", action="store_true", help="validate config + catalog, no network")
    args = parser.parse_args()

    cfg = cfg_mod.load()

    if args.check_config:
        return check_config(cfg)

    errors = config_errors(cfg)
    if errors:
        raise SystemExit("\n".join(errors))

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
