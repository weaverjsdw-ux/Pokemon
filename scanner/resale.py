"""Stale-aware resale price estimates for sealed products."""
from __future__ import annotations

import base64
import html
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable
from urllib.parse import urlencode

import requests

DEFAULT_INTERVAL_SECONDS = 4 * 60 * 60
MIN_INTERVAL_SECONDS = 60 * 60
MEDIUM_CONFIDENCE_ACTIVE_SAMPLE_SIZE = 3
HIGH_CONFIDENCE_SOLD_SAMPLE_SIZE = 8
HIGH_PREMIUM_RATIO = 4.0
EBAY_SCOPE = "https://api.ebay.com/oauth/api_scope"
EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
EBAY_WEB_SEARCH_URL = "https://www.ebay.com/sch/i.html"
PRICECHARTING_SEARCH_URL = "https://www.pricecharting.com/search-products"
SOURCE_LABEL = "eBay Browse API"
PUBLIC_SOURCE_LABEL = "eBay public search"
PRICECHARTING_SOURCE_LABEL = "PriceCharting market fallback"
PUBLIC_FALLBACK_SOURCE_LABEL = "eBay public search / PriceCharting fallback"
# PokemonPriceTracker (TCGplayer market price) is a single-source daily market
# summary — same confidence class as the PriceCharting fallback, not a sold-comp sample.
POKEMONPRICETRACKER_SOURCE_LABEL = "PokemonPriceTracker"
MARKET_SUMMARY_SOURCE_LABELS = (PRICECHARTING_SOURCE_LABEL, POKEMONPRICETRACKER_SOURCE_LABEL)
CONFIDENCE_LABELS = {
    "high": "High confidence",
    "medium": "Medium confidence",
    "low": "Low confidence",
    "none": "No estimate confidence",
}

GENERIC_QUERY_TOKENS = {"tcg", "the", "scarlet", "violet", "and", "sealed"}
NEGATIVE_TITLE_PARTS = (
    "box only",
    "empty box",
    "empty etb",
    "code card",
    "digital",
    "proxy",
    "japanese",
    "korean",
    "chinese",
    "case of",
    "sealed case",
    "display case",
    "lot of",
    "pack art",
    "sleeves only",
    "lego",
    "video game",
    "xbox",
    "playstation",
    "nintendo",
)


class ResaleAuthMissing(RuntimeError):
    """Raised when eBay auth is not configured."""


@dataclass(frozen=True)
class ResaleCredentials:
    token: str = ""
    client_id: str = ""
    client_secret: str = ""
    marketplace_id: str = "EBAY_US"

    @property
    def configured(self) -> bool:
        return bool(self.token or (self.client_id and self.client_secret))


def interval_seconds(value: int | None) -> int:
    try:
        raw = int(value or DEFAULT_INTERVAL_SECONDS)
    except (TypeError, ValueError):
        raw = DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, raw)


def credentials_from_config(cfg: Any) -> ResaleCredentials:
    return ResaleCredentials(
        token=str(
            getattr(cfg, "ebay_browse_api_token", "")
            or os.getenv("EBAY_BROWSE_API_TOKEN", "")
            or os.getenv("EBAY_OAUTH_TOKEN", "")
        ).strip(),
        client_id=str(
            getattr(cfg, "ebay_client_id", "") or os.getenv("EBAY_CLIENT_ID", "")
        ).strip(),
        client_secret=str(
            getattr(cfg, "ebay_client_secret", "") or os.getenv("EBAY_CLIENT_SECRET", "")
        ).strip(),
        marketplace_id=str(
            getattr(cfg, "ebay_marketplace_id", "") or os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US")
        ).strip()
        or "EBAY_US",
    )


def auth_configured(cfg: Any) -> bool:
    return credentials_from_config(cfg).configured


