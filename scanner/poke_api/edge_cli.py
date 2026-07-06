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

from .. import resale
from . import divergence as dv_mod
from . import edge as edge_mod
from . import paper_ledger as ledger_mod
from . import sources as sources_mod


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

    prc = sub.add_parser(
        "record-asset-comp",
        help="persist a sold-derived raw/graded asset comp into the price-history "
             "ledger (0-credit from-value default; operator-gated billed --refresh)")
    prc.add_argument("--asset-key", required=True)
    prc.add_argument("--comp", type=float,
                     help="already-captured sold-derived comp value (from-value mode)")
    prc.add_argument("--source", default="",
                     help="sold source slug (e.g. ppt_cards, pricecharting); an ask "
                          "source (ebay) is refused — an ask is context, never a comp")
    prc.add_argument("--confidence", default="none")
    prc.add_argument("--capture-date", help="ISO capture date of the observation (default: today)")
    prc.add_argument("--source-url", default="")
    prc.add_argument("--basis", default="", help="comp basis / provenance note")
    prc.add_argument("--refresh", action="store_true",
                     help="billed: fetch the comp from the configured external card source "
                          "and persist it (money-class; needs --yes + a key)")
    prc.add_argument("--refresh-independent", action="store_true", dest="refresh_independent",
                     help="0-PPT-credit live fetch from the independent PriceCharting/TCGplayer "
                          "sources; persists with the real source slug (needs poke.independent_sources)")
    prc.add_argument("--yes", action="store_true",
                     help="operator go-ahead for the surfaced --refresh credit spend")
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


def _today_ts(today) -> int:
    """Deterministic timestamp from the injected ISO ``today`` (no wall clock) for the
    resolver's capture labels on the billed refresh path."""
    from datetime import date, datetime
    try:
        return int(datetime(*[int(p) for p in str(today).split("-")]).timestamp())
    except (TypeError, ValueError):
        return int(datetime.combine(date(1970, 1, 1), datetime.min.time()).timestamp())


def _row_primary_source(row: dict) -> str:
    for s in row.get("sources") or []:
        if isinstance(s, dict) and s.get("source"):
            return str(s["source"]).strip().lower()
    return ""


def _row_ok_source(row: dict) -> str:
    """The slug of the FIRST ok sold-derived source in a resolved row (the source that
    actually produced the comp) — not merely the first listed source, which may be a
    blocked/skipped quote. Falls back to the first listed source for single-source rows
    whose entries omit status (e.g. the graded _legacy_row)."""
    for s in row.get("sources") or []:
        if isinstance(s, dict) and s.get("source") and s.get("status") == "ok" and s.get("price"):
            return str(s["source"]).strip().lower()
    return _row_primary_source(row)


def _record_billed(args, deps, asset, ledger_path) -> int:
    """Operator-gated billed refresh: fetch the comp from the configured external card
    source and persist it. Refuses without a client or without --yes (surfacing the
    spend); a resolver failure / no-price degrades honestly and persists nothing."""
    credits = sources_mod.expected_asset_credits(asset, card_client=deps.card_client)
    if deps.card_client is None:
        print("refused: no external card client configured "
              "(needs market.preferred + market.api_key)")
        return 2
    if not args.yes:
        print(f"refused: pass --yes only after operator go-ahead (estimated spend "
              f"~{credits.total} credit(s), limit=1 pinned, money-class)")
        return 2
    try:
        row = sources_mod.resolve_asset_source_row(
            asset, card_client=deps.card_client, checked_at=_today_ts(deps.today))
    except Exception as exc:  # noqa: BLE001 - never persist a number on a resolver bug
        print(f"refresh billed {credits.total} credit(s); resolver failed "
              f"({str(exc)[:120]}); nothing recorded")
        return 1
    estimate = resale._amount(row.get("estimate"))
    if estimate is None:
        print(f"refresh billed {credits.total} credit(s) but no usable sold comp "
              f"(honest no-source); nothing recorded")
        return 1
    source = _row_primary_source(row) or "ppt_cards"
    try:
        wrote = sources_mod.record_asset_comp(
            ledger_path, asset, comp=estimate, confidence=row.get("confidence"),
            source=source, capture_date=deps.today,
            source_url=row.get("sourceUrl") or row.get("url") or "",
            basis=row.get("compBasis") or row.get("basis") or "", asset_key=args.asset_key)
    except ValueError as exc:
        print(f"refresh billed {credits.total} credit(s); refused to persist ({exc})")
        return 1
    print(f"{'recorded' if wrote else 'already recorded'} asset comp {args.asset_key} "
          f"= ${estimate:.2f} [{source}, {row.get('confidence')}] "
          f"(billed {credits.total} credit(s), limit=1 pinned)")
    return 0


