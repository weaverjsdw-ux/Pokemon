"""Scanner entry point.

  python -m scanner               # run scan loop forever
  python -m scanner --once        # single pass, then exit
  python -m scanner --dry-run     # print plan (route + stores) without polling
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
from .retailers.base import Store
from .route import get_polyline
from .state import State


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


def run_pass(cfg: cfg_mod.Config, stores_by_retailer: dict[str, list[Store]], state: State, notifier: Notifier) -> None:
    products = cfg_mod.selected_products(cfg)
    for slug, RClass in RETAILER_REGISTRY.items():
        rcfg = cfg.retailers.get(slug)
        if not rcfg or not rcfg.enabled:
            continue
        retailer = RClass(api_key=rcfg.api_key)
        stores = stores_by_retailer.get(slug, [])
        try:
            for result in retailer.check(products, stores):
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="single pass then exit")
    parser.add_argument("--dry-run", action="store_true", help="print plan only, no stock checks")
    args = parser.parse_args()

    cfg = cfg_mod.load()
    home, work, polyline = build_corridor(cfg)
    stores_by_retailer = discover_stores(cfg, home, work, polyline)

    if args.dry_run:
        for slug, stores in stores_by_retailer.items():
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
