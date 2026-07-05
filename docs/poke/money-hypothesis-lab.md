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

> The read API produces opportunities from **catalog + comp + momentum**, plus any
> **verified candidate** in the intake ledger (see *Activation* below). With an
> empty candidate ledger, `entry_price` is `None` and every opportunity is a
> `WATCH`/`catalog_gap`/`momentum_watch` — honestly, because there is no verified
> buy price to act on. Supply a verified candidate (manual intake or manifest
> replay) and the `PAPER_BUY` / `LIVE_PACKET_ELIGIBLE` paths light up for that
> product.

## Activation — the verified candidate wire

Phase C ships dormant-but-correct: structurally right, but producing no buy-shaped
decisions until a **verified entry price** flows in. That wire is
`scanner/poke_api/candidates.py` + an append-only ledger at
`data/poke/verified_candidates.jsonl`.

**The entry gate (STOP-class).** A candidate carries an `entry_price` **only** when
it clears an evidence gate that mirrors `discovery/verify.alert_allowed`:
positive-buyable `stock_status` (`verified_buyable` / `in_stock` / `limited`) **and**
an observed price > 0 **and** a `buy_url` **and** stock evidence text **and** a
`stock_checked_at`. Miss any of those and the candidate is still recorded — as an
**evidence row** with `entry_price = None` — but it can only WATCH/REJECT, never
PAPER_BUY or LIVE_PACKET_ELIGIBLE. A `parser_suspect` / `unverifiable` candidate is
evidence, never a buy. Idempotent by a sha256 `candidate_id`; old rows are never
rewritten.

**Two evidence-backed intake sources** (both structurally PPT-free / network-free):

1. **Manual, operator-verified** — `lab candidate-add` appends one candidate the
   operator has verified on the retail page. This is not a fake source; it is an
   evidence-backed manual observation.
2. **Discovery manifest replay** — `lab candidates-from-manifest` reads an existing
   discovery board / manifest and imports **only** verified-buyable rows (positive
   stock + `buy_url` + verified price) as candidates. Rows that are
   `parser_suspect` / `unverifiable` / `out_of_stock` / `price_mismatch` are
   summarized as **blocked evidence**, never converted to buys; a buyable row that
   maps to no catalog product is reported as **unmatched**, never silently dropped.
   Replay gates on **stock evidence**, never on `deal_price` — a sealed board
   carries MSRP-as-`deal_price` with a *comp*-level `price_confidence: verified`,
   which is **not** a purchasable entry. Pointed at a bare sealed *manifest* (no
   `deals` array), replay resolves the sibling `<sweep_id>.json` board, or reports
   `manifest_no_deals` — it never reads a wrong file as "0 buyable".

eBay Browse is prepared but **not required**: `candidates-from-ebay` returns a
clean `not_configured` (`NEEDS_API_KEY`) when no keyset is present; with a keyset,
the model maps injected Browse items to **evidence-only** candidates (an advertised
BIN price is not a verified entry until the keyed live check — a later slice).

**`build_deps` wires it automatically.** The live API defaults `candidate_for` to a
provider folded from `verified_candidates.jsonl`, so a manually-added or replayed
verified candidate flows into `/api/poke/opportunities` and `/signals` with no code
change. Empty ledger ⇒ honestly dormant.

**Provenance is preserved.** A candidate-backed opportunity carries the candidate's
source + stock evidence in `input_snapshot`, which the paper decision row records
immutably — the audit trail runs verified evidence → decision.

`price_history.jsonl` stays **read-only** throughout; activation only appends to
`verified_candidates.jsonl` (candidates) and `paper_decisions.jsonl` (decisions).

## Dormancy & activation report

`lab candidates-report` (and `GET /api/poke/candidates/report`, and the `activation`
block on `/api/poke/signals`) answers *why there are no live packets today*:

```json
{"products_seen": 22, "candidates_seen": 0, "verified_candidates": 0,
 "paper_buy_count": 0, "live_packet_eligible_count": 0, "watch_count": 22,
 "reject_count": 0, "no_entry_price_count": 22, "no_comp_count": 9,
 "stale_comp_count": 0, "parser_suspect_count": 0,
 "top_blockers": [{"blocker": "opportunities_without_verified_entry_price", "count": 22}, ...],
 "closest_products": [{"product_key": "...", "score": 12.0, "decision_hint": "WATCH",
                       "blocker": "no verified entry price"}, ...],
 "dormant": true,
 "why_no_live_packets": "no verified buy candidates yet — every opportunity lacks a
   verified entry price; add one via `candidate-add` or replay a discovery manifest"}
```

Add one valid verified candidate and the same report goes **active**: the product's
opportunity gains `entry_price` / net / ROI, records `PAPER_BUY` (or
`LIVE_PACKET_ELIGIBLE` if it clears the stricter live floor), and `dormant` flips
to `false`.

## CLI

