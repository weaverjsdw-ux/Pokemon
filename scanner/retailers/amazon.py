"""Amazon (online-only).

Amazon is the hardest retailer to wire up cleanly. They run aggressive
anti-bot (Captcha, fingerprinting, IP-based shadow-bans) and prohibit
scraping in their ToS. We do not work around any of that.

What this adapter does instead:

  - Hits the public product PDP HTML (the URL anyone can paste into a
    browser, no login).
  - Reads only the visible in-stock marker that the rendered page would
    show to a human ("In Stock" / "Currently unavailable" / "Only X
    left in stock").
  - Backs off aggressively the moment we see a Captcha challenge — that
    is Amazon explicitly telling us to slow down. We respect it.
  - Counts as a SOFT signal: surface it but tag it. Cross-check before
    paying scalper prices.

Per docs/retailer-tos.md, this adapter is disabled by default. Enabling
is the user's call, and we will drop it if Amazon asks.

ID field: `amazon_asin` — 10-char alphanumeric, visible in the URL like
    https://www.amazon.com/dp/B0XXXXXXXX
"""
from __future__ import annotations

import re
import time
from typing import Any, Iterable

from .base import Retailer, StockResult, Store, variant_ids
from ..log import get_logger

log = get_logger(__name__)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_CAPTCHA_MARKERS = ("captcha-image", "Enter the characters you see below", "errors/validateCaptcha")
_IN_STOCK = re.compile(r"In Stock|Only \d+ left in stock", re.I)
_PRICE = re.compile(r'"priceToPay"\s*:\s*\{[^}]*"amount"\s*:\s*"?([\d.]+)"?', re.I)
_PRICE_ALT = re.compile(r'<span class="a-offscreen">\$([\d,.]+)</span>')


class Amazon(Retailer):
    name = "Amazon"
    slug = "amazon"
    online_only = True

    def find_stores(self, lat: float, lng: float, radius_miles: float) -> list[Store]:
        return []

    def check(
        self, products: dict[str, dict[str, Any]], stores: list[Store]
    ) -> Iterable[StockResult]:
        for key, prod in products.items():
            for asin in variant_ids(prod, "amazon_asin"):
                url = f"https://www.amazon.com/dp/{asin}"
                resp = self.http_get(
                    url,
                    headers={
                        "User-Agent": UA,
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                    timeout=25,
                )
                if resp is None or resp.status_code != 200:
                    continue
                text = resp.text or ""
                if any(marker in text for marker in _CAPTCHA_MARKERS):
                    log.warning("amazon captcha for asin=%s — backing off", asin)
                    # One CAPTCHA per pass disables the adapter for the rest
                    # of this pass; the HTTP client's health tracker takes
                    # over for longer-term disable if it keeps happening.
                    self.http._mark_failure(self.slug)  # type: ignore[attr-defined]
                    return
                if not _IN_STOCK.search(text):
                    continue
                price = ""
                m = _PRICE.search(text) or _PRICE_ALT.search(text)
                if m:
                    try:
                        amount = float(m.group(1).replace(",", ""))
                        price = f"${amount:.2f}"
                    except ValueError:
                        pass
                yield StockResult(
                    store=None,
                    product_key=key,
                    product_name=prod.get("name", key) + " (Amazon — soft signal)",
                    status="ONLINE_IN_STOCK",
                    url=url,
                    price=price,
                )
                time.sleep(1.0)  # extra polite on Amazon
