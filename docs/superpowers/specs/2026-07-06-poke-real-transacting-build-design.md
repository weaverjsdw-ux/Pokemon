# Real Transacting Build — Buy Loop + Economics + Guards (Design)

**Date:** 2026-07-06
**Status:** Draft for review.
**Repo:** `Pokemon-main` (package `scanner/`; price-and-edge subsystem `scanner/poke_api/`).
**Ladder position:** the continuation of the private price-API ladder
(A → B → C → D/D.5 → E → F → F.1 → G → **this build**). G (population / gem-rate + grading-EV
credibility) is built and handed back. This build is **not** the older discovery/scanner A–E program.

**Decision this build executes.** The operator has committed to **transacting for real** (buy & sell),
not staying paper. Everything prior is a paper sandbox; it converts to money only at the *buy loop*.
This build makes that loop real, fee-honest, and safe — and deliberately stops there.

**Scope decision — ONE build, not a phase ladder.** The G–M roadmap listed ~16 follow-on phases. That
ladder was itself an over-engineering risk. This build collapses the items that serve *transacting now*
into a single coherent deliverable (one spec → one plan → one green suite), and **explicitly excludes**
the speculative operational-depth items until a real need names each one (see §"Do NOT build"). Building
a dashboard / scheduler / parser / export tooling *before the first real trade* is the over-engineering
being avoided.

---

## 1. The system in one line

Turn a **verified real listing** into a **fee-honest buy signal**, let the operator execute, record the
**actual acquisition and sale** in a first-class **inventory / cost-basis / P&L ledger**, and reconcile
outcomes back to the decision — while making the numbers the decision reads **correct** (data-quality
audit), **cheap** (free TCGCSV reference at 0 credits), and **drift-proof** (a monitor over the one
brittle scraped source). No auto-buy, no fabricated evidence, no false cross-source validation.

## 2. Cross-cutting invariants (every task inherits)

- **Price accuracy is STOP-class.** No source → no number. Every price/rate/fee carries a source URL +
  capture/effective date. Estimates are badged `EST` / `operator_assumption`, never presented as sold comps.
- **Exact identity only.** No fuzzy match, no guessed slug/id/grade; a miss is honest data.
- **Tool advises, human transacts.** No auto-buy / cart / checkout / login automation. The acquisition and
  sale records are **operator-entered records of a purchase the human already made** — never an executor.
  The terminal decision state stays `LIVE_PACKET_ELIGIBLE` (eligible, not executed).
- **The D-vs-E split is load-bearing and must not be "reconciled."** Comp-alone-never-promotes-off-WATCH is
  hardcoded in the **D** layer (`opportunities.py`: `LIVE_ELIGIBLE = {"sealed_retail_arbitrage"}`,
  `build_asset_opportunity` hardcodes `decision_hint="WATCH"`). Verified entries reach live **only** through
  the **E** layer (`edge.LIVE_ELIGIBLE_EDGE`, `edge.py:40`). This build extends the **E** route only and
  **must not touch** the D functions. The apparent contradiction is intentional.
- **Independent-of-PPT is structural, and TCGCSV is NOT independent.** `_INDEPENDENT_OF_PPT = {pricecharting}`
  (`divergence.py:36`). TCGCSV is TCGplayer lineage; TCGplayer market == PPT. A `tcgcsv` comp is a **reference**
  (free substitute for the paid PPT number), classified **external / non-independent**, and is **never**
  counted as `cross_source_validated`.
- **PAPER_BUY < LIVE ceiling.** `LIVE_PACKET_ELIGIBLE` stays strictly stricter than `PAPER_BUY`, reachable
  only through the full verified-evidence spine. A gem-rate/EV number caps at `PAPER_BUY`.
- **Two ledgers never conflated → now three.** Observation (`price_history.jsonl`) vs paper decisions
  (`paper_decisions.jsonl`) vs the **new inventory/P&L ledger** (`inventory.jsonl`) — each a physically
  distinct file/`kind`, append-only, idempotent by a sha256 `entry_id`, pure writer (`capture_date` passed in).
