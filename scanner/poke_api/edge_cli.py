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
from . import gem_rates as gem_rates_mod
from . import paper_ledger as ledger_mod
from . import sources as sources_mod
from . import tcgcsv as tcgcsv_mod
from . import tcgcsv_check as tcgcsv_check_mod
from . import tcgcsv_ingest as tcgcsv_ingest_mod
from . import tcgcsv_source as tcgcsv_source_mod


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
        src = f" via {r.get('ours_source')}" if r.get("ours_source") else ""
        xsv = "  [cross-source OK]" if r.get("cross_source_validated") else ""
        print(f"  [{flag:<8}] {r['subject_key']:<28} {r['category']}{src}"
              f"  ours={_fmt_money(r.get('ours'))} theirs={_fmt_money(r.get('theirs'))}"
              f"  ({r.get('delta_pct')}%){xsv}")
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
    pd.add_argument("--matrix", action="store_true",
                    help="F.1: print the multi-asset PPT-vs-ours gap matrix (local, 0 credits)")
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

    # F.1 batch: 0-PPT-credit independent recording across several assets at once.
    pbc = sub.add_parser(
        "record-asset-comps",
        help="F.1 batch: record independent (PriceCharting) asset comps for several "
             "assets at 0 PPT credits (--dry-run previews; --yes persists)")
    pbc.add_argument("--assets", default="", help="comma-separated asset keys")
    pbc.add_argument("--refresh-independent", action="store_true", dest="refresh_independent",
                     help="required: the only mode the batch supports (independent sources, "
                          "0 PPT credits; never constructs the PPT client)")
    pbc.add_argument("--dry-run", action="store_true", dest="dry_run",
                     help="preview only — resolve + show what WOULD be recorded, write nothing")
    pbc.add_argument("--yes", action="store_true",
                     help="persist the resolved comps (absent/--dry-run => preview only)")
    pbc.add_argument("--json", action="store_true")

    # Phase G: gem-rate evidence ledger. `record` captures a SOURCED gem rate from the
    # PriceCharting population blob (0 PPT credits — the pop path never builds a PPT
    # client); `record-assumption`/`list`/`show` are ledger-only, 0 network.
    pgr = sub.add_parser("gem-rate",
                         help="Phase G gem-rate evidence ledger (record/list/show)")
    grsub = pgr.add_subparsers(dest="gem_action", required=True)

    grr = grsub.add_parser(
        "record", help="capture PriceCharting population -> a SOURCED gem rate (0 PPT "
                       "credits; gated on poke.independent_sources + --yes)")
    grr.add_argument("--asset-key", required=True)
    grr.add_argument("--grader", default="PSA",
                     help="single grader (default PSA); PSA and CGC are NEVER combined")
    grr.add_argument("--source", default="pricecharting",
                     help="only 'pricecharting' population is supported (0-credit pop blob)")
    grr.add_argument("--sample-floor", type=int, dest="sample_floor",
                     default=gem_rates_mod.SAMPLE_FLOOR_DEFAULT,
                     help=(f"min total pop for a sourced rate (default "
                           f"{gem_rates_mod.SAMPLE_FLOOR_DEFAULT}); below -> block, never guess"))
    grr.add_argument("--basis", default="")
    grr.add_argument("--yes", action="store_true",
                     help="operator go-ahead for the live 0-credit PriceCharting pop fetch")

    gra = grsub.add_parser(
        "record-assumption",
        help="record an explicit operator-assumption gem rate (no network, capped PAPER_BUY)")
    gra.add_argument("--asset-key", required=True)
    gra.add_argument("--grader", default="PSA")
    gra.add_argument("--gem-rate", type=float, required=True, dest="gem_rate")
    gra.add_argument("--basis", required=True, help="why this rate (required — an assumption "
                                                    "is a labeled judgment, not a fabrication)")

    grl = grsub.add_parser("list", help="list recorded gem-rate rows (ledger-only, 0 network)")
    grl.add_argument("--json", action="store_true")

    grs = grsub.add_parser("show",
                           help="recorded gem-rate rows for one asset (ledger-only, 0 network)")
    grs.add_argument("--asset-key", required=True)
    grs.add_argument("--json", action="store_true")

    # TCGCSV foundation T1: sample-check gate. Earns the "TCGplayer market == PPT"
    # credit-saving claim at real n BEFORE TCGCSV is trusted as a reference source.
    # Free/keyless (0 credits) but gated on a dedicated poke.tcgcsv flag (default off).
    ptc = sub.add_parser(
        "tcgcsv-check",
        help="TCGCSV-vs-PPT sample-check gate (fixed >=5 raw pairs / <=2%%; 0 credits; "
             "gated on poke.tcgcsv)")
    ptc.add_argument("--json", action="store_true")

    # TCGCSV foundation T3: identity ingest — EXACT mapping proposals only, never
    # writes assets.yaml (exact identity stays human-confirmed). Free/keyless (0
    # credits) but gated on the same poke.tcgcsv flag as tcgcsv-check.
    pti = sub.add_parser(
        "tcgcsv-ingest",
        help="TCGCSV exact-identity mapping proposals for unmapped catalog assets in "
             "a set (writes a REVIEW artifact only, never assets.yaml; 0 credits; "
             "gated on poke.tcgcsv)")
    pti.add_argument("--group", required=True,
                     help="TCGCSV set name (catalog-native, e.g. 'Prismatic Evolutions') "
                          "or a numeric TCGCSV groupId")
    pti.add_argument("--json", action="store_true")

    # TCGCSV raw-asset reference recording (Task 5 Part B): the free TCGplayer-market
    # mirror for one mapped raw asset, recorded as a low-confidence, external-footing
    # market_comp. Never displaces an independent/paid comp as the served headline
    # (see lab.resolve_asset_comp_row, Part A). 0 credits; gated on poke.tcgcsv.
    ptr = sub.add_parser(
        "tcgcsv-ref",
        help="record the free TCGCSV TCGplayer-market reference for a mapped raw asset "
             "as a low-confidence market_comp (0 credits; gated on poke.tcgcsv; never "
             "displaces an independent/paid comp as the served headline)")
    ptr.add_argument("--asset", required=True, dest="asset_key",
                     help="asset_key from the asset catalog")
    ptr.add_argument("--json", action="store_true")
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


