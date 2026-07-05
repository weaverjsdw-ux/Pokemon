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
        if args.json:
            print(json.dumps({"signals": rep, "current": current}, indent=2))
        else:
            _print_report(rep, current)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