def product_query(product: dict[str, Any]) -> str:
    explicit = str(product.get("resale_query") or "").strip()
    if explicit:
        return explicit
    game = str(product.get("game") or product.get("brand") or "Pokemon TCG").strip()
    parts = [
        game,
        str(product.get("set") or "").strip(),
        str(product.get("type") or "").strip(),
        "sealed",
    ]
    return " ".join(part for part in parts if part).strip()


def product_family(product: dict[str, Any]) -> str:
    text = " ".join(
        str(product.get(field) or "") for field in ("game", "brand", "name", "resale_query")
    ).lower()
    if "magic" in text or "mtg" in text:
        return "magic"
    if "pokemon" in text or "pokémon" in text:
        return "pokemon"
    return ""


def ebay_search_web_url(query: str) -> str:
    params = urlencode(
        {
            "_nkw": query,
            "_sop": "12",
            "LH_BIN": "1",
            "LH_ItemCondition": "1000",
        }
    )
    return f"https://www.ebay.com/sch/i.html?{params}"


def _search_params(query: str) -> dict[str, str]:
    return {
        "_nkw": query,
        "_sop": "12",
        "LH_BIN": "1",
        "LH_ItemCondition": "1000",
    }


def _money(value: float | None) -> str:
    if value is None:
        return ""
    return f"${value:.2f}"


