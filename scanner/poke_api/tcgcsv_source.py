"""TCGCSV reference adapter — turns the free TCGplayer-market mirror into a CompSourceQuote.

TCGCSV is a REFERENCE source (TCGplayer lineage == PPT), NOT independent of PPT. This
adapter fills the dead SEALED ``tcg`` slot in ``CompEngine`` (its number lifts confidence
via the existing tcg+pc agreement path) and supplies a raw-asset REFERENCE quote that is
recorded external-footing but never slotted into the raw independent resolver (spec §9).
0 PPT credits by construction (never constructs a PPT client). Resolves by EXACT
tcgplayer_id + tcgcsv_group_id + optional exact subTypeName; any miss is an honest status,
never a guess. A source bug never raises into a caller (honest degrade)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from ..comps.model import SOLD_DERIVED, CompSourceQuote
from . import tcgcsv as tcgcsv_mod

PRICES_URL = "https://tcgcsv.com/tcgplayer/3/{group_id}/prices"


def _quote(status: str, price: float | None, url: str, checked_at: int,
           detail: str) -> CompSourceQuote:
    fetched_at = datetime.fromtimestamp(int(checked_at)).isoformat(timespec="seconds")
    return CompSourceQuote("tcgcsv", SOLD_DERIVED, status, price, url, fetched_at,
                           detail=detail)


def _resolve(product_id_raw: Any, group_id_raw: Any, subtype: Any, checked_at: int,
             fetch_prices: Callable[[int], list[dict]]) -> CompSourceQuote:
    """Shared exact-identity resolve for both sealed products and raw assets."""
    product_id_s = str(product_id_raw or "").strip()
    group_id_s = str(group_id_raw or "").strip()
    if not product_id_s or not group_id_s:
        return _quote("skipped", None, "", checked_at,
                      "no tcgplayer_id / tcgcsv_group_id mapped")
    try:
        product_id = int(product_id_s)
        group_id = int(group_id_s)
    except ValueError:
        return _quote("skipped", None, "", checked_at,
                      "non-numeric tcgplayer_id / tcgcsv_group_id")
    url = PRICES_URL.format(group_id=group_id)
    rows = fetch_prices(group_id)  # honest degrade: tcgcsv.fetch_prices returns [] on failure
    subtype_s = str(subtype).strip() if subtype not in (None, "") else None
    price = tcgcsv_mod.pick_market_price(product_id, subtype_s, rows)
    if price is None:
        return _quote("no_match", None, url, checked_at,
                      "no clean TCGCSV market price (missing/ambiguous/null)")
    return _quote("ok", price, url, checked_at, "TCGCSV TCGplayer market (reference)")


class TcgCsvSource:
    """Sealed CompEngine ``tcg`` slot (mirrors ``comps.tcgplayer.TcgPlayerSource``)."""

    def __init__(self, cfg: Any = None, *, fetch_prices: Callable[[int], list[dict]] | None = None) -> None:
        self._fetch_prices = fetch_prices or tcgcsv_mod.fetch_prices

    def fetch(self, product_key: str, product: dict, checked_at: int) -> CompSourceQuote:
        return _resolve(product.get("ppt_id"), product.get("tcgcsv_group_id"),
                        product.get("tcgcsv_subtype"), checked_at, self._fetch_prices)


def raw_reference_quote(asset: dict, checked_at: int, *,
                        fetch_prices: Callable[[int], list[dict]] | None = None) -> CompSourceQuote:
    """Free raw-asset TCGplayer-market REFERENCE (0 credits). Recorded external-footing;
    never fills the raw independent ``tcg`` slot (spec §9.3)."""
    fp = fetch_prices or tcgcsv_mod.fetch_prices
    return _resolve(asset.get("tcgplayer_id"), asset.get("tcgcsv_group_id"),
                    asset.get("tcgcsv_subtype"), checked_at, fp)
