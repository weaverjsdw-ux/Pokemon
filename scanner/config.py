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
    try:
        poke_cfg = PokeCfg(
            min_rows=int(poke_raw.get("min_rows", 10)),
            staleness_days=int(poke_raw.get("staleness_days", 30)),
            steal_pct=_num(poke_raw, "steal_pct", 30.0, "poke.steal_pct"),
            min_discount_pct=_num(poke_raw, "min_discount_pct", 5.0, "poke.min_discount_pct"),
            grading_cost_all_in=_num(poke_raw, "grading_cost_all_in", 97.50, "poke.grading_cost_all_in"),
        )
    except (TypeError, ValueError):
        raise SystemExit("config.yaml: poke.min_rows / poke.staleness_days must be integers.")

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