- **0 credits, no new dependency.** Every new read path reports `apiCallsConsumed.total = 0`. TCGCSV is plain
  `requests` + JSON — **no Playwright, no paid client, no new runtime dependency.** Live fetches are
  operator-gated (mirroring `poke.independent_sources`). `config.yaml` ends with live gates **off**.
- **TDD, full suite green.** Every unit test-first; `.venv/Scripts/python.exe -m pytest -q` (network-mocked)
  green at completion.

## 3. The one design decision resolved (acquisition/sale home)

**Acquisition and sale events live in the new `inventory_ledger`, not as a `paper_ledger` kind.** Rationale:
an acquisition is the birth of an **owned position with a real cost basis**, and a sale closes it with
**realized P&L** — a portfolio/money concern, distinct from decision-lifecycle. The code already anticipates
this exact ledger (`discovery/ledger.py:5`: *"…NOT the Phase-2 inventory ledger"*). The gem-rate ledger
(`gem_rates.py`) is the build template (separate file, own `entry_id`, own `kind`, own CLI subgroup,
gitignored + committed result doc as durable proof).

**The paper-vs-real boundary (explicit, per advisor).**
- `inventory_ledger` = the **money system-of-record**: real acquisitions + sales, actual paid, actual fees,
  realized P&L. Each row references the `edge_packet_id` / `opportunity_id` it acted on (when one exists;
  an acquisition may also be recorded with no packet).
- `paper_ledger` = **decisions + paper (hypothetical) outcomes**. It still records every decision (buy or
  pass); its **distinct ongoing value** is calibrating signals on opportunities the operator **passed on or
  did not buy**. Its `outcome` rows stay paper-hypothetical — real *sale* outcomes live in `inventory_ledger`.
- `signals_report` (task H.2) reads **both**: real realized P&L from `inventory_ledger` joined to the edge
  packet, and paper outcomes from `paper_ledger`, labelled distinctly. It never blends real and hypothetical
  into one number.

## 4. Build — the ordered task list

Order encodes dependency: doc edits (clear) → TCGCSV gate + adapters → fee model → accounting/quality/drift
(independent, interleavable) → inventory ledger → asset intake → acquisition wiring → outcome tie-back.
Each task is TDD; the suite is green at each task boundary.

### T0 — Roadmap reasoning-hardening (4 doc edits, near-zero)
Not code. In `docs/superpowers/specs/2026-07-06-poke-api-ladder-g-through-m-roadmap.md`: (1) reframe the
TCGplayer-independence justification from "structural" to **"conservative default under asymmetric error
cost"** (false corroboration is truth-poisoning; a forgone check is safe) + note it is the one claim F.1
could not re-probe (Playwright); (2) relabel G's sourced-pop as **transcription-verify + gap-fill** (one
PSA/CGC census underneath — not independent corroboration); (3) split every "no" into **permanent-vs-deferred**
tiers; (4) **name the cost** of each "no." Retires the chat-vs-roadmap portfolio contradiction (portfolio
*app* rejected; inventory/P&L *ledger* is this build).

### T1 — TCGCSV sample-check (the gate)
**Purpose.** Verify the load-bearing n=1 claim (TCGCSV market == PPT `ppt_cards`) at real n **before** trusting
TCGCSV as a reference for credit-saving.
**Delta.** A CLI/one-off (`edge_cli tcgcsv-check`) that, for each currently-mapped asset holding a `ppt_cards`
row in `price_history.jsonl`, fetches the matching TCGCSV `productId` market price and diffs it.
**Pass criteria (fixed).** ≥ 5 mapped assets compared (all available if fewer than 5 exist, and flag the thin
n), and **every** compared pair agrees within **≤ 2%** (TCGplayer market vs `ppt_cards`). Writes a committed
result doc (the ledger is gitignored).
**Failure fork (explicit).** On FAIL (any pair diverges > 2%, or n < the operator-approved floor): **TCGCSV-as-
reference (T2) is disabled** — the reference source stays gated off and paid PPT remains the reference — while
**TCGCSV-as-identity (T3) still ships** (identity ingest does not depend on price equality). The negative branch
is a first-class, tested outcome, not a hand-wave.
**Guardrail.** 0 PPT credits (reads the *already-recorded* `ppt_cards` rows; does not mint new PPT calls).
Operator-gated live TCGCSV fetch.

