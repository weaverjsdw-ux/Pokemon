"""Money Hypothesis Lab orchestrator + CLI (Phase C).

Builds deterministic opportunities from the read-first comp + ledger momentum +
optional verified deal candidates the private API already produces, and drives
the paper-trade ledger (record a decision, mark an outcome later, replay what
the signals did). Read path is network-free and PPT-free; writes go to the
append-only ``paper_decisions.jsonl``.

``resolve_comp_row``/``_ledger_comp_row`` live here (not in ``router``) so both
the API endpoints and this orchestrator share one read-first comp resolution;
``router`` imports them. This module never imports ``router`` at load time (the
CLI imports it lazily), so there is no import cycle.
"""
from __future__ import annotations

import json
from dataclasses import asdict

from .. import resale
from . import candidates as candidates_mod
from . import history as history_mod
from . import model as model_mod
from . import opportunities as opp_mod
from . import paper_ledger as ledger_mod


def _ledger_comp_row(obs: dict, product_key: str, product: dict) -> dict:
    """Shape a latest ledger market_comp observation into a legacy comp row so
    model.comp_response can adapt it (money-formatted estimate parses back)."""
    price = history_mod._comp_value(obs)
    src = history_mod.source_of(obs)
    url = str(obs.get("source_url") or "")
    return {
        "productKey": product_key,
        "status": "ok",
        "estimate": resale._money(price) if price is not None else "",
        "confidence": str(obs.get("comp_confidence") or "low"),
        "confidenceReason": "latest recorded market_comp (no fresh comp cache)",
        "compBasis": "ledger latest",
        "sources": [{"source": src, "status": "ok", "price": price, "url": url}],
        "sourceUrl": url,
        "url": url,
        "checkedAt": obs.get("capture_date"),
        "cacheHit": False,
    }


def resolve_comp_row(comp_provider, observations, key, product):
    """Read-first comp resolution: in-house comp cache (offline), else the latest
    ledger market_comp (offline), else None. Never constructs a network source."""
    cached = comp_provider.cached(key, product)
    if cached:
        return cached
    ikey = history_mod.item_key_for_product(product, key)
    latest = history_mod.latest(observations, ikey)
    return _ledger_comp_row(latest, key, product) if latest is not None else None


def build_opportunity_row(deps, key, product, observations, *, as_of) -> dict:
    """One opportunity (as a dict) for a single catalog product from deps."""
    row = resolve_comp_row(deps.comp_provider, observations, key, product)
    if row:
        comp = model_mod.comp_response(key, product, row)
    else:
        comp = model_mod.no_comp_response(
            key, product, status="no_history",
            detail="no cached comp; ledger has no comp for this item")
    ikey = history_mod.item_key_for_product(product, key)
    momentum = history_mod.momentum(
        observations, ikey, today=deps.today,
        stale_days=deps.cfg.opportunity.stale_after_days)
    candidate = deps.candidate_for(key, product) if getattr(deps, "candidate_for", None) else None
    return asdict(opp_mod.build_opportunity(key, product, comp, momentum, candidate,
                                            deps.cfg, as_of=as_of))


def build_opportunities(deps, *, as_of=None) -> list[dict]:
    """Scored opportunities for the whole catalog. Read-first, no network.
    Sorted by score descending (stable on product_key)."""
    as_of = as_of or deps.today
    observations = deps.read_observations()   # single ledger read for the whole pass
    opps = [build_opportunity_row(deps, key, product, observations, as_of=as_of)
            for key, product in deps.products.items()]
    opps.sort(key=lambda o: (-o["score"], o["product_key"]))
    return opps


def summary(opps: list[dict]) -> dict:
    by_decision: dict[str, int] = {}
    by_trade_type: dict[str, int] = {}
    by_momentum: dict[str, int] = {}
    live = 0
    for o in opps:
        by_decision[o["decision_hint"]] = by_decision.get(o["decision_hint"], 0) + 1
        by_trade_type[o["trade_type"]] = by_trade_type.get(o["trade_type"], 0) + 1
        by_momentum[o["momentum_status"]] = by_momentum.get(o["momentum_status"], 0) + 1
        if o["decision_hint"] == "LIVE_PACKET_ELIGIBLE":
            live += 1
    return {
        "count": len(opps),
        "by_decision": by_decision,
        "by_trade_type": by_trade_type,
        "by_momentum_status": by_momentum,
        "live_packet_eligible": live,
    }