def _amount(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    cleaned = value.replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _premium_ratio(product: dict[str, Any], estimate: Any) -> float | None:
    estimate_amount = _amount(estimate)
    msrp_amount = _amount(product.get("msrp"))
    if estimate_amount is None or not msrp_amount or msrp_amount <= 0:
        return None
    return round(estimate_amount / msrp_amount, 2)


def _unique_flags(flags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for flag in flags:
        if flag in seen:
            continue
        seen.add(flag)
        result.append(flag)
    return result


def annotate_quote(product: dict[str, Any], quote: dict[str, Any]) -> dict[str, Any]:
    """Add source-confidence metadata used by the dashboard."""
    row = dict(quote)
    status = str(row.get("status") or "")
    if status != "ok":
        return row | {
            "confidence": "none",
            "confidenceLabel": CONFIDENCE_LABELS["none"],
            "confidenceReason": str(row.get("detail") or status or "No estimate."),
            "premiumRatio": None,
            "flags": [],
            "needsVerification": False,
            "asterisk": False,
        }

    source = str(row.get("source") or "")
    basis = str(row.get("basis") or "").lower()
    sample_size = _int_value(row.get("sampleSize"))
    ratio = _premium_ratio(product, row.get("estimate"))
    flags: list[str] = []
    reasons: list[str] = []

    if "active" in basis:
        flags.append("asking_price")
        reasons.append("active listing asks, not sold comps")
    if source == PUBLIC_SOURCE_LABEL:
        flags.append("public_ebay_search")
        reasons.append("public eBay page parsing")
    if source in MARKET_SUMMARY_SOURCE_LABELS:
        flags.append("single_source_summary")
        reasons.append("single-source market summary")
    if source not in MARKET_SUMMARY_SOURCE_LABELS and 0 < sample_size < MEDIUM_CONFIDENCE_ACTIVE_SAMPLE_SIZE:
        flags.append("thin_sample")
        reasons.append(f"{sample_size} matched result")
    if ratio is not None and ratio >= HIGH_PREMIUM_RATIO:
        flags.append("high_premium")
        reasons.append(f"{ratio:g}x MSRP")

    has_sold_comp_basis = "sold" in basis and source != PRICECHARTING_SOURCE_LABEL
    high_premium = "high_premium" in flags
    if has_sold_comp_basis and sample_size >= HIGH_CONFIDENCE_SOLD_SAMPLE_SIZE and not high_premium:
        confidence = "high"
    elif (
        source == SOURCE_LABEL
        and sample_size >= MEDIUM_CONFIDENCE_ACTIVE_SAMPLE_SIZE
        and not high_premium
    ):
        confidence = "medium"
    elif source in MARKET_SUMMARY_SOURCE_LABELS and not high_premium:
        confidence = "medium"
    else:
        confidence = "low"

    flags = _unique_flags(flags)
    needs_verification = confidence == "low" or high_premium
    return row | {
        "confidence": confidence,
        "confidenceLabel": CONFIDENCE_LABELS[confidence],
        "confidenceReason": " / ".join(reasons) or CONFIDENCE_LABELS[confidence],
        "premiumRatio": ratio,
        "flags": flags,
        "needsVerification": needs_verification,
        "asterisk": needs_verification,
    }


def _converted_amount(raw: Any) -> tuple[float | None, str]:
    if not isinstance(raw, dict):
        return None, ""
    currency = str(raw.get("currency") or "").upper()
    return _amount(raw.get("value")), currency


def _price_from_text(text: str) -> float | None:
    if " to " in text.lower():
        return None
    match = re.search(r"\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)", text)
    return _amount(match.group(1)) if match else None


def _listing_total(item: dict[str, Any]) -> float | None:
    price, currency = _converted_amount(item.get("price"))
    if price is None or (currency and currency != "USD"):
        return None
    shipping_total = 0.0
    for option in item.get("shippingOptions") or []:
        shipping, shipping_currency = _converted_amount(option.get("shippingCost"))
        if shipping is None:
            continue
        if shipping_currency and shipping_currency != "USD":
            continue
        shipping_total = shipping
        break
    return price + shipping_total


def _strip_tags(text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _tokens(text: str) -> set[str]:
    found = set(re.findall(r"[a-z0-9]+", text.lower()))
    if "etb" in found:
        found.update({"elite", "trainer", "box"})
    return found


def _required_tokens(product: dict[str, Any]) -> set[str]:
    source = str(
        product.get("resale_match")
        or product.get("name")
        or product_query(product)
    )
    tokens = _tokens(source) - GENERIC_QUERY_TOKENS
    if "etb" in str(product.get("type") or "").lower():
        tokens.update({"elite", "trainer", "box"})
    return tokens


def _title_allowed(product: dict[str, Any], item: dict[str, Any]) -> bool:
    title = str(item.get("title") or "")
    title_lower = title.lower()
    if any(part in title_lower for part in NEGATIVE_TITLE_PARTS):
        return False
    query = product_query(product).lower()
    if "pokemon center" in title_lower and "pokemon center" not in query:
        return False
    title_tokens = _tokens(title)
    family = product_family(product)
    if family == "magic" and not ({"magic", "gathering"} <= title_tokens or "mtg" in title_tokens):
        return False
    if family == "pokemon" and "pokemon" not in title_tokens:
        return False
    return _required_tokens(product).issubset(title_tokens)


def public_search_quotes_from_html(
    product_key: str,
    product: dict[str, Any],
    body: str,
    checked_at: int,
) -> dict[str, Any]:
    query = product_query(product)
    items: list[dict[str, Any]] = []
    blocks = re.findall(
        r"<li\b[^>]*class=\"[^\"]*\bs-item\b[^\"]*\"[\s\S]*?</li>",
        body,
        flags=re.I,
    )
    if not blocks:
        blocks = re.findall(
            r"<div\b[^>]*class=\"[^\"]*\bs-item\b[^\"]*\"[\s\S]*?</div>\s*</div>",
            body,
            flags=re.I,
        )
    for block in blocks:
        title_match = re.search(
            r"class=\"[^\"]*\bs-item__title\b[^\"]*\"[^>]*>([\s\S]*?)</(?:div|span)>",
            block,
            flags=re.I,
        )
        price_match = re.search(
            r"class=\"[^\"]*\bs-item__price\b[^\"]*\"[^>]*>([\s\S]*?)</span>",
            block,
            flags=re.I,
        )
        if not (title_match and price_match):
            continue
        title = _strip_tags(title_match.group(1))
        price = _price_from_text(_strip_tags(price_match.group(1)))
        if not title or price is None:
            continue
        shipping = 0.0
        shipping_match = re.search(
            r"class=\"[^\"]*\bs-item__shipping[^\"]*\"[^>]*>([\s\S]*?)</span>",
            block,
            flags=re.I,
        )
        if shipping_match:
            shipping_text = _strip_tags(shipping_match.group(1))
            shipping = 0.0 if "free" in shipping_text.lower() else (_price_from_text(shipping_text) or 0.0)
        items.append(
            {
                "title": title,
                "price": {"value": f"{price:.2f}", "currency": "USD"},
                "shippingOptions": [
                    {"shippingCost": {"value": f"{shipping:.2f}", "currency": "USD"}}
                ],
            }
        )
    return quote_from_search_payload(
        product_key,
        product,
        {"itemSummaries": items},
        checked_at,
        source=PUBLIC_SOURCE_LABEL,
        basis="active fixed-price asking median from public search",
    )


def pricecharting_quote_from_html(
    product_key: str,
    product: dict[str, Any],
    body: str,
    checked_at: int,
) -> dict[str, Any]:
    query = product_query(product)
    base = {
        "productKey": product_key,
        "source": PRICECHARTING_SOURCE_LABEL,
        "basis": "PriceCharting ungraded market summary",
        "query": query,
        "url": _pricecharting_search_url(query),
        "checkedAt": checked_at,
    }
    rows = re.findall(r"<tr\b[^>]*id=\"product-[^\"]+\"[\s\S]*?</tr>", body, flags=re.I)
    for row in rows:
        title_match = re.search(
            r"<td\b[^>]*class=\"[^\"]*\btitle\b[^\"]*\"[^>]*>([\s\S]*?)</td>",
            row,
            flags=re.I,
        )
        console_match = re.search(
            r"<td\b[^>]*class=\"[^\"]*\bconsole\b[^\"]*\"[^>]*>([\s\S]*?)</td>",
            row,
            flags=re.I,
        )
        price_match = re.search(
            r"<td\b[^>]*class=\"[^\"]*\bused_price\b[^\"]*\"[^>]*>[\s\S]*?"
            r"<span\b[^>]*class=\"[^\"]*\bjs-price\b[^\"]*\"[^>]*>([\s\S]*?)</span>",
            row,
            flags=re.I,
        )
        if not (title_match and price_match):
            continue
        title = " ".join(
            part
            for part in [
                _strip_tags(title_match.group(1)),
                _strip_tags(console_match.group(1)) if console_match else "",
            ]
            if part
        )
        price = _price_from_text(_strip_tags(price_match.group(1)))
        if not title or price is None:
            continue
        if not _title_allowed(product, {"title": title}):
            continue
        link_match = re.search(
            r"<a\b[^>]*href=\"([^\"]+)\"",
            title_match.group(1),
            flags=re.I,
        )
        url = (
            _absolute_pricecharting_url(html.unescape(link_match.group(1)))
            if link_match
            else base["url"]
        )
        estimate = _money(price)
        return annotate_quote(product, base | {
            "status": "ok",
            "estimate": estimate,
            "low": estimate,
            "high": estimate,
            "sampleSize": 1,
            "url": url,
            "detail": "PriceCharting ungraded market summary; used because eBay public search was blocked.",
        })
    return annotate_quote(product, base | {
        "status": "no_matches",
        "estimate": "",
        "low": "",
        "high": "",
        "sampleSize": 0,
        "detail": "No usable PriceCharting result matched this product.",
    })


def _pricecharting_search_url(query: str) -> str:
    return f"{PRICECHARTING_SEARCH_URL}?{urlencode({'q': query, 'type': 'prices'})}"


def _absolute_pricecharting_url(url: str) -> str:
    if url.startswith("https://"):
        return url
    if url.startswith("/"):
        return f"https://www.pricecharting.com{url}"
    return url


def _release_date(product: dict[str, Any]) -> date | None:
    raw = str(product.get("release_date") or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _market_unavailable_status(product: dict[str, Any], checked_at: int) -> tuple[str, str]:
    release_date = _release_date(product)
    if release_date and datetime.fromtimestamp(checked_at).date() < release_date:
        return (
            "not_released",
            f"MSRP only until release/preorder market data is available ({release_date.isoformat()}).",
        )
    return (
        "no_market",
        "No reliable resale market estimate yet; MSRP is the source of truth.",
    )


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(values) - 1)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (pos - lower)


def quote_from_search_payload(
    product_key: str,
    product: dict[str, Any],
    payload: dict[str, Any],
    checked_at: int,
    source: str = SOURCE_LABEL,
    basis: str = "active fixed-price asking median",
) -> dict[str, Any]:
    query = product_query(product)
    prices = [
        price
        for item in payload.get("itemSummaries") or []
        if isinstance(item, dict) and _title_allowed(product, item)
        for price in [_listing_total(item)]
        if price is not None
    ]
    prices.sort()
    base = {
        "productKey": product_key,
        "source": source,
        "basis": basis,
        "query": query,
        "url": ebay_search_web_url(query),
        "checkedAt": checked_at,
    }
    if not prices:
        return annotate_quote(product, base | {
            "status": "no_matches",
            "estimate": "",
            "low": "",
            "high": "",
            "sampleSize": 0,
            "detail": "No usable active eBay listings matched this product.",
        })
    median = _quantile(prices, 0.5)
    low = _quantile(prices, 0.25)
    high = _quantile(prices, 0.75)
    return annotate_quote(product, base | {
        "status": "ok",
        "estimate": _money(median),
        "low": _money(low),
        "high": _money(high),
        "sampleSize": len(prices),
        "detail": f"Median of {len(prices)} active fixed-price asking prices.",
    })


class EbayResaleClient:
    def __init__(
        self,
        credentials: ResaleCredentials,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.credentials = credentials
        self.session = session or requests.Session()
        self.clock = clock
        self._token = credentials.token
        self._token_expires_at = 0

    @classmethod
    def from_config(cls, cfg: Any) -> "EbayResaleClient":
        return cls(credentials_from_config(cfg))

    def _access_token(self) -> str:
        if self._token and int(self.clock()) < self._token_expires_at - 60:
            return self._token
        if self.credentials.token:
            return self.credentials.token
        if not (self.credentials.client_id and self.credentials.client_secret):
            raise ResaleAuthMissing("eBay API credentials are not configured.")

        raw = f"{self.credentials.client_id}:{self.credentials.client_secret}".encode("utf-8")
        basic = base64.b64encode(raw).decode("ascii")
        response = self.session.post(
            EBAY_TOKEN_URL,
            data={"grant_type": "client_credentials", "scope": EBAY_SCOPE},
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise RuntimeError("eBay token response did not include access_token.")
        self._token = token
        self._token_expires_at = int(self.clock()) + int(payload.get("expires_in") or 0)
        return token

    def estimate(self, product_key: str, product: dict[str, Any], checked_at: int) -> dict[str, Any]:
        query = product_query(product)
        response = self.session.get(
            EBAY_SEARCH_URL,
            params={
                "q": query,
                "limit": "50",
                "filter": "buyingOptions:{FIXED_PRICE},conditions:{1000},priceCurrency:USD",
            },
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "X-EBAY-C-MARKETPLACE-ID": self.credentials.marketplace_id,
            },
            timeout=20,
        )
        response.raise_for_status()
        return quote_from_search_payload(product_key, product, response.json(), checked_at)


class PublicEbaySearchClient:
    def __init__(
        self,
        session: requests.Session | None = None,
    ) -> None:
        self.session = session or requests.Session()

    @classmethod
    def from_config(cls, cfg: Any) -> "PublicEbaySearchClient":
        return cls()

    def estimate(self, product_key: str, product: dict[str, Any], checked_at: int) -> dict[str, Any]:
        query = product_query(product)
        response = self.session.get(
            EBAY_WEB_SEARCH_URL,
            params=_search_params(query),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0 Safari/537.36"
                )
            },
            timeout=20,
        )
        response.raise_for_status()
        return public_search_quotes_from_html(product_key, product, response.text, checked_at)


class PriceChartingSearchClient:
    def __init__(
        self,
        session: requests.Session | None = None,
    ) -> None:
        self.session = session or requests.Session()

    def estimate(self, product_key: str, product: dict[str, Any], checked_at: int) -> dict[str, Any]:
        query = product_query(product)
        response = self.session.get(
            PRICECHARTING_SEARCH_URL,
            params={"q": query, "type": "prices"},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0 Safari/537.36"
                )
            },
            timeout=20,
        )
        response.raise_for_status()
        return pricecharting_quote_from_html(product_key, product, response.text, checked_at)


