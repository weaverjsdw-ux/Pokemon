"""eBay Browse discovery adapter — the underpriced-active-listing lane.

Keyset-gated: without configured eBay credentials it reports NEEDS_API_KEY
and yields nothing (the pipeline stays honest about why). With credentials it
runs one Browse search per watched set per refresh, reusing the existing
resale client machinery — no duplicate auth or parsing stack.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from ... import confidence, resale
from ...retailers import http as retailer_http
from ..candidates import CandidateDeal, junk_title, match_title, stable_listing_id
from .base import DiscoverySource


def _shipping(item: dict) -> float | None:
    costs = [
        resale._amount((opt.get("shippingCost") or {}).get("value"))
        for opt in item.get("shippingOptions") or []
        if isinstance(opt, dict)
    ]
    costs = [c for c in costs if c is not None]
    return min(costs) if costs else None  # option order is not cheapest-first


def candidates_from_payload(
    payload: dict, catalog: dict, set_watch: list[str], seen_at: str,
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
        if not url.startswith(("https://", "http://")):
            continue                      # a buy link is http(s) or it is nothing
        # Ring resolution comes from the TITLE only. Browse fuzzy-matches
        # aggressively, so the query's set name must never be stamped onto an
        # unmatched item — that would smuggle Ring-3 wildcards past the
        # min_alert_confidence gate as fake Ring-2 matches.
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
            matched_set=matched_set,
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
        saw_summaries_key = False
        for set_name in set_watch:
            query = f"Pokemon TCG {set_name} sealed"
            try:  # never-raise contract: ANY per-query failure degrades, not crashes
                payload = search_fn(query)
                if isinstance(payload, dict) and "itemSummaries" in payload:
                    saw_summaries_key = True
                out.extend(candidates_from_payload(
                    payload if isinstance(payload, dict) else {},
                    catalog, set_watch, seen_at))
            except Exception as exc:
                errors.append(retailer_http._redact_query_strings(
                    str(exc) or exc.__class__.__name__)[:120])
                continue
        if errors:
            self._set_state(
                confidence.DEGRADED,
                f"{len(errors)}/{len(set_watch)} set queries failed "
                f"({len(out)} candidates): " + "; ".join(errors)[:160])
        elif set_watch and not saw_summaries_key:
            # every query answered but none carried the itemSummaries key:
            # Browse schema drift, not a legitimately empty result set
            self._set_state(confidence.PARSER_SUSPECT,
                            "no query returned an itemSummaries key; "
                            "Browse response schema may have drifted")
        else:
            self._set_state(confidence.WORKING,
                            f"{len(out)} candidates from {len(set_watch)} set queries")
        return out