### T2 — TCGCSV reference adapter (free PPT substitute; NON-INDEPENDENT)
**Purpose.** Provide the raw/sealed TCGplayer-market reference for **free (0 credits)**, freeing PPT budget for
graded (where TCGCSV has no number). Only wired if T1 passed.
**Delta.** A new module `scanner/poke_api/tcgcsv.py`: an adapter exposing
`fetch(asset_or_product, checked_at) -> CompSourceQuote` (contract at `comps/model.py:21-31`), parsing
`resp.json()` from `https://tcgcsv.com/tcgplayer/3/{groupId}/products`, resolving by **exact `tcgplayer_id`**
(never fuzzy). Sealed: replaces the dead `comps/tcgplayer.py:44-47` `blocked` slot in `CompEngine`
(`engine.py:39-41`). Raw/graded: a reference source on the **external** footing (a free alternative to the
`ppt_cards` `ExternalCardPriceClient`, `sources.py:85-128`), **not** an independent one.
**CRITICAL classification.** Register a new `tcgcsv` provenance slug in `_EXTERNAL_SLUGS`/`_LOCAL_SLUGS`
(`edge.py:55-57`) and in `divergence.py:36` as **NOT** in `_INDEPENDENT_OF_PPT`. A lone reference number with
no independent corroboration resolves `low` confidence (`sources.py:425-439`) and is gated out of
`live_min_confidence` (`config.py:85`) — expected; `tcgcsv` is reference-only and never itself supplies
cross-source confidence.
**Naming-trap guard (per advisor).** If the raw/graded adapter reuses `build_independent_sources`
(`independent_sources.py:349-357`) plumbing, add a **loud comment** at that seam that `tcgcsv` is
NON-independent, and keep the real guard as a **test**: *a `tcgcsv` comp agreeing with `ppt_cards` is NEVER
flagged `cross_source_validated`* (mirrors the existing tcgplayer-not-independent test). Prefer a distinct
reference-source seam if it reads cleaner than reusing that builder.
**Fetch pattern.** Mirror `_fetch_body` (`independent_sources.py:175-189`): plain `requests`, custom UA
(`independent_sources.py:25-26`), 403/429 → `blocked` (never evaded), degrade honestly on `RequestException`.
Gated by a **dedicated `poke.tcgcsv`** flag (default **false**), kept separate from `poke.independent_sources`
so "reference ≠ independent" stays honest (§8.1).
**Guardrail.** 0 PPT credits by construction (never constructs a PPT client).

### T3 — TCGCSV identity ingest (exact mapping bootstrap; the J-replacement)
**Purpose.** Bootstrap exact `tcgplayer_id` + card number for catalog mapping from TCGCSV, replacing the
proposed fuzzy mapping-assistant with an exact join. Ships regardless of T1's result.
**Delta.** A helper (`edge_cli tcgcsv-ingest --group <name|id>`) that lists `/tcgplayer/3/groups` (217 groups,
recent sets confirmed present) → `/tcgplayer/3/{groupId}/products` → each product's exact `productId` +
`extendedData` "Number". Emits **proposals** (exact `tcgplayer_id` + card_number) for operator review against
`catalog.py` assets — **never an auto-write** to `assets.yaml`. PriceCharting slugs still come from the existing
redirect-confirmed resolver (unchanged).
**Guardrail.** Exact join only (match on set + number + name → exact `productId`); a non-exact candidate is
surfaced for review, never written. 0 credits (TCGCSV is free/keyless).

