"""Scanner entry point.

  python -m scanner                  # run scan loop forever
  python -m scanner --once           # single pass, then exit
  python -m scanner --dry-run        # print plan (route + stores) without polling
  python -m scanner --check-config   # validate config + catalog, no network
  python -m scanner --init           # interactive setup wizard -> config.yaml
"""
from __future__ import annotations

import argparse
import random
import sys
import time

from . import config as cfg_mod
from .geo import distance_to_polyline_miles
from .geocode import geocode
from .heartbeat import Heartbeat
from .http import BudgetExceeded, RetailerDisabled, default_client
from .log import configure as configure_logging, get_logger
from .notify import Notifier, StockAlert
from .priority import parse_quiet_hours, product_tier, should_alert as priority_gate
from .retailers import ALL as RETAILER_REGISTRY
from .retailers.base import Store
from .route import get_polyline
from .state import State

log = get_logger(__name__)


def build_corridor(cfg: cfg_mod.Config):
    log.info("geocoding addresses")
    home = geocode(cfg.home_address)
    work = geocode(cfg.work_address)
    log.info("geocoded home=%s work=%s", home, work)

    log.info("computing route engine=%s", cfg.routing_engine)
    forward = get_polyline(home, work, cfg.routing_engine, cfg.google_api_key)
    reverse = get_polyline(work, home, cfg.routing_engine, cfg.google_api_key)
    polyline = forward + reverse
    log.info("route polyline points=%d", len(polyline))
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
                log.warning("retailer=%s store search failed: %s", slug, exc)
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
        log.info("retailer=%s stores_in_corridor=%d", slug, len(kept))
    return out


def run_pass(cfg: cfg_mod.Config, stores_by_retailer: dict[str, list[Store]], state: State, notifier: Notifier) -> int:
    """One full scan pass across all enabled retailers. Returns alerts fired."""
    products = cfg_mod.selected_products(cfg)
    quiet = parse_quiet_hours(cfg.quiet_hours_raw, cfg.timezone)
    alerts_fired = 0
    for slug, RClass in RETAILER_REGISTRY.items():
        rcfg = cfg.retailers.get(slug)
        if not rcfg or not rcfg.enabled:
            continue
        retailer = RClass(api_key=rcfg.api_key)
        stores = stores_by_retailer.get(slug, [])
        try:
            for result in retailer.check(products, stores):
                store_id = result.store.store_id if result.store else "_online_"
                product = products.get(result.product_key, {})
                if not priority_gate(product, quiet):
                    continue
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
                    tier=product_tier(product),
                    msrp=str(product.get("msrp", "")),
                    cart_url=result.cart_url,
                    image_url=result.image_url or str(product.get("image_url", "")),
                )
                notifier.send(alert)
                alerts_fired += 1
        except RetailerDisabled as exc:
            log.warning("retailer=%s skipped: %s", slug, exc)
        except BudgetExceeded as exc:
            log.warning("retailer=%s budget hit: %s", slug, exc)
        except Exception:
            log.exception("retailer=%s check raised", slug)
    return alerts_fired


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
    print(f"  timezone: {cfg.timezone}")
    print(f"  heartbeat: {'every ' + str(cfg.heartbeat_seconds) + 's' if cfg.heartbeat_seconds else 'disabled'}")
    quiet = parse_quiet_hours(cfg.quiet_hours_raw, cfg.timezone)
    if quiet.start is None or quiet.end is None:
        print(f"  quiet_hours: disabled")
    else:
        print(f"  quiet_hours: {quiet.start.strftime('%H:%M')} - {quiet.end.strftime('%H:%M')} ({cfg.timezone})")
    pri_tiers = [t for t, w in cfg.priority_channels.items() if w]
    print(f"  priority_channels: {', '.join(pri_tiers) if pri_tiers else 'none (all tiers -> global webhook)'}")
    print(f"  discord_webhook: {'set' if cfg.discord_webhook else 'not set (console-only)'}")
    print(f"  ntfy_topic: {'set' if cfg.ntfy_topic else 'not set'}")

    enabled = [s for s, r in cfg.retailers.items() if r.enabled]
    disabled = [s for s, r in cfg.retailers.items() if not r.enabled]
    print(f"\nretailers enabled ({len(enabled)}): {', '.join(enabled) or '(none)'}")
    print(f"retailers disabled ({len(disabled)}): {', '.join(disabled) or '(none)'}")

    unknown = [s for s in cfg.retailers if s not in RETAILER_REGISTRY]
    if unknown:
        print(f"\n! config.yaml references unknown retailers: {', '.join(unknown)}")

    selected = cfg_mod.selected_products(cfg)
    print(f"\nproducts: {len(selected)} selected / {len(cfg.products)} in catalog")
    filt = cfg.products_filter
    if isinstance(filt, list):
        missing = [k for k in filt if k not in cfg.products]
        if missing:
            print(f"! products filter lists keys not in catalog: {', '.join(missing)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="single pass then exit")
    parser.add_argument("--dry-run", action="store_true", help="print plan only, no stock checks")
    parser.add_argument("--check-config", action="store_true", help="validate config + catalog, no network")
    parser.add_argument("--init", action="store_true", help="interactive setup wizard")
    parser.add_argument("--log-level", default="INFO", help="DEBUG / INFO / WARNING / ERROR")
    args = parser.parse_args()

    configure_logging(args.log_level)

    if args.init:
        from .setup_wizard import run as run_wizard
        return run_wizard()

    cfg = cfg_mod.load()

    if args.check_config:
        return check_config(cfg)

    home, work, polyline = build_corridor(cfg)
    stores_by_retailer = discover_stores(cfg, home, work, polyline)

    if args.dry_run:
        for slug, stores in stores_by_retailer.items():
            print(f"\n{slug} ({len(stores)} stores in corridor):")
            for s in stores:
                print(f"  {s.label()}  ({s.distance_miles:.2f} mi from route)")
        return 0

    notifier = Notifier(cfg.discord_webhook, cfg.ntfy_topic, cfg.priority_channels)
    state = State()
    heartbeat = Heartbeat(cfg.heartbeat_seconds) if cfg.heartbeat_seconds else None

    if args.once:
        run_pass(cfg, stores_by_retailer, state, notifier)
        return 0

    log.info("scanning interval=%ds (+jitter). Ctrl-C to stop.", cfg.poll_interval_seconds)
    while True:
        fired = run_pass(cfg, stores_by_retailer, state, notifier)
        if heartbeat is not None:
            heartbeat.record_pass(fired)
            heartbeat.maybe_send(
                notifier.send_status,
                default_client.health_snapshot(),
                stores_by_retailer,
            )
        state.maybe_backup()
        jitter = random.uniform(0.8, 1.3)
        time.sleep(cfg.poll_interval_seconds * jitter)


if __name__ == "__main__":
    sys.exit(main())
