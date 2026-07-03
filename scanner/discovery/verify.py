"""Purchasability verifier: stock + price evidence from the actual buy page.

Every candidate ends in exactly one terminal state; only VERIFIED_BUYABLE may
ever alert, and the gate re-checks the evidence rather than trusting the
label. Comp confidence and buyability are deliberately separate signals — a
great comp with unknown stock never alerts, and verified stock with a weak
comp renders honestly instead of being hidden or overstated.

Verification uses sanctioned read-only paths only: the existing retailer
adapters (stock-query endpoints) and a single polite product-page GET. No
carts, no logins, no bot-wall evasion — the retailers/http.py contract
extends here verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..main import _price_to_float
from ..retailers.base import StockResult
from .schema import POSITIVE_STOCK, STOCK_STATUSES

# Terminal verification states. UNKNOWN_NO_ALERT is the catch-all: whatever
# could not be affirmatively verified lands there and never alerts.
VERIFIED_BUYABLE = "VERIFIED_BUYABLE"
OUT_OF_STOCK = "OUT_OF_STOCK"
PRICE_MISMATCH = "PRICE_MISMATCH"
PAGE_UNAVAILABLE = "PAGE_UNAVAILABLE"
PARSER_SUSPECT = "PARSER_SUSPECT"
SOURCE_BLOCKED = "SOURCE_BLOCKED"
UNKNOWN_NO_ALERT = "UNKNOWN_NO_ALERT"

TERMINAL_STATES = frozenset({
    VERIFIED_BUYABLE, OUT_OF_STOCK, PRICE_MISMATCH, PAGE_UNAVAILABLE,
    PARSER_SUSPECT, SOURCE_BLOCKED, UNKNOWN_NO_ALERT,
})
ALERTABLE_STATES = frozenset({VERIFIED_BUYABLE})

PRICE_MATCH_TOLERANCE_PCT = 5.0
EVIDENCE_MAX_CHARS = 300

# Retailer adapter status -> stock vocabulary (schema.STOCK_STATUSES).
_ADAPTER_STATUS = {
    "IN_STOCK": "in_stock",
    "ONLINE_IN_STOCK": "in_stock",
    "LIMITED": "limited",
    "OUT": "out_of_stock",
    "ONLINE_OUT": "out_of_stock",
}


class AlertGateError(Exception):
    """Raised when an alert is attempted without verified stock evidence."""


@dataclass(frozen=True)
class StockVerification:
    state: str                     # TERMINAL_STATES
    stock_status: str              # schema.STOCK_STATUSES
    verified_price: float | None   # price READ from the live check, never the ad
    expected_price: float | None   # candidate/MSRP expectation, when known
    price_matches: bool | None     # None when either price is missing
    buy_url: str                   # what a human clicks to buy
    checked_at: str                # ISO datetime of the live check
    source: str                    # retailer/source slug
    method: str                    # "retailer_adapter:<slug>" | "page_fetch" | "none"
    evidence: str                  # raw status/price text seen, <= 300 chars
    degraded_reason: str = ""      # honest cause when not VERIFIED_BUYABLE


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text[:EVIDENCE_MAX_CHARS]


def classify_stock(
    stock_status: str,
    verified_price: float | None,
    expected_price: float | None,
    tolerance_pct: float = PRICE_MATCH_TOLERANCE_PCT,
) -> tuple[str, bool | None, str]:
    """(terminal state, price_matches, degraded_reason) for an observed check.

    Pure decision table for outcomes where a page/API answered; transport
    failures (blocked/unavailable/unparseable) are classified by the adapters
    that saw them, not here.
    """
    if stock_status not in STOCK_STATUSES:
        raise ValueError(f"unknown stock_status {stock_status!r}")
    if stock_status == "out_of_stock":
        return OUT_OF_STOCK, None, ""
    if stock_status in POSITIVE_STOCK:
        if verified_price is None or verified_price <= 0:
            return (UNKNOWN_NO_ALERT, None,
                    "stock positive but no price read from the buy page")
        if expected_price is None or expected_price <= 0:
            return VERIFIED_BUYABLE, None, ""
        drift_pct = abs(verified_price - expected_price) / expected_price * 100.0
        if drift_pct <= tolerance_pct:
            return VERIFIED_BUYABLE, True, ""
        return (PRICE_MISMATCH, False,
                f"observed ${verified_price:.2f} differs from expected "
                f"${expected_price:.2f} by {drift_pct:.0f}%")
    return UNKNOWN_NO_ALERT, None, ""


def alert_allowed(v: StockVerification) -> bool:
    """THE alert gate. Re-checks evidence; never trusts the state label alone."""
    return (
        v.state in ALERTABLE_STATES
        and v.stock_status in POSITIVE_STOCK
        and v.verified_price is not None
        and v.verified_price > 0
        and bool(v.buy_url)
        and bool(v.evidence)
        and bool(v.checked_at)
    )


def assert_alertable(v: StockVerification) -> None:
    """Raise AlertGateError naming every failed condition. Alert emitters call
    this before sending anything — enforcement in code, not UI filtering."""
    problems: list[str] = []
    if v.state not in ALERTABLE_STATES:
        problems.append(f"state {v.state} is not alertable")
    if v.stock_status not in POSITIVE_STOCK:
        problems.append(f"stock_status {v.stock_status!r} is not verified-positive")
    if v.verified_price is None or v.verified_price <= 0:
        problems.append("no verified_price from the buy page")
    if not v.buy_url:
        problems.append("no buy_url")
    if not v.evidence:
        problems.append("no stock evidence")
    if not v.checked_at:
        problems.append("no checked_at timestamp")
    if problems:
        raise AlertGateError("alert refused: " + "; ".join(problems))


def from_stock_result(
    result: StockResult,
    *,
    source: str,
    expected_price: float | None = None,
    checked_at: str = "",
) -> StockVerification:
    """Translate a live retailer-adapter check into verification evidence."""
    stock_status = _ADAPTER_STATUS.get(result.status, "unknown")
    verified_price = _price_to_float(result.price)
    state, matches, reason = classify_stock(stock_status, verified_price, expected_price)
    if stock_status == "unknown":
        reason = f"unrecognized adapter status {result.status!r}"
    return StockVerification(
        state=state,
        stock_status=stock_status,
        verified_price=verified_price,
        expected_price=expected_price,
        price_matches=matches,
        buy_url=result.url,
        checked_at=checked_at,
        source=source,
        method=f"retailer_adapter:{source}",
        evidence=_clip(f"{source} adapter: status={result.status} "
                       f"price={result.price or 'n/a'}"),
        degraded_reason=reason,
    )