class PublicFallbackResaleClient:
    def __init__(
        self,
        clients: list[PublicEbaySearchClient | PriceChartingSearchClient] | None = None,
    ) -> None:
        self.clients = clients or [PublicEbaySearchClient(), PriceChartingSearchClient()]

    @classmethod
    def from_config(cls, cfg: Any) -> "PublicFallbackResaleClient":
        return cls()

    def estimate(self, product_key: str, product: dict[str, Any], checked_at: int) -> dict[str, Any]:
        errors: list[str] = []
        saw_no_match = False
        for client in self.clients:
            try:
                quote = client.estimate(product_key, product, checked_at)
            except requests.RequestException as exc:
                errors.append(_safe_detail(str(exc)))
                continue
            if quote.get("status") == "ok":
                return quote
            if quote.get("status") == "no_matches":
                saw_no_match = True
            errors.append(str(quote.get("detail") or quote.get("status") or "no match"))
        if saw_no_match:
            status, detail = _market_unavailable_status(product, checked_at)
            return _status_row(
                product_key,
                product,
                status,
                detail,
                checked_at,
                PRICECHARTING_SOURCE_LABEL,
                "MSRP reference; resale market unavailable",
            )
        return _status_row(
            product_key,
            product,
            "error",
            " / ".join(errors[-2:]) or "No resale fallback returned a usable price.",
            checked_at,
            PRICECHARTING_SOURCE_LABEL,
            "fallback resale estimate",
        )