def _print_matrix(result) -> None:
    print(f"PPT-vs-ours gap matrix [{result['mode']}] - {len(result['rows'])} asset(s), "
          f"0 credits\n")
    for r in result.get("rows", []):
        flag = "BLOCKING" if r.get("blocking") else ("material" if r.get("material") else "ok")
        xsv = "  [cross-source OK]" if r.get("cross_source_validated") else ""
        print(f"  [{flag:<8}] {r['asset_key']:<30} {r['classification']}{xsv}")
        print(f"        {r['asset_class']}/{r.get('condition_or_grade_key') or '-'}  "
              f"ours={_fmt_money(r.get('ours'))} ({r.get('ours_source') or '-'} "
              f"{r.get('ours_capture_date') or '-'})  ppt={_fmt_money(r.get('ppt_reference'))} "
              f"({r.get('ppt_capture_date') or '-'})  delta={r.get('delta_pct')}%")
        print(f"        defensibility: {r.get('defensibility')}  |  {r.get('notes')}")
    print(f"\n  result: {'FAILED (material unexplained divergence)' if result['failed'] else 'ok'}"
          f"  material={result.get('material_count', 0)}  credits_spent=0")


def _cmd_divergence(args, deps) -> int:
    products = [k.strip() for k in args.products.split(",") if k.strip()]
    assets = [k.strip() for k in args.assets.split(",") if k.strip()]
    # F.1 gap matrix: local-only, 0 credits, richer per-asset classification.
    if getattr(args, "matrix", False):
        result = dv_mod.audit_matrix(deps, asset_keys=assets)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            _print_matrix(result)
        return 1 if result.get("failed") else 0
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


