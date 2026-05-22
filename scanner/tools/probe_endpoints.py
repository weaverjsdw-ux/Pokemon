"""Verify each retailer's endpoint still returns the JSON shape our
parsers depend on. Run nightly in CI; surfaces breakage before the
scanner silently misses a drop because a field got renamed.

Each probe hits the real endpoint with a well-known SKU and asserts that
the response 200s AND the keys we extract are present. Availability is
NOT asserted — the SKU may legitimately be out of stock when the probe
runs. We're only checking that *if* the field were populated, we'd be
able to find it.

Exit status:
  0   all enabled probes passed
  1   at least one probe failed (CI fails -> alert fires)
  2   network problem unrelated to retailer shape (try again later)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Callable

import requests

from ..retailers.target import REDSKY_KEY, UA as TARGET_UA


@dataclass
class Probe:
    name: str
    fn: Callable[[], None]
    requires_env: str | None = None


class ShapeError(AssertionError):
    pass


def _get(url: str, *, params=None, headers=None) -> dict:
    resp = requests.get(url, params=params, headers=headers, timeout=20)
    if resp.status_code != 200:
        raise ShapeError(f"{url} -> {resp.status_code} {resp.reason}")
    try:
        return resp.json()
    except ValueError as exc:
        raise ShapeError(f"{url} -> non-JSON body ({exc})")


def _require(obj, path: list[str], where: str) -> None:
    """Walk a dotted-path through dicts; raise ShapeError if any key is missing."""
    cur = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            raise ShapeError(f"{where}: missing key {'.'.join(path)} (stopped at {key!r})")
        cur = cur[key]


def probe_target() -> None:
    # Known stable-ish product: Surging Sparks ETB on Target.
    data = _get(
        "https://redsky.target.com/redsky_aggregations/v1/web/product_fulfillment_v1",
        params={
            "key": REDSKY_KEY,
            "tcin": "91553808",
            "store_id": "1234",
            "pricing_store_id": "1234",
            "latitude": 39.78,
            "longitude": -89.65,
            "has_pricing_store_id": "true",
            "channel": "WEB",
            "page": "/p/A-91553808",
        },
        headers={"User-Agent": TARGET_UA, "Accept": "application/json"},
    )
    _require(data, ["data", "product", "fulfillment"], "target.fulfillment")


def probe_pokemoncenter() -> None:
    # PC slug structure rarely changes; any /products/<slug>.js works.
    data = _get(
        "https://www.pokemoncenter.com/products/pokemon-tcg-prismatic-evolutions-elite-trainer-box.js",
        headers={"User-Agent": TARGET_UA, "Accept": "application/json"},
    )
    if "variants" not in data:
        raise ShapeError("pokemoncenter: missing 'variants' key")


def probe_bestbuy() -> None:
    key = os.environ.get("BESTBUY_API_KEY", "").strip()
    if not key:
        print("  bestbuy: SKIPPED (no BESTBUY_API_KEY)")
        return
    data = _get(
        "https://api.bestbuy.com/v1/products(sku=6566943)",
        params={"format": "json", "show": "sku,name,salePrice", "apiKey": key},
        headers={"Accept": "application/json"},
    )
    _require(data, ["products"], "bestbuy.products")


PROBES = [
    Probe("target", probe_target),
    Probe("pokemoncenter", probe_pokemoncenter),
    Probe("bestbuy", probe_bestbuy),
]


def main() -> int:
    failures: list[tuple[str, str]] = []
    transient: list[tuple[str, str]] = []
    for p in PROBES:
        try:
            p.fn()
            print(f"  {p.name}: OK")
        except ShapeError as exc:
            print(f"  {p.name}: SHAPE FAIL — {exc}")
            failures.append((p.name, str(exc)))
        except requests.RequestException as exc:
            print(f"  {p.name}: network — {exc}")
            transient.append((p.name, str(exc)))

    if failures:
        print("\nShape failures (parsers will silently break):")
        for name, why in failures:
            print(f"  - {name}: {why}")
        return 1
    if transient and not failures:
        print("\nOnly transient/network errors. Treating as inconclusive.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
