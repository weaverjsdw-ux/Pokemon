"""ID Doctor - verify catalog identifiers against the retailers.

The catalog's whole design principle is that it "never carries stale or guessed
identifiers" - but a value pasted into ``products.yaml`` can rot or be mistyped,
and you can't tell the trustworthy IDs from the suspect ones by looking. This
turns "verified" into a maintained property:

  python -m scanner.verify_ids                 # check everything, write verdicts
  python -m scanner.verify_ids --offline       # format sanity only, no network
  python -m scanner.verify_ids --only crown_zenith_etb
  python -m scanner.verify_ids --retailer target --json

Each populated ``(product, retailer-field)`` is classified:

  CONFIRMED       endpoint returns the product
  NOT_FOUND       endpoint says no such item -> the ID is wrong/dead
  BLOCKED         403/429 -> can't tell, retry later (the ID is not blamed)
  AMBIGUOUS       resolves but the format/name looks off -> eyeball it
  SUSPECT_FORMAT  offline: the value doesn't look like a real ID for that retailer
  NO_KEY          can't verify (Best Buy needs an API key)
  UNCHECKED       format ok, network verification not run

Verdicts (plus a timestamp) are written to the provenance sidecar
(:mod:`scanner.provenance`), which feeds the confidence model and work queue.
Verification calls are GET-only product-identity lookups; they never touch
cart/purchase state, matching the scanner's no-purchase contract.
"""
from __future__ import annotations

import argparse
import re
import time
from typing import Any, Callable

from . import config as cfg_mod
from . import provenance
from .provenance import (
    AMBIGUOUS,
    BLOCKED,
    CONFIRMED,
    ERROR,
    NO_KEY,
    NOT_FOUND,
    SUSPECT_FORMAT,
    UNCHECKED,
)
from .identifiers import FIELD_BY_SLUG
from .retailers import http

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Default network fetcher. Injected in tests. Verification health is kept
# separate from scan health (no ``retailer=`` arg) so probing IDs never moves a
# source's healthy/blocked state.
HttpGet = Callable[..., Any]


def _default_get(url: str, **kwargs: Any) -> Any:
    kwargs.setdefault("timeout", 15)
    kwargs.setdefault("headers", {"User-Agent": UA, "Accept": "*/*"})
    return http.get(url, **kwargs)


# --- offline format sanity --------------------------------------------------
# Cheap, deterministic, no network. Catches transcription errors (e.g. a Target
# TCIN with the wrong digit count) before any request goes out.

def _digit_len_check(lo: int, hi: int, label: str):
    def check(value: str) -> tuple[bool, str]:
        digits = re.sub(r"\D", "", value)
        if not digits or digits != value.strip():
            return False, f"{label} should be all digits"
        if not (lo <= len(digits) <= hi):
            return False, f"{label} is usually {lo}-{hi} digits, got {len(digits)}"
        return True, ""
    return check


def _nonempty_check(value: str) -> tuple[bool, str]:
    return (bool(value.strip()), "" if value.strip() else "empty value")


FORMAT_CHECKS: dict[str, Callable[[str], tuple[bool, str]]] = {
    "target": _digit_len_check(7, 9, "Target TCIN"),
    "walmart": _digit_len_check(6, 12, "Walmart item id"),
    "bestbuy": _digit_len_check(6, 8, "Best Buy SKU"),
    "costco": _digit_len_check(6, 12, "Costco item number"),
    "gamestop": _nonempty_check,       # free-form slug
    "pokemoncenter": _nonempty_check,  # free-form slug
}


# --- online resolvers -------------------------------------------------------
# Each returns (status, detail). Status-code driven, with light identity
# extraction where a title is cheaply available. Never raises.

def _status_for_code(code: int) -> tuple[str, str]:
    if code in (403, 429):
        return BLOCKED, f"HTTP {code}: blocked or rate-limited; retry later"
    if code == 404:
        return NOT_FOUND, "HTTP 404: no such product at this ID"
    if 500 <= code <= 599:
        return BLOCKED, f"HTTP {code}: retailer endpoint unavailable"
    if code != 200:
        return BLOCKED, f"HTTP {code}: unexpected response"
    return CONFIRMED, "HTTP 200: product resolved"


def _safe_json(resp: Any) -> Any:
    try:
        return resp.json()
    except Exception:
        return None


