"""TCGplayer product-page market price (sold-derived; the number PPT resells).

Acquisition path fixed by the Task-1 probe - see docs/poke/reference/tcgplayer-probe.md.
Plain requests only; 403/429 -> blocked (never evaded).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from .model import SOLD_DERIVED, CompSourceQuote

PRODUCT_URL = "https://www.tcgplayer.com/product/{ppt_id}"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)


class TcgPlayerSource:
    def __init__(self, cfg: Any, session: Any = None) -> None:
        self.session = session or requests.Session()

    def fetch(self, product_key: str, product: dict, checked_at: int) -> CompSourceQuote:
        fetched_at = datetime.fromtimestamp(checked_at).isoformat(timespec="seconds")
        ppt_id = str(product.get("ppt_id") or "").strip()
        if not ppt_id:
            return CompSourceQuote("tcgplayer", SOLD_DERIVED, "skipped", None, "",
                                   fetched_at,
                                   detail="no ppt_id (TCGplayer product id) mapped")
        url = PRODUCT_URL.format(ppt_id=ppt_id)
        try:
            resp = self.session.get(url, headers={"User-Agent": UA, "Accept": "text/html"},
                                    timeout=20)
        except requests.RequestException as exc:
            return CompSourceQuote("tcgplayer", SOLD_DERIVED, "error", None, url,
                                   fetched_at, detail=str(exc)[:200])
        if resp.status_code in (403, 429):
            return CompSourceQuote("tcgplayer", SOLD_DERIVED, "blocked", None, url,
                                   fetched_at, detail=f"HTTP {resp.status_code}")
        return CompSourceQuote(
            "tcgplayer", SOLD_DERIVED, "blocked", None, url, fetched_at,
            detail="acquisition unresolved (probe 2026-07-03): page serves no parseable "
                   "price to plain requests; see docs/poke/reference/tcgplayer-probe.md")
