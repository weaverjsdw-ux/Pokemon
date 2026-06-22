"""Extract retailer product identifiers from product-page URLs and write
them into the catalog without disturbing its comments/formatting.

The scanner can't invent real SKUs - but pasting a product-page URL and
having the right id pulled out (and saved) removes the error-prone manual
step. See ``python -m scanner.add_id``.

ID locations (mirrors the README "Adding products" section):
  - target:        ``/p/.../A-<digits>``      -> target_tcin
  - walmart:       ``/ip/.../<digits>``        -> walmart_item_id
  - bestbuy:       ``/site/.../<digits>.p``    -> bestbuy_sku
  - costco:        ``.product.<digits>.html``  -> costco_item_id
  - gamestop:      ``/p/<slug>``               -> gamestop_pid
  - pokemoncenter: ``/product/<slug>``         -> pokemoncenter_slug
"""
from __future__ import annotations

import re

# Retailer slug -> the catalog field that holds its identifier.
FIELD_BY_SLUG = {
    "target": "target_tcin",
    "walmart": "walmart_item_id",
    "bestbuy": "bestbuy_sku",
    "costco": "costco_item_id",
    "gamestop": "gamestop_pid",
    "pokemoncenter": "pokemoncenter_slug",
}

# Retailer slug -> regex whose first group is the id within a product URL.
_URL_PATTERNS = {
    "target": r"A-(\d+)",
    "walmart": r"/ip/(?:[^/?#]+/)*(\d+)",
    "bestbuy": r"/(\d+)\.p(?:\b|$)",
    "costco": r"(?:\.product\.|/product/)(\d+)(?:\.html)?(?:\b|$)",
    "gamestop": r"/p/([^/?#]+)",
    "pokemoncenter": r"/product/([^/?#]+)",
}


def field_for_slug(slug: str) -> str | None:
    """Catalog field name for a retailer slug, or None if it has no id field."""
    return FIELD_BY_SLUG.get(slug.lower())


def extract_id(slug: str, value: str) -> str | None:
    """Pull the retailer id out of a product-page URL.

    If ``value`` has no ``/`` it's assumed to already be a bare id/slug and
    is returned as-is (trimmed). Returns None if nothing matches.
    """
    value = (value or "").strip()
    if not value:
        return None
    if "/" not in value:
        return value  # already a bare id/slug
    pattern = _URL_PATTERNS.get(slug.lower())
    if not pattern:
        return None
    match = re.search(pattern, value)
    return match.group(1) if match else None


def set_product_id(text: str, product_key: str, field: str, value: str) -> str:
    """Return ``text`` (raw products.yaml) with one field rewritten in place.

    Only the single ``  <field>: ...`` line under ``<product_key>:`` is
    replaced, so comments, ordering, and untouched fields are preserved.
    Raises KeyError if the product key or field line isn't found.
    """
    header = re.compile(rf"(?m)^{re.escape(product_key)}:[ \t]*$")
    m = header.search(text)
    if m is None:
        raise KeyError(f"product key not found: {product_key}")
    start = m.end()

    nxt = re.compile(r"(?m)^\S").search(text, start)
    end = nxt.start() if nxt else len(text)
    block = text[start:end]

    field_line = re.compile(rf"(?m)^([ \t]+){re.escape(field)}:[ \t]*.*$")
    fm = field_line.search(block)
    if fm is None:
        raise KeyError(f"field {field!r} not found under {product_key!r}")

    replacement = f'{fm.group(1)}{field}: "{value}"'
    new_block = block[: fm.start()] + replacement + block[fm.end() :]
    return text[:start] + new_block + text[end:]
