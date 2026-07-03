"""eBay Browse discovery adapter — the underpriced-active-listing lane.

Keyset-gated: without configured eBay credentials it reports NEEDS_API_KEY
and yields nothing (the pipeline stays honest about why). With credentials it
runs one Browse search per watched set per refresh, reusing the existing
resale client machinery — no duplicate auth or parsing stack.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import requests

from ... import confidence, resale
from ..candidates import CandidateDeal, junk_title, match_title, stable_listing_id
from .base import DiscoverySource


def _shipping(item: dict) -> float | None:
    options = item.get("shippingOptions") or []
    if not options:
        return None
    return resale._amount((options[0].get("shippingCost") or {}).get("value"))


def candidates_from_payload(
    payload: dict, query_set: str, catalog: dict, set_watch: list[str], seen_at: str,
) -> list[CandidateDeal]:
    out: list[CandidateDeal] = []
    for item in payload.get("itemSummaries") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        if not title or junk_title(title):
            continue
        price = resale._amount((item.get("price") or {}).get("value"))
        if price is None or price <= 0:
            continue                      # no price, no candidate — never invented
        url = str(item.get("itemWebUrl") or "")
        if not url:
            continue                      # a candidate without a buy link is useless
        product_key, matched_set = match_title(title, catalog, set_watch)
        out.append(CandidateDeal(
            source="ebay_browse",
            listing_id=str(item.get("itemId") or "") or stable_listing_id(url),
            item_name=title,
            price=price,
            shipping=_shipping(item),
            url=url,
            retailer="eBay",
            seen_at=seen_at,
            evidence_excerpt=f"{title} | ${price:.2f}"[:200],
            matched_product_key=product_key,
            matched_set=matched_set or query_set,
        ))
    return out


class EbayBrowse(DiscoverySource):
    slug = "ebay_browse"
    min_interval_seconds = 300
    requires = "ebay_keyset"

    def discover(self, cfg: Any, catalog: dict, set_watch: list[str],
                 **kwargs: Any) -> list[CandidateDeal]:
        search_fn: Callable[[str], dict] | None = kwargs.get("search_fn")
        if search_fn is None:
            if not resale.auth_configured(cfg):
                self._set_state(confidence.NEEDS_API_KEY,
                                "eBay keyset not provisioned; adapter idle")
                return []
            client = resale.EbayResaleClient.from_config(cfg)

            def search_fn(query: str) -> dict:
                return client.search_payload({"resale_query": query})

        seen_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out: list[CandidateDeal] = []
        errors: list[str] = []
        for set_name in set_watch:
            query = f"Pokemon TCG {set_name} sealed"
            try:
                payload = search_fn(query)
            except requests.RequestException as exc:
                errors.append((str(exc) or exc.__class__.__name__)[:120])
                continue
            out.extend(candidates_from_payload(
                payload, set_name, catalog, set_watch, seen_at))
        if errors and not out:
            self._set_state(confidence.DEGRADED, "; ".join(errors)[:200])
        else:
            self._set_state(confidence.WORKING,
                            f"{len(out)} candidates from {len(set_watch)} set queries"
                            + (f"; {len(errors)} query errors" if errors else ""))
        return out
