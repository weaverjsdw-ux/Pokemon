"""eBay Browse active-ask source: median + floor + matched count.

Ask prices are context and corroboration - kind=ACTIVE_ASK is load-bearing (an
ask-derived comp can never mint a STEAL). Degrades to not_configured while the
operator's eBay developer keyset is pending (docs/poke/ebay-keyset-setup.md).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from .. import resale
from .model import ACTIVE_ASK, CompSourceQuote, EbayAsk


class EbayAskSource:
    def __init__(self, cfg: Any, client: Any = None) -> None:
        if client is not None:
            self.client = client
        elif cfg is not None and resale.auth_configured(cfg):
            self.client = resale.EbayResaleClient.from_config(cfg)
        else:
            self.client = None

    def fetch(self, product_key: str, product: dict, checked_at: int) -> EbayAsk:
        query = resale.product_query(product)
        url = resale.ebay_search_web_url(query)
        fetched_at = datetime.fromtimestamp(checked_at).isoformat(timespec="seconds")

        def quote(status, price=None, sample=None, detail="", excerpt=""):
            return EbayAsk(CompSourceQuote("ebay_api", ACTIVE_ASK, status, price, url,
                                           fetched_at, sample_size=sample, detail=detail,
                                           raw_excerpt=excerpt))

        if self.client is None:
            return quote("not_configured",
                         detail="eBay Browse keyset not configured "
                                "(docs/poke/ebay-keyset-setup.md)")
        try:
            payload = self.client.search_payload(product)
        except resale.ResaleAuthMissing as exc:
            return quote("not_configured", detail=str(exc))
        except requests.RequestException as exc:
            return quote("error", detail=resale._safe_detail(str(exc)))
        prices = resale.matched_prices(product, payload)
        if not prices:
            return quote("no_match", detail="no matched active listings")
        median = resale._quantile(prices, 0.5)
        return EbayAsk(
            CompSourceQuote("ebay_api", ACTIVE_ASK, "ok", median, url, fetched_at,
                            sample_size=len(prices),
                            raw_excerpt=f"{len(prices)} matched active listings; "
                                        f"floor ${prices[0]:.2f}"),
            floor=prices[0], count=len(prices))