def _independent_result(deps, asset, asset_key, ledger_path, *, write: bool) -> dict:
    """Resolve one asset's INDEPENDENT (PriceCharting) comp and, when ``write``, persist
    it with the ACTUAL source slug (never ppt_cards). Returns a structured per-asset
    result (shared by the single ``--refresh-independent`` command and the F.1 batch).
    Never constructs a PPT client — 0 PPT credits by construction. A raw non-NM
    condition, no-source/no-match/blocked/wrong-slug, or an ask/ppt slug records nothing
    (honest). ``status`` ∈ recorded|already_recorded|previewed|skipped_condition|
    skipped_no_source|skipped_bad_source|error."""
    from . import independent_sources as indep

    def _res(status, message, **extra):
        base = {"asset_key": asset_key, "status": status, "wrote": False,
                "source": None, "comp": None, "confidence": None, "basis": "",
                "source_url": "", "message": message}
        base.update(extra)
        return base

    # Raw-condition guard (0 network): a non-NM raw is not auto-recorded off Ungraded.
    ok_cond, cond_reason = indep.raw_condition_recordable(asset)
    if not ok_cond:
        return _res("skipped_condition", cond_reason)

    srcs = indep.build_independent_sources()   # PriceCharting real; TCGplayer dormant shell
    try:
        row = sources_mod.resolve_independent_asset_row(
            asset, sources=srcs, checked_at=_today_ts(deps.today))
    except Exception as exc:  # noqa: BLE001 - never persist on a resolver bug
        return _res("error", f"independent fetch failed ({str(exc)[:120]})")
    estimate = resale._amount(row.get("estimate"))
    if estimate is None:
        detail = row.get("confidenceReason") or row.get("detail") or "honest no-source"
        return _res("skipped_no_source", f"no usable sold comp ({detail})")
    source = _row_ok_source(row)               # the OK sold source, NOT the first (blocked) one;
    if not source or source in ("ebay", "ppt_cards"):   # NO ppt_cards fallback on this path
        return _res("skipped_bad_source",
                    f"no independent sold source slug (got {source!r}); nothing recorded")

    resolved = {"asset_key": asset_key, "source": source, "comp": estimate,
                "confidence": row.get("confidence"),
                "basis": row.get("compBasis") or row.get("basis") or "",
                "source_url": row.get("sourceUrl") or row.get("url") or ""}
    if not write:
        return {**resolved, "status": "previewed", "wrote": False,
                "message": f"would record ${estimate:.2f} [{source}, {row.get('confidence')}]"}
    try:
        wrote = sources_mod.record_asset_comp(
            ledger_path, asset, comp=estimate, confidence=row.get("confidence"),
            source=source, capture_date=deps.today, source_url=resolved["source_url"],
            basis=resolved["basis"], asset_key=asset_key)
    except ValueError as exc:
        return {**resolved, "status": "error", "wrote": False,
                "message": f"refused to persist ({exc}); nothing recorded"}
    return {**resolved, "status": "recorded" if wrote else "already_recorded",
            "wrote": bool(wrote),
            "message": f"{'recorded' if wrote else 'already recorded'} ${estimate:.2f} "
                       f"[{source}, {row.get('confidence')}] (0 PPT credits)"}


def _record_independent(args, deps, asset, ledger_path) -> int:
    """0-PPT-credit live fetch from the independent (PriceCharting/TCGplayer) sources,
    persisted with the ACTUAL source slug (never ppt_cards). Gated on
    poke.independent_sources; a no-source result records nothing (honest)."""
    from . import independent_sources as indep
    if not indep.independent_sources_enabled(deps.cfg):
        print("refused: independent live fetch is off (set poke.independent_sources: true)")
        return 2
    result = _independent_result(deps, asset, args.asset_key, ledger_path, write=True)
    print(f"{result['message']} ({args.asset_key})" if result["status"] in
          ("recorded", "already_recorded") else result["message"])
    return 0 if result["wrote"] or result["status"] == "already_recorded" else 1


def _print_batch(results, write: bool) -> None:
    mode = "WRITE" if write else "PREVIEW (no writes)"
    print(f"record-asset-comps [{mode}] - {len(results)} asset(s), 0 PPT credits\n")
    for r in results:
        comp = f"${r['comp']:.2f}" if isinstance(r.get("comp"), (int, float)) else "-"
        src = r.get("source") or "-"
        print(f"  [{r['status']:<17}] {r['asset_key']:<30} {comp:>11} [{src}]")
        print(f"        {r.get('message', '')}")
    wrote = sum(1 for r in results if r["wrote"])
    prev = sum(1 for r in results if r["status"] == "previewed")
    skipped = sum(1 for r in results if r["status"].startswith("skipped")
                  or r["status"] in ("error", "unknown_asset", "already_recorded"))
    print(f"\n  summary: {wrote} recorded, {prev} previewed, {skipped} skipped/other; "
          f"credits_spent=0")


