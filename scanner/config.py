"""Load and validate user config + product catalog."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
PRODUCTS_PATH = ROOT / "data" / "products.yaml"

VALID_CONFIDENCE = {"none", "low", "medium", "high"}


def _num(mapping: dict[str, Any], key: str, default: float, label: str) -> float:
    try:
        return float(mapping.get(key, default))
    except (TypeError, ValueError):
        raise SystemExit(f"config.yaml: {label} must be a number.")


@dataclass
class RetailerCfg:
    enabled: bool = False
    api_key: str = ""


@dataclass
class PokeCfg:
    min_rows: int = 10            # golden-test acquisition-failure floor
    staleness_days: int = 30      # comp older than this is flagged stale
    steal_pct: float = 30.0       # verified deal at/above this % off -> STEAL eligible
    min_discount_pct: float = 5.0 # below this % off market -> not a deal row
    grading_cost_all_in: float = 97.50  # live PSA tier all-in (config, value tiers paused 2026-06)
    buy_basis: str = "msrp"       # sealed-board deal-price basis ("observed" is a future hook)
    daily_credit_cap: int = 90    # PPT credits/run guard; past this the sweep uses the resale fallback


@dataclass
class CompsCfg:
    engine: str = "legacy"                 # legacy | inhouse (Slice-6 flips the default)
    agreement_tolerance_pct: float = 20.0
    ebay_floor_sanity_pct: float = 50.0
    cache_ttl_seconds: int = 21600
    politeness_seconds: float = 1.0


DEFAULT_SET_WATCH = [
    "Prismatic Evolutions", "Destined Rivals", "Journey Together",
    "Surging Sparks", "Scarlet & Violet 151", "Paldean Fates", "Crown Zenith",
]


@dataclass
class DiscoveryCfg:
    enabled: bool = True
    interval_seconds: int = 7200
    sources: list[str] = field(
        default_factory=lambda: ["target_search", "slickdeals", "ebay_browse"])
    set_watch: list[str] = field(default_factory=lambda: list(DEFAULT_SET_WATCH))
    min_alert_confidence: str = "medium"


@dataclass
class AlertsCfg:
    quiet_hours: str = "23:00-08:00"   # HH:MM-HH:MM local; ntfy pushes suppressed in-window
    price_drop_realert_pct: float = 5.0  # re-alert a live listing when price drops >= this %
    cooldown_hours: float = 24.0        # otherwise no repeat alert until this elapses


@dataclass
class OpportunityCfg:
    """Money Hypothesis Lab (Phase C) business policy.

    Fees, tax, shipping, and the PAPER buy floor are intentionally NOT here — they
    are cited from deal_intelligence (correct units + the $0.40 fixed fee) so
    opportunity net/ROI matches the alert path exactly. Only genuinely-new business
    policy lives here; unset per-type values surface as TBD_OPERATOR_POLICY."""
    live_min_expected_net: float = 25.0   # stricter than paper buy_floor_net (15) — TBD_OPERATOR_POLICY
    live_min_roi_pct: float = 30.0        # stricter than paper buy_floor_roi (20) — TBD_OPERATOR_POLICY
    live_min_confidence: str = "medium"   # TBD_OPERATOR_POLICY
    stale_after_days: int = 30            # default mirrors poke.staleness_days
    max_hold_days: dict[str, int] = field(default_factory=dict)  # empty => TBD per trade type
    exit_venue: dict[str, str] = field(default_factory=dict)     # empty => TBD per trade type


def parse_quiet_hours(value: str) -> tuple[int, int]:
    """('23:00-08:00') -> (1380, 480) minutes-of-day. Wrap (start > end) allowed.

    Raises ValueError on anything not HH:MM-HH:MM with valid clock values."""
    text = str(value).strip()
    if text.count("-") != 1:
        raise ValueError(f"quiet_hours must be HH:MM-HH:MM, got {value!r}")
    start_s, end_s = text.split("-")

    def _to_minutes(clock: str) -> int:
        parts = clock.strip().split(":")
        if len(parts) != 2:
            raise ValueError(f"quiet_hours time must be HH:MM, got {clock!r}")
        hh, mm = int(parts[0]), int(parts[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError(f"quiet_hours time out of range: {clock!r}")
        return hh * 60 + mm

    return _to_minutes(start_s), _to_minutes(end_s)


@dataclass
class Config:
    home_address: str
    work_address: str
    route_radius_miles: float
    routing_engine: str
    google_api_key: str
    retailers: dict[str, RetailerCfg]
    poll_interval_seconds: int
    discord_webhook: str
    ntfy_topic: str
    products_filter: Any  # "all_sealed"/"all_tcg", "pokemon", "magic", or list[str]
    products: dict[str, dict[str, Any]] = field(default_factory=dict)
    resale_price_enabled: bool = True
    resale_price_interval_seconds: int = 14400
    ebay_marketplace_id: str = "EBAY_US"
    ebay_browse_api_token: str = ""
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    # --- Phase 1 deal intelligence ---
    tax_rate: float = 0.07
    ebay_fvf_pct: float = 0.1325
    ebay_fixed_fee: float = 0.40
    ebay_est_shipping: float = 8.0
    local_haircut_pct: float = 0.15
    skip_floor_net: float = 5.0
    buy_floor_net: float = 15.0
    roi_gate_enabled: bool = True
    skip_floor_roi: float = 10.0
    buy_floor_roi: float = 20.0
    min_buy_confidence: str = "medium"
    market_preferred: bool = False
    market_api_key: str = ""
    market_cache_ttl_seconds: int = 86400
    poke: PokeCfg = field(default_factory=PokeCfg)
    comps: CompsCfg = field(default_factory=CompsCfg)
    discovery: DiscoveryCfg = field(default_factory=DiscoveryCfg)
    alerts: AlertsCfg = field(default_factory=AlertsCfg)
    opportunity: OpportunityCfg = field(default_factory=OpportunityCfg)


def load(path: Path | None = None) -> Config:
    path = path or CONFIG_PATH
    if not path.exists():
        raise SystemExit(
            f"Missing {path.name}. Run:\n"
            f"  cp config.example.yaml config.yaml\n"
            f"Then edit config.yaml with your addresses + Discord webhook."
        )

    with path.open() as f:
        raw = yaml.safe_load(f) or {}

    return from_mapping(raw)


def from_mapping(raw: dict[str, Any]) -> Config:
    locations = raw.get("locations") or {}
    home = (locations.get("home") or "").strip()
    work = (locations.get("work") or "").strip()
    if not home or not work:
        raise SystemExit("config.yaml: locations.home and locations.work are required.")

    routing = raw.get("routing") or {}
    retailers_raw = raw.get("retailers") or {}
    retailers = {}
    for name, value in retailers_raw.items():
        cfg = value or {}
        if not isinstance(cfg, dict):
            raise SystemExit(f"config.yaml: retailers.{name} must be a mapping.")
        retailers[name] = RetailerCfg(
            enabled=bool(cfg.get("enabled", False)),
            api_key=str(cfg.get("api_key", "")),
        )

    with PRODUCTS_PATH.open() as f:
        products = yaml.safe_load(f) or {}

    try:
        route_radius_miles = float(raw.get("route_radius_miles", 4))
    except (TypeError, ValueError):
        raise SystemExit("config.yaml: route_radius_miles must be a number.")

    try:
        poll_interval_seconds = int(raw.get("poll_interval_seconds", 180))
    except (TypeError, ValueError):
        raise SystemExit("config.yaml: poll_interval_seconds must be an integer.")

    resale_raw = raw.get("resale_prices") or {}
    if not isinstance(resale_raw, dict):
        raise SystemExit("config.yaml: resale_prices must be a mapping.")
    ebay_raw = resale_raw.get("ebay") or {}
    if not isinstance(ebay_raw, dict):
        raise SystemExit("config.yaml: resale_prices.ebay must be a mapping.")
    try:
        resale_price_interval_seconds = int(
            resale_raw.get("interval_seconds", 14400)
        )
    except (TypeError, ValueError):
        raise SystemExit("config.yaml: resale_prices.interval_seconds must be an integer.")

    di_raw = raw.get("deal_intelligence") or {}
    if not isinstance(di_raw, dict):
        raise SystemExit("config.yaml: deal_intelligence must be a mapping.")
    fees_raw = di_raw.get("fees") or {}
    verdict_raw = di_raw.get("verdict") or {}
    market_raw = raw.get("market") or {}
    if not isinstance(market_raw, dict):
        raise SystemExit("config.yaml: market must be a mapping.")
    min_conf = str(verdict_raw.get("min_buy_confidence", "medium")).lower()
    if min_conf not in VALID_CONFIDENCE:
        raise SystemExit(
            "config.yaml: deal_intelligence.verdict.min_buy_confidence must be one of "
            + ", ".join(sorted(VALID_CONFIDENCE))
        )
    try:
        market_cache_ttl = int(market_raw.get("cache_ttl_seconds", 86400))
    except (TypeError, ValueError):
        raise SystemExit("config.yaml: market.cache_ttl_seconds must be an integer.")

    poke_raw = raw.get("poke")
    if poke_raw is None:
        poke_raw = {}
    if not isinstance(poke_raw, dict):
        raise SystemExit("config.yaml: poke must be a mapping.")
    buy_basis = str(poke_raw.get("buy_basis", "msrp")).strip().lower()
    if buy_basis != "msrp":
        raise SystemExit(
            "config.yaml: poke.buy_basis only supports 'msrp' in this build "
            "('observed' is a future hook, not implemented)."
        )
    try:
        poke_cfg = PokeCfg(
            min_rows=int(poke_raw.get("min_rows", 10)),
            staleness_days=int(poke_raw.get("staleness_days", 30)),
            steal_pct=_num(poke_raw, "steal_pct", 30.0, "poke.steal_pct"),
            min_discount_pct=_num(poke_raw, "min_discount_pct", 5.0, "poke.min_discount_pct"),
            grading_cost_all_in=_num(poke_raw, "grading_cost_all_in", 97.50, "poke.grading_cost_all_in"),
            buy_basis=buy_basis,
            daily_credit_cap=int(poke_raw.get("daily_credit_cap", 90)),
        )
    except (TypeError, ValueError):
        raise SystemExit("config.yaml: poke.min_rows / poke.staleness_days / poke.daily_credit_cap must be integers.")

    comps_raw = raw.get("comps")
    if comps_raw is None:
        comps_raw = {}
    if not isinstance(comps_raw, dict):
        raise SystemExit("config.yaml: comps must be a mapping.")
    comps_engine = str(comps_raw.get("engine", "legacy")).strip().lower()
    if comps_engine not in {"legacy", "inhouse"}:
        raise SystemExit("config.yaml: comps.engine must be 'legacy' or 'inhouse'.")
    try:
        comps_cfg = CompsCfg(
            engine=comps_engine,
            agreement_tolerance_pct=_num(comps_raw, "agreement_tolerance_pct", 20.0,
                                         "comps.agreement_tolerance_pct"),
            ebay_floor_sanity_pct=_num(comps_raw, "ebay_floor_sanity_pct", 50.0,
                                       "comps.ebay_floor_sanity_pct"),
            cache_ttl_seconds=int(comps_raw.get("cache_ttl_seconds", 21600)),
            politeness_seconds=_num(comps_raw, "politeness_seconds", 1.0,
                                    "comps.politeness_seconds"),
        )
    except (TypeError, ValueError):
        raise SystemExit("config.yaml: comps.cache_ttl_seconds must be an integer.")

    disc_raw = raw.get("discovery")
    if disc_raw is None:
        disc_raw = {}
    if not isinstance(disc_raw, dict):
        raise SystemExit("config.yaml: discovery must be a mapping.")
    disc_conf = str(disc_raw.get("min_alert_confidence", "medium")).strip().lower()
    if disc_conf not in VALID_CONFIDENCE:
        raise SystemExit(
            "config.yaml: discovery.min_alert_confidence must be one of "
            + ", ".join(sorted(VALID_CONFIDENCE)))
    disc_sources = disc_raw.get("sources",
                                ["target_search", "slickdeals", "ebay_browse"])
    disc_watch = disc_raw.get("set_watch", list(DEFAULT_SET_WATCH))
    if not isinstance(disc_sources, list) or not isinstance(disc_watch, list):
        raise SystemExit("config.yaml: discovery.sources and discovery.set_watch must be lists.")
    try:
        discovery_cfg = DiscoveryCfg(
            enabled=bool(disc_raw.get("enabled", True)),
            interval_seconds=int(disc_raw.get("interval_seconds", 7200)),
            sources=[str(s) for s in disc_sources],
            set_watch=[str(s) for s in disc_watch],
            min_alert_confidence=disc_conf,
        )
    except (TypeError, ValueError):
        raise SystemExit("config.yaml: discovery.interval_seconds must be an integer.")

    alerts_raw = raw.get("alerts")
    if alerts_raw is None:
        alerts_raw = {}
    if not isinstance(alerts_raw, dict):
        raise SystemExit("config.yaml: alerts must be a mapping.")
    quiet_hours = str(alerts_raw.get("quiet_hours", "23:00-08:00")).strip()
    try:
        parse_quiet_hours(quiet_hours)  # validate now so the pipeline can trust it
    except ValueError:
        raise SystemExit(
            "config.yaml: alerts.quiet_hours must be HH:MM-HH:MM (24h), "
            f"got {quiet_hours!r}.")
    alerts_cfg = AlertsCfg(
        quiet_hours=quiet_hours,
        price_drop_realert_pct=_num(alerts_raw, "price_drop_realert_pct", 5.0,
                                    "alerts.price_drop_realert_pct"),
        cooldown_hours=_num(alerts_raw, "cooldown_hours", 24.0, "alerts.cooldown_hours"),
    )

    opp_raw = raw.get("opportunity")
    if opp_raw is None:
        opp_raw = {}
    if not isinstance(opp_raw, dict):
        raise SystemExit("config.yaml: opportunity must be a mapping.")
    live_conf = str(opp_raw.get("live_min_confidence", "medium")).strip().lower()
    if live_conf not in VALID_CONFIDENCE:
        raise SystemExit(
            "config.yaml: opportunity.live_min_confidence must be one of "
            + ", ".join(sorted(VALID_CONFIDENCE)))
    hold_raw = opp_raw.get("max_hold_days") or {}
    venue_raw = opp_raw.get("exit_venue") or {}
    if not isinstance(hold_raw, dict) or not isinstance(venue_raw, dict):
        raise SystemExit(
            "config.yaml: opportunity.max_hold_days and opportunity.exit_venue must be mappings.")
    try:
        max_hold_days = {str(k): int(v) for k, v in hold_raw.items()}
    except (TypeError, ValueError):
        raise SystemExit("config.yaml: opportunity.max_hold_days values must be integers.")
    exit_venue = {str(k): str(v) for k, v in venue_raw.items()}
    try:
        opportunity_cfg = OpportunityCfg(
            live_min_expected_net=_num(opp_raw, "live_min_expected_net", 25.0,
                                       "opportunity.live_min_expected_net"),
            live_min_roi_pct=_num(opp_raw, "live_min_roi_pct", 30.0,
                                  "opportunity.live_min_roi_pct"),
            live_min_confidence=live_conf,
            stale_after_days=int(opp_raw.get("stale_after_days", 30)),
            max_hold_days=max_hold_days,
            exit_venue=exit_venue,
        )
    except (TypeError, ValueError):
        raise SystemExit("config.yaml: opportunity.stale_after_days must be an integer.")

    return Config(
        home_address=home,
        work_address=work,
        route_radius_miles=route_radius_miles,
        routing_engine=str(routing.get("engine", "osrm")).lower(),
        google_api_key=str(routing.get("google_api_key", "") or os.getenv("GOOGLE_API_KEY", "")),
        retailers=retailers,
        poll_interval_seconds=poll_interval_seconds,
        discord_webhook=str(raw.get("discord_webhook", "") or os.getenv("DISCORD_WEBHOOK", "")),
        ntfy_topic=str(raw.get("ntfy_topic", "") or os.getenv("NTFY_TOPIC", "")),
        products_filter=raw.get("products", "all_sealed"),
        products=products,
        resale_price_enabled=bool(resale_raw.get("enabled", True)),
        resale_price_interval_seconds=resale_price_interval_seconds,
        ebay_marketplace_id=str(
            ebay_raw.get("marketplace_id") or os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US")
        ),
        ebay_browse_api_token=str(
            ebay_raw.get("browse_api_token")
            or os.getenv("EBAY_BROWSE_API_TOKEN", "")
            or os.getenv("EBAY_OAUTH_TOKEN", "")
        ),
        ebay_client_id=str(ebay_raw.get("client_id") or os.getenv("EBAY_CLIENT_ID", "")),
        ebay_client_secret=str(
            ebay_raw.get("client_secret") or os.getenv("EBAY_CLIENT_SECRET", "")
        ),
        tax_rate=_num(di_raw, "tax_rate", 0.07, "deal_intelligence.tax_rate"),
        ebay_fvf_pct=_num(fees_raw, "ebay_fvf_pct", 0.1325, "deal_intelligence.fees.ebay_fvf_pct"),
        ebay_fixed_fee=_num(fees_raw, "ebay_fixed_fee", 0.40, "deal_intelligence.fees.ebay_fixed_fee"),
        ebay_est_shipping=_num(fees_raw, "ebay_est_shipping", 8.0, "deal_intelligence.fees.ebay_est_shipping"),
        local_haircut_pct=_num(fees_raw, "local_haircut_pct", 0.15, "deal_intelligence.fees.local_haircut_pct"),
        skip_floor_net=_num(verdict_raw, "skip_floor_net", 5.0, "deal_intelligence.verdict.skip_floor_net"),
        buy_floor_net=_num(verdict_raw, "buy_floor_net", 15.0, "deal_intelligence.verdict.buy_floor_net"),
        roi_gate_enabled=bool(verdict_raw.get("roi_gate_enabled", True)),
        skip_floor_roi=_num(verdict_raw, "skip_floor_roi", 10.0, "deal_intelligence.verdict.skip_floor_roi"),
        buy_floor_roi=_num(verdict_raw, "buy_floor_roi", 20.0, "deal_intelligence.verdict.buy_floor_roi"),
        min_buy_confidence=min_conf,
        market_preferred=bool(market_raw.get("preferred", False)),
        market_api_key=str(market_raw.get("api_key", "") or os.getenv("PPT_API_KEY", "")),
        market_cache_ttl_seconds=market_cache_ttl,
        poke=poke_cfg,
        comps=comps_cfg,
        discovery=discovery_cfg,
        alerts=alerts_cfg,
        opportunity=opportunity_cfg,
    )


ALL_PRODUCT_FILTERS = {"all", "all_sealed", "all_tcg", "all_products"}
MAGIC_FILTERS = {"magic", "mtg", "magic_the_gathering"}
POKEMON_FILTERS = {"pokemon", "pokemon_tcg", "pkmn"}


def product_game_key(product: dict[str, Any]) -> str:
    raw = str(product.get("game") or product.get("tcg") or product.get("brand") or "").lower()
    if "magic" in raw or "mtg" in raw:
        return "magic"
    if "pokemon" in raw or "pokémon" in raw:
        return "pokemon"
    # Existing catalog rows predate the game field and are Pokemon products.
    return "pokemon"


def selected_products(cfg: Config) -> dict[str, dict[str, Any]]:
    """Return the product subset the user opted into."""
    if cfg.products_filter is None:
        return cfg.products
    if isinstance(cfg.products_filter, str):
        filter_key = cfg.products_filter.strip().lower()
        if filter_key in ALL_PRODUCT_FILTERS:
            return cfg.products
        if filter_key in POKEMON_FILTERS:
            return {
                key: product
                for key, product in cfg.products.items()
                if product_game_key(product) == "pokemon"
            }
        if filter_key in MAGIC_FILTERS:
            return {
                key: product
                for key, product in cfg.products.items()
                if product_game_key(product) == "magic"
            }
    if isinstance(cfg.products_filter, list):
        missing = [k for k in cfg.products_filter if k not in cfg.products]
        if missing:
            raise SystemExit(
                "config.yaml: products filter lists keys not in catalog: "
                + ", ".join(missing)
            )
        return {k: cfg.products[k] for k in cfg.products_filter}
    raise SystemExit(f"config.yaml: invalid 'products' value: {cfg.products_filter!r}")
