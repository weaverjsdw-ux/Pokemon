# Money Hypothesis Lab (Phase C)

The Opportunity + Paper-Trade Lab turns the private sealed price API (Tracks A+B)
into a testbed for the program's own Pokémon deal hypotheses. For every catalog
product it answers, deterministically and from evidence the pipeline already
produced:

1. **What opportunity is this?** — a scored `Opportunity` record.
2. **What hypothesis does it test?** — one of five sealed `trade_type`s.
3. **What evidence supports or weakens it?** — `evidence` + `risks` lists.
4. **Would I paper-buy, watch, reject, or mark live-packet-eligible?** — `decision_hint`.
5. **If recorded, what happened later?** — the append-only paper ledger + outcome replay.
6. **Which signals are working over time?** — the signals report (hit-rate + realized net).

**Structurally PPT-free and network-free on the read path.** Nothing here calls
PokemonPriceTracker or the network; opportunities are built from the read-first
comp (in-house cache → ledger latest → honest none) and the ledger momentum. The
only "live" surface is a `LIVE_PACKET_ELIGIBLE` tag for later **human** action —
there is no auto-purchase logic.

Code: `scanner/poke_api/` — `opportunities.py` (pure model + scoring),
`paper_ledger.py` (append-only decisions + outcomes), `lab.py` (orchestrator +
CLI), endpoints in `router.py`.

> **Relationship to the design spec.** The `2026-07-04-money-hypothesis-lab-core-design.md`
> spec sketched an *alternative* realization wired into the discovery pipeline
> (`scanner/discovery/taxonomy.py` + `paper_ledger.py`). Phase C is realized in the
> **`poke_api` layer** instead (per the Phase C mission), consuming the A+B comp/
> momentum responses. The spec's discovery modules are **not** built — do not add
> them, or you will create a conflicting duplicate. The spec's *doctrine* (three
> orthogonal axes, evidence-spine anchor, `decide()` table, math-reuse, no
> hindsight mutation) is carried over verbatim.

---

## Price accuracy (STOP-class — unchanged)

- `expected_net` / `expected_roi_pct` are computed by the **same** functions the
  alert path uses (`margin.net_margin` + `verdict.buy_verdict`, fed like
  `scanner.main.verdict_for_alert`). No new money math; the numbers match the
  alert path exactly.
- **No verified entry price or no comp ⇒ the dollar fields are `None`**, never a
  fabricated value and never MSRP-as-if-a-price. `discount_pct` is likewise
  `None` without a verified entry.
- Every numeric evidence line carries its source + capture date.

## The five sealed trade types

| `trade_type` | hypothesis it tests | live-eligible |
|---|---|---|
| `sealed_catalog_gap` | product lacks enough comp/history data; improve before acting | no |
| `sealed_stale_comp` | a comp exists but is stale; not safe for action, refresh first | no |
| `sealed_retail_arbitrage` | verified retail price is materially below current market comp | **yes** |
| `sealed_momentum_watch` | appreciating/strengthening, but no buyable entry confirmed yet | no |
| `sealed_no_edge` | no current actionable edge | no |

`classify_trade` is deterministic and first-match-wins: no comp → `catalog_gap`;
stale → `stale_comp`; verified entry + comp + discount ≥ `poke.min_discount_pct`
→ `retail_arbitrage` (this precedes the no-history check — a verified deal is
actionable even with a thin ledger, and a weak comp is still demoted downstream by
the fee-adjusted verdict); no price history → `catalog_gap`; positive momentum →
`momentum_watch`; else `no_edge`.

## Decision hints — `decide()`

| condition (first match) | `decision_hint` |
|---|---|
| live-eligible type + verified entry & comp + fresh + `BUY` verdict + clears **live floor** | `LIVE_PACKET_ELIGIBLE` |
| `sealed_retail_arbitrage` + `BUY` verdict (below the live floor) | `PAPER_BUY` |
| `sealed_retail_arbitrage` + `SKIP` verdict | `REJECT` |
| `sealed_retail_arbitrage` + `THIN` verdict | `WATCH` |
| `catalog_gap` / `stale_comp` / `momentum_watch` / `no_edge` | `WATCH` |

`LIVE_PACKET_ELIGIBLE` is reachable **only** through the existing evidence spine
(verified entry price + attributed comp + discount + confidence + fresh data + a
`BUY` verdict) **and** the stricter live floor. A non-live-eligible trade type can
never reach it, regardless of the numbers.

## Scoring (rules-first, 0–100, no ML)

`score_breakdown` holds signed component contributions (discount, net, roi,
momentum, confidence, sources; minus staleness / no-history / risk penalties); the
pre-clamp sum is the raw score, clamped to `[0, 100]`. Weights are module-level
constants in `opportunities.py`, easy to audit and tune.

## Business policy config — `opportunity:`

Fees, tax, shipping, and the **paper** BUY floor are **cited from
`deal_intelligence`** (correct units, incl. the `$0.40` fixed fee) — they are
**not** re-declared under `opportunity:`, so an opportunity's net/ROI matches the
alert path. The `opportunity:` block carries only genuinely-new business policy;
unset per-type values surface as `TBD_OPERATOR_POLICY` (never invented):

