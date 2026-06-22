"""Add or update a retailer product identifier in data/products.yaml.

Usage:
  python -m scanner.add_id <retailer> <product_key> <url-or-id>

Examples:
  python -m scanner.add_id target prismatic_evolutions_etb \\
      https://www.target.com/p/-/A-93954435
  python -m scanner.add_id walmart prismatic_evolutions_etb 15433520586

Paste the product-page URL and the matching id is extracted for you, or
pass a bare id directly. The catalog's comments and formatting are
preserved (only the one field line is rewritten)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config as cfg_mod
from . import provenance
from .identifiers import FIELD_BY_SLUG, extract_id, set_product_id
from .retailers import ALL as RETAILER_REGISTRY


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scanner.add_id",
        description="Add/update a retailer product ID in data/products.yaml.",
    )
    parser.add_argument("retailer", help="retailer slug, e.g. target, walmart, bestbuy")
    parser.add_argument("product_key", help="product key in data/products.yaml")
    parser.add_argument(
        "url_or_id", help="product-page URL (id is extracted) or a bare id"
    )
    parser.add_argument(
        "--products", default=None, help="path to products.yaml (default: bundled catalog)"
    )
    args = parser.parse_args(argv)

    slug = args.retailer.lower()
    if slug not in RETAILER_REGISTRY:
        known = ", ".join(sorted(RETAILER_REGISTRY))
        print(f"unknown retailer: {slug!r}. known: {known}", file=sys.stderr)
        return 2

    field = FIELD_BY_SLUG.get(slug)
    if not field:
        print(
            f"{slug} has no catalog identifier field "
            "(placeholder/unsupported retailer).",
            file=sys.stderr,
        )
        return 2

    value = extract_id(slug, args.url_or_id)
    if not value:
        print(f"could not extract a {slug} id from {args.url_or_id!r}", file=sys.stderr)
        return 2

    path = Path(args.products) if args.products else cfg_mod.PRODUCTS_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read {path}: {exc}", file=sys.stderr)
        return 2

    try:
        updated = set_product_id(text, args.product_key, field, value)
    except KeyError as exc:
        print(str(exc).strip('"'), file=sys.stderr)
        return 2

    path.write_text(updated, encoding="utf-8")
    # Record where this ID came from (only when a URL was pasted, not a bare id),
    # so the ID Doctor and work queue have provenance to work with. Best-effort:
    # only when writing the bundled catalog, and never fatal.
    if "/" in args.url_or_id and args.products is None:
        try:
            provenance.record(args.product_key, field, source_url=args.url_or_id)
        except OSError:
            pass
    print(f"{path.name}: set {args.product_key}.{field} = {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