### T4 — Honest fee model (P; extend, don't rebuild)
**Purpose.** Net **real, current, versioned** fees into every margin/EV so a real buy is not shown a fake profit.
**Today.** `FeeModel` (`margin.py:11-16`) is eBay-only (`ebay_fvf_pct=0.1325`, `ebay_fixed_fee=0.40`,
`local_haircut_pct=0.15`); `net_margin` (`margin.py:50-73`) applies it; `cost_basis` (`margin.py:27-29`) is a
forward buy-breakeven (grosses retail by tax) — **not** realized cost basis (see T8).
**Delta.**
- **Channels.** Parameterize by sell channel: **eBay** (~13.25% FVF + $0.30/$0.40 per order, on item+ship+tax;
  50% FVF discount on singles ≥ $1,000) and **TCGplayer** (**10.75%** marketplace commission effective
  2026-02-10, + payment processing ~2–2.5% + $0.30). Channel selected per packet/sale.
- **Grading cost provenance.** Encode PSA tiers with the **live reality**: value tiers ($25–$59) **paused
  2026-06-02**; realistic floor **~$80 (Regular)** + shipping both ways. `grading_ev` (`grading_ev.py:79`)
  consumes the sourced grading_fee, so its break-even reflects today's real cost, not a stale ~$25 assumption.
- **Versioning (required, not gold-plating).** Every fee carries an **`effective_date` + `source_url`**; the
  model is selected by date so historical rows keep their era's fees. Fees change often (TCGplayer 2026-02,
  PSA 2026-02 & 2026-06) — un-versioned fees silently misprice.
- **Shipping realism** as a channel/weight input.
**Attach points.** Extend `FeeModel` (`margin.py:11`) + `net_margin` (`margin.py:50`); it propagates to
`edge._fee_model` (`edge.py:254-257`), grading-EV (`edge.py:354`), `opportunities.compute_margin`
(`opportunities.py:143-156`), `discovery/score.py:41-51`, `main.py:361-367`. **Touch both `_shipping_for`
copies** (`main.py:347`, `opportunities.py:115`) — kept identical by contract. The reserved
`fee_assumption_difference` divergence slot (`divergence.py:42-45`) is the audit hook.
**Sources (pin exact rates at build time, cite):** eBay selling fees, TCGplayer fees help, PSA 2026 pricing.

### T5 — Sealed refresh credit accounting (I; close the silent 0)
**Purpose.** Every billable path reports bounded spend or refuses first; no billed call reports 0.
**Today (the gap).** Sealed `refresh=true` hardcodes `row["creditsConsumed"]=0` (`engine.py:82`) and
`model.comp_response` (`model.py:47-76`) **drops the field entirely** — no accounting at all.
**Delta.** Mirror the asset path (`router.py:255-260` + `sources.expected_asset_credits`,
`sources.py:206-228`, and `asset_model` `apiCallsConsumed`): emit a deterministic upper-bound
`apiCallsConsumed` on the sealed `refresh=true` route; read / `refresh=false` / no-client / unmapped report
`0`, `source:"local"`. Surface estimated spend + require operator go-ahead before a billable sealed lookup.
Shrinks naturally as T2 displaces sealed PPT calls.
**Test.** A counting/failing-client belt asserting no billed sealed path reports 0 (twin of the asset/edge belts).
**Guardrail (money-class).** `limit=1` mandatory on by-id PPT lookups (`market.py:49`), never removed; resolve
sealed by exact `tcgPlayerId`; free tier 100 cr/day.

### T6 — Data-quality audit (O; validate before a number drives a buy)
**Purpose.** Catch a bad slug / missing URL / unsupported grade / stale observation **before** it prices a
real purchase.
**Today.** `catalog.validate_asset` (`catalog.py:44`) checks identity **presence** only — no slug/URL format,
no grade vocabulary, no `tcgplayer_id` check.
**Delta.** An audit CLI/report over catalog + ledgers: slug/URL format, grade-vocabulary (`_grade_cell_for`,
`independent_sources.py:223` as prior art), `tcgplayer_id` presence/shape, missing source URL, non-NM raw
caveat (`raw_condition_recordable`), stale observations vs `staleness_days`, missing gem-rate, missing
entry-evidence. **Fix the concrete latent bug:** `price_history.jsonl` stores `source_url` with `&amp;` while
`assets.yaml` slugs use literal `&` — since `entry_id` hashes the URL, this can defeat idempotency and
**double-record**; normalize encoding and add a regression test.
**Guardrail.** Report only — computes no new truth, changes no decision.

