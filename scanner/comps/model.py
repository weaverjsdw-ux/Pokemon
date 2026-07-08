"""In-house comp model: normalized source quotes + deterministic confidence.

Pure - no I/O, no network, no clock. Normative contract:
docs/superpowers/specs/2026-07-02-buyable-deal-pipeline-design.md section 4.
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import resale

SOLD_DERIVED = "sold_derived"
ACTIVE_ASK = "active_ask"
VALIDATOR = "validator"
HIGH_PREMIUM_RATIO = 4.0  # mirrors resale.HIGH_PREMIUM_RATIO; kept per Phase-0 closure
ASK_MIN_SAMPLE = 3        # ask-only comps need at least this many matched listings

QUOTE_STATUSES = {"ok", "no_match", "blocked", "error", "not_configured", "skipped"}


@dataclass(frozen=True)
class CompSourceQuote:
    source: str            # "tcgplayer" | "pricecharting" | "ebay_api" | "ppt"
    kind: str              # SOLD_DERIVED | ACTIVE_ASK | VALIDATOR
    status: str            # QUOTE_STATUSES
    price: float | None
    url: str               # exact page/search URL fetched (attribution)
    fetched_at: str        # ISO datetime
    sample_size: int | None = None
    detail: str = ""
    raw_excerpt: str = ""


@dataclass(frozen=True)
class EbayAsk:
    quote: CompSourceQuote
    floor: float | None = None
    count: int | None = None


@dataclass(frozen=True)
class NormalizedComp:
    item_key: str
    comp: float | None
    comp_basis: str
    confidence: str          # high | medium | low | unknown
    confidence_reason: str
    sources: tuple[CompSourceQuote, ...]
    ebay_floor: float | None
    ebay_active_count: int | None
    spread_pct: float | None
    captured_at: str         # ISO date
    stale: bool = False


def _ok(quote: CompSourceQuote | None) -> bool:
    return bool(quote and quote.status == "ok" and quote.price and quote.price > 0)


def _spread(a: float, b: float) -> float:
    return abs(a - b) / min(a, b) * 100.0


def _premium_capped(comp: float, msrp: float | None) -> bool:
    return bool(msrp and msrp > 0 and comp / msrp >= HIGH_PREMIUM_RATIO)


def resolve(
    item_key: str,
    msrp: float | None,
    tcg: CompSourceQuote | None,
    pc: CompSourceQuote | None,
    ebay: EbayAsk | None,
    captured_at: str,
    *,
    tolerance_pct: float = 20.0,
    floor_sanity_pct: float = 50.0,
    allow_ask_only: bool = True,
) -> NormalizedComp:
    """Spec 4.3 precedence table. UNKNOWN means comp None - never invent a number.

    ``allow_ask_only`` (default ``True``, preserving the sealed/discovery contract):
    when ``False`` an ask-only source set (no sold-derived quote) can NEVER become the
    comp — it degrades to no-comp with the ask retained in ``sources`` as context. The
    raw asset path (``poke_api.sources.resolve_raw_comp``) passes ``False`` so a raw
    single is never priced off active asks alone (D.5 policy)."""
    sources = tuple(q for q in (tcg, pc, ebay.quote if ebay else None) if q is not None)
    floor = ebay.floor if ebay else None
    count = ebay.count if ebay else None
    e_ok = ebay is not None and _ok(ebay.quote)

    def build(comp, basis, confidence, reason, spread=None):
        return NormalizedComp(
            item_key=item_key, comp=comp, comp_basis=basis, confidence=confidence,
            confidence_reason=reason, sources=sources, ebay_floor=floor,
            ebay_active_count=count, spread_pct=spread, captured_at=captured_at,
        )

    if _ok(tcg) and _ok(pc):
        spread = _spread(tcg.price, pc.price)
        comp = min(tcg.price, pc.price)
        premium = _premium_capped(comp, msrp)
        if spread <= tolerance_pct:
            basis = f"min(tcgplayer,pricecharting) agree@{tolerance_pct:g}%"
            if premium:
                return build(comp, basis, "low",
                             f"high_premium: comp >= {HIGH_PREMIUM_RATIO:g}x MSRP", spread)
            if floor is None or floor >= comp * (floor_sanity_pct / 100.0):
                return build(comp, basis, "high",
                             f"two sold-derived sources agree within {tolerance_pct:g}%", spread)
            return build(comp, basis, "medium",
                         f"floor_below_comp: eBay floor ${floor:.2f} is under "
                         f"{floor_sanity_pct:g}% of comp", spread)
        basis = f"min(tcgplayer,pricecharting) spread {spread:.0f}%"
        if premium:
            return build(comp, basis, "low",
                         f"high_premium: comp >= {HIGH_PREMIUM_RATIO:g}x MSRP", spread)
        return build(comp, basis, "medium",
                     f"source_spread: sold-derived sources disagree by {spread:.0f}%", spread)

    sold = tcg if _ok(tcg) else pc if _ok(pc) else None
    if sold is not None:
        comp = sold.price
        if _premium_capped(comp, msrp):
            return build(comp, f"{sold.source} uncorroborated", "low",
                         f"high_premium: comp >= {HIGH_PREMIUM_RATIO:g}x MSRP")
        if e_ok and _spread(comp, ebay.quote.price) <= tolerance_pct:
            return build(comp, f"{sold.source} corroborated by ebay ask median", "medium",
                         "single sold-derived source, ask-side corroboration")
        return build(comp, f"{sold.source} uncorroborated", "low",
                     "single sold-derived source, no corroboration")

    if e_ok and (count or 0) >= ASK_MIN_SAMPLE:
        if allow_ask_only:
            return build(ebay.quote.price, f"ebay active_ask median (n={count})", "low",
                         "ask-basis only: median of active fixed-price listings, not sold comps")
        return build(None, "none", "unknown",
                     "ask-only: active listings are context, not a comp (no sold-derived source)")

    return build(None, "none", "unknown", "no usable source; no comp invented")


_EXACT_PC_PREFIX = "https://www.pricecharting.com/game/"


def _exact_source_url(n: NormalizedComp) -> str:
    """Exact-product attribution URL, or '' - the sweep's verified gate keys on this."""
    for quote in n.sources:
        if quote.status != "ok":
            continue
        if quote.source in ("tcgplayer", "tcgcsv") and quote.url:
            return quote.url                       # product page (tcgplayer) / prices endpoint (tcgcsv)
        if quote.source == "pricecharting" and quote.url.startswith(_EXACT_PC_PREFIX):
            return quote.url
    return ""


