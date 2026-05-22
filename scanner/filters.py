"""Price-based alert filters.

Two complementary controls:

1. Global `price_filter.only_at_or_near_msrp` (with `msrp_multiplier`).
   When enabled, an alert is dropped if its listed price exceeds
   `msrp * multiplier`. This kills the scalper-tier resell noise that
   shows up on third-party marketplace listings within retailer sites.

2. Per-product `max_price: "$X"` ceiling. When set, an alert is dropped
   if listed price exceeds the ceiling. Useful for low-volume sets the
   user is willing to pay over MSRP for but not unlimited (e.g.,
   willing to grab a 151 ETB at $59 but not $80).

If we can't parse a listed price out of the retailer response, the
filter abstains — better to send the alert than to swallow it because
we couldn't read the price.

This module sits alongside scanner.priority; both filters run before
the dedupe check in scanner.main."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PriceFilter:
    only_at_or_near_msrp: bool = False
    msrp_multiplier: float = 1.10  # default: allow up to 10% over MSRP


def parse_price_filter(raw: Any) -> PriceFilter:
    if not isinstance(raw, dict):
        return PriceFilter()
    try:
        mult = float(raw.get("msrp_multiplier", 1.10))
    except (TypeError, ValueError):
        raise SystemExit(
            f"config.yaml: price_filter.msrp_multiplier must be a number, "
            f"got {raw.get('msrp_multiplier')!r}"
        )
    if mult <= 0:
        raise SystemExit("config.yaml: price_filter.msrp_multiplier must be > 0")
    return PriceFilter(
        only_at_or_near_msrp=bool(raw.get("only_at_or_near_msrp", False)),
        msrp_multiplier=mult,
    )


def _to_dollars(price: str) -> float | None:
    if not price:
        return None
    s = price.strip().lstrip("$").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def passes(
    product: dict[str, Any],
    listed_price: str,
    pf: PriceFilter,
) -> bool:
    """Apply the configured price filters. Returns True if the alert is allowed.

    - Listed price unparseable      -> True (abstain, send alert)
    - max_price set + listed > cap  -> False
    - only-at-MSRP on + listed > msrp * multiplier -> False
    - Otherwise                     -> True
    """
    listed = _to_dollars(listed_price)
    if listed is None:
        return True

    max_price = _to_dollars(str(product.get("max_price", "")))
    if max_price is not None and listed > max_price:
        return False

    if pf.only_at_or_near_msrp:
        msrp = _to_dollars(str(product.get("msrp", "")))
        if msrp is not None and listed > msrp * pf.msrp_multiplier:
            return False

    return True