### T7 — Source-drift monitor (R; guard the one brittle leg)
**Purpose.** The buy-side now bets real money on one scraped source (PriceCharting). Detect parser-shape drift
and **fail safe** instead of silently emitting a wrong/empty number.
**Today.** All PriceCharting/pop parsing is regex over raw HTML (`independent_sources.py`): date-verified cell
ids (`:30-37`, "Verified 2026-07-05"), price regex, and the pop blob `_POP_RE` (`:98-99`) that matches only a
**flat** `{[^{}]*}` — a nested-brace change degrades **silently** to `present:True, pop:{}` (no error). No
drift detector exists.
**Delta.** A monitor (operator-run, 0 credits) that fetches known-good fixture/live pages and asserts the cells
+ pop blob still parse to expected shapes; on a shape change it **fails loudly** and writes a drift report,
rather than letting a downstream `no_match`/empty-pop pass as truth.
**Guardrail.** Detection only; never evades a challenge; never auto-repairs a parser.

### T8 — Inventory / cost-basis / P&L ledger (the "am I making money" record)
**Purpose.** A first-class record of **owned positions**, **cost basis**, and **realized/unrealized P&L** — the
legitimate need the rejected *portfolio app* was burying.
**Home & pattern.** New `scanner/poke_api/inventory_ledger.py` → `data/poke/inventory.jsonl` (gitignored,
"runtime ledgers" block), CLI subgroup in `edge_cli.py` dispatch (`:681-697`); template = `gem_rates.py`
(separate file, own `entry_id`, own `kind`). **Key via `history.item_key_for_asset`** (`history.py:96`) — never
hand-replicate the 5 identity slots (drift risk flagged at `history.py:80`).
**Quantity model (deliberately simple, per advisor — NOT FIFO lots).** Per `asset_key`: **quantity +
weighted-average cost basis.** An acquisition adds quantity at its all-in unit cost (updating the average); a
sale reduces quantity and realizes P&L against the average. No per-lot tracking, no FIFO/LIFO — a hobby-scale
model, stated so no painful migration is needed later.
**Realized-P&L formula (explicit).**
- **Acquisition unit cost basis** = actual price paid + buy-side fees + buy-side shipping + tax paid.
- **Realized P&L on a sale** = sale proceeds − sell-side fees (channel-selected from the T4 `FeeModel`) −
  sell-side shipping − (units sold × weighted-average cost basis).
- Do **not** reuse `margin.cost_basis` (it is forward buy-breakeven, not realized).
- **Worked example.** Buy 1× raw card for $40 + $2 tax = $42 basis. Sell on eBay for $100: FVF 13.25% =
  $13.25 + $0.40 + $6 ship = $19.65 sell cost. Realized = $100 − $19.65 − $42 = **$38.35**.
**Rows.** `kind ∈ {acquisition, sale}`; acquisition carries `asset_key, item_key, qty, unit_price_paid,
buy_fees, shipping, tax, all_in_unit_basis, source_url, edge_packet_id?, checked_at`; sale carries
`asset_key, item_key, qty, proceeds, channel, sell_fees, shipping, realized_pnl, checked_at`. Read projections:
current positions (qty + avg basis + unrealized vs latest comp) and lifetime realized P&L.
**Guardrail.** Append-only, idempotent, operator-entered (records a purchase the human made — never an executor).

### T9 — Asset verified-entry intake (H.1; the load-bearing unblock)
**Purpose.** Make the raw/graded buy route reachable in production. Today it is **dead code**:
`current_asset_entry_candidates` requires a non-empty `asset_key` (`candidates.py:231/241`), but nothing writes
an asset candidate with `asset_key` set, so `asset_candidate_for_provider` (`candidates.py:279`) and
`build_asset_packet`'s live route (`edge.py:317`) never fire outside tests.
**Delta.** A validated asset intake path: extend `lab candidate-add` to route on `deps.assets` (parallel to the
sealed gate at `lab.py:314`) **or** add `edge_cli candidate-add-asset`; pass `asset_key`/`condition`/`grade_key`
into `make_candidate` (already accepted, `candidates.py:109`). Reuse the STOP-class gate `entry_evidence_ok`
(`candidates.py:67`): requires verified stock status, price > 0, buy URL, evidence text, checked-at; a gate-fail
becomes an evidence-only row (stays WATCH), never a fabricated entry.
**Guardrail.** No fabricated candidates; downstream provider + packet already exist (small delta).

