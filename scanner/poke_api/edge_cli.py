"""Personal edge layer CLI (Session E Slice G).

    python -m scanner.poke_api.edge_cli <command>

Commands (aligned with the Phase C ``lab`` CLI; decisions/outcomes share the SAME
append-only ``paper_decisions.jsonl`` ledger because an edge packet's id uses the
same recipe as an opportunity id):

  list                    score + list edge packets (sealed + raw/graded)
  show   --id ID          one edge packet
  record --id ID          record a paper decision FROM an edge packet
  outcome --id ID --status S   mark what happened later
  divergence-audit        API-vs-external audit — dry/local by default; external
                          (PPT/card provider) only with an explicit --yes + a key

The read commands are structurally 0-credit; ``divergence-audit`` is the only
surface that can spend credits, and only in external mode with ``--yes``.
"""
from __future__ import annotations

import argparse
import json

from . import divergence as dv_mod
from . import edge as edge_mod
from . import paper_ledger as ledger_mod


def _packets(deps):
    return edge_mod.build_edge_packets(deps, as_of=deps.today)


def _find(packets, edge_packet_id):
    for p in packets:
        if p["edge_packet_id"] == edge_packet_id:
            return p
    return None


def _fmt_money(value) -> str:
    return f"${value:.2f}" if isinstance(value, (int, float)) else "-"


def _print_packets(packets) -> None:
    print(f"{len(packets)} edge packets (score desc)\n")
    for p in packets:
        print(f"[{p['decision_hint']:<20}] {p['score']:>5} {p['subject_key']} "
              f"({p['asset_class']})")
        print(f"    {p['trade_type']}: {p['thesis']}")
        print(f"    entry {_fmt_money((p.get('entry_provenance') or {}).get('entry_price'))}"
              f"  comp {_fmt_money((p.get('comp_provenance') or {}).get('estimate'))}"
              f"  net {_fmt_money(p.get('expected_net'))}"
              f"  posture {','.join(p.get('source_posture') or []) or '-'}")
        if p.get("blockers"):
            print(f"    blockers: {', '.join(p['blockers'])}")
        if p.get("grading_ev"):
            g = p["grading_ev"]
            print(f"    grading EV [{g['status']}] net {_fmt_money(g.get('expected_net'))}"
                  f" (target {g.get('target_grade') or '-'})")
        print()


def _print_audit(result) -> None:
    print(f"divergence audit [{result['mode']}] - {result['message']}")
    if result.get("refused"):
        return
    if result.get("spend_estimate", {}).get("credits"):
        print(f"  estimated spend: ~{result['spend_estimate']['credits']} credit(s)")
    for r in result.get("rows", []):
        flag = "BLOCKING" if r.get("blocking") else ("material" if r.get("material") else "ok")
        print(f"  [{flag:<8}] {r['subject_key']:<28} {r['category']}"
              f"  ours={_fmt_money(r.get('ours'))} theirs={_fmt_money(r.get('theirs'))}"
              f"  ({r.get('delta_pct')}%)")
        print(f"             {r.get('note', '')}")
    if result.get("hard_stopped"):
        print("  HARD STOP: daily remaining below floor; stopped before the next subject")
    print(f"  result: {'FAILED (material unexplained divergence)' if result['failed'] else 'ok'}"
          f"  credits_spent={result.get('credits_spent', 0)}")