def _record_independent(args, deps, asset, ledger_path) -> int:
    """0-PPT-credit live fetch from the independent (PriceCharting/TCGplayer) sources,
    persisted with the ACTUAL source slug (never ppt_cards). Gated on
    poke.independent_sources; a no-source result records nothing (honest)."""
    from . import independent_sources as indep
    if not indep.independent_sources_enabled(deps.cfg):
        print("refused: independent live fetch is off (set poke.independent_sources: true)")
        return 2
    srcs = indep.build_independent_sources()   # PriceCharting real; TCGplayer dormant shell
    try:
        row = sources_mod.resolve_independent_asset_row(
            asset, sources=srcs, checked_at=_today_ts(deps.today))
    except Exception as exc:  # noqa: BLE001 - never persist on a resolver bug
        print(f"independent fetch failed ({str(exc)[:120]}); nothing recorded")
        return 1
    estimate = resale._amount(row.get("estimate"))
    if estimate is None:
        print("independent fetch found no usable sold comp (honest no-source); nothing recorded")
        return 1
    source = _row_ok_source(row)               # the OK sold source, NOT the first (blocked) one;
    if not source or source == "ebay":         # and NO ppt_cards fallback on the independent path
        print(f"refused: independent row has no sold source slug (got {source!r}); nothing recorded")
        return 1
    try:
        wrote = sources_mod.record_asset_comp(
            ledger_path, asset, comp=estimate, confidence=row.get("confidence"),
            source=source, capture_date=deps.today,
            source_url=row.get("sourceUrl") or row.get("url") or "",
            basis=row.get("compBasis") or row.get("basis") or "", asset_key=args.asset_key)
    except ValueError as exc:
        print(f"refused to persist ({exc}); nothing recorded")
        return 1
    print(f"{'recorded' if wrote else 'already recorded'} asset comp {args.asset_key} "
          f"= ${estimate:.2f} [{source}, {row.get('confidence')}] (0 PPT credits)")
    return 0


def _cmd_record_asset_comp(args, deps) -> int:
    asset = (getattr(deps, "assets", None) or {}).get(args.asset_key)
    if asset is None:
        print(f"unknown asset_key: {args.asset_key!r} (not in the asset catalog) — not written")
        return 1
    ledger_path = getattr(deps, "ledger_path", None)
    if ledger_path is None:
        print("refused: no ledger_path configured on deps")
        return 1

    if getattr(args, "refresh_independent", False):
        return _record_independent(args, deps, asset, ledger_path)

    if args.refresh:
        return _record_billed(args, deps, asset, ledger_path)

    # from-value (0 credits): persist an already-captured, provenance-bearing observation.
    if args.comp is None or not args.source:
        print("record-asset-comp needs --comp and --source (an already-captured "
              "sold-derived value), or --refresh --yes for an operator-approved billed fetch")
        return 1
    capture_date = args.capture_date or deps.today
    try:
        wrote = sources_mod.record_asset_comp(
            ledger_path, asset, comp=args.comp, confidence=args.confidence,
            source=args.source, capture_date=capture_date,
            source_url=args.source_url, basis=args.basis, asset_key=args.asset_key)
    except ValueError as exc:
        print(f"refused: {exc}")
        return 1
    print(f"{'recorded' if wrote else 'already recorded'} asset comp {args.asset_key} "
          f"= ${float(args.comp):.2f} [{args.source}, {args.confidence}] "
          f"capture {capture_date} (0 credits)")
    return 0


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
    if args.cmd == "record-asset-comp":
        return _cmd_record_asset_comp(args, deps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