def _cmd_record_asset_comps(args, deps) -> int:
    """F.1 batch independent recording (0 PPT credits). --dry-run previews; --yes
    persists; neither => safe preview. Gated on poke.independent_sources."""
    from . import independent_sources as indep
    if not getattr(args, "refresh_independent", False):
        print("record-asset-comps requires --refresh-independent (the batch supports only "
              "the 0-PPT-credit independent path)")
        return 1
    if not indep.independent_sources_enabled(deps.cfg):
        print("refused: independent live fetch is off (set poke.independent_sources: true)")
        return 2
    ledger_path = getattr(deps, "ledger_path", None)
    if ledger_path is None:
        print("refused: no ledger_path configured on deps")
        return 1
    keys = [k.strip() for k in (args.assets or "").split(",") if k.strip()]
    if not keys:
        print("record-asset-comps needs --assets a,b,c")
        return 1

    write = bool(args.yes) and not bool(args.dry_run)   # --dry-run always wins
    catalog = getattr(deps, "assets", None) or {}
    results = []
    for key in keys:
        asset = catalog.get(key)
        if asset is None:
            results.append({"asset_key": key, "status": "unknown_asset", "wrote": False,
                            "source": None, "comp": None, "confidence": None, "basis": "",
                            "source_url": "", "message": "not in the asset catalog"})
            continue
        results.append(_independent_result(deps, asset, key, ledger_path, write=write))

    if args.json:
        print(json.dumps({"mode": "write" if write else "preview", "credits_spent": 0,
                          "results": results}, indent=2))
    else:
        _print_batch(results, write)
    return 1 if any(r["status"] == "unknown_asset" for r in results) else 0


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


# ---------------------------------------------------------------- Phase G: gem-rate ledger

def _gem_rate_path(deps):
    return getattr(deps, "gem_rates_path", None)


def _print_gem_rows(rows) -> None:
    print(f"{len(rows)} gem-rate row(s) (ledger-only, 0 network)\n")
    for r in rows:
        gr_val = r.get("gem_rate")
        gr_str = f"{gr_val:.4f}" if isinstance(gr_val, (int, float)) else "-"
        ss = r.get("sample_size")
        ss_str = f"n={ss}" if ss is not None else "n=-"
        print(f"  [{str(r.get('label', '?')):<19}] {str(r.get('asset_key', '')):<28} "
              f"{str(r.get('grader', '')):<4} gem {gr_str} {ss_str} "
              f"[{r.get('source', '')}] {r.get('capture_date', '')}")
        if r.get("basis"):
            print(f"        {r['basis']}")