# ------------------------------------------------------- activation / dormancy

def _closest_blocker(o: dict) -> str:
    """The single most-proximate reason this opportunity is not live-eligible."""
    if o.get("market_comp") is None:
        return "no comp"
    if o.get("stale"):
        return "stale comp"
    if o.get("entry_price") is None:
        return "no verified entry price"
    if o.get("verdict_tier") != "BUY":
        return "fee-adjusted margin below buy floor"
    if o.get("trade_type") not in opp_mod.LIVE_ELIGIBLE:
        return "trade type not live-eligible"
    return "below live floor (net / roi / confidence)"


def _why_no_live(*, live, verified, no_entry, products) -> str:
    if live:
        return f"{live} product(s) are live-packet-eligible today"
    if verified == 0:
        return ("no verified buy candidates yet — every opportunity lacks a verified "
                "entry price; add one via `candidate-add` or replay a discovery manifest "
                "with `candidates-from-manifest`")
    return ("verified candidate(s) present but none clear the live floor "
            "(net / ROI / confidence), comp freshness, or an actionable trade type")


def activation_report(opps: list[dict], candidate_rows: list[dict] | None = None) -> dict:
    """Make the 'dormant but correct' state legible: what decisions exist, why there
    are no live packets, which products are closest, and what would unlock them.

    Combines opportunity-level facts (decisions, missing entry / comp / freshness)
    with the verified-candidate ledger (how many candidates, how many entry-verified,
    how many are parser_suspect / other evidence-only rows)."""
    candidate_rows = candidate_rows or []
    by_decision: dict[str, int] = {}
    no_entry = no_comp = stale = 0
    for o in opps:
        by_decision[o["decision_hint"]] = by_decision.get(o["decision_hint"], 0) + 1
        if o.get("entry_price") is None:
            no_entry += 1
        if o.get("market_comp") is None:
            no_comp += 1
        if o.get("stale"):
            stale += 1

    verified = sum(1 for r in candidate_rows if r.get("entry_verified"))
    parser_suspect = sum(1 for r in candidate_rows
                         if str(r.get("stock_status") or "") == "parser_suspect")
    live = by_decision.get("LIVE_PACKET_ELIGIBLE", 0)
    paper = by_decision.get("PAPER_BUY", 0)

    # top blockers: opportunity-side (why no buyable edge) + candidate-side evidence.
    blocker_counts: dict[str, int] = {}
    if no_entry:
        blocker_counts["opportunities_without_verified_entry_price"] = no_entry
    if no_comp:
        blocker_counts["opportunities_without_comp"] = no_comp
    if stale:
        blocker_counts["opportunities_with_stale_comp"] = stale
    for r in candidate_rows:
        if r.get("entry_verified"):
            continue
        status = str(r.get("stock_status") or "unknown")
        blocker_counts[f"candidate_{status}"] = blocker_counts.get(f"candidate_{status}", 0) + 1
    top_blockers = sorted(({"blocker": k, "count": v} for k, v in blocker_counts.items()),
                          key=lambda b: (-b["count"], b["blocker"]))

    closest = []
    for o in sorted(opps, key=lambda o: -float(o.get("score") or 0.0)):
        if o["decision_hint"] == "LIVE_PACKET_ELIGIBLE":
            continue
        closest.append({"product_key": o["product_key"], "score": o.get("score"),
                        "decision_hint": o["decision_hint"], "trade_type": o.get("trade_type"),
                        "blocker": _closest_blocker(o)})
        if len(closest) >= 5:
            break

    return {
        "products_seen": len(opps),
        "candidates_seen": len(candidate_rows),
        "verified_candidates": verified,
        "paper_buy_count": paper,
        "live_packet_eligible_count": live,
        "watch_count": by_decision.get("WATCH", 0),
        "reject_count": by_decision.get("REJECT", 0),
        "no_entry_price_count": no_entry,
        "no_comp_count": no_comp,
        "stale_comp_count": stale,
        "parser_suspect_count": parser_suspect,
        "top_blockers": top_blockers,
        "closest_products": closest,
        "dormant": live == 0 and paper == 0,
        "why_no_live_packets": _why_no_live(live=live, verified=verified,
                                            no_entry=no_entry, products=len(opps)),
    }