def _resolve_target(value: str, prod: dict, get: HttpGet, api_key: str) -> tuple[str, str]:
    from .retailers.target import REDSKY_KEY

    try:
        resp = get(
            "https://redsky.target.com/redsky_aggregations/v1/web/pdp_client_v1",
            params={"key": REDSKY_KEY, "tcin": value},
        )
    except Exception as exc:
        return ERROR, _short(str(exc) or exc.__class__.__name__)
    code = getattr(resp, "status_code", 200)
    status, detail = _status_for_code(code)
    if status != CONFIRMED:
        return status, detail
    data = _safe_json(resp) or {}
    product = (((data.get("data") or {}).get("product")) or {})
    if not product:
        return NOT_FOUND, "RedSky returned no product for this TCIN"
    return CONFIRMED, "RedSky resolved the TCIN"


def _resolve_bestbuy(value: str, prod: dict, get: HttpGet, api_key: str) -> tuple[str, str]:
    if not api_key:
        return NO_KEY, "Best Buy API key required to verify SKUs"
    try:
        resp = get(
            f"https://api.bestbuy.com/v1/products/{value}.json",
            params={"apiKey": api_key, "show": "sku,name"},
        )
    except Exception as exc:
        return ERROR, _short(str(exc) or exc.__class__.__name__)
    code = getattr(resp, "status_code", 200)
    status, detail = _status_for_code(code)
    if status != CONFIRMED:
        return status, detail
    data = _safe_json(resp) or {}
    if str(data.get("sku") or "") != value:
        return NOT_FOUND, "Best Buy returned no product for this SKU"
    return CONFIRMED, f"Best Buy resolved SKU ({data.get('name') or 'unnamed'})"


def _resolve_pokemoncenter(value: str, prod: dict, get: HttpGet, api_key: str) -> tuple[str, str]:
    try:
        resp = get(f"https://www.pokemoncenter.com/products/{value}.js")
    except Exception as exc:
        return ERROR, _short(str(exc) or exc.__class__.__name__)
    code = getattr(resp, "status_code", 200)
    status, detail = _status_for_code(code)
    if status != CONFIRMED:
        return status, detail
    data = _safe_json(resp) or {}
    if not (isinstance(data, dict) and data.get("variants")):
        return NOT_FOUND, "Pokemon Center returned no product JSON for this slug"
    return CONFIRMED, "Pokemon Center resolved the slug"


def _resolve_page(url_template: str, name: str):
    """Generic 'does the product page resolve' check for retailers without a
    clean identity endpoint (Walmart, Costco, GameStop product pages)."""

    def resolve(value: str, prod: dict, get: HttpGet, api_key: str) -> tuple[str, str]:
        try:
            resp = get(url_template.format(value=value), headers={"User-Agent": UA, "Accept": "text/html"})
        except Exception as exc:
            return ERROR, _short(str(exc) or exc.__class__.__name__)
        code = getattr(resp, "status_code", 200)
        status, detail = _status_for_code(code)
        if status == CONFIRMED:
            return CONFIRMED, f"{name} product page resolved"
        return status, detail

    return resolve


RESOLVERS: dict[str, Callable[[str, dict, HttpGet, str], tuple[str, str]]] = {
    "target": _resolve_target,
    "bestbuy": _resolve_bestbuy,
    "pokemoncenter": _resolve_pokemoncenter,
    "walmart": _resolve_page("https://www.walmart.com/ip/{value}", "Walmart"),
    "costco": _resolve_page("https://www.costco.com/.product.{value}.html", "Costco"),
    "gamestop": _resolve_page("https://www.gamestop.com/p/{value}", "GameStop"),
}


def _short(text: str, limit: int = 160) -> str:
    text = re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?...", str(text))
    return text if len(text) <= limit else text[: limit - 3] + "..."


def verify_one(
    slug: str,
    product_key: str,
    value: str,
    prod: dict[str, Any],
    *,
    online: bool = True,
    get: HttpGet | None = None,
    api_key: str = "",
) -> dict[str, Any]:
    """Classify a single (product, retailer) identifier. Never raises."""
    field = FIELD_BY_SLUG.get(slug, slug)
    get = get or _default_get
    fmt_ok, fmt_reason = FORMAT_CHECKS.get(slug, _nonempty_check)(value)

    if not online:
        status = UNCHECKED if fmt_ok else SUSPECT_FORMAT
        detail = "format ok; not network-verified" if fmt_ok else fmt_reason
        return _verdict(slug, field, product_key, value, status, detail)

    resolver = RESOLVERS.get(slug)
    if resolver is None:
        status = UNCHECKED if fmt_ok else SUSPECT_FORMAT
        detail = "no online verifier for this retailer" if fmt_ok else fmt_reason
        return _verdict(slug, field, product_key, value, status, detail)

    rstatus, rdetail = resolver(value, prod, get, api_key)

    # Reconcile the offline format signal with the network verdict.
    if not fmt_ok:
        if rstatus == CONFIRMED:
            return _verdict(
                slug, field, product_key, value, AMBIGUOUS,
                f"resolves, but {fmt_reason} - verify it is the right product",
            )
        if rstatus in (BLOCKED, ERROR, NO_KEY):
            return _verdict(slug, field, product_key, value, SUSPECT_FORMAT, fmt_reason)
    return _verdict(slug, field, product_key, value, rstatus, rdetail)


