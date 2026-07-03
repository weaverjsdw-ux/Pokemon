"""One-shot discovery pipeline: DISCOVER -> VERIFY -> COMP/VERDICT -> DEDUPE ->
BOARD/MANIFEST -> ALERT DECISION.

    python -m scanner.discovery.pipeline --once [--sources a,b] [--dry-run]

Every stage is dependency-injected (adapters/verifier/comp/notifier/state), so
tests never touch the network. Doctrine, all load-bearing:

* **No alert without verified purchasability.** Only a fresh, same-run
  ``StockVerification`` in state ``VERIFIED_BUYABLE`` that passes
  ``verify.assert_alertable`` (evidence re-checked, never the label) can push.
  The verification object is held in memory end-to-end — alertability is never
  re-derived from a board-row dict (a PRICE_MISMATCH row is indistinguishable
  from VERIFIED_BUYABLE at row level).
* **No live PPT.** The comp lookup is structurally PPT-free (resale fallback or
  the in-house engine, never ``MarketFallbackClient``).
* **No silent drops.** Every candidate lands in exactly one terminal bucket and
  the manifest counts reconcile with the candidate total.

Slice-4 scope (advisor-reviewed): the default verifier honestly degrades every
current live source to ``unverifiable`` (a slickdeals URL is a deal-thread, not
a merchant page; eBay item lookup needs the pending keyset; catalog-retailer
verification would check a *different* listing than the one discovered). The
VERIFIED_BUYABLE -> alert path is proven by tests with injected verifiers and
lands live behind the Slice-6 merchant resolver.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from .. import config as cfg_mod
from .. import main as main_mod
from .. import market as market_mod
from .. import resale
from ..comps import engine as comps_engine
from ..notify import DealAlert, Notifier
from ..retailers import http as retailer_http
from ..state import State
from . import golden as golden_mod
from . import ledger as ledger_mod
from . import render as render_mod
from . import schema, score
from . import sweep as sweep_mod
from . import verify as verify_mod
from .adapters import ALL as ADAPTER_REGISTRY
from .candidates import CandidateDeal
from .verify import StockVerification

Verifier = Callable[[CandidateDeal], StockVerification]
CompLookup = Callable[[CandidateDeal, "dict | None"], dict]

# Terminal buckets — every candidate lands in exactly one; the manifest asserts
# sum(counts) == candidates (no silent drops).
TERMINAL_BUCKETS = (
    "alerted", "suppressed_dupe", "out_of_stock", "price_mismatch",
    "unverifiable", "no_comp", "below_min_discount", "below_confidence",
)

_CONF_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}


class PipelineConfigError(Exception):
    """A configured discovery source slug is not in the adapter registry."""


def _no_network(*args: Any, **kwargs: Any):
    """Injected in --dry-run so any adapter fetch attempt raises (and is caught
    by the adapter's never-raise contract -> DEGRADED). Zero real network."""
    raise RuntimeError("network disabled (--dry-run)")


def _in_quiet_hours(now_dt: datetime, quiet_hours: str) -> bool:
    """Wrap-aware: '23:00-08:00' (start > end) means 'in-window when after 23:00
    OR before 08:00'."""
    start, end = cfg_mod.parse_quiet_hours(quiet_hours)
    cur = now_dt.hour * 60 + now_dt.minute
    if start <= end:
        return start <= cur < end
    return cur >= start or cur < end


# ------------------------------------------------------------ default stages

def default_verifier(cfg: Any) -> Verifier:
    """Route by candidate origin. No current live source has a same-listing
    buyability check wired, so every candidate honestly degrades to
    unverifiable (network-free) until the Slice-6 merchant-page resolver /
    eBay item lookup land."""

    def verify(candidate: CandidateDeal) -> StockVerification:
        reason = (f"no same-listing buyability check wired for source "
                  f"{candidate.source!r}; a merchant-page resolver / eBay item "
                  f"lookup land in a later slice")
        return StockVerification(
            state=verify_mod.UNKNOWN_NO_ALERT, stock_status="unverifiable",
            verified_price=None, expected_price=candidate.price, price_matches=None,
            buy_url="", checked_at=verify_mod._now_iso(), source=candidate.source,
            method="none", evidence="", degraded_reason=reason)

    return verify


def default_comp_lookup(cfg: Any) -> CompLookup:
    """PPT-free comp lookup. Ring-1 (catalog-matched) candidates get a comp via
    the resale fallback or the in-house engine; non-catalog candidates get no
    ad-hoc comp in this build (honest no_comp). The client is built lazily so a
    dry run with zero candidates never constructs it."""
    box: dict[str, Any] = {}

    def _client():
        if "c" not in box:
            engine = getattr(getattr(cfg, "comps", None), "engine", "legacy")
            box["c"] = (comps_engine.CompEngine.from_config(cfg) if engine == "inhouse"
                        else resale.resale_client_from_config(cfg))  # never PPT
        return box["c"]

    def lookup(candidate: CandidateDeal, product: dict | None) -> dict:
        if product is None:
            return {"status": "no_match",
                    "detail": "non-catalog candidate; no ad-hoc comp in this build"}
        try:
            return _client().estimate(candidate.matched_product_key, product,
                                      int(time.time()))
        except Exception as exc:  # a comp failure skips the row, never errors the run
            return {"status": "error", "detail": str(exc)[:200]}

    return lookup


def _dry_run_comp_lookup(candidate: CandidateDeal, product: dict | None) -> dict:
    """The comp stage in --dry-run: network-free by construction, so the
    zero-network guarantee never depends on the verifier happening to skip
    VERIFIED_BUYABLE. A skipped comp resolves to no_comp (honest)."""
    return {"status": "skipped", "detail": "dry-run: comp lookup skipped (no network)"}


# ------------------------------------------------------------ row + payload

def _build_row(cfg: Any, c: CandidateDeal, v: StockVerification, product: dict | None,
               comp_row: dict, comp: float, comp_conf: str,
               captured_at: str) -> schema.DealRow | None:
    price_conf, source_url, derivation, detail = sweep_mod._provenance(comp_row, comp_conf)
    if not source_url:
        return None  # unattributable comp -> no board row (counted as no_comp upstream)
    row = schema.DealRow(
        item=c.item_name,
        asset_class=c.asset_class or "sealed",
        category=sweep_mod._category(product) if product else "discovered",
        deal_price=v.verified_price,
        market_comp=comp,
        retailer=c.retailer or v.source,
        source_url=source_url,
        captured_at=captured_at,
        price_confidence=price_conf,
        comp_confidence=comp_conf,
        pct_off=score.compute_pct_off(v.verified_price, comp),
        derivation_method=derivation,
        confidence_detail=detail,
        capture_method="discovery",
        set=(str(product.get("set")) if product else "") or c.matched_set or "",
        variant=c.variant or "",
        comp_basis=str(comp_row.get("compBasis") or comp_row.get("basis") or ""),
        stock_status=v.stock_status,
        stock_evidence=v.evidence or v.degraded_reason,
        buy_url=v.buy_url,
        stock_checked_at=v.checked_at,
        stock_method=v.method,
    )
    row.badges = score.assign_badges(row, cfg)
    row.lens_tags = score.lens_tags(row, cfg)
    row.scanner_verdict = main_mod.verdict_for_alert(
        cfg, product or {}, f"${row.deal_price:.2f}", comp_row)
    return row


def _deal_alert(c: CandidateDeal, v: StockVerification, comp: float | None, comp_conf: str,
                comp_row: dict, row: schema.DealRow, msrp: float | None) -> DealAlert:
    return DealAlert(
        item=c.item_name,
        retailer=row.retailer,
        source_adapter=c.source,
        listing_id=c.listing_id,
        buy_url=v.buy_url,
        verified_price=v.verified_price,
        stock_status=v.stock_status,
        stock_evidence=v.evidence or v.degraded_reason,
        checked_at=v.checked_at,
        msrp=msrp,
        comp=comp,
        comp_confidence=comp_conf,
        comp_basis=str(comp_row.get("compBasis") or comp_row.get("basis") or ""),
        pct_off=row.pct_off,
        verdict_headline=row.scanner_verdict,
        badges=list(row.badges),
        warn_flags=[row.warn_reason] if row.warn_reason else [],
    )


def _append_listing(path: Path, c: CandidateDeal, capture_date: str) -> None:
    ledger_mod.append_observation(path, {
        "kind": "listing", "set": c.matched_set or "", "item": c.item_name,
        "variant": c.variant or "", "grade": "", "condition": "",
        "source": c.source, "source_url": c.url, "capture_date": capture_date,
        "price": c.price, "listing_id": c.listing_id, "retailer": c.retailer,
    })


# ------------------------------------------------------------ per-candidate

def _classify(cfg: Any, c: CandidateDeal, v: StockVerification, comp_lookup: CompLookup,
              catalog: dict, board_rows: list, state: Any, notifier: Any,
              now_ts: int, quiet: bool, captured_at: str, dry_run: bool) -> tuple[str, str]:
    """Return (terminal bucket, human reason) for one candidate. Every path
    yields a reason so the manifest records an honest per-candidate disposition."""
    # 1) VERIFY outcome
    if v.state == verify_mod.OUT_OF_STOCK:
        return "out_of_stock", (v.degraded_reason or "affirmatively out of stock")
    if v.state == verify_mod.PRICE_MISMATCH:
        return "price_mismatch", (v.degraded_reason or "verified price differs from candidate")
    if v.state != verify_mod.VERIFIED_BUYABLE:
        return "unverifiable", (v.degraded_reason or f"not verified buyable ({v.state})")

    # 2) Gate the evidence immediately: a VERIFIED_BUYABLE that fails the gate is
    # a broken/lying verification (no price/buy_url/evidence) -> never trusted.
    try:
        verify_mod.assert_alertable(v)
    except verify_mod.AlertGateError as exc:
        return "unverifiable", f"alert gate refused: {exc}"

    # 3) COMP (PPT-free); no usable comp -> no_comp. A comp source that raises
    # never errors the run (sweep's "one comp failure just skips + counts" doctrine).
    product = catalog.get(c.matched_product_key) if c.matched_product_key else None
    try:
        comp_row = comp_lookup(c, product) or {}
    except Exception:
        comp_row = {}
    comp, comp_conf = market_mod.comp_from_row(comp_row)
    if comp is None:
        return "no_comp", (str(comp_row.get("detail") or "") or "no usable comp from any source")
    row = _build_row(cfg, c, v, product, comp_row, comp, comp_conf, captured_at)
    if row is None:
        return "no_comp", "comp had no attribution URL"

    # 4) VERDICT gates
    pct = row.pct_off
    if pct is None or pct < cfg.poke.min_discount_pct:
        board_rows.append(row)
        return ("below_min_discount",
                f"pct_off {pct} < min_discount_pct {cfg.poke.min_discount_pct}")
    ring3 = (c.matched_product_key is None) and not c.matched_set
    if ring3 and _CONF_RANK.get(comp_conf, 0) < _CONF_RANK.get(cfg.discovery.min_alert_confidence, 0):
        board_rows.append(row)
        return ("below_confidence",
                f"ring-3 comp_confidence {comp_conf!r} < min_alert_confidence "
                f"{cfg.discovery.min_alert_confidence!r}")

    board_rows.append(row)

    # 5) DEDUPE + ALERT (baseline = last ALERTED, recorded only on fire)
    if state is not None:
        fire, reason = state.should_deal_alert(
            c.source, c.listing_id, v.verified_price, v.stock_status, now=now_ts,
            cooldown_hours=cfg.alerts.cooldown_hours,
            price_drop_realert_pct=cfg.alerts.price_drop_realert_pct)
    else:
        fire, reason = True, "no state (alert)"
    if not fire:
        return "suppressed_dupe", reason
    msrp = resale._amount(product.get("msrp")) if product else None
    deal = _deal_alert(c, v, comp, comp_conf, comp_row, row, msrp)
    if not dry_run:
        notifier.send_deal(deal, push=not quiet)
        if state is not None:
            state.record_deal_alert(c.source, c.listing_id, v.verified_price,
                                    v.stock_status, ts=now_ts)
    return "alerted", reason


# ------------------------------------------------------------ orchestrator

def run_once(
    cfg: Any,
    *,
    sources: list | None = None,
    verifier: Verifier | None = None,
    comp_lookup: CompLookup | None = None,
    notifier: Any = None,
    state: Any = None,
    catalog: dict | None = None,
    source_slugs: list[str] | None = None,
    registry: dict | None = None,
    now_ts: int | None = None,
    now_dt: datetime | None = None,
    dry_run: bool = False,
    http_get: Callable | None = None,
    ledger_path: Path | None = None,
    event: str = "discovery",
    captured_at: str | None = None,
) -> dict:
    """Run the discovery pipeline once and return the manifest (board under
    ``manifest['board']``). Pure of clocks/network beyond injected stages."""
    now_ts = int(time.time()) if now_ts is None else int(now_ts)
    now_dt = datetime.now() if now_dt is None else now_dt
    registry = ADAPTER_REGISTRY if registry is None else registry
    catalog = cfg_mod.selected_products(cfg) if catalog is None else catalog
    set_watch = list(getattr(cfg.discovery, "set_watch", []))
    captured_at = captured_at or date.today().isoformat()
    sweep_id = f"{captured_at}-{event}"

    # slug validation happens only when the pipeline BUILDS sources from config
    # (injected sources are caller-owned). Unknown configured slug -> hard error.
    effective_slugs = (list(source_slugs) if source_slugs is not None
                       else list(getattr(cfg.discovery, "sources", [])))
    if sources is None:
        unknown = [s for s in effective_slugs if s not in registry]
        if unknown:
            raise PipelineConfigError(
                "unknown discovery source(s): " + ", ".join(unknown)
                + "; known: " + ", ".join(sorted(registry)))
        source_instances = [registry[s]() for s in effective_slugs]
    else:
        source_instances = list(sources)

    verifier = verifier or default_verifier(cfg)
    if comp_lookup is None:
        # the default comp path touches the network; in --dry-run it is replaced
        # with a network-free stub so zero-network is structural, not incidental.
        comp_lookup = _dry_run_comp_lookup if dry_run else default_comp_lookup(cfg)
    if notifier is None:
        notifier = Notifier(getattr(cfg, "discord_webhook", "") or "",
                            getattr(cfg, "ntfy_topic", "") or "")

    if dry_run:
        discover_kwargs = {"http_get": _no_network, "search_fn": _no_network}
    elif http_get is not None:
        discover_kwargs = {"http_get": http_get}
    else:
        discover_kwargs = {}

    # DISCOVER (min_interval-throttled; never-raise even against a bad adapter)
    raw_candidates: list[CandidateDeal] = []
    source_reports: list[dict] = []
    for src in source_instances:
        slug = getattr(src, "slug", "") or src.__class__.__name__
        interval = int(getattr(src, "min_interval_seconds", 0) or 0)
        last_run = state.get_last_run(slug) if state is not None else None
        if last_run is not None and interval > 0 and (now_ts - last_run) < interval:
            source_reports.append({
                "slug": slug, "state": "THROTTLED", "candidates": 0,
                "detail": f"throttled: {now_ts - last_run}s since last run < "
                          f"min_interval {interval}s"})
            continue
        try:
            found = list(src.discover(cfg, catalog, set_watch, **discover_kwargs) or [])
        except Exception as exc:  # adapters shouldn't raise; if one does, degrade it
            detail = retailer_http._redact_query_strings(
                str(exc) or exc.__class__.__name__)[:200]
            source_reports.append({"slug": slug, "state": "DEGRADED", "candidates": 0,
                                   "detail": f"discover raised: {detail}"})
            continue
        source_reports.append({
            "slug": slug, "state": getattr(src, "state", "WORKING"),
            "detail": getattr(src, "state_detail", ""), "candidates": len(found)})
        raw_candidates.extend(found)
        if not dry_run and state is not None:
            state.set_last_run(slug, now_ts)

    # collapse within-run duplicates by (source, listing_id)
    seen: set[tuple[str, str]] = set()
    candidates: list[CandidateDeal] = []
    for c in raw_candidates:
        key = (c.source, c.listing_id)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(c)

    quiet = _in_quiet_hours(now_dt, cfg.alerts.quiet_hours)
    counts = {b: 0 for b in TERMINAL_BUCKETS}
    board_rows: list[schema.DealRow] = []
    outcomes: list[dict] = []

    for c in candidates:
        if not dry_run and state is not None:
            state.record_listing(c.source, c.listing_id, c.price, "live", ts=now_ts)
            if ledger_path is not None:
                _append_listing(ledger_path, c, captured_at)
        v = verifier(c)
        bucket, reason = _classify(cfg, c, v, comp_lookup, catalog, board_rows, state,
                                   notifier, now_ts, quiet, captured_at, dry_run)
        counts[bucket] += 1
        outcomes.append({"source": c.source, "listing_id": c.listing_id,
                         "terminal": bucket, "reason": reason})

    schema.assert_sweep(board_rows)  # STOP-gate belt on every constructed row

    board = {
        "event": event, "sweep_id": sweep_id, "captured_window": captured_at,
        "notes": f"Discovery pipeline - {len(board_rows)} verified-buyable rows",
        "deals": [asdict(r) for r in board_rows],
        "promo_codes": [], "bundled_offers": [], "watchlist_results": [],
        # render-shaped so the dashboard shows each source's honest state
        "sources": [{"name": s["slug"], "tier": "discovery", "status": s["state"],
                     "note": s.get("detail", "")} for s in source_reports],
        "counts": counts,
    }
    manifest = {
        "sweep_id": sweep_id, "captured_at": captured_at, "event": event,
        "dry_run": dry_run, "quiet_hours": quiet,
        "candidates": len(candidates), "counts": counts,
        "sources": source_reports, "outcomes": outcomes, "board": board,
    }
    # invariant: no silent drops
    assert sum(counts.values()) == len(candidates) == len(outcomes), \
        "manifest counts must reconcile"
    return manifest


# ------------------------------------------------------------ CLI

def main(argv: list[str] | None = None, *, cfg: Any = None, sources: list | None = None,
         verifier: Verifier | None = None, comp_lookup: CompLookup | None = None,
         notifier: Any = None, state: Any = None, catalog: dict | None = None,
         now_ts: int | None = None, now_dt: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scanner.discovery.pipeline",
        description="Run the discovery deal pipeline once (not a daemon).")
    parser.add_argument("--once", action="store_true",
                        help="run a single one-shot pass (the scheduler invokes this)")
    parser.add_argument("--sources", default="",
                        help="comma-separated adapter slugs (default: discovery.sources)")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate + report only: zero network, no alerts, no writes")
    parser.add_argument("--out", default=None,
                        help="output root (default: repo root; writes data/poke/)")
    args = parser.parse_args(argv)

    if not args.once and not args.dry_run:
        parser.print_usage()
        print("nothing to do: pass --once (or --dry-run to validate without side effects)")
        return 2

    cfg = cfg or cfg_mod.load()
    root = Path(args.out) if args.out else cfg_mod.ROOT
    source_slugs = ([s.strip() for s in args.sources.split(",") if s.strip()]
                    if args.sources else None)
    state = state if state is not None else State()
    poke_dir = root / "data" / "poke"
    ledger_path = None if args.dry_run else poke_dir / "price_history.jsonl"

    try:
        manifest = run_once(
            cfg, sources=sources, verifier=verifier, comp_lookup=comp_lookup,
            notifier=notifier, state=state, catalog=catalog, source_slugs=source_slugs,
            now_ts=now_ts, now_dt=now_dt, dry_run=args.dry_run, ledger_path=ledger_path)
    except PipelineConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2

    counts = manifest["counts"]
    summary = " ".join(f"{k}={v}" for k, v in counts.items())
    print(f"candidates={manifest['candidates']} {summary} "
          f"quiet_hours={manifest['quiet_hours']} dry_run={manifest['dry_run']}")
    degraded = [s for s in manifest["sources"] if s["state"] not in ("WORKING",)]
    for s in degraded:
        print(f"  source {s['slug']}: {s['state']} - {s.get('detail', '')}")

    if args.dry_run:
        print("dry-run: no board/manifest written, no alerts, no network.")
        return 0

    # Write JSON evidence first (survives a golden halt), then render the
    # dashboard. The discovery board can be legitimately empty, so no min_rows
    # acquisition floor here; the golden belt (Buyable-now evidence, dangling
    # anchors, provenance) still runs and halts the dashboard write on failure.
    poke_dir.mkdir(parents=True, exist_ok=True)
    sweep_id = manifest["sweep_id"]
    board_path = poke_dir / f"{sweep_id}.json"
    board_path.write_text(
        json.dumps(manifest["board"], indent=2, ensure_ascii=False), encoding="utf-8")
    (poke_dir / f"{sweep_id}.manifest.json").write_text(
        json.dumps({k: v for k, v in manifest.items() if k != "board"},
                   indent=2, ensure_ascii=False), encoding="utf-8")

    html = render_mod.render_sweep(manifest["board"])   # STOP gate runs again inside
    fails = golden_mod.golden_check(html, min_rows=0)
    if fails:
        for message in fails:
            print(f"GOLDEN FAIL: {message}")
        print(f"HALTED: dashboard not written ({len(fails)} golden failures). "
              f"Evidence kept at {board_path}")
        return 1

    dash_dir = root / "dashboards"
    dash_dir.mkdir(parents=True, exist_ok=True)
    dash_path = dash_dir / f"{sweep_id}.html"
    dash_path.write_text(html, encoding="utf-8")
    print(f"board: {board_path}")
    print(f"dashboard: {dash_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