# ---------------------------------------------------------------- CLI

def _fmt_money(value) -> str:
    return f"${value:.2f}" if isinstance(value, (int, float)) else "-"


def _print_opportunities(opps: list[dict]) -> None:
    print(f"{len(opps)} opportunities (score desc)\n")
    for o in opps:
        print(f"[{o['decision_hint']:<20}] {o['score']:>5} {o['product_key']}")
        print(f"    {o['trade_type']}: {o['hypothesis']}")
        print(f"    entry {_fmt_money(o['entry_price'])}  comp {_fmt_money(o['market_comp'])}"
              f"  net {_fmt_money(o['expected_net'])}"
              f"  roi {o['expected_roi_pct'] if o['expected_roi_pct'] is not None else '-'}"
              f"  conf {o['latest_confidence'] or '-'}  {'STALE' if o['stale'] else 'fresh'}")
        if o["risks"]:
            print(f"    risks: {', '.join(o['risks'])}")
        print()


def _print_report(rep: dict, current: dict) -> None:
    print("Money Hypothesis Lab — signals report\n")
    print(f"opportunities recorded: {rep['decisions_recorded']}  "
          f"outcomes: {rep['outcomes_recorded']}")
    print(f"by decision: {rep['by_decision']}\n")
    for tt, agg in sorted(rep["by_trade_type"].items()):
        hr = "-" if agg["hit_rate"] is None else f"{agg['hit_rate']:.0%}"
        mn = "-" if agg["mean_realized_net"] is None else _fmt_money(agg["mean_realized_net"])
        print(f"  {tt:<26} n={agg['count']:>3}  outcomes={agg['with_outcome']:>3}"
              f"  hit_rate={hr:>5}  mean_net={mn}")


def _print_activation(a: dict) -> None:
    print("\nMoney Hypothesis Lab — activation / dormancy")
    print(f"  state: {'DORMANT' if a['dormant'] else 'ACTIVE'} — {a['why_no_live_packets']}")
    print(f"  products_seen={a['products_seen']}  candidates_seen={a['candidates_seen']}  "
          f"verified_candidates={a['verified_candidates']}")
    print(f"  decisions: live={a['live_packet_eligible_count']} paper={a['paper_buy_count']} "
          f"watch={a['watch_count']} reject={a['reject_count']}")
    print(f"  gaps: no_entry_price={a['no_entry_price_count']} no_comp={a['no_comp_count']} "
          f"stale_comp={a['stale_comp_count']} parser_suspect={a['parser_suspect_count']}")
    if a["top_blockers"]:
        print("  top blockers:")
        for b in a["top_blockers"]:
            print(f"    {b['count']:>3}  {b['blocker']}")
    if a["closest_products"]:
        print("  closest products:")
        for c in a["closest_products"]:
            print(f"    {c['score']:>5}  {c['product_key']:<28} {c['decision_hint']:<20} "
                  f"blocker: {c['blocker']}")


def _read_candidates(deps) -> list[dict]:
    reader = getattr(deps, "read_candidates", None)
    if reader is not None:
        return list(reader())
    path = getattr(deps, "candidates_path", None)
    return candidates_mod.read_rows(path) if path else []


def _cmd_candidate_add(args, deps, today) -> int:
    if args.product_key not in deps.products:
        print(f"unknown product_key: {args.product_key!r} (not in catalog) — not written")
        return 1
    observed_at = args.observed_at or today
    checked_at = args.stock_checked_at or observed_at
    product = deps.products[args.product_key]
    c = candidates_mod.make_candidate(
        source=args.source, product_key=args.product_key, listing_id=args.listing_id,
        item_name=args.item_name or product.get("name") or args.product_key,
        entry_price=args.entry_price, buy_url=args.buy_url, observed_at=observed_at,
        stock_status=args.stock_status, stock_evidence=args.evidence,
        stock_checked_at=checked_at, evidence_method=args.evidence_method,
        source_url=args.source_url, retailer=args.retailer, confidence=args.confidence,
        asset_class=str(product.get("asset_class") or "sealed"))
    wrote = candidates_mod.append_candidate(deps.candidates_path, c)
    kind = "entry-verified" if c.entry_verified else f"evidence-only ({c.reason})"
    tail = f" entry ${c.entry_price:.2f}" if c.entry_price is not None else ""
    print(f"{'appended' if wrote else 'already recorded'} {kind} candidate "
          f"{c.product_key} [{c.candidate_id[:12]}]{tail}")
    return 0


