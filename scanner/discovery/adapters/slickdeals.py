"""Slickdeals discovery adapter (fetchable-plain, Phase-0 verdict; live-probed
2026-07-03 — parser targets confirmed against the real search page).

One polite GET of the deal search per refresh. Expired cards and junk titles
are dropped; a card without a parseable price yields no candidate (a price is
never fabricated). Zero parsed cards on HTTP 200 is PARSER_SUSPECT: the
standing query has hundreds of results, so an empty parse means drift.
"""
from __future__ import annotations

import html as html_lib
import re
from datetime import datetime, timezone
from typing import Any

from ... import confidence
from ...retailers import http as retailer_http
from ..candidates import CandidateDeal, junk_title, match_title
from .base import DiscoverySource

SEARCH_URL = "https://slickdeals.net/newsearch.php"
DEFAULT_QUERY = "pokemon tcg"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_CARD_RE = re.compile(r'<div class="dealCardListView([^"]*)" data-threadid="(\d+)"')
_TITLE_RE = re.compile(r'class="dealCardListView__title[^"]*"[^>]*title="([^"]+)"')
_PRICE_RE = re.compile(r'dealCardListView__finalPrice" title="\$?([\d,]+(?:\.\d+)?)"')
_STORE_RE = re.compile(r'dealCardListView__store"[^>]*>([^<]+)<')
_HREF_RE = re.compile(r'<a href="(/f/[^"?]+)')
_TITLE_PRICE_RE = re.compile(r"\$(\d[\d,]*\.\d{2})")


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _card_price(title: str, final_price_raw: str) -> float | None:
    """Displayed finalPrice is rounded ('$50' for a $49.99 deal); prefer the
    precise figure the deal author put in the title when it agrees.

    Titles often carry several figures ('Reg. $50.49, now $49.99'); take the
    one CLOSEST to the displayed price, later-wins on ties (deal price is
    conventionally stated last)."""
    final_price = _to_float(final_price_raw)
    precise = [p for m in _TITLE_PRICE_RE.finditer(title)
               for p in [_to_float(m.group(1))] if p is not None]
    if final_price is None:
        return precise[-1] if len(precise) == 1 else None
    agreeing = [p for p in precise if abs(p - final_price) <= 1.0]
    if agreeing:
        return min(reversed(agreeing), key=lambda p: abs(p - final_price))
    return final_price


def parse_search_html(
    text: str, catalog: dict, set_watch: list[str], seen_at: str,
) -> tuple[list[CandidateDeal], int]:
    """(candidates, cards_found). cards_found=0 on a 200 page means drift."""
    matches = list(_CARD_RE.finditer(text))
    candidates: list[CandidateDeal] = []
    for i, m in enumerate(matches):
        if "--expired" in m.group(1):
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[m.start():end]
        title_m = _TITLE_RE.search(chunk)
        price_m = _PRICE_RE.search(chunk)
        href_m = _HREF_RE.search(chunk)
        if not (title_m and price_m and href_m):
            continue                      # no price/link = no candidate, ever
        title = html_lib.unescape(title_m.group(1))
        if junk_title(title):
            continue
        price = _card_price(title, price_m.group(1))
        if price is None or price <= 0:
            continue
        store_m = _STORE_RE.search(chunk)
        product_key, matched_set = match_title(title, catalog, set_watch)
        # unescape BEFORE stripping the query: an entity like &#63; must not
        # decode back into a '?' after the strip already ran
        href = html_lib.unescape(href_m.group(1)).split("?")[0].split('"')[0]
        candidates.append(CandidateDeal(
            source="slickdeals",
            listing_id=m.group(2),
            item_name=title,
            price=price,
            shipping=None,
            url="https://slickdeals.net" + href,
            retailer=html_lib.unescape(store_m.group(1)).strip() if store_m else "",
            seen_at=seen_at,
            evidence_excerpt=f"{title} | ${price_m.group(1)}"[:200],
            matched_product_key=product_key,
            matched_set=matched_set,
        ))
    return candidates, len(matches)


class Slickdeals(DiscoverySource):
    slug = "slickdeals"
    min_interval_seconds = 900

    def discover(self, cfg: Any, catalog: dict, set_watch: list[str],
                 **kwargs: Any) -> list[CandidateDeal]:
        http_get = kwargs.get("http_get") or retailer_http.get
        try:
            resp = http_get(
                SEARCH_URL,
                retailer="disc:slickdeals",
                params={"q": DEFAULT_QUERY, "searcharea": "deals", "searchin": "first"},
                headers={"User-Agent": _UA, "Accept": "text/html"},
                timeout=25,
            )
        except Exception as exc:
            self._set_state(confidence.DEGRADED, retailer_http._redact_query_strings(
                str(exc) or exc.__class__.__name__)[:200])
            return []
        status = getattr(resp, "status_code", 200)
        if status in (403, 429):
            self._set_state(confidence.BLOCKED, f"HTTP {status}")
            return []
        if status != 200:
            self._set_state(confidence.DEGRADED, f"HTTP {status}")
            return []
        seen_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        candidates, cards_found = parse_search_html(
            getattr(resp, "text", "") or "", catalog, set_watch, seen_at)
        if cards_found == 0:
            self._set_state(confidence.PARSER_SUSPECT,
                            "HTTP 200 but no deal cards parsed for the standing query")
            return []
        self._set_state(confidence.WORKING,
                        f"{len(candidates)} candidates from {cards_found} cards")
        return candidates