### T10 — Acquisition wiring (H stage 3; decision → real position)
**Purpose.** Close the "operator executes" gap — confirmed absent today (no execution/position surface), which
is what structurally enforces advise-not-buy.
**Delta.** An operator CLI (`edge_cli acquire`, manual like `outcome`) that takes an `EdgePacket` /
`opportunity_id` the operator acted on and writes an **acquisition** row into `inventory_ledger` (T8) with the
actual paid price, fees, shipping, tax, and the `edge_packet_id` link. The **decision** side (recording the
buy decision into `paper_ledger`) stays the existing path via the mandated bridge `paper_ledger_view`
(`edge.py:513`) — unchanged; T10 adds only the real-fill inventory row, joined to the decision by
`edge_packet_id` (so the durable audit columns `entry_price`/`market_comp`/`product_key` are never nulled).
**Guardrail.** A **record**, never an executor. No order/cart/checkout code. Read paths stay 0-credit.

### T11 — Outcome / P&L tie-back (H.2; did the buys pay off)
**Purpose.** Reconcile the decision (assumed) against reality (actual fill + realized sale).
**Delta.** Extend `signals_report` (`paper_ledger.py:164`) to read **both** ledgers per the §3 boundary: real
realized P&L from `inventory_ledger` joined to the `edge_packet_id`, and paper outcomes from `paper_ledger`
(non-buys), labelled distinctly — never blended. Surfaces expected-vs-actual, hit rate, and the basis for an
avoid-list. Additive to the existing fold.
**Guardrail.** Read-only projection; no decision-logic change.

## 5. Do NOT build (in this build)