```yaml
opportunity:
  live_min_expected_net: 25.00   # TBD_OPERATOR_POLICY — stricter than paper $15 floor
  live_min_roi_pct: 30.0         # TBD_OPERATOR_POLICY — stricter than paper 20%
  live_min_confidence: medium    # TBD_OPERATOR_POLICY
  stale_after_days: 30           # mirrors poke.staleness_days
  max_hold_days: {sealed_retail_arbitrage: 45, sealed_momentum_watch: 90}
  exit_venue:   {sealed_retail_arbitrage: ebay, sealed_momentum_watch: ebay}
```

## Endpoints (all GET, read-only, 0 credits)

### `GET /api/poke/opportunities`
Scored opportunities across the catalog + a summary.
```json
{"ok": true, "count": 22,
 "summary": {"count": 22, "by_decision": {"WATCH": 22, "PAPER_BUY": 0, ...},
             "by_trade_type": {...}, "by_momentum_status": {...},
             "live_packet_eligible": 0},
 "opportunities": [ { "opportunity_id": "...", "product_key": "...",
   "trade_type": "sealed_momentum_watch", "hypothesis": "...",
   "entry_price": null, "market_comp": 49.94, "discount_pct": null,
   "expected_net": null, "expected_roi_pct": null, "verdict_tier": "n/a",
   "momentum_delta_pct": 1.13, "momentum_status": "ok", "latest_confidence": "medium",
   "stale": false, "hold_days": 90, "exit_venue": "ebay",
   "evidence": ["market comp $49.94 from tcgplayer (medium) as of 2026-07-03", ...],
   "risks": ["no_verified_entry", ...], "decision_hint": "WATCH",
   "score": 12.0, "score_breakdown": {...} } ] }
```

### `GET /api/poke/opportunities/{product_key}`
The single-product opportunity detail (404 for an unknown key).

### `GET /api/poke/paper-decisions`
The replay fold — current decision + latest outcome per `opportunity_id`.
```json
{"ok": true, "count": 1, "decisions": [
  {"opportunity_id": "...",
   "decision": {"kind": "decision", "decision": "PAPER_BUY", ...},
   "outcome":  {"kind": "outcome", "status": "SOLD", "realized_net": 20.0, ...}}]}
```

### `GET /api/poke/signals`
Which hypotheses are working over time.
```json
{"ok": true, "signals": {
  "opportunities": 3, "decisions_recorded": 3, "outcomes_recorded": 2,
  "by_decision": {"PAPER_BUY": 2, "WATCH": 1},
  "by_trade_type": {"sealed_retail_arbitrage": {
     "count": 2, "with_outcome": 2, "wins": 1,
     "hit_rate": 0.5, "mean_realized_net": 7.5}}}}
```

> The read API produces opportunities from **catalog + comp + momentum only**;
> `entry_price` requires a *verified deal candidate*, which is a future discovery
> wire (`candidate_for` defaults to none). Until that lands, every opportunity is
> a `WATCH`/`catalog_gap`/`momentum_watch` — honestly, because there is no verified
> buy price to act on. The `LIVE_PACKET_ELIGIBLE` / `PAPER_BUY` paths are exercised
> whenever a verified candidate is supplied.

## CLI

```
python -m scanner.poke_api.lab list [--json]          # score the catalog
python -m scanner.poke_api.lab record --product KEY [--decision D] [--reason R] [--as-of DATE]
python -m scanner.poke_api.lab record-all [--as-of DATE]   # record every decision hint
python -m scanner.poke_api.lab outcome --opportunity ID --status S \
        [--price P] [--net N] [--note ...] [--observed-at DATE]
python -m scanner.poke_api.lab report [--json]        # signals + replay
```

Outcome `status` ∈ `SOLD | HELD | PRICE_UP | PRICE_DOWN | EXPIRED | VOID`.

## Ledger & immutability

Paper decisions and outcomes are one immutable JSON object per line in
`data/poke/paper_decisions.jsonl` (a **separate** file from the market-observation
`price_history.jsonl`, which the Lab only reads). Idempotent by a sha256
`entry_id` (mirrors `scanner/discovery/ledger.py`).

**No hindsight mutation.** A recorded decision is never edited. A changed call is a
new appended line; an outcome is a separate row keyed by `opportunity_id`.
"Current state" is always the `current_by_id` fold (latest row wins), so the
history is auditable and replay-safe. `opportunity_id = sha256(product_key |
trade_type | as_of)` — stable within an evidence date, so the same product on a
later day is a fresh hypothesis instance.

## Limitations

- **Sealed-only.** Singles/graded are Phase D; `asset_class` is present for
  forward-compatibility.
- **No verified-entry wire yet.** See the endpoint note above — arbitrage /
  live-packet paths need a verified deal candidate source (future discovery wire).
- **History depth = ledger depth.** Momentum is only as deep as
  `price_history.jsonl` has grown.
- **Paper mode only.** `LIVE_PACKET_ELIGIBLE` is a tag for human review, not an
  action; recording a decision never buys anything.
