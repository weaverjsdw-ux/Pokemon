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

Verifier scope: the default verifier resolves a **slickdeals** thread to its
real merchant page and verifies stock+price there (Slice 6B,
``verify.verify_slickdeals_candidate``); every other current live source still
honestly degrades to ``unverifiable`` (eBay item lookup needs the pending
keyset; catalog-retailer verification would check a *different* listing than the
one discovered). The VERIFIED_BUYABLE -> alert path is proven by tests with
injected verifiers and, for slickdeals, end-to-end from a resolved thread.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .. import config as cfg_mod
from .. import main as main_mod
from .. import market as market_mod
from .. import resale
from ..comps import engine as comps_engine
from ..notify import DealAlert, Notifier
from ..poke_api import history as history_mod
from ..retailers import http as retailer_http
from ..state import State
from . import assets_feed
from . import golden as golden_mod
from . import ledger as ledger_mod
from . import render as render_mod
from . import resolve as resolve_mod
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

def default_verifier(cfg: Any, http_get: Callable | None = None) -> Verifier:
    """Route by candidate origin. Slickdeals candidates are resolved to a real
    merchant page and verified there (Slice 6B, ``verify.verify_slickdeals_candidate``
    -> ``verify_page``); every other current live source still honestly degrades
    to unverifiable (network-free) until its same-listing check (eBay item lookup,
    catalog-retailer matching) lands in a later slice.

    ``http_get`` is threaded into the fetching verifier so a caller that injects
    a network stub into ``run_once`` gets a hermetic verify stage too (the
    ``run_once`` "pure of network beyond injected stages" contract). Left None on
    a real ``--once`` run, it defaults to ``retailers/http.py``; ``--dry-run``
    swaps this out entirely for ``_dry_run_verifier``."""

    def verify(candidate: CandidateDeal) -> StockVerification:
        if candidate.source == "slickdeals":
            return verify_mod.verify_slickdeals_candidate(candidate, http_get=http_get)
        reason = (f"no same-listing buyability check wired for source "
                  f"{candidate.source!r}; an eBay item lookup / catalog-retailer "
                  f"match land in a later slice")
        return StockVerification(
            state=verify_mod.UNKNOWN_NO_ALERT, stock_status="unverifiable",
            verified_price=None, expected_price=candidate.price, price_matches=None,
            buy_url="", checked_at=verify_mod._now_iso(), source=candidate.source,
            method="none", evidence="", degraded_reason=reason)

    return verify


def _dry_run_verifier(candidate: CandidateDeal) -> StockVerification:
    """The verify stage in --dry-run: network-free by construction (no thread
    fetch, no merchant-page GET), so the zero-network guarantee never depends on
    a candidate's source. Every candidate honestly degrades to unverifiable."""
    return StockVerification(
        state=verify_mod.UNKNOWN_NO_ALERT, stock_status="unverifiable",
        verified_price=None, expected_price=candidate.price, price_matches=None,
        buy_url="", checked_at=verify_mod._now_iso(), source=candidate.source,
        method="none", evidence="",
        degraded_reason="dry-run: purchasability verification skipped (no network)")


# Resolved-destination identity for verify-stage dedupe. Amazon collapses to the
# ASIN and eBay to the item id, so tracking query strings and title slugs never
# split one listing in two. Every other host keeps host + path + query: an
# affiliate redirector such as goto.walmart.com/c/<ids>?u=<product url> carries
# the product only in its query, so host + path alone would merge two different
# products and hand one listing's verdict to the other. Under-merging costs one
# GET; over-merging reports the wrong listing, so ties go to under-merging.
_ASIN_PATH_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Za-z0-9]{10})(?=/|$)")
_EBAY_ITEM_PATH_RE = re.compile(r"^/itm/(?:[^/]+/)?(\d{6,})/?$")


def destination_key(url: str) -> str:
    parsed = urlparse((url or "").strip())
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    path = parsed.path or "/"
    if host == "amazon.com" or host.endswith(".amazon.com"):
        asin = _ASIN_PATH_RE.search(path)
        if asin:
            return f"amazon.com/asin/{asin.group(1).upper()}"
    if host == "ebay.com" or host.endswith(".ebay.com"):
        item = _EBAY_ITEM_PATH_RE.match(path)
        if item:
            return f"ebay.com/itm/{item.group(1)}"
    return f"{host}{path}?{parsed.query}" if parsed.query else f"{host}{path}"