def resale_client_from_config(cfg: Any) -> EbayResaleClient | PublicFallbackResaleClient:
    if auth_configured(cfg):
        return EbayResaleClient.from_config(cfg)
    return PublicFallbackResaleClient.from_config(cfg)


class ResalePriceCache:
    def __init__(
        self,
        client_factory: Callable[
            [Any], EbayResaleClient | PublicFallbackResaleClient
        ] = resale_client_from_config,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client_factory = client_factory
        self.clock = clock
        self._lock = threading.Lock()
        self._quotes: dict[str, dict[str, Any]] = {}
        self._thread: threading.Thread | None = None
        self._last_refresh_at: int | None = None
        self._next_refresh_at: int | None = None

    def snapshot(self, cfg: Any) -> dict[str, Any]:
        interval = interval_seconds(getattr(cfg, "resale_price_interval_seconds", None))
        enabled = bool(getattr(cfg, "resale_price_enabled", True))
        has_auth = auth_configured(cfg)
        now = int(self.clock())
        with self._lock:
            quotes = {key: dict(value) for key, value in self._quotes.items()}
            running = bool(self._thread and self._thread.is_alive())
            last_refresh = self._last_refresh_at
            next_refresh = self._next_refresh_at

        products: dict[str, dict[str, Any]] = {}
        for key, product in getattr(cfg, "products", {}).items():
            row = quotes.get(key)
            if row:
                products[key] = row | {
                    "nextCheckAt": (row.get("checkedAt") or now) + interval,
                }
            elif not enabled:
                products[key] = _status_row(
                    key,
                    product,
                    "disabled",
                    "Resale pricing is disabled.",
                    source=SOURCE_LABEL if has_auth else PUBLIC_FALLBACK_SOURCE_LABEL,
                )
            else:
                products[key] = _status_row(
                    key,
                    product,
                    "pending",
                    "Waiting for the first resale refresh.",
                    source=SOURCE_LABEL if has_auth else PUBLIC_FALLBACK_SOURCE_LABEL,
                )
        confidence_counts = {"high": 0, "medium": 0, "low": 0, "none": 0}
        for row in products.values():
            confidence = str(row.get("confidence") or "none")
            confidence_counts[confidence if confidence in confidence_counts else "none"] += 1
        return {
            "enabled": enabled,
            "authSet": has_auth,
            "intervalSeconds": interval,
            "source": SOURCE_LABEL if has_auth else PUBLIC_FALLBACK_SOURCE_LABEL,
            "running": running,
            "lastRefreshAt": last_refresh,
            "nextRefreshAt": next_refresh,
            "confidenceCounts": confidence_counts,
            "products": products,
        }

    def refresh_due_async(self, cfg: Any) -> None:
        if not bool(getattr(cfg, "resale_price_enabled", True)):
            return
        interval = interval_seconds(getattr(cfg, "resale_price_interval_seconds", None))
        now = int(self.clock())
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            if self._next_refresh_at and now < self._next_refresh_at:
                return
            products = {key: dict(value) for key, value in getattr(cfg, "products", {}).items()}
            self._next_refresh_at = now + interval
            self._thread = threading.Thread(
                target=self._refresh,
                args=(cfg, products, interval),
                name="ebay-resale-prices",
                daemon=True,
            )
            self._thread.start()

    def _refresh(self, cfg: Any, products: dict[str, dict[str, Any]], interval: int) -> None:
        client = self.client_factory(cfg)
        source = SOURCE_LABEL if isinstance(client, EbayResaleClient) else PUBLIC_FALLBACK_SOURCE_LABEL
        basis = (
            "active fixed-price asking median"
            if isinstance(client, EbayResaleClient)
            else "public fallback resale estimate"
        )
        for key, product in products.items():
            checked_at = int(self.clock())
            try:
                row = client.estimate(key, product, checked_at)
            except ResaleAuthMissing as exc:
                row = _status_row(key, product, "needs_auth", str(exc), checked_at, source, basis)
            except requests.RequestException as exc:
                row = _status_row(key, product, "error", _safe_detail(str(exc)), checked_at, source, basis)
            except Exception as exc:
                row = _status_row(key, product, "error", _safe_detail(str(exc)), checked_at, source, basis)
            with self._lock:
                self._quotes[key] = row
            time.sleep(0.2)
        finished_at = int(self.clock())
        with self._lock:
            self._last_refresh_at = finished_at
            self._next_refresh_at = finished_at + interval


def _status_row(
    product_key: str,
    product: dict[str, Any],
    status: str,
    detail: str,
    checked_at: int | None = None,
    source: str = SOURCE_LABEL,
    basis: str = "active fixed-price asking median",
) -> dict[str, Any]:
    return {
        "productKey": product_key,
        "status": status,
        "source": source,
        "basis": basis,
        "query": product_query(product),
        "estimate": "",
        "low": "",
        "high": "",
        "sampleSize": 0,
        "checkedAt": checked_at,
        "nextCheckAt": None,
        "url": ebay_search_web_url(product_query(product)),
        "detail": detail,
        "confidence": "none",
        "confidenceLabel": CONFIDENCE_LABELS["none"],
        "confidenceReason": detail,
        "premiumRatio": None,
        "flags": [],
        "needsVerification": False,
        "asterisk": False,
    }


def _safe_detail(text: str) -> str:
    return re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?...", str(text))
