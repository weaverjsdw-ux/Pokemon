"""Pull retailer-specific SKU/ID out of a product URL.

    python -m scanner.tools.extract_sku https://www.target.com/p/.../A-93954435
    -> target_tcin: 93954435

Handles target, walmart, bestbuy, gamestop, pokemoncenter.

The goal is to make catalog-filling a copy-paste workflow: paste a URL,
get the right field name + value to put in data/products.yaml.
"""
from __future__ import annotations

import re
import sys
from urllib.parse import urlparse

# Each entry: (host substring, field name in products.yaml, regex to pull the ID)
_PATTERNS = [
    ("target.com",         "target_tcin",          re.compile(r"/A-(\d+)")),
    ("walmart.com",        "walmart_item_id",      re.compile(r"/ip/[^/]*/?(\d+)")),
    ("bestbuy.com",        "bestbuy_sku",          re.compile(r"/(\d+)\.p")),
    ("gamestop.com",       "gamestop_pid",         re.compile(r"/p/([^/?#]+)")),
    ("pokemoncenter.com",  "pokemoncenter_slug",   re.compile(r"/product/([^/?#]+)")),
    ("costco.com",         "costco_item_id",       re.compile(r"\.product\.(\d+)\.html")),
    ("samsclub.com",       "samsclub_product_id",  re.compile(r"/p/[^/]+/(\d+)")),
    ("amazon.com",         "amazon_asin",          re.compile(r"/dp/([A-Z0-9]{10})")),
    ("tcgplayer.com",      "tcgplayer_product_id", re.compile(r"/product/(\d+)")),
    ("barnesandnoble.com", "barnesnoble_id",       re.compile(r"/w/[^/]+/(\d+)")),
    ("meijer.com",         "meijer_product_id",    re.compile(r"/product/[^/]+/(\d+)\.html")),
    ("fivebelow.com",      "fivebelow_product_id", re.compile(r"/p/([^/?#]+)")),
]


def extract(url: str) -> tuple[str, str] | None:
    """Return (field_name, sku) or None if the URL isn't recognized."""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = parsed.path or url
    for needle, field, pattern in _PATTERNS:
        if needle in host:
            m = pattern.search(path)
            if m:
                return field, m.group(1)
            return None
    return None


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    rc = 0
    for url in args:
        result = extract(url)
        if result is None:
            print(f"{url}\n  ! unrecognized retailer or no SKU found", file=sys.stderr)
            rc = 1
            continue
        field, sku = result
        print(f"{url}")
        print(f"  {field}: \"{sku}\"")
    return rc


if __name__ == "__main__":
    sys.exit(main())
