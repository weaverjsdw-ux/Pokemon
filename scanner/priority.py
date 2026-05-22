"""Per-product priority tiers + quiet hours.

Three tiers, hard-coded so they're stable across the codebase:

  must_have   — always alerts, even during quiet hours
  nice_to_have — default; suppressed during quiet hours
  fyi          — low-priority; suppressed during quiet hours

A product entry in products.yaml can override:

  priority: must_have   # one of must_have | nice_to_have | fyi
  mute: true            # short-circuit; never alert at all

Quiet hours live in config.yaml as { start: "HH:MM", end: "HH:MM" } and
are interpreted in the configured timezone. start > end wraps midnight
(e.g. 23:00 to 07:00)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dtime
from typing import Any
from zoneinfo import ZoneInfo

MUST_HAVE = "must_have"
NICE_TO_HAVE = "nice_to_have"
FYI = "fyi"
VALID_TIERS = (MUST_HAVE, NICE_TO_HAVE, FYI)
DEFAULT_TIER = NICE_TO_HAVE


def product_tier(product: dict[str, Any]) -> str:
    raw = (product.get("priority") or DEFAULT_TIER).strip().lower()
    if raw not in VALID_TIERS:
        return DEFAULT_TIER
    return raw


def is_muted(product: dict[str, Any]) -> bool:
    return bool(product.get("mute", False))


@dataclass
class QuietHours:
    start: dtime | None
    end: dtime | None
    tz: ZoneInfo

    def active_at(self, dt: datetime) -> bool:
        if self.start is None or self.end is None:
            return False
        local = dt.astimezone(self.tz).time()
        if self.start == self.end:
            return False
        if self.start < self.end:
            return self.start <= local < self.end
        # Wraps midnight (e.g. 23:00 - 07:00)
        return local >= self.start or local < self.end


def parse_quiet_hours(raw: Any, tz_name: str) -> QuietHours:
    tz = ZoneInfo(tz_name)
    if not isinstance(raw, dict):
        return QuietHours(None, None, tz)
    start = _parse_hhmm(raw.get("start"))
    end = _parse_hhmm(raw.get("end"))
    return QuietHours(start, end, tz)


def _parse_hhmm(val: Any) -> dtime | None:
    if not val:
        return None
    if isinstance(val, dtime):
        return val
    s = str(val).strip()
    if not s:
        return None
    try:
        h, m = s.split(":")
        return dtime(int(h), int(m))
    except (ValueError, IndexError):
        raise SystemExit(
            f"config.yaml: quiet_hours expects 'HH:MM', got {val!r}"
        )


def should_alert(
    product: dict[str, Any],
    quiet_hours: QuietHours,
    now: datetime | None = None,
) -> bool:
    """Combined gate: mute + quiet-hours + tier."""
    if is_muted(product):
        return False
    tier = product_tier(product)
    if tier == MUST_HAVE:
        return True
    now = now or datetime.now(quiet_hours.tz)
    if quiet_hours.active_at(now):
        return False
    return True