```
python -m scanner.poke_api.lab list [--json]          # score the catalog
python -m scanner.poke_api.lab record --product KEY [--decision D] [--reason R] [--as-of DATE]
python -m scanner.poke_api.lab record-all [--as-of DATE]   # record every decision hint
python -m scanner.poke_api.lab outcome --opportunity ID --status S \
        [--price P] [--net N] [--note ...] [--observed-at DATE]
python -m scanner.poke_api.lab report [--json] [--include-candidates]   # signals + replay (+ activation)

# --- activation: verified candidate intake + replay + reporting ---
python -m scanner.poke_api.lab candidate-add --product-key KEY --entry-price P \
        --buy-url URL --stock-status verified_buyable --evidence "..." \
        [--source manual_verified] [--retailer R] [--confidence C] [--observed-at DATE]
python -m scanner.poke_api.lab candidates-from-manifest --manifest PATH [--json]
python -m scanner.poke_api.lab candidates-report [--json]   # dormancy / blockers / closest
python -m scanner.poke_api.lab record-candidates            # record candidate-backed decisions
python -m scanner.poke_api.lab candidates-from-ebay [--json]  # not_configured without a keyset
```

Outcome `status` ∈ `SOLD | HELD | PRICE_UP | PRICE_DOWN | EXPIRED | VOID`. A
`candidate-add` whose `--product-key` is not in the catalog is rejected (reported,
not written); one missing stock evidence is kept as an **evidence row** (no
`entry_price`), never a buy.

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

## Endpoints (activation)

### `GET /api/poke/candidates`
Current verified (entry-bearing) candidates + ledger counts (`candidates_seen`,
`verified_candidates`). Evidence-only rows are counted, not returned as buys.

### `GET /api/poke/candidates/report`
The dormancy / activation report (same shape as `candidates-report`).

`GET /api/poke/signals` also carries the `activation` block alongside `signals`.

## Session E — personal edge layer (on top of the Lab)

Session E adds the program's **own decision layer** over this spine:
`scanner/poke_api/edge.py` emits a first-class `EdgePacket` per subject (sealed **and**
raw/graded), with an explainable `decision_hint`, `blockers`, `source_posture`, and
(for raw) a `grading_ev` block. `edge_packet_id` uses the **same recipe** as
`opportunity_id`, so a decision recorded from an edge packet (`edge_cli.py record`)
lands in this same `paper_decisions.jsonl` and replays through `signals`.

What E adds over Phase C / Track D:

- **Raw/graded verified-entry route.** `candidates.py` now carries `asset_key` /
  `condition` / `grade_key` and a **disjoint** asset fold (`current_asset_entry_candidates`
  / `asset_candidate_for_provider`), so a raw/graded single can become buy-shaped —
  but **only** through a verified asset candidate (the same STOP-class
  `entry_evidence_ok` gate). A D-era raw/graded WATCH row is never promoted to live off
  a comp alone; `opportunities.py` is untouched.
- **Grading EV** (`grading_ev.py`): the "buy raw, grade, sell the slab" hypothesis.
  Blocks on any missing input (raw entry, raw comp, graded comp, grading fee, resale
  fees, gem rate); the gem rate is an operator assumption (`gem_rate` +
  `gem_rate_source` on the asset), so grading EV is capped at PAPER_BUY (never LIVE).
- **Divergence audit** (`divergence.py`): an off-hot-path, operator-gated comparison of
  our comp vs the external provider. Read paths remain 0 credits; external mode needs
  `--yes` + a key and prints/limits the spend. **PPT/external comparison is audit-only.**
- **Endpoints** (read-only, 0 credits): `GET /api/poke/edge-packets`,
  `/api/poke/edge-packets/{id}`, `/api/poke/edge-summary`. **CLI**: `edge_cli.py list /
  show / record / outcome / divergence-audit`.

See [`private-price-api.md`](private-price-api.md#session-e--personal-edge-layer) and the
[edge-layer runbook](edge-layer-runbook.md).

## Limitations

- **Singles/graded now have a buy route (Session E).** Raw/graded assets are buy-shaped
  **only** through the E verified-entry route (a verified asset candidate); with none
  they stay WATCH/DATA_NEEDED evidence. Grading-EV-driven LIVE eligibility is a
  documented follow-on (gem rate is an operator assumption, capped at PAPER_BUY).
- **Verified-entry wire is live, evidence-gated.** Arbitrage / live-packet paths
  activate from the `verified_candidates.jsonl` ledger (manual intake or manifest
  replay). eBay Browse is prepared but keyset-gated (`not_configured` until
  provisioned); catalog-retailer same-listing verification is a later slice.
- **History depth = ledger depth.** Momentum is only as deep as
  `price_history.jsonl` has grown.
- **Paper mode only.** `LIVE_PACKET_ELIGIBLE` is a tag for human review, not an
  action; recording a decision never buys anything.