def _build_argparser():
    p = argparse.ArgumentParser(
        prog="python -m scanner.poke_api.edge_cli",
        description="Personal edge layer: list/show packets, record paper decisions, "
                    "and run the off-hot-path API-vs-external divergence audit.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="score + list edge packets")
    pl.add_argument("--json", action="store_true")
    pl.add_argument("--asset-class", help="filter: sealed | raw | graded")
    pl.add_argument("--decision", help="filter by decision hint")

    ps = sub.add_parser("show", help="show one edge packet by id")
    ps.add_argument("--id", required=True)
    ps.add_argument("--json", action="store_true")

    pr = sub.add_parser("record", help="record a paper decision from an edge packet")
    pr.add_argument("--id", required=True)
    pr.add_argument("--decision", help="override the computed decision hint")
    pr.add_argument("--reason", default="")

    po = sub.add_parser("outcome", help="mark what happened to a recorded packet")
    po.add_argument("--id", required=True)
    po.add_argument("--status", required=True,
                    help="one of " + ", ".join(sorted(ledger_mod.OUTCOME_STATUSES)))
    po.add_argument("--price", type=float)
    po.add_argument("--net", type=float)
    po.add_argument("--note", default="")
    po.add_argument("--observed-at")

    pd = sub.add_parser("divergence-audit",
                        help="API-vs-external divergence audit (dry/local unless --yes)")
    pd.add_argument("--products", default="", help="comma-separated sealed product keys")
    pd.add_argument("--assets", default="", help="comma-separated raw/graded asset keys")
    pd.add_argument("--local", action="store_true",
                    help="force dry/local mode (0 credits); the default when --yes is absent")
    pd.add_argument("--yes", action="store_true",
                    help="operator go-ahead for the surfaced external credit spend")
    pd.add_argument("--json", action="store_true")
    return p


def _cmd_list(args, deps) -> int:
    packets = _packets(deps)
    if args.asset_class:
        packets = [p for p in packets if p["asset_class"] == args.asset_class]
    if args.decision:
        packets = [p for p in packets if p["decision_hint"] == args.decision]
    if args.json:
        print(json.dumps({"summary": edge_mod.edge_summary(packets),
                          "edge_packets": packets}, indent=2))
    else:
        _print_packets(packets)
    return 0


def _cmd_show(args, deps) -> int:
    p = _find(_packets(deps), args.id)
    if p is None:
        print(f"unknown edge_packet_id: {args.id!r}")
        return 1
    print(json.dumps(p, indent=2) if args.json
          else f"{p['subject_key']} [{p['decision_hint']}] {p['trade_type']}\n"
               f"  {json.dumps(p, indent=2)}")
    return 0


def _cmd_record(args, deps) -> int:
    p = _find(_packets(deps), args.id)
    if p is None:
        print(f"unknown edge_packet_id: {args.id!r}")
        return 1
    # Record the ledger-shaped VIEW (not the raw packet) so the durable audit row
    # keeps entry_price/market_comp/product_key/... under the Phase C column names.
    wrote = ledger_mod.record_decision(
        deps.decisions_path, edge_mod.paper_ledger_view(p), decision=args.decision,
        reason=args.reason, as_of=p["as_of"], recorded_at=deps.today)
    print(f"{'recorded' if wrote else 'already recorded'}: {p['subject_key']} -> "
          f"{args.decision or p['decision_hint']} ({p['edge_packet_id'][:12]})")
    return 0


def _cmd_outcome(args, deps) -> int:
    try:
        wrote = ledger_mod.record_outcome(
            deps.decisions_path, args.id, args.status, args.observed_at or deps.today,
            realized_price=args.price, realized_net=args.net, note=args.note)
    except ValueError as exc:
        print(str(exc))
        return 1
    print(f"{'recorded' if wrote else 'already recorded'} outcome {args.status} "
          f"for {args.id[:12]}")
    return 0


def _cmd_divergence(args, deps) -> int:
    products = [k.strip() for k in args.products.split(",") if k.strip()]
    assets = [k.strip() for k in args.assets.split(",") if k.strip()]
    # External intent = subjects listed or --yes passed, unless --local forces the free
    # path. A bare `divergence-audit` defaults to the safe local mode. This makes
    # `divergence-audit --products X` (no --yes) REFUSE and surface the spend, rather
    # than silently running local — the operator asked to compare against the provider.
    wants_external = (bool(products or assets) or args.yes) and not args.local
    result = dv_mod.run_audit(deps, product_keys=products, asset_keys=assets,
                              local=not wants_external, yes=args.yes)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_audit(result)
    if result.get("refused"):
        return 2
    return 1 if result.get("failed") else 0


def main(argv=None, *, deps=None) -> int:
    args = _build_argparser().parse_args(argv)
    if deps is None:                       # lazy import avoids an import cycle with router
        from .. import config as config_mod
        from . import router as router_mod
        deps = router_mod.build_deps(config_mod.load())

    if args.cmd == "list":
        return _cmd_list(args, deps)
    if args.cmd == "show":
        return _cmd_show(args, deps)
    if args.cmd == "record":
        return _cmd_record(args, deps)
    if args.cmd == "outcome":
        return _cmd_outcome(args, deps)
    if args.cmd == "divergence-audit":
        return _cmd_divergence(args, deps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
