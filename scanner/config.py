"""Load and validate user config + product catalog."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
PRODUCTS_PATH = ROOT / "data" / "products.yaml"

_ENV_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::-([^}]*))?\}")


def _expand_env(val: Any) -> Any:
    """Recursively expand ${VAR} or ${VAR:-default} in string config values.

    Lets users keep secrets out of config.yaml entirely:
        discord_webhook: "${DISCORD_WEBHOOK}"
        retailers:
          bestbuy: { enabled: true, api_key: "${BESTBUY_KEY:-}" }
    """
    if isinstance(val, str):
        def sub(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            return os.environ.get(name, default if default is not None else "")
        return _ENV_RE.sub(sub, val)
    if isinstance(val, dict):
        return {k: _expand_env(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_expand_env(v) for v in val]
    return val


@dataclass
class RetailerCfg:
    enabled: bool = False
    api_key: str = ""
    extra: dict[str, Any] = field(default_factory=dict)  # adapter-specific options


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
    timezone: str  # IANA name, e.g. "America/Chicago"
    heartbeat_seconds: int  # 0 = disable
    quiet_hours_raw: Any  # passed through to scanner.priority.parse_quiet_hours
    priority_channels: dict[str, str]  # tier -> webhook URL (empty = use global)
    drop_windows_raw: Any  # passed through to scanner.drop_windows.parse
    price_filter_raw: Any  # passed through to scanner.filters.parse_price_filter
    pushover: dict
    email: dict
    outbound_webhooks: list[str]
    community_signal: dict  # passed through to scanner.sources.*
    dashboard: dict         # {token: ...} for the interactive dashboard
    operator_email: str     # included in the From: header per RFC 2616 §14.22
    products_filter: Any  # "all_sealed" or list[str]
    products: dict[str, dict[str, Any]] = field(default_factory=dict)

    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def _validate_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError:
        raise SystemExit(
            f"config.yaml: unknown timezone {name!r}. "
            f"Use an IANA name like 'America/Chicago' or 'UTC'."
        )
    return name


def load() -> Config:
    if not CONFIG_PATH.exists():
        raise SystemExit(
            f"Missing {CONFIG_PATH.name}. Run:\n"
            f"  cp config.example.yaml config.yaml\n"
            f"Then edit config.yaml with your addresses + Discord webhook."
        )

    with CONFIG_PATH.open() as f:
        raw = yaml.safe_load(f) or {}
    raw = _expand_env(raw)

    locations = raw.get("locations") or {}
    home = (locations.get("home") or "").strip()
    work = (locations.get("work") or "").strip()
    if not home or not work:
        raise SystemExit("config.yaml: locations.home and locations.work are required.")

    routing = raw.get("routing") or {}
    retailers_raw = raw.get("retailers") or {}
    retailers = {
        name: RetailerCfg(
            enabled=bool(cfg.get("enabled", False)),
            api_key=str(cfg.get("api_key", "")),
            extra={k: v for k, v in cfg.items() if k not in ("enabled", "api_key")},
        )
        for name, cfg in retailers_raw.items()
    }

    with PRODUCTS_PATH.open() as f:
        products = yaml.safe_load(f) or {}

    tz = _validate_timezone(str(raw.get("timezone", "America/Chicago")))

    return Config(
        home_address=home,
        work_address=work,
        route_radius_miles=float(raw.get("route_radius_miles", 4)),
        routing_engine=str(routing.get("engine", "osrm")).lower(),
        google_api_key=str(routing.get("google_api_key", "") or os.getenv("GOOGLE_API_KEY", "")),
        retailers=retailers,
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 180)),
        discord_webhook=str(raw.get("discord_webhook", "") or os.getenv("DISCORD_WEBHOOK", "")),
        ntfy_topic=str(raw.get("ntfy_topic", "") or os.getenv("NTFY_TOPIC", "")),
        timezone=tz,
        heartbeat_seconds=int(raw.get("heartbeat_seconds", 6 * 3600)),
        quiet_hours_raw=raw.get("quiet_hours") or {},
        priority_channels={
            k: str(v) for k, v in (raw.get("priority_channels") or {}).items()
        },
        drop_windows_raw=raw.get("drop_windows") or [],
        price_filter_raw=raw.get("price_filter") or {},
        pushover=dict(raw.get("pushover") or {}),
        email=dict(raw.get("email") or {}),
        outbound_webhooks=[str(u) for u in (raw.get("outbound_webhooks") or []) if str(u).strip()],
        community_signal=dict(raw.get("community_signal") or {}),
        dashboard=dict(raw.get("dashboard") or {}),
        operator_email=str(raw.get("operator_email", "")).strip(),
        products_filter=raw.get("products", "all_sealed"),
        products=products,
    )


def selected_products(cfg: Config) -> dict[str, dict[str, Any]]:
    """Return the product subset the user opted into."""
    if cfg.products_filter == "all_sealed" or cfg.products_filter is None:
        return cfg.products
    if isinstance(cfg.products_filter, list):
        return {k: cfg.products[k] for k in cfg.products_filter if k in cfg.products}
    raise SystemExit(f"config.yaml: invalid 'products' value: {cfg.products_filter!r}")