def _gem_rate_record(args, deps) -> int:
    """Capture PriceCharting population -> a SOURCED gem rate. 0 PPT credits by
    construction (``PriceChartingPopSource`` takes a plain requests session; NO PPT client
    is ever built). Gated on poke.independent_sources + --yes. Below the sample floor /
    grader absent / no pop -> honest block, never a guessed rate. Always prints
    ``credits_spent=0``."""
    from . import independent_sources as indep

    if str(args.source or "").strip().lower() not in ("pricecharting", "pricecharting_pop"):
        print(f"gem-rate record supports only --source pricecharting (0-credit population); "
              f"got {args.source!r}")
        return 1
    asset = (getattr(deps, "assets", None) or {}).get(args.asset_key)
    if asset is None:
        print(f"unknown asset_key: {args.asset_key!r} (not in the asset catalog) — not written")
        return 1
    path = _gem_rate_path(deps)
    if path is None:
        print("refused: no gem_rates_path configured on deps")
        return 1
    if not indep.independent_sources_enabled(deps.cfg):
        print("refused: live pop fetch is off (set poke.independent_sources: true)")
        return 2
    if not args.yes:
        print("refused: pass --yes only after operator go-ahead for the live PriceCharting "
              "pop fetch (0 PPT credits)")
        return 2

    grader = str(args.grader or "PSA").strip().upper()
    src = indep.PriceChartingPopSource()          # plain requests; NO PPT client constructed
    res = src.fetch_pop(asset, _today_ts(deps.today))
    if res.get("status") != "ok":
        print(f"no sourced gem rate: pop {res.get('status')} ({res.get('detail', '')}); "
              f"credits_spent=0")
        return 1
    counts = (res.get("pop") or {}).get(grader.lower())
    if counts is None:
        print(f"no sourced gem rate: grader {grader} absent from the pop blob "
              f"(graders present: {res.get('graders')}); credits_spent=0")
        return 1
    basis = args.basis or f"PriceCharting {grader} population census (monthly), pop-blob sourced"
    try:
        wrote = gem_rates_mod.record_sourced(
            path, asset_key=args.asset_key, grader=grader, counts=counts,
            source_url=res.get("url", ""), capture_date=deps.today, basis=basis,
            sample_floor=args.sample_floor)
    except ValueError as exc:
        print(f"blocked: {exc}; credits_spent=0")
        return 1
    calc = gem_rates_mod.gem_rate_from_counts(counts, grader=grader,
                                              sample_floor=args.sample_floor)
    print(f"{'recorded' if wrote else 'already recorded'} gem rate {args.asset_key} [{grader}] "
          f"= {calc['gem_rate']:.4f} ({grader}10 {calc['psa10']}/{calc['sample_size']} pop) "
          f"[sourced, pricecharting_pop] credits_spent=0")
    return 0


def _gem_rate_record_assumption(args, deps) -> int:
    """Record an explicit operator-assumption gem rate (no network). The rate must be a
    probability in (0, 1] with a stated basis — a labeled judgment, never a fabrication."""
    asset = (getattr(deps, "assets", None) or {}).get(args.asset_key)
    if asset is None:
        print(f"unknown asset_key: {args.asset_key!r} (not in the asset catalog) — not written")
        return 1
    path = _gem_rate_path(deps)
    if path is None:
        print("refused: no gem_rates_path configured on deps")
        return 1
    grader = str(args.grader or "PSA").strip().upper()
    try:
        wrote = gem_rates_mod.record_assumption(
            path, asset_key=args.asset_key, grader=grader, gem_rate=args.gem_rate,
            basis=args.basis, capture_date=deps.today)
    except ValueError as exc:
        print(f"refused: {exc}")
        return 1
    print(f"{'recorded' if wrote else 'already recorded'} gem rate {args.asset_key} [{grader}] "
          f"= {float(args.gem_rate):.4f} [operator_assumption] (0 network, capped PAPER_BUY)")
    return 0


def _gem_rate_list(args, deps) -> int:
    path = _gem_rate_path(deps)
    rows = gem_rates_mod.read_rows(path) if path is not None else []
    if getattr(args, "json", False):
        print(json.dumps({"count": len(rows), "gem_rates": rows}, indent=2))
    else:
        _print_gem_rows(rows)
    return 0


def _gem_rate_show(args, deps) -> int:
    path = _gem_rate_path(deps)
    all_rows = gem_rates_mod.read_rows(path) if path is not None else []
    rows = gem_rates_mod.rows_for_asset(all_rows, args.asset_key)
    if getattr(args, "json", False):
        print(json.dumps({"asset_key": args.asset_key, "count": len(rows),
                          "gem_rates": rows}, indent=2))
    else:
        print(f"gem-rate rows for {args.asset_key}:")
        _print_gem_rows(rows)
    return 0


def _cmd_gem_rate(args, deps) -> int:
    action = getattr(args, "gem_action", None)
    if action == "record":
        return _gem_rate_record(args, deps)
    if action == "record-assumption":
        return _gem_rate_record_assumption(args, deps)
    if action == "list":
        return _gem_rate_list(args, deps)
    if action == "show":
        return _gem_rate_show(args, deps)
    return 1


# ---------------------------------------------------------------- TCGCSV sample-check (T1)

def _docs_dir():
    """``docs/poke`` under the repo root. A function (not a module constant) so tests can
    monkeypatch it to a tmp dir — the CLI must never write into the real committed docs
    tree as a side effect of a test run."""
    from .. import config as config_mod
    return config_mod.ROOT / "docs" / "poke"


