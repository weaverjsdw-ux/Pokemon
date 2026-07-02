"""Live sealed deal board: build a /poke sweep from live comps (MSRP buy basis).

    python -m scanner.discovery.sweep [--out DIR] [--event NAME]

Pure assembly (build_sealed_sweep) is separated from I/O (main): the comp
lookup is injected, so tests never touch the network. Doctrine: never
fabricate a row; a product with no usable comp / MSRP / attribution URL is
skipped and counted. STOP gate before render; a golden hard-fail halts the
run (exit 1) instead of shipping a bad dashboard.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .. import config as cfg_mod
from .. import main as main_mod
from .. import market as market_mod
from .. import resale
from . import golden as golden_mod
from . import ledger as ledger_mod
from . import render as render_mod
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


class LiveCompLookup:
    """One live comp call per product, credit-guarded.

    Uses PPT (behind MarketFallbackClient) while the run's credit budget and
    the account's daily balance hold; afterwards short-circuits straight to
    the resale fallback. Any exception becomes an error row - a comp failure
    never errors the run (it just skips + counts that product).
    """

    def __init__(self, cfg: Any, market_client: Any = None, resale_client: Any = None) -> None:
        self.cfg = cfg
        self.resale_client = resale_client or resale.resale_client_from_config(cfg)
        if market_client is not None:
            self.market_client = market_client
        elif getattr(cfg, "market_preferred", False) and getattr(cfg, "market_api_key", ""):
            self.market_client = market_mod.MarketFallbackClient(
                market_mod.PokemonPriceTrackerClient.from_config(cfg), self.resale_client)
        else:
            self.market_client = None
        self.credits_used = 0
        self.exhausted = False

    def __call__(self, product_key: str, product: dict) -> dict:
        checked_at = int(time.time())
        try:
            if (self.market_client is not None and not self.exhausted
                    and self.credits_used < self.cfg.poke.daily_credit_cap):
                row = self.market_client.estimate(product_key, product, checked_at)
                self.credits_used += int(row.get("creditsConsumed") or 0)
                remaining = row.get("dailyRemaining")
                if isinstance(remaining, int) and remaining <= 0:
                    self.exhausted = True
                return row
            return self.resale_client.estimate(product_key, product, checked_at)
        except Exception as exc:  # never error the run over one comp
            return {"status": "error", "detail": str(exc)[:200]}


def _badge_breakdown(deals: list[dict]) -> dict[str, int]:
    breakdown: dict[str, int] = {}
    for d in deals:
        for badge in d.get("badges", []):
            breakdown[badge] = breakdown.get(badge, 0) + 1
    return breakdown


def _append_ledger(path: Path, sweep: dict, capture_date: str) -> int:
    """market_comp + deal observation per rendered row. Idempotent; returns appended count."""
    appended = 0
    for d in sweep["deals"]:
        base = {
            "set": d.get("set", ""), "item": d.get("item", ""),
            "variant": d.get("variant", ""), "grade": "", "condition": "",
            "source_url": d.get("source_url", ""), "capture_date": capture_date,
        }
        appended += ledger_mod.append_observation(path, base | {
            "kind": "market_comp",
            "comp": d.get("market_comp"),
            "comp_confidence": d.get("comp_confidence", ""),
        })
        appended += ledger_mod.append_observation(path, base | {
            "kind": "deal",
            "deal_price": d.get("deal_price"),
            "market_comp": d.get("market_comp"),
            "pct_off": d.get("pct_off"),
            "price_confidence": d.get("price_confidence", ""),
            "badges": d.get("badges", []),
        })
    return appended


def main(argv: list[str] | None = None,
         comp_lookup: CompLookup | None = None,
         cfg: Any = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scanner.discovery.sweep",
        description="Render the live sealed deal board from the tracked catalog.")
    parser.add_argument("--out", default=None,
                        help="output root (default: repo root; writes data/poke/ + dashboards/)")
    parser.add_argument("--event", default="sealed", help="event label for the sweep id")
    args = parser.parse_args(argv)

    cfg = cfg or cfg_mod.load()
    root = Path(args.out) if args.out else cfg_mod.ROOT
    today = date.today().isoformat()
    sweep_id = f"{today}-{args.event}"
    lookup = comp_lookup if comp_lookup is not None else LiveCompLookup(cfg)

    sweep = build_sealed_sweep(cfg, lookup,
                               event=args.event, sweep_id=sweep_id, captured_at=today)

    poke_dir = root / "data" / "poke"
    poke_dir.mkdir(parents=True, exist_ok=True)
    sweep_path = poke_dir / f"{sweep_id}.json"
    sweep_path.write_text(json.dumps(sweep, indent=2, ensure_ascii=False), encoding="utf-8")

    html = render_mod.render_sweep(sweep)  # STOP gate runs again inside
    fails = golden_mod.golden_check(html, cfg.poke.min_rows)
    credits = getattr(lookup, "credits_used", 0)

    manifest = {
        "sweep_id": sweep_id,
        "captured_at": today,
        "counts": sweep["counts"],
        "badges": _badge_breakdown(sweep["deals"]),
        "sources": sweep["sources"],
        "credits_consumed": credits,
        "golden_failures": fails,
    }
    (poke_dir / f"{sweep_id}.manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    appended = _append_ledger(poke_dir / "price_history.jsonl", sweep, today)

    if fails:
        for message in fails:
            print(f"GOLDEN FAIL: {message}")
        print(f"HALTED: dashboard not written ({len(fails)} golden failures). "
              f"Evidence kept at {sweep_path}")
        return 1

    dash_dir = root / "dashboards"
    dash_dir.mkdir(parents=True, exist_ok=True)
    dash_path = dash_dir / f"{today}-sealed.html"
    dash_path.write_text(html, encoding="utf-8")

    c = sweep["counts"]
    steals = sum(1 for d in sweep["deals"] if "STEAL" in d.get("badges", []))
    print(f"scanned={c['scanned']} comped={c['comped']} no_comp={c['no_comp']} "
          f"no_msrp={c['no_msrp']} no_source={c['no_source']} steals={steals} "
          f"credits={credits} ledger+={appended}")
    print(f"dashboard: {dash_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
