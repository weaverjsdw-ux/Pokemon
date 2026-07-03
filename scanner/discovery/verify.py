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

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlparse

from .. import health
from ..main import _price_to_float
from ..retailers import ALL as RETAILER_REGISTRY
from ..retailers import http as retailer_http
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


def _unverified(
    state: str,
    *,
    source: str,
    method: str,
    reason: str,
    expected_price: float | None,
    checked_at: str,
    stock_status: str = "unverifiable",
    evidence: str = "",
) -> StockVerification:
    return StockVerification(
        state=state, stock_status=stock_status, verified_price=None,
        expected_price=expected_price, price_matches=None, buy_url="",
        checked_at=checked_at, source=source, method=method,
        evidence=_clip(evidence or reason), degraded_reason=_clip(reason),
    )


def _blocked_or_unavailable(detail: str) -> str:
    return SOURCE_BLOCKED if ("403" in detail or "429" in detail) else PAGE_UNAVAILABLE


# Ordering for picking the most informative verification across retailers:
# positive stock first, then negative, then failures; price-bearing wins ties.
_STATUS_RANK = {"in_stock": 0, "limited": 1, "out_of_stock": 2,
                "unverifiable": 3, "unknown": 4}


def _rank(v: StockVerification) -> tuple[int, int]:
    return (_STATUS_RANK.get(v.stock_status, 9),
            0 if (v.verified_price or 0) > 0 else 1)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def verify_catalog_product(
    cfg: Any,
    product_key: str,
    product: dict,
    *,
    registry: dict | None = None,
    expected_price: float | None = None,
    checked_at: str = "",
    health_lookup: Callable[[str], dict | None] | None = None,
) -> StockVerification:
    """Verify a tracked catalog product via its enabled retailer adapters.

    Online-capable adapters only (store-based ones need corridor stores, which
    this context does not have — recorded honestly, never guessed around).
    Returns the most informative single verification; every degradation path
    lands in an explicit terminal state with a reason.
    """
    registry = RETAILER_REGISTRY if registry is None else registry
    health_lookup = health.get if health_lookup is None else health_lookup
    checked_at = checked_at or _now_iso()
    candidates: list[StockVerification] = []
    skipped_store_based: list[str] = []

    for slug, RClass in registry.items():
        rcfg = cfg.retailers.get(slug)
        if not rcfg or not getattr(rcfg, "enabled", False):
            continue
        if not getattr(RClass, "supported", True):
            continue
        fields = getattr(RClass, "product_id_fields", ())
        if not any(str(product.get(f) or "").strip() for f in fields):
            continue
        if not getattr(RClass, "online_only", False):
            skipped_store_based.append(slug)
            continue
        method = f"retailer_adapter:{slug}"
        try:
            results = list(RClass(api_key=rcfg.api_key).inventory(
                {product_key: product}, []))
        except Exception as exc:  # adapter failure = degraded state, not a crash
            detail = str(exc) or exc.__class__.__name__
            candidates.append(_unverified(
                _blocked_or_unavailable(detail), source=slug, method=method,
                reason=f"{slug} adapter error: {detail}",
                expected_price=expected_price, checked_at=checked_at))
            continue
        if results:
            candidates.extend(
                from_stock_result(r, source=slug, expected_price=expected_price,
                                  checked_at=checked_at)
                for r in results)
            continue
        # The adapter had an id to look up but yielded nothing: same canary
        # logic the scanner uses (HTTP-200-zero-rows means the parser broke).
        http_status = (health_lookup(slug) or {}).get("last_http_status")
        if http_status in (403, 429):
            state, why = SOURCE_BLOCKED, f"HTTP {http_status}; endpoint blocked or rate-limited"
        elif isinstance(http_status, int) and 500 <= http_status <= 599:
            state, why = PAGE_UNAVAILABLE, f"HTTP {http_status}; endpoint unavailable"
        else:
            state, why = PARSER_SUSPECT, (
                f"{slug} returned no inventory row for a product with an id"
                + (f" (last HTTP {http_status})" if http_status else ""))
        candidates.append(_unverified(
            state, source=slug, method=method, reason=why,
            expected_price=expected_price, checked_at=checked_at))

    if candidates:
        return min(candidates, key=_rank)
    reason = "no online-capable retailer adapter holds an id for this product"
    if skipped_store_based:
        reason += ("; store-based adapters skipped (no stores in this context): "
                   + ", ".join(skipped_store_based))
    return _unverified(UNKNOWN_NO_ALERT, source="", method="none", reason=reason,
                       expected_price=expected_price, checked_at=checked_at,
                       stock_status="unknown")