def _flags(n: NormalizedComp) -> list[str]:
    flags = []
    for marker in ("floor_below_comp", "source_spread", "high_premium"):
        if marker in n.confidence_reason:
            flags.append(marker)
    if "active_ask" in n.comp_basis:
        flags.append("asking_price")
    return flags


def to_legacy_row(n: NormalizedComp, product_key: str, product: dict, checked_at: int) -> dict:
    """Emit the quote-dict shape the existing pipeline consumes (resale.annotate_quote
    superset). market.comp_from_row and sweep._provenance read this unchanged."""
    query = resale.product_query(product)
    base = {
        "productKey": product_key,
        "source": "InHouse comp engine",
        "basis": n.comp_basis,
        "query": query,
        "checkedAt": checked_at,
        "compBasis": n.comp_basis,
        "ebayFloor": n.ebay_floor,
        "ebayActiveCount": n.ebay_active_count,
        "sources": [
            {"source": q.source, "kind": q.kind, "status": q.status, "price": q.price,
             "url": q.url, "fetchedAt": q.fetched_at, "detail": q.detail}
            for q in n.sources
        ],
    }
    if n.comp is None:
        return base | {
            "status": "no_matches", "estimate": "", "low": "", "high": "",
            "sampleSize": 0, "url": resale.ebay_search_web_url(query),
            "detail": n.confidence_reason, "confidence": "none",
            "confidenceLabel": resale.CONFIDENCE_LABELS["none"],
            "confidenceReason": n.confidence_reason, "premiumRatio": None,
            "flags": _flags(n), "needsVerification": False, "asterisk": False,
        }
    money = resale._money(n.comp)
    ok_sold = [q.price for q in n.sources
               if q.status == "ok" and q.kind == SOLD_DERIVED and q.price]
    row = base | {
        "status": "ok",
        "estimate": money,
        "low": resale._money(min(ok_sold)) if len(ok_sold) >= 2 else money,
        "high": resale._money(max(ok_sold)) if len(ok_sold) >= 2 else money,
        "sampleSize": n.ebay_active_count if "active_ask" in n.comp_basis else 0,
        "url": _exact_source_url(n) or resale.ebay_search_web_url(query),
        "detail": n.confidence_reason,
        "confidence": n.confidence,
        "confidenceLabel": resale.CONFIDENCE_LABELS.get(n.confidence,
                                                        resale.CONFIDENCE_LABELS["low"]),
        "confidenceReason": n.confidence_reason,
        "premiumRatio": resale._premium_ratio(product, money),
        "flags": _flags(n),
        "needsVerification": n.confidence == "low",
        "asterisk": n.confidence == "low",
    }
    exact = _exact_source_url(n)
    if exact and n.confidence in {"high", "medium"}:
        row["sourceUrl"] = exact
    return row
