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

from datetime import datetime

from . import analytics
from . import config as cfg_mod
from . import drop_windows as drop_windows_mod
from . import filters as filters_mod
from .sources.nitter import NitterSource
from .sources.reddit import RedditSource
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
from . import state as state_mod
from .state import State

log = get_logger(__name__)


def _price_to_cents(price: str) -> int | None:
    """Parse '$49.99' / '49.99' / '' -> integer cents or None."""
    if not price:
        return None
    cleaned = price.lstrip("$").replace(",", "").strip()
    try:
        return int(round(float(cleaned) * 100))
    except ValueError:
        return None


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
        retailer = RClass(api_key=rcfg.api_key, **rcfg.extra)
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


def _build_signal_sources(cfg: cfg_mod.Config) -> list:
    """Construct any community-signal sources the user opted into."""
    sources = []
    cs = cfg.community_signal or {}
    reddit_cfg = cs.get("reddit") or {}
    if reddit_cfg.get("enabled"):
        sources.append(RedditSource(
            subs=reddit_cfg.get("subs"),
            keywords=reddit_cfg.get("keywords"),
            retailers=reddit_cfg.get("retailers"),
            max_age_seconds=int(reddit_cfg.get("max_age_seconds", 3600)),
        ))
    nitter_cfg = cs.get("nitter") or {}
    if nitter_cfg.get("enabled"):
        sources.append(NitterSource(
            instance=str(nitter_cfg.get("instance") or ""),
            accounts=list(nitter_cfg.get("accounts") or []),
            keywords=nitter_cfg.get("keywords"),
            max_age_seconds=int(nitter_cfg.get("max_age_seconds", 3600)),
        ))
    return sources


def community_signal_pass(sources: list, state: State, notifier: Notifier) -> int:
    """Poll each community-signal source, dedupe, and forward as status
    messages. Returns the number of signals surfaced."""
    fired = 0
    for src in sources:
        try:
            for hit in src.fetch():
                if not state.signal_should_alert(hit.source, hit.external_id):
                    continue
                fields = [
                    ("Source", f"{hit.source} · {hit.where}"),
                    ("Author", hit.author),
                    ("Matched", ", ".join(hit.matched_keywords)),
                    ("Link", hit.url),
                ]
                notifier.send_status(f"COMMUNITY: {hit.title}", fields)
                fired += 1
        except Exception:
            log.exception("source=%s fetch raised", getattr(src, "name", "?"))
    return fired