# ------------------------------------------------------------ page fallback

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# schema.org availability markers, JSON-LD or microdata. Conservative on
# purpose: no recognizable marker means PARSER_SUSPECT, never a guess.
_AVAILABILITY_RE = re.compile(
    r'(?:"availability"\s*:\s*"|itemprop="availability"[^>]*?(?:href|content)=")'
    r'(?:https?://schema\.org/)?(\w+)"')
_PRICE_RES = (
    re.compile(r'"price"\s*:\s*"?(\d[\d,]*\.?\d*)"?'),
    re.compile(r'itemprop="price"[^>]*?content="(\d[\d,]*\.?\d*)"'),
)
_AVAILABILITY_STOCK = {
    "InStock": "in_stock",
    "InStoreOnly": "in_stock",
    "OnlineOnly": "in_stock",
    "PreSale": "in_stock",
    "LimitedAvailability": "limited",
    "OutOfStock": "out_of_stock",
    "SoldOut": "out_of_stock",
    "Discontinued": "out_of_stock",
}


def _page_price(text: str) -> float | None:
    for pattern in _PRICE_RES:
        m = pattern.search(text)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def verify_page(
    url: str,
    *,
    expected_price: float | None = None,
    checked_at: str = "",
    http_get: Callable[..., Any] | None = None,
) -> StockVerification:
    """One polite GET of a merchant product page; parse schema.org signals.

    The buy page itself is the evidence source. Pages that resist parsing are
    PARSER_SUSPECT (honest), never guessed from bare numbers in prose.
    """
    checked_at = checked_at or _now_iso()
    source = urlparse(url).netloc
    get = http_get or retailer_http.get
    try:
        resp = get(url, headers={"User-Agent": _UA, "Accept": "text/html"}, timeout=20)
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        return _unverified(PAGE_UNAVAILABLE, source=source, method="page_fetch",
                           reason=f"transport failure: {detail}",
                           expected_price=expected_price, checked_at=checked_at)
    status_code = getattr(resp, "status_code", 200)
    if status_code in (403, 429):
        return _unverified(SOURCE_BLOCKED, source=source, method="page_fetch",
                           reason=f"HTTP {status_code}; page blocked or rate-limited",
                           expected_price=expected_price, checked_at=checked_at)
    if status_code != 200:
        return _unverified(PAGE_UNAVAILABLE, source=source, method="page_fetch",
                           reason=f"HTTP {status_code}",
                           expected_price=expected_price, checked_at=checked_at)

    text = getattr(resp, "text", "") or ""
    marker = _AVAILABILITY_RE.search(text)
    stock_status = _AVAILABILITY_STOCK.get(marker.group(1)) if marker else None
    if stock_status is None:
        return _unverified(PARSER_SUSPECT, source=source, method="page_fetch",
                           reason="no schema.org availability signal parsed; "
                                  "refusing to guess stock from page text",
                           expected_price=expected_price, checked_at=checked_at)

    price = _page_price(text)
    state, matches, reason = classify_stock(stock_status, price, expected_price)
    snippet_start = max(0, marker.start() - 80)
    evidence = _clip(f"availability={marker.group(1)} "
                     f"price={price if price is not None else 'n/a'} :: "
                     f"{text[snippet_start:marker.end() + 40]}")
    return StockVerification(
        state=state, stock_status=stock_status, verified_price=price,
        expected_price=expected_price, price_matches=matches, buy_url=url,
        checked_at=checked_at, source=source, method="page_fetch",
        evidence=evidence, degraded_reason=reason,
    )