class _MerchantPageMemo:
    """Verify-stage getter for one run: each resolved merchant destination is
    fetched at most once, however many candidates resolve to it.

    Slickdeals-host requests (the thread page and its /click hop) pass straight
    through: the destination is unknown until they have run, so a duplicate still
    spends its own thread GET and hop and saves exactly one GET, the merchant
    page. Only the fetched page is shared; verify_page still classifies every
    candidate against its OWN expected price and keeps its own audit trail."""

    def __init__(self, http_get: Callable | None = None):
        self._http_get = http_get
        self._pages: dict[str, tuple[str, Any, Exception | None]] = {}
        self.shared_fetched_at = ""

    def start_candidate(self) -> None:
        self.shared_fetched_at = ""

    def __call__(self, url: str, **kwargs: Any):
        get = self._http_get or retailer_http.get   # resolved per call, as the verifier does
        if not resolve_mod.safe_merchant_url(url):
            return get(url, **kwargs)
        key = destination_key(url)
        if key in self._pages:
            fetched_at, resp, exc = self._pages[key]
            self.shared_fetched_at = fetched_at
            if exc is not None:
                raise exc
            return resp
        fetched_at = verify_mod._now_iso()
        try:
            resp = get(url, **kwargs)
        except Exception as exc:
            self._pages[key] = (fetched_at, None, exc)
            raise
        self._pages[key] = (fetched_at, resp, None)
        return resp


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
        if product.get("asset_class"):
            # A single's comp is read-first off the append-only ledger: offline,
            # 0 credits, and it degrades to an honest no-comp rather than
            # reaching for a live source mid-run.
            if "obs" not in box:
                box["obs"] = history_mod.read_ledger(
                    cfg_mod.ROOT / "data" / "poke" / "price_history.jsonl").observations
            return assets_feed.asset_comp(
                box["obs"], candidate.matched_product_key or "", product)
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
    is_asset = bool(product and product.get("asset_class"))
    row = schema.DealRow(
        item=c.item_name,
        asset_class=c.asset_class or "sealed",
        category=(assets_feed.SINGLES_CATEGORY if is_asset
                  else sweep_mod._category(product) if product else "discovered"),
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
    if is_asset:
        # STOP gate: a graded row needs grade+grader and a raw row needs
        # condition. They come off the matched asset, never off the listing
        # title — the title is what we matched, not a source of truth.
        row.grade = str(product.get("grade") or "")
        row.grader = str(product.get("grader") or "")
        row.condition = str(product.get("condition") or "")
        row.variant = row.variant or str(product.get("card_number") or "")
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

def _match_asset_candidate(c: CandidateDeal, assets: dict) -> CandidateDeal:
    """Attach a raw/graded asset to a candidate the sealed catalog did not match.

    An already-matched (Ring 1) candidate is returned untouched — sealed wins, so
    turning the feed on can never change a sealed disposition. An unmatched title
    with no single unambiguous asset is also returned untouched (honest Ring 2/3),
    because raw NM and PSA 10 of one card are different money."""
    if c.matched_product_key:
        return c
    asset_key = assets_feed.match_asset(c.item_name, assets)
    if asset_key is None:
        return c
    asset = assets[asset_key]
    return replace(
        c,
        matched_product_key=asset_key,
        matched_set=str(asset.get("set") or "") or c.matched_set,
        asset_class=str(asset.get("asset_class") or "raw"),
        variant=c.variant or str(asset.get("card_number") or ""),
    )


def _classify(cfg: Any, c: CandidateDeal, v: StockVerification, comp_lookup: CompLookup,
              catalog: dict, board_rows: list, state: Any, notifier: Any,
              now_ts: int, quiet: bool, captured_at: str, dry_run: bool,
              assets: dict | None = None) -> tuple[str, str]:
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
    if product is None and assets and c.matched_product_key:
        # Singles live in their own catalog; the sealed one is never widened, so
        # sealed matching and every sealed adapter see exactly what they saw.
        product = assets.get(c.matched_product_key)
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
        try:
            notifier.send_deal(deal, push=not quiet)
        except Exception as exc:
            # A notifier failure must never abort the run (and lose the board /
            # every other candidate's disposition). The real Notifier already
            # swallows per-channel RequestExceptions; this is the belt for an
            # unexpected failure. Dedupe is deliberately NOT recorded so the next
            # run re-attempts delivery instead of suppressing this alert forever.
            detail = retailer_http._redact_query_strings(
                str(exc) or exc.__class__.__name__)[:120]
            print(f"  ! deal notify failed for {c.source}:{c.listing_id}: {detail}",
                  file=sys.stderr)
            return "alerted", f"{reason}; notify failed (not recorded, retries next run)"
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
    assets: dict | None = None,
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
    assets_error = ""
    if assets is None:
        assets, assets_error = assets_feed.load_feed_assets(cfg)
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

    page_memo: _MerchantPageMemo | None = None
    if verifier is None:
        # dry-run uses a network-free verifier so zero-network is structural, not
        # incidental on the live resolver happening not to fetch. A live run
        # threads any injected http_get into the verifier so an instrumented
        # caller stays hermetic (not just the DISCOVER stage), through a per-run
        # memo that fetches each resolved merchant destination once.
        if dry_run:
            verifier = _dry_run_verifier
        else:
            page_memo = _MerchantPageMemo(http_get)
            verifier = default_verifier(cfg, http_get=page_memo)
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

    # Singles match pass. Runs only on candidates the SEALED catalog did not
    # claim, so a sealed match can never be displaced by an asset and sealed
    # dispositions are untouched. The adapters were never handed the asset
    # catalog: they discover exactly what they discovered before.
    if assets:
        candidates = [_match_asset_candidate(c, assets) for c in candidates]

    quiet = _in_quiet_hours(now_dt, cfg.alerts.quiet_hours)
    counts = {b: 0 for b in TERMINAL_BUCKETS}
    board_rows: list[schema.DealRow] = []
    outcomes: list[dict] = []

    for c in candidates:
        if not dry_run and state is not None:
            state.record_listing(c.source, c.listing_id, c.price, "live", ts=now_ts)
            if ledger_path is not None:
                _append_listing(ledger_path, c, captured_at)
        if page_memo is not None:
            page_memo.start_candidate()
        v = verifier(c)
        if page_memo is not None and page_memo.shared_fetched_at:
            # This candidate's merchant page was fetched for an earlier candidate
            # with the same destination: carry the real fetch time and mark the
            # method, so the audit trail never implies a second, fresher look.
            v = replace(v, checked_at=page_memo.shared_fetched_at,
                        method=f"{v.method}+shared_page")
        bucket, reason = _classify(cfg, c, v, comp_lookup, catalog, board_rows, state,
                                   notifier, now_ts, quiet, captured_at, dry_run,
                                   assets=assets)
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
    if assets:
        manifest["assets_fed"] = len(assets)
    if assets_error:
        # Contained, never raised: a malformed assets.yaml must not take the
        # sealed pipeline down, and it must not vanish either.
        manifest["assets_error"] = assets_error
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