def run_pass(cfg: cfg_mod.Config, stores_by_retailer: dict[str, list[Store]], state: State, notifier: Notifier) -> int:
    """One full scan pass across all enabled retailers. Returns alerts fired."""
    products = cfg_mod.selected_products(cfg)
    quiet = parse_quiet_hours(cfg.quiet_hours_raw, cfg.timezone)
    price_filter = filters_mod.parse_price_filter(cfg.price_filter_raw)
    alerts_fired = 0
    for slug, RClass in RETAILER_REGISTRY.items():
        rcfg = cfg.retailers.get(slug)
        if not rcfg or not rcfg.enabled:
            continue
        retailer = RClass(api_key=rcfg.api_key, **rcfg.extra)
        stores = stores_by_retailer.get(slug, [])
        try:
            for result in retailer.check(products, stores):
                store_id = result.store.store_id if result.store else "_online_"
                product = products.get(result.product_key, {})
                if state_mod.is_runtime_muted(state.db, result.product_key):
                    continue
                if state_mod.is_suppressed(state.db, slug, result.product_key, store_id):
                    continue
                if not priority_gate(product, quiet):
                    continue
                if not filters_mod.passes(product, result.price, price_filter):
                    log.info(
                        "retailer=%s product=%s suppressed by price filter (listed=%s msrp=%s)",
                        slug, result.product_key, result.price or "?", product.get("msrp", "?"),
                    )
                    continue
                if not state.should_alert(slug, store_id, result.product_key, result.status):
                    continue
                state.record_price(slug, result.product_key, store_id,
                                   _price_to_cents(result.price))
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
                state.record_hit(
                    retailer=slug,
                    store_id=store_id,
                    product_key=result.product_key,
                    status=result.status,
                    tier=alert.tier,
                    url=result.url,
                    price_cents=_price_to_cents(result.price),
                )
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
    print(f"  operator_email: {cfg.operator_email or 'not set (recommended for ToS)'}")
    dash_token = (cfg.dashboard or {}).get("token", "")
    print(f"  dashboard.token: {'set' if dash_token else 'open (localhost only)'}")

    pf = filters_mod.parse_price_filter(cfg.price_filter_raw)
    print(f"  price_filter: only_at_or_near_msrp={pf.only_at_or_near_msrp} multiplier={pf.msrp_multiplier}")

    windows = drop_windows_mod.parse(cfg.drop_windows_raw)
    if windows:
        print(f"  drop_windows: {len(windows)} configured")
        for w in windows:
            days = "all" if len(w.days) == 7 else ",".join(
                d for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
                if {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}[d] in w.days
            )
            print(f"    - {'+'.join(w.retailers)} {days} {w.start.strftime('%H:%M')}-{w.end.strftime('%H:%M')} -> {w.poll_interval_seconds}s")
    else:
        print(f"  drop_windows: none (global cadence always applies)")

    extra_channels = []
    if (cfg.pushover.get("user_key") or "").strip() and (cfg.pushover.get("app_token") or "").strip():
        extra_channels.append("pushover")
    if (cfg.email.get("smtp_host") or "").strip() and cfg.email.get("to"):
        extra_channels.append("email")
    if cfg.outbound_webhooks:
        extra_channels.append(f"outbound_webhooks×{len(cfg.outbound_webhooks)}")
    print(f"  extra channels: {', '.join(extra_channels) if extra_channels else 'none'}")

    cs = cfg.community_signal or {}
    on = [name for name in ("reddit", "nitter") if (cs.get(name) or {}).get("enabled")]
    print(f"  community_signal: {', '.join(on) if on else 'none'}")

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
    default_client.operator_email = cfg.operator_email

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

    notifier = Notifier(
        cfg.discord_webhook,
        cfg.ntfy_topic,
        cfg.priority_channels,
        pushover=cfg.pushover,
        email=cfg.email,
        outbound_webhooks=cfg.outbound_webhooks,
    )
    state = State()
    heartbeat = Heartbeat(cfg.heartbeat_seconds) if cfg.heartbeat_seconds else None

    if args.once:
        run_pass(cfg, stores_by_retailer, state, notifier)
        return 0

    explicit_windows = drop_windows_mod.parse(cfg.drop_windows_raw)
    observed_windows: list = []
    observed_refresh_at: float = 0.0
    enabled_slugs = [s for s, r in cfg.retailers.items() if r.enabled]
    signal_sources = _build_signal_sources(cfg)

    log.info(
        "scanning interval=%ds (+jitter), drop_windows=%d, signal_sources=%d. Ctrl-C to stop.",
        cfg.poll_interval_seconds, len(explicit_windows), len(signal_sources),
    )
    while True:
        fired = run_pass(cfg, stores_by_retailer, state, notifier)
        if signal_sources:
            fired += community_signal_pass(signal_sources, state, notifier)
        if heartbeat is not None:
            heartbeat.record_pass(fired)
            heartbeat.maybe_send(
                notifier.send_status,
                default_client.health_snapshot(),
                stores_by_retailer,
            )
        state.maybe_backup()

        # Refresh analytics-derived windows hourly. Avoids re-querying
        # SQLite on every pass when there are thousands of hits.
        now_secs = time.time()
        if now_secs >= observed_refresh_at:
            try:
                observed_windows = analytics.suggested_drop_windows_as_runtime(
                    state.db, tz=cfg.timezone,
                )
                if observed_windows:
                    log.info(
                        "analytics suggested %d observed drop windows; merging",
                        len(observed_windows),
                    )
            except Exception:
                log.exception("analytics window refresh failed")
                observed_windows = []
            observed_refresh_at = now_secs + 3600

        now = datetime.now(cfg.tzinfo())
        interval, tags = drop_windows_mod.effective_interval(
            explicit_windows + observed_windows,
            enabled_slugs, cfg.poll_interval_seconds, now=now,
        )
        if tags:
            log.info("drop-window active (%s) — interval=%ds", ",".join(tags), interval)

        # Anomaly-based boost: if any enabled retailer's latency is
        # elevated (often a leading indicator of a drop), shrink the
        # interval. Take the lowest factor across retailers.
        factor = 1.0
        anomaly_tags = []
        for slug in enabled_slugs:
            f = default_client.anomaly_factor(slug)
            if f < factor:
                factor = f
                anomaly_tags = [slug]
            elif f == factor and f < 1.0:
                anomaly_tags.append(slug)
        if factor < 1.0:
            boosted = max(15, int(interval * factor))
            log.info(
                "latency anomaly on %s (factor=%.2f) — interval %d -> %d",
                ",".join(anomaly_tags), factor, interval, boosted,
            )
            interval = boosted

        jitter = random.uniform(0.8, 1.3)
        time.sleep(interval * jitter)


if __name__ == "__main__":
    sys.exit(main())