def _cmd_candidates_from_manifest(args, deps, today) -> int:
    from pathlib import Path
    mpath = Path(args.manifest)
    if not mpath.exists():
        print(f"manifest not found: {args.manifest}")
        return 1
    result = candidates_mod.load_and_replay(
        mpath, deps.products, source=args.source, observed_at=today)
    appended = sum(1 for c in result.candidates
                   if candidates_mod.append_candidate(deps.candidates_path, c))
    rep = result.summary()
    rep["appended"] = appended
    if args.json:
        print(json.dumps({"replay": rep, "blocked": result.blocked,
                          "unmatched": result.unmatched}, indent=2))
    else:
        note = f" - {result.note}" if result.note else ""
        print(f"manifest replay [{result.input_kind}]{note}")
        print(f"  scanned={result.scanned}  verified_buyable={len(result.candidates)}  "
              f"appended={appended}  blocked={len(result.blocked)}  "
              f"unmatched={len(result.unmatched)}")
        for b in result.blocked[:10]:
            print(f"    blocked: {b['item'][:44]} -> {b['reason']}")
        for u in result.unmatched[:10]:
            print(f"    unmatched: {u['item'][:44]} -> {u['reason']}")
    return 0


def _build_argparser():
    import argparse
    p = argparse.ArgumentParser(
        prog="python -m scanner.poke_api.lab",
        description="Money Hypothesis Lab (Phase C): score opportunities, record "
                    "paper decisions, mark outcomes, replay which signals work.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl_ = sub.add_parser("list", help="score opportunities across the catalog")
    pl_.add_argument("--json", action="store_true")

    pr = sub.add_parser("record", help="record a paper decision for one product")
    pr.add_argument("--product", required=True)
    pr.add_argument("--decision", help="override the computed decision hint")
    pr.add_argument("--reason", default="")
    pr.add_argument("--as-of")

    pa = sub.add_parser("record-all", help="record each opportunity's decision hint")
    pa.add_argument("--as-of")

    po = sub.add_parser("outcome", help="mark what happened to a recorded opportunity")
    po.add_argument("--opportunity", required=True)
    po.add_argument("--status", required=True,
                    help="one of " + ", ".join(sorted(ledger_mod.OUTCOME_STATUSES)))
    po.add_argument("--price", type=float)
    po.add_argument("--net", type=float)
    po.add_argument("--note", default="")
    po.add_argument("--observed-at")

    prp = sub.add_parser("report", help="signals report + decision/outcome replay")
    prp.add_argument("--json", action="store_true")
    prp.add_argument("--include-candidates", action="store_true",
                     help="also show the candidate activation / dormancy report")

    # ---- Phase C activation: verified candidate intake + replay + reporting ----
    ca = sub.add_parser("candidate-add",
                        help="append one evidence-backed verified candidate to the ledger")
    ca.add_argument("--product-key", required=True)
    ca.add_argument("--entry-price", help="observed buy price (only kept with stock evidence)")
    ca.add_argument("--buy-url", default="")
    ca.add_argument("--stock-status", default="unknown",
                    help="verified_buyable / in_stock / limited => entry; else evidence-only")
    ca.add_argument("--evidence", default="", help="stock/price evidence text")
    ca.add_argument("--source", default="manual_verified")
    ca.add_argument("--retailer", default="")
    ca.add_argument("--confidence", default="none")
    ca.add_argument("--listing-id", default="")
    ca.add_argument("--item-name", default="")
    ca.add_argument("--source-url", default="")
    ca.add_argument("--evidence-method", default="operator")
    ca.add_argument("--stock-checked-at", help="ISO datetime of the stock check (default observed-at)")
    ca.add_argument("--observed-at")

    cm = sub.add_parser("candidates-from-manifest",
                        help="replay a discovery board/manifest into candidate evidence")
    cm.add_argument("--manifest", required=True)
    cm.add_argument("--source", default="manifest_replay")
    cm.add_argument("--json", action="store_true")

    cr = sub.add_parser("candidates-report",
                        help="candidate activation / dormancy report (why no live packets)")
    cr.add_argument("--json", action="store_true")

    sub.add_parser("record-candidates",
                   help="record paper decisions for candidate-backed opportunities only")

    ce = sub.add_parser("candidates-from-ebay",
                        help="ingest eBay Browse candidates (requires eBay keyset; else not_configured)")
    ce.add_argument("--json", action="store_true")
    return p


def main(argv=None, *, deps=None) -> int:
    args = _build_argparser().parse_args(argv)
    if deps is None:                       # lazy import avoids an import cycle with router
        from .. import config as config_mod
        from . import router as router_mod
        deps = router_mod.build_deps(config_mod.load())
    decisions_path = deps.decisions_path
    today = deps.today

    if args.cmd == "list":
        opps = build_opportunities(deps, as_of=today)
        if args.json:
            print(json.dumps({"summary": summary(opps), "opportunities": opps}, indent=2))
        else:
            _print_opportunities(opps)
        return 0

    if args.cmd == "record":
        as_of = args.as_of or today
        opps = {o["product_key"]: o for o in build_opportunities(deps, as_of=as_of)}
        o = opps.get(args.product)
        if o is None:
            print(f"unknown product_key: {args.product!r}")
            return 1
        wrote = ledger_mod.record_decision(
            decisions_path, o, decision=args.decision, reason=args.reason,
            as_of=as_of, recorded_at=today)
        print(f"{'recorded' if wrote else 'already recorded'}: "
              f"{o['product_key']} -> {args.decision or o['decision_hint']} "
              f"({o['opportunity_id'][:12]})")
        return 0

    if args.cmd == "record-all":
        as_of = args.as_of or today
        opps = build_opportunities(deps, as_of=as_of)
        wrote = sum(1 for o in opps if ledger_mod.record_decision(
            decisions_path, o, as_of=as_of, recorded_at=today))
        print(f"recorded {wrote} new decision(s) of {len(opps)} opportunities")
        return 0

    if args.cmd == "outcome":
        try:
            wrote = ledger_mod.record_outcome(
                decisions_path, args.opportunity, args.status,
                args.observed_at or today, realized_price=args.price,
                realized_net=args.net, note=args.note)
        except ValueError as exc:
            print(str(exc))
            return 1
        print(f"{'recorded' if wrote else 'already recorded'} outcome "
              f"{args.status} for {args.opportunity[:12]}")
        return 0

    if args.cmd == "report":
        rows = ledger_mod.read_rows(decisions_path)
        rep = ledger_mod.signals_report(rows)
        current = ledger_mod.current_by_id(rows)
        activation = None
        if args.include_candidates:
            opps = build_opportunities(deps, as_of=today)
            activation = activation_report(opps, _read_candidates(deps))
        if args.json:
            payload = {"signals": rep, "current": current}
            if activation is not None:
                payload["activation"] = activation
            print(json.dumps(payload, indent=2))
        else:
            _print_report(rep, current)
            if activation is not None:
                _print_activation(activation)
        return 0

    if args.cmd == "candidate-add":
        return _cmd_candidate_add(args, deps, today)

    if args.cmd == "candidates-from-manifest":
        return _cmd_candidates_from_manifest(args, deps, today)

    if args.cmd == "candidates-report":
        opps = build_opportunities(deps, as_of=today)
        activation = activation_report(opps, _read_candidates(deps))
        current = [candidates_mod.to_opportunity_candidate(r)
                   for r in candidates_mod.current_entry_candidates(_read_candidates(deps)).values()]
        if args.json:
            print(json.dumps({"activation": activation, "candidates": current}, indent=2))
        else:
            _print_activation(activation)
        return 0

    if args.cmd == "record-candidates":
        as_of = today
        opps = build_opportunities(deps, as_of=as_of)
        backed = [o for o in opps if o.get("input_snapshot")]
        wrote = sum(1 for o in backed if ledger_mod.record_decision(
            decisions_path, o, as_of=as_of, recorded_at=today))
        print(f"recorded {wrote} candidate-backed decision(s) of {len(backed)} "
              f"candidate-backed opportunit(ies) [{len(opps)} scored]")
        return 0

    if args.cmd == "candidates-from-ebay":
        status = candidates_mod.ebay_candidate_source(deps.cfg)
        print(json.dumps(status, indent=2) if args.json
              else f"eBay candidate source: {status['status']} — {status['detail']}")
        return 0 if status["status"] != "error" else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
