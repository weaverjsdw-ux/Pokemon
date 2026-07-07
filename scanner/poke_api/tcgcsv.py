"""TCGCSV client + pure parsers — free nightly TCGplayer catalog/price mirror.

TCGCSV is a REFERENCE source (TCGplayer lineage == PPT), NOT independent of PPT; it is
used for exact identity (productId) and a free market reference, never as independent
cross-source validation. Plain requests + JSON, 0 credits, keyless. Server-side only
(CORS-blocked in browsers — irrelevant here). Prices are one-to-many with products
(one row per subTypeName); an ambiguous pick is honest None, never a guess.
"""
from __future__ import annotations

import requests

from .independent_sources import UA

CATEGORY_POKEMON = 3
BASE = "https://tcgcsv.com/tcgplayer"
LAST_UPDATED_URL = "https://tcgcsv.com/last-updated.txt"
_TIMEOUT = 20


def _get_json(url: str) -> dict | None:
    """Plain GET → parsed JSON dict, or None on any HTTP/parse failure (honest degrade)."""
    try:
        resp = requests.get(url, headers={"User-Agent": UA, "Accept": "application/json"},
                            timeout=_TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _results(body: dict | None) -> list[dict]:
    if not body:
        return []
    results = body.get("results")
    return [r for r in results if isinstance(r, dict)] if isinstance(results, list) else []


def fetch_groups() -> list[dict]:
    return _results(_get_json(f"{BASE}/{CATEGORY_POKEMON}/groups"))


def fetch_products(group_id: int) -> list[dict]:
    return _results(_get_json(f"{BASE}/{CATEGORY_POKEMON}/{int(group_id)}/products"))


def fetch_prices(group_id: int) -> list[dict]:
    return _results(_get_json(f"{BASE}/{CATEGORY_POKEMON}/{int(group_id)}/prices"))


def card_number_of(product: dict) -> str | None:
    for field in product.get("extendedData", []) or []:
        if isinstance(field, dict) and field.get("name") == "Number":
            value = str(field.get("value") or "").strip()
            return value or None
    return None


def tcgcsv_enabled(cfg) -> bool:
    """The ``poke.tcgcsv`` gate (default False). Kept separate from
    ``poke.independent_sources`` (spec: a dedicated flag) — purely a 'live TCGCSV
    network is allowed on the CLI path' switch. TCGCSV is free/keyless (0 credits);
    the gate exists to keep it off by default, not because it costs anything."""
    return bool(getattr(getattr(cfg, "poke", None), "tcgcsv", False))


def pick_market_price(product_id: int, subtype: str | None,
                      price_rows: list[dict]) -> float | None:
    """Exact-subtype marketPrice for a product, or None (never guess).

    None when: no row, null/≤0 marketPrice, OR ambiguous (multiple subtype rows and no
    subtype supplied). A single row for the product resolves even with subtype=None.
    """
    rows = [r for r in price_rows if r.get("productId") == product_id]
    if not rows:
        return None
    if subtype is not None:
        rows = [r for r in rows if r.get("subTypeName") == subtype]
    elif len(rows) > 1:
        return None  # ambiguous printing — never pick one blindly
    if len(rows) != 1:
        return None
    price = rows[0].get("marketPrice")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return None
    return float(price)