def _print_tcgcsv_check(result: dict, skipped: list[dict]) -> None:
    print(f"tcgcsv-check [{result['status'].upper()}] - {result['reason']}\n")
    for p in result["pairs"]:
        print(f"  {p['asset_key']:<28} ppt=${p['ppt_price']:.2f} "
              f"tcgcsv=${p['tcgcsv_price']:.2f}  diff={p['diff_pct']:.2f}%")
    if skipped:
        print("\n  skipped (honest, never guessed):")
        for s in skipped:
            print(f"    {s['asset_key']:<28} {s['reason']}")
    print(f"\n  result: {result['status']}  n={result['n']}  credits_spent=0")


def _write_tcgcsv_check_doc(result: dict, skipped: list[dict], capture_date: str,
                            docs_dir) -> "Path":
    from pathlib import Path

    docs_dir = Path(docs_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / f"tcgcsv-sample-check-{capture_date}.md"

    max_diff = result.get("max_diff_pct")
    max_diff_line = f"- max diff = {max_diff:.2f}%" if max_diff is not None \
        else "- max diff = n/a (no pairs)"
    lines = [
        f"# TCGCSV Sample-Check Result — {capture_date}",
        "",
        f"**Status:** {result['status'].upper()}",
        "**Gate:** fixed >= 5 raw pairs, <= 2% max diff (spec T1, not per-run tunable)",
        "**Credits:** 0 PPT (reads only already-recorded `ppt_cards` rows; TCGCSV is "
        "free/keyless)",
        "",
        "## Verdict",
        "",
        result["reason"],
        "",
        f"- n = {result['n']}",
        max_diff_line,
        "",
        "## Pairs compared",
        "",
    ]
    if result["pairs"]:
        lines += ["| asset_key | tcgplayer_id | ppt_price | tcgcsv_price | diff_pct |",
                  "|---|---|---:|---:|---:|"]
        for p in result["pairs"]:
            lines.append(f"| {p['asset_key']} | {p['tcgplayer_id']} | "
                        f"${p['ppt_price']:.2f} | ${p['tcgcsv_price']:.2f} | "
                        f"{p['diff_pct']:.2f}% |")
    else:
        lines.append("_none_")
    lines += ["", "## Skipped (honest, never guessed)", ""]
    if skipped:
        lines += ["| asset_key | reason |", "|---|---|"]
        for s in skipped:
            lines.append(f"| {s['asset_key']} | {s['reason']} |")
    else:
        lines.append("_none_")
    lines += [
        "",
        "## Scope note",
        "",
        "Only **raw** assets are eligible for a pair. TCGCSV `marketPrice` is an "
        "ungraded-card price with no graded-slab (PSA/CGC) counterpart in the catalog — "
        "comparing a graded asset's `ppt_cards` comp (a different quantity, e.g. a PSA10 "
        "smart price) against it would fail on tolerance for a reason that has nothing to "
        "do with TCGCSV-vs-PPT agreement. Graded assets are honestly skipped, never "
        "compared.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _cmd_tcgcsv_check(args, deps) -> int:
    """TCGCSV-vs-PPT sample-check gate (spec T1). Refuses (no network call) unless
    ``poke.tcgcsv`` is true. Compares held ``ppt_cards`` raw comps against a live TCGCSV
    market price for the same exact identity; writes the committed result doc (the
    ledger is gitignored, so the doc is the durable proof)."""
    if not tcgcsv_mod.tcgcsv_enabled(deps.cfg):
        print("refused: TCGCSV live fetch is off (set poke.tcgcsv: true)")
        return 2

    assets = getattr(deps, "assets", None) or {}
    observations = deps.read_observations() if getattr(deps, "read_observations", None) else []
    groups = tcgcsv_mod.fetch_groups()
    pairs, skipped = tcgcsv_check_mod.build_pairs(assets, observations, groups)
    result = tcgcsv_check_mod.sample_check(pairs)

    doc_path = _write_tcgcsv_check_doc(result, skipped, deps.today, _docs_dir())

    if getattr(args, "json", False):
        print(json.dumps({**result, "skipped": skipped, "doc_path": str(doc_path)}, indent=2))
    else:
        _print_tcgcsv_check(result, skipped)
        print(f"  wrote {doc_path}")
    return 0 if result["status"] == "pass" else 1


# ---------------------------------------------------------------- TCGCSV identity ingest (T3)

def _proposals_dir():
    """``data/poke`` under the repo root. A function (not a module constant) so tests
    can monkeypatch it to a tmp dir — the CLI must never write into the real
    committed data tree as a side effect of a test run. This is a REVIEW artifact
    directory, never the ``assets.yaml`` catalog itself."""
    from .. import config as config_mod
    return config_mod.ROOT / "data" / "poke"


def _slug(text: str) -> str:
    """A filesystem-safe slug for the proposals artifact filename, e.g.
    'SV: Prismatic Evolutions' / '23821' -> 'sv_prismatic_evolutions' / '23821'."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().lower()).strip("_")
    return slug or "group"


def _write_tcgcsv_proposals(proposals: list[dict], raw_group: str, group_id: int,
                            data_dir) -> "Path":
    from pathlib import Path

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"tcgcsv-proposals-{_slug(raw_group)}.json"
    path.write_text(json.dumps({"group": raw_group, "group_id": group_id,
                                "proposals": proposals}, indent=2), encoding="utf-8")
    return path


def _print_tcgcsv_ingest(proposals: list[dict], raw_group: str, group_id: int, path) -> None:
    exact = [p for p in proposals if p["match"] == "exact"]
    none_ = [p for p in proposals if p["match"] != "exact"]
    print(f"tcgcsv-ingest [{raw_group}] group_id={group_id} - {len(proposals)} candidate(s), "
          f"0 credits\n")
    for p in exact:
        print(f"  [ACCEPT?] {p['asset_key']:<28} -> tcgplayer_id={p['tcgplayer_id']} "
              f"({p['product_name']!r}, card_number={p['card_number']})")
    for p in none_:
        print(f"  [REJECT ] {p['asset_key']:<28} -> no exact match "
              f"(card_number={p['card_number']!r}) — never guessed")
    print(f"\n  result: {len(exact)} exact / {len(none_)} none — proposals only, "
          f"assets.yaml NOT modified; review + hand-confirm at {path}")


def _cmd_tcgcsv_ingest(args, deps) -> int:
    """TCGCSV identity ingest (spec T3): EXACT tcgplayer_id mapping proposals for the
    unmapped catalog assets in one set. Refuses (no network) unless ``poke.tcgcsv``
    is true. ``--group`` accepts a catalog-native set name or a numeric TCGCSV
    groupId; a name/id that doesn't resolve to exactly one TCGCSV group is a clean
    refusal with no product fetch. Writes a REVIEW artifact under
    ``data/poke/tcgcsv-proposals-<group>.json`` — NEVER assets.yaml; exact identity
    stays human-confirmed (a non-exact candidate is surfaced as 'none', never
    auto-accepted)."""
    if not tcgcsv_mod.tcgcsv_enabled(deps.cfg):
        print("refused: TCGCSV live fetch is off (set poke.tcgcsv: true)")
        return 2

    raw_group = str(args.group or "").strip()
    if not raw_group:
        print("tcgcsv-ingest needs --group <set name or numeric groupId>")
        return 1

    groups = tcgcsv_mod.fetch_groups()
    if raw_group.isdigit():
        candidate_id = int(raw_group)
        known_ids = {g.get("groupId") for g in groups}
        group_id = candidate_id if candidate_id in known_ids else None
    else:
        group_id = tcgcsv_check_mod.resolve_group_id(raw_group, groups)
    if group_id is None:
        print(f"refused: no unambiguous TCGCSV group for {raw_group!r} — no products fetched")
        return 2

    assets = getattr(deps, "assets", None) or {}
    candidates = []
    for asset_key, asset in assets.items():
        if str(asset.get("tcgplayer_id") or "").strip():
            continue  # already mapped — not up for ingest proposal
        if tcgcsv_check_mod.resolve_group_id(asset.get("set", ""), groups) != group_id:
            continue  # different (or unresolvable) set — out of scope for this group
        candidates.append({**asset, "asset_key": asset_key})

    proposals = (tcgcsv_ingest_mod.propose_mappings(tcgcsv_mod.fetch_products(group_id),
                                                     candidates, group_id=group_id)
                 if candidates else [])

    path = _write_tcgcsv_proposals(proposals, raw_group, group_id, _proposals_dir())

    if getattr(args, "json", False):
        print(json.dumps({"group": raw_group, "group_id": group_id,
                          "proposals": proposals, "path": str(path)}, indent=2))
    else:
        _print_tcgcsv_ingest(proposals, raw_group, group_id, path)
    return 0


# ---------------------------------------------------------------- TCGCSV raw reference (Task 5)

def _cmd_tcgcsv_ref(args, deps) -> int:
    """Record the free TCGCSV TCGplayer-market reference for one mapped raw asset as a
    ``low``-confidence, external-footing ``market_comp`` (spec §9.3). Refuses (0 network)
    unless ``poke.tcgcsv`` is true — mirrors ``_cmd_tcgcsv_check``'s refuse pattern. The
    reference never lifts live confidence (single-source + external) and, per Part A's
    never-displace rule in ``lab.resolve_asset_comp_row``, never overwrites an existing
    independent/paid comp as the served headline; it is recorded purely for provenance/
    audit. Raw-only: a graded asset (which can share its raw counterpart's tcgplayer_id)
    is an honest, named skip — TCGCSV's marketPrice is ungraded-only, not a comp for a
    graded identity (same scope exclusion ``tcgcsv-check`` already applies to pairs). Any
    non-``ok`` quote status records nothing and prints the honest reason."""
    if not tcgcsv_mod.tcgcsv_enabled(deps.cfg):
        print("refused: TCGCSV live fetch is off (set poke.tcgcsv: true)")
        return 2

    asset = (getattr(deps, "assets", None) or {}).get(args.asset_key)
    if asset is None:
        print(f"unknown asset_key: {args.asset_key!r} (not in the asset catalog) — not written")
        return 1
    # A graded asset can share its raw counterpart's tcgplayer_id/tcgcsv_group_id (same
    # physical card), so raw_reference_quote would happily resolve one — but TCGCSV's
    # marketPrice is an UNGRADED quantity, not comparable to a graded identity (same scope
    # exclusion tcgcsv-check already names for pairs). Honest, named skip — never fetched.
    if str(asset.get("asset_class") or "").strip().lower() != "raw":
        print(f"skipped {args.asset_key}: graded asset — TCGCSV marketPrice is "
              f"ungraded-only, not a comp for a graded identity — nothing recorded")
        return 1
    ledger_path = getattr(deps, "ledger_path", None)
    if ledger_path is None:
        print("refused: no ledger_path configured on deps")
        return 1

    quote = tcgcsv_source_mod.raw_reference_quote(asset, _today_ts(deps.today))
    if quote.status != "ok":
        print(f"tcgcsv-ref {args.asset_key}: {quote.status} ({quote.detail}) — "
              f"nothing recorded (0 credits)")
        return 1

    try:
        wrote = sources_mod.record_asset_comp(
            ledger_path, asset, comp=quote.price, confidence="low", source="tcgcsv",
            capture_date=deps.today, source_url=quote.url, basis=quote.detail,
            asset_key=args.asset_key)
    except ValueError as exc:
        print(f"refused: {exc}")
        return 1

    if getattr(args, "json", False):
        print(json.dumps({"asset_key": args.asset_key, "wrote": wrote, "source": "tcgcsv",
                          "confidence": "low", "comp": quote.price, "source_url": quote.url,
                          "capture_date": deps.today, "credits_spent": 0}, indent=2))
    else:
        print(f"{'recorded' if wrote else 'already recorded'} tcgcsv reference "
              f"{args.asset_key} = ${quote.price:.2f} [tcgcsv, low] capture {deps.today} "
              f"(0 credits; never served over an independent/paid comp)")
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
    if args.cmd == "record-asset-comps":
        return _cmd_record_asset_comps(args, deps)
    if args.cmd == "gem-rate":
        return _cmd_gem_rate(args, deps)
    if args.cmd == "tcgcsv-check":
        return _cmd_tcgcsv_check(args, deps)
    if args.cmd == "tcgcsv-ingest":
        return _cmd_tcgcsv_ingest(args, deps)
    if args.cmd == "tcgcsv-ref":
        return _cmd_tcgcsv_ref(args, deps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