**Deferred — build only when a real pain names it (not phases, triggers):** trade analytics beyond the T11
tie-back; history depth + scheduled snapshots (net-new scheduler); operator dashboard + coverage report; local
title parser + corpus (build when drowning in listings); grading-EV scenario lab (build when actively grading
enough that G's static sensitivity table is insufficient); export pack; backup-hygiene tooling; PPT audit
sample-expansion (operator action); auction-house APR (manual, high-value graded only — no clean free API).

**Permanent rejections (identity-level, never):** auto-buy / cart / checkout / login automation · fuzzy
mapping that writes catalog truth · portfolio / wishlist app (the *ledger* is T8; the *app* is rejected) ·
public API polish / hosting · TCGplayer/Playwright as *independent* validation · PPT-clone behavior ·
ask-only comps · fabricated / seeded verified entries · read-path paid calls.

## 6. Acceptance

1. A **real operator-supplied listing** for a raw/graded asset produces a **fee-honest** buy-signal edge packet
   (net margin nets current versioned fees) or blocks with named inputs; **no listing → WATCH**, never a buy.
2. The operator records an **acquisition** and later a **sale**; the inventory ledger reports the position
   (qty + weighted-average basis + unrealized) and **realized P&L** matching the worked-example formula.
3. `signals_report` reconciles real realized P&L (inventory) vs paper outcomes (non-buys), labelled distinctly.
4. TCGCSV: the sample-check gate passes (or its fail-branch disables reference while identity still ships); a
   `tcgcsv` comp is **never** `cross_source_validated`; TCGCSV reference reads at **0 credits**.
5. Every billable path reports bounded credit spend or refuses first; **no** billed path reports `0`.
6. The data-quality audit flags bad slugs/URLs/grades and the `&`-encoding bug is fixed (no double-record).
7. The drift monitor fails loudly on a simulated PriceCharting shape change (incl. nested pop blob) instead of
   emitting empty/wrong data.
8. The 4 roadmap doc edits are applied. Full network-mocked suite green; `config.yaml` live gates **off**; no
   new runtime dependency added; 0 PPT credits on every new read path.

## 7. Code anchors (consolidated)

- **Buy loop:** `edge.py` (`decide_edge:131`, `LIVE_ELIGIBLE_EDGE:40`, `EdgePacket:171`, `build_asset_packet:317`,
  `paper_ledger_view:513`, slug classes `:55-57`), `candidates.py` (`entry_evidence_ok:67`, `make_candidate:105`,
  `current_asset_entry_candidates:231`, `append_candidate:166`), `lab.py` (`candidate-add:313`),
  `opportunities.py` (D-layer WATCH invariant — **do not edit**).
- **Ledgers:** `paper_ledger.py` (`decision:45`, `outcome:65`, `current_by_id:147`, `signals_report:164`),
  `gem_rates.py` (template), `history.py` (`item_key_for_asset:96`, `staleness:234`), `discovery/ledger.py:5`
  (the anticipated inventory ledger).
- **Pricing / TCGCSV / accounting:** `comps/engine.py` (`estimate:71`, sources `:39-41`, `creditsConsumed=0:82`),
  `comps/tcgplayer.py:44` (dead slot TCGCSV replaces), `comps/model.py:21` (`CompSourceQuote`),
  `independent_sources.py` (`_fetch_body:175`, `build_independent_sources:349`, pop `_POP_RE:98`, cells `:30-37`),
  `sources.py` (`ExternalCardPriceClient:85`, `expected_asset_credits:206`, `resolve_independent_asset_row:300`),
  `market.py` (PPT client `:39`, `limit=1:49`), `poke_api/model.py` (`comp_response:47`, `sealed_facade:151`),
  `router.py` (`_comp:116`, asset credits `:255-260`, `_signals:385`), `divergence.py`
  (`_INDEPENDENT_OF_PPT:36`, `fee_assumption_difference:42`).
- **Fees:** `margin.py` (`FeeModel:11`, `net_margin:50`, `cost_basis:27`), consumers `edge.py:254`,
  `opportunities.py:143`, `main.py:361` + `_shipping_for` twins (`main.py:347`, `opportunities.py:115`),
  `config.py:385`. **Grading EV:** `grading_ev.py` (`grading_ev:79`, sensitivity `:60`).
- **Catalog / quality:** `catalog.py` (`validate_asset:44`, `_SUMMARY_FIELDS:29`), `edge_cli.py` (subcommands +
  dispatch `:681`).

## 8. Resolved decisions (operator-confirmed 2026-07-07)

1. **TCGCSV config gate:** a **dedicated `poke.tcgcsv`** flag (default false) — TCGCSV is a *reference* source,
   kept semantically separate from `poke.independent_sources` so "reference ≠ independent" stays honest.
2. **Sample-check floor (T1):** **fixed** — ≥ 5 mapped assets compared, every pair within **≤ 2%**. Not
   per-run operator-tunable.
3. **Fee channel default (T4):** when a packet has no chosen sell channel, default to **eBay** (conservative,
   higher fees); explicit channel override allowed.
4. **Unrealized P&L mark (T8):** value open positions against the latest **independent PriceCharting** comp,
   never the TCGCSV reference (which is reference-only).

## 9. Plan-2 reference-adapter decisions (operator-confirmed 2026-07-07)

Resolved via brainstorming before Plan 2 (which builds **T2 + T4 + T5**). These extend §8 and
govern how the T2 reference adapter wires in. They change no §2 invariant.

1. **Plan-2 scope — build T2 now AND attempt to pass T1 this plan.** Plan 2 = T2 (reference
   adapter) + T4 (fee model) + T5 (sealed credit accounting), plus a mapping workstream that tries
   to turn the still-false T1 gate green: map ≥ 4 more raw singles with exact `tcgplayer_id` (the
   F.1 Charizard / Pikachu / Sylveon raws via `tcgcsv-ingest`, + ~1 new), record a fresh `ppt_cards`
   raw comp for each (~4–5 PPT credits, `limit=1`, **money-class → operator go-ahead at execution**),
   then run `tcgcsv-check` at n ≥ 5. **Honesty is absolute:** if any pair diverges > 2% the gate
   FAILS, T2 ships **dormant** (flag false), and the fail is documented — nothing is tuned to force a
   pass. Current state: **1** mapped+comped raw pair (Umbreon `610516`); **2** `ppt_cards` comps total.

2. **Sealed comp-engine confidence — keep `high`.** tcgcsv fills the dead sealed `tcg` slot
   (`comps/tcgplayer.py:44` always-`blocked`); `resolve()` is **unchanged**, so its `tcg + pc agree →
   high` precedence (`model.py:99-110`) applies with a real number in the slot. Rationale: tcgcsv IS
   the TCGplayer-market number that slot always meant; PriceCharting is the independent leg; PPT is
   not in the sealed path (no double-count); and at the default `medium` live floor (`config.py:86`),
   `high` vs `medium` changes no gate. The conservative alternative (a source-aware `medium` cap) was
   **rejected** — it requires surgery on the load-bearing pure `resolve()` for zero gate benefit.
   Stricter sealed live buys, if ever wanted, come from raising `live_min_confidence` to `high`
   (config), not from distorting comp math. Integration: `_exact_source_url` (`model.py:152`) is
   extended to accept `source == "tcgcsv"` for STOP-class attribution (the tcgcsv price-endpoint URL).

3. **Raw/graded footing — reference-only.** tcgcsv does **not** fill the raw independent `tcg` slot in
   `sources.resolve_independent_asset_row` (`sources.py:300`); it never lifts raw/graded confidence.
   A raw single stays PriceCharting-alone `low` on free data, so a raw LIVE buy still requires a paid
   PPT confirmation. Rationale: matches the spec's plain "external footing, NOT independent" (T2);
   conservative default under asymmetric error cost for the real-money E-layer; trivially reversible
   if raw-live proves too rare in practice. Graded is unaffected (tcgcsv has no graded number).

4. **Independence classification + guards.** Register `tcgcsv` in `_EXTERNAL_SLUGS` in **both**
   `edge.py:55` and `divergence.py:36` (external footing, so a `tcgcsv + ppt_cards` comp never mistags
   `local_plus_external_audit` and tcgcsv is auto-excluded from the matrix's `_latest_independent_comp`
   at `divergence.py:200`); **never** add it to `_INDEPENDENT_OF_PPT` (`divergence.py:40`). tcgcsv is
   excluded from **both** sides of the divergence audit — neither the independent "ours" nor the
   canonical PPT "theirs" (which stays `ppt_cards`). Mechanically this separates the "PPT-reference"
   selector role from the "non-independent-exclusion" role, so widening `_EXTERNAL_SLUGS` does not pull
   tcgcsv into the "theirs" side. **Two required tests:** (a) a `tcgcsv` comp agreeing with `ppt_cards`
   is **never** `cross_source_validated` (mirrors the tcgplayer-not-independent test); (b) a recorded
   `tcgcsv` observation is **never** selected as the independent/"ours" side of the divergence matrix.

5. **`tcgcsv_group_id` catalog field (Plan-1 deferred follow-up).** Add a per-asset and
   per-sealed-product `tcgcsv_group_id` field; the adapter and `tcgcsv-check` fetch prices by exact
   group id, **retiring the set-NAME matching** in `tcgcsv_check.resolve_group_id`. Exact-id discipline
   (id > name). Populated during the (1) mapping step — `tcgcsv-ingest` already surfaces the groupId
   alongside the productId.

6. **Gate coupling — soft, via `poke.tcgcsv`.** The `poke.tcgcsv` flag (default **false**; `config.yaml`
   stays false) gates the whole adapter — live fetch **and** confidence contribution — mirroring
   `poke.independent_sources`. The committed sample-check PASS doc is the operator's evidence to flip
   it on locally. No separate hard runtime pass-marker (avoids over-engineering); if the (1) gate run
   fails at n ≥ 5, T2 stays dormant, identical to shipping it gated-off.