def _verdict(
    slug: str, field: str, product_key: str, value: str, status: str, detail: str
) -> dict[str, Any]:
    return {
        "productKey": product_key,
        "slug": slug,
        "field": field,
        "value": value,
        "status": status,
        "detail": detail,
    }


def verify_catalog(
    cfg: cfg_mod.Config,
    *,
    only: str | None = None,
    retailer: str | None = None,
    online: bool = True,
    get: HttpGet | None = None,
    record: bool = True,
    path: Any | None = None,
) -> list[dict[str, Any]]:
    """Verify every populated identifier in the selected catalog.

    Writes each verdict (plus a timestamp) to the provenance sidecar unless
    ``record`` is False. Returns the list of verdicts.
    """
    try:
        products = cfg_mod.selected_products(cfg)
    except SystemExit:
        products = cfg.products
    api_keys = {slug: rcfg.api_key for slug, rcfg in cfg.retailers.items()}

    results: list[dict[str, Any]] = []
    now = int(time.time())
    for product_key, prod in products.items():
        if only and product_key != only:
            continue
        for slug, field in FIELD_BY_SLUG.items():
            if retailer and slug != retailer:
                continue
            value = str(prod.get(field) or "").strip()
            if not value:
                continue
            verdict = verify_one(
                slug, product_key, value, prod,
                online=online, get=get, api_key=api_keys.get(slug, ""),
            )
            results.append(verdict)
            if record:
                provenance.record(
                    product_key, field,
                    status=verdict["status"], verified_at=now,
                    detail=verdict["detail"], path=path,
                )
    return results


_STATUS_ORDER = [NOT_FOUND, AMBIGUOUS, SUSPECT_FORMAT, BLOCKED, ERROR, NO_KEY, UNCHECKED, CONFIRMED]


def format_report(results: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines = ["ID Doctor - catalog identifier verification", ""]
    if not results:
        lines.append("No populated identifiers to verify.")
        return "\n".join(lines)
    # Surface the actionable verdicts first.
    ordered = sorted(
        results,
        key=lambda r: (
            _STATUS_ORDER.index(r["status"]) if r["status"] in _STATUS_ORDER else 99,
            r["productKey"],
            r["slug"],
        ),
    )
    for r in ordered:
        flag = "OK " if r["status"] == CONFIRMED else "!! "
        lines.append(
            f"  {flag}{r['status']:<14} {r['slug']:<13} {r['productKey']}."
            f"{r['field']} = {r['value']}"
        )
        if r["status"] != CONFIRMED and r["detail"]:
            lines.append(f"       {r['detail']}")
    summary = ", ".join(f"{counts[s]} {s.lower()}" for s in _STATUS_ORDER if s in counts)
    lines += ["", f"summary: {summary}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scanner.verify_ids",
        description="Verify catalog identifiers against the retailers (ID Doctor).",
    )
    parser.add_argument("--only", help="verify a single product key")
    parser.add_argument("--retailer", help="verify a single retailer slug")
    parser.add_argument(
        "--offline", action="store_true", help="format sanity only, no network"
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument(
        "--no-record", action="store_true", help="do not write verdicts to provenance"
    )
    args = parser.parse_args(argv)

    cfg = cfg_mod.load()
    results = verify_catalog(
        cfg,
        only=args.only,
        retailer=args.retailer,
        online=not args.offline,
        record=not args.no_record,
    )
    if args.json:
        import json

        print(json.dumps(results, indent=2))
    else:
        print(format_report(results))
    suspect = sum(1 for r in results if r["status"] in provenance.SUSPECT_STATUSES)
    return 1 if suspect else 0


if __name__ == "__main__":
    raise SystemExit(main())
