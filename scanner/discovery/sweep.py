"""Live sealed deal board: build a /poke sweep from live comps (MSRP buy basis).

    python -m scanner.discovery.sweep [--out DIR] [--event NAME]

Pure assembly (build_sealed_sweep) is separated from I/O (main): the comp
lookup is injected, so tests never touch the network. Doctrine: never
fabricate a row; a product with no usable comp / MSRP / attribution URL is
skipped and counted. STOP gate before render; a golden hard-fail halts the
run (exit 1) instead of shipping a bad dashboard.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from .. import config as cfg_mod
from .. import main as main_mod
from .. import market as market_mod
from .. import resale
from . import schema, score

CompLookup = Callable[[str, dict], dict]


def _msrp(product: dict) -> float | None:
    return resale._amount(product.get("msrp"))


def _category(product: dict) -> str:
    ptype = str(product.get("type") or "").strip().lower()
    if ptype == "etb":
        return "sealed-etb"
    if ptype == "booster bundle":
        return "sealed-bundle"
    return "sealed-other"


def _provenance(comp_row: dict, comp_confidence: str) -> tuple[str, str, str, str]:
    """(price_confidence, source_url, derivation_method, confidence_detail).

    Only an exact-product sourceUrl (PPT tcgPlayerUrl) at high/medium
    confidence earns "verified". Fallback comps keep their search-page url
    as attribution but stay "est" - the STOP gate then requires the EST
    badge + derivation_method, so an est comp can never render as a
    confirmed STEAL.
    """
    exact_url = str(comp_row.get("sourceUrl") or "")
    source_url = exact_url or str(comp_row.get("url") or "")
    if exact_url and comp_confidence in {"high", "medium"}:
        return "verified", source_url, "", ""
    method = " / ".join(
        part for part in (str(comp_row.get("source") or ""), str(comp_row.get("basis") or ""))
        if part
    ) or "market comp"
    detail = str(comp_row.get("confidenceReason") or "")
    return "est", source_url, method, detail


def build_sealed_sweep(
    cfg: Any,
    comp_lookup: CompLookup,
    *,
    event: str,
    sweep_id: str,
    captured_at: str,
) -> dict:
    products = cfg_mod.selected_products(cfg)
    rows: list[schema.DealRow] = []
    counts = {"scanned": 0, "comped": 0, "no_comp": 0, "no_msrp": 0, "no_source": 0}
    comp_sources: dict[str, int] = {}

    for key, product in products.items():
        counts["scanned"] += 1
        deal_price = _msrp(product)
        if deal_price is None or deal_price <= 0:
            counts["no_msrp"] += 1
            continue
        comp_row = comp_lookup(key, product) or {}
        comp, comp_confidence = market_mod.comp_from_row(comp_row)
        if comp is None:
            counts["no_comp"] += 1
            continue
        price_confidence, source_url, derivation, detail = _provenance(comp_row, comp_confidence)
        if not source_url:
            counts["no_source"] += 1  # unattributable comp: never render without provenance
            continue
        row = schema.DealRow(
            item=str(product.get("name") or key),
            asset_class="sealed",
            category=_category(product),
            deal_price=deal_price,
            market_comp=comp,
            retailer="MSRP",
            source_url=source_url,
            captured_at=captured_at,
            price_confidence=price_confidence,
            comp_confidence=comp_confidence,
            pct_off=score.compute_pct_off(deal_price, comp),
            derivation_method=derivation,
            confidence_detail=detail,
            capture_method="live-comp",
            set=str(product.get("set") or ""),
        )
        row.badges = score.assign_badges(row, cfg)
        row.lens_tags = score.lens_tags(row, cfg)
        row.scanner_verdict = main_mod.verdict_for_alert(
            cfg, product, f"${deal_price:.2f}", comp_row)
        rows.append(row)
        counts["comped"] += 1
        label = str(comp_row.get("source") or "unknown")
        comp_sources[label] = comp_sources.get(label, 0) + 1

    schema.assert_sweep(rows)  # STOP gate before the dict leaves this function
    rows.sort(key=lambda r: (r.pct_off is None, -(r.pct_off or 0)))

    sources = [
        {"name": name, "category": "comp", "tier": "api", "status": "used",
         "note": f"{n} comps"}
        for name, n in sorted(comp_sources.items())
    ]
    sources.append({"name": "no_comp", "category": "comp", "tier": "n/a",
                    "status": "skipped",
                    "note": f"{counts['no_comp']} products had no usable comp"})

    return {
        "event": event,
        "sweep_id": sweep_id,
        "captured_window": captured_at,
        "notes": (f"Live sealed board - buy basis {cfg.poke.buy_basis.upper()} - "
                  f"{counts['comped']}/{counts['scanned']} comped"),
        "deals": [asdict(r) for r in rows],
        "promo_codes": [],
        "bundled_offers": [],
        "watchlist_results": [],
        "sources": sources,
        "counts": counts,
    }
