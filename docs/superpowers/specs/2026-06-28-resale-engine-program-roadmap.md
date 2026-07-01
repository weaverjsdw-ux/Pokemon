# Hobby-Funded-Resale Intelligence Engine — Program Roadmap (A–E)

**Date:** 2026-06-28
**Status:** Approved decomposition. A **menu**, not a commitment — each phase gets its own
spec → plan → build cycle and is built only when a real consumer earns it.
**Repo:** `Pokemon-main` (package `scanner/`, discovery subsystem `scanner/discovery/`)

> This roadmap captures the whole program the operator wants ("scope it all"). It is
> deliberately a menu built **along the grain of real consumers**, not a horizontal
> foundation poured up front (that was the YAGNI trap the first-build discussion corrected).
> Build order A→E is the dependency order; the **first detailed build is a vertical slice**
> (`2026-06-28-poke-live-sealed-slice-design.md`), which pulls in only the Phase-A bits it needs.

---

## The system in one line

One engine across the full lifecycle — **discover → decide-to-buy → track → decide-to-sell/open/grade**
— powered by rich market data (PPT v2 + eBay Browse + retailer adapters), surfaced through
dashboards + alerts. The human transacts; the tool advises. All existing doctrine holds
(no auto-checkout / auto-listing / account abuse; every number traces to a real comp with a
confidence tier; demote-never-hide; truthful confidence labelling).

## What already exists (do not rebuild)

- **Scanner** (buy-side): route-aware multi-retailer stock polling → fee-adjusted **BUY/THIN/SKIP**
  verdicts on alerts (`margin.py`, `verdict.py`), Discord/ntfy/console + web board.
- **Comp backbone:** `resale.py` (eBay Browse + public/PriceCharting fallback, confidence tiers),
  `market.py` (**PPT v2 sealed comp by `tcgPlayerId`**, medium-confidence market summary),
  `confidence.py`.
- **`/poke` deterministic core:** `discovery/schema.py` (STOP gate), `ledger.py` (append-only
  observation ledger), `score.py` (badges / fake-markdown / COL·PLY·INV·FLP lenses, FLP via backbone),
  `render.py` + `template.html`, golden test — all exercised on a fixture today.
- **PPT v2 contract** captured in `docs/poke/reference/ppt-v2-notes.md`; Phase-0 findings in
  `docs/poke/PHASE0_FINDINGS.md`.

## Tiering (graceful degradation, not a paywall)

Features light up by PPT plan and degrade cleanly when data is absent (the existing
"enable-when-key" doctrine):
- **Free (100 cr/day, 3-day history):** sealed + graded + raw current comps, velocity. History-based
  signals are noise at 3 days — treat momentum as needing the paid tier.
- **API ($9.99, 20k cr/day, 6-mo history):** momentum/appreciation signals become real; full catalog
  + discovery coverage.
- **Business ($99, 200k cr/day):** GemRate population (grading-EV depth), eBay per-listing sold detail,
  daily bulk CSV (full-catalog sync). Only Phase C/D grading depth needs this.

---

## Phase A — Comp/data backbone enrichment *(foundation; built incrementally as B/C/D pull it)*

**Goal:** give every downstream decision richer inputs than "one sealed price."
**Components (each added when its consumer exists — NOT all up front):**
- `/cards` comp methods: **graded** (`includeEbay` → `salesByGrade[grade].smartMarketPrice.{price,confidence}`,
  confidence maps 1:1 to our tiers) and **raw singles** (`prices.market` by condition). +1 credit for eBay.
- **Momentum** signal from price history (needs API-tier's 6-mo window; noise on Free) + PPT `marketTrend`.
- **Sell-through velocity** (`salesVelocity`) → the Flipper lens's missing "how fast it sells."
- **Enriched comp row** (backward-compatible optional fields: `graded` map, `momentum`, `velocity`) —
  the scanner's `estimate`/`confidence` path stays unchanged; new consumers read the new fields.
- **`ppt_id` seeding** (sealed catalog data task, `docs/poke/ppt-id-seeding.md`) + on-demand card-id
  resolution for discovery.
- **Credit governance:** read `X-RateLimit-Daily-Remaining` / `metadata.apiCallsConsumed`; config daily
  cap; enrich **on-demand for evaluated/alerted/discovered items**, never the whole catalog speculatively.
**Depends on:** nothing new. **Consumers:** B (discovery comps), C (signals), D (grading/sell-side).

## Phase B — Live `/poke` discovery *(the AI-research pipeline goes live)*

**Goal:** surface real market-wide deals beyond the tracked catalog, rendered as curated dashboards.
**Components:** DISCOVER adapters (Playwright + eBay Browse API + retailer sale pages + PPT
min/max-price scans — sources per the Phase-0 fetchability sweep); RESEARCH comp routing through A;
the **OPENER persona + `/poke` command + mode dispatch** (scan / watch / check / expert); live rendered
dashboards + scheduled sweeps; **regression hardening** (golden test live, persona self-test,
prompt-durability sidecar `.poke-opener-verified.json`, watchlist write-path, manifest delta).
**Depends on:** A (graded/raw comps for discovered items), the vertical slice (live render path).
**Prereq:** the exhaustive source-fetchability sweep (Phase-0 Probe B) signed off.

## Phase C — Decision intelligence *(the "why buy/hold/sell" brain)*

**Goal:** turn comps + signals into guidance, not just prices.
**Components:** momentum/appreciation folded into verdicts (buy-the-dip / sell-the-peak);
**graded arbitrage** (raw↔graded spread net of grading cost + gem-rate odds); **open-vs-flip EV**
(sealed: E[open] vs sell-sealed); **opportunity scanner** (undervalued sealed/raw/graded as its own
alert class). **Depends on:** A (momentum, velocity, graded comps, population for gem-rate).

## Phase D — Lifecycle / portfolio *(closes the loop; = original spec's Phase 2 + 3)*

**Goal:** manage what you own, end to end.
**Components:** **inventory ledger** (`ledger.py` sibling: lots, cost basis incl. tax, state machine
`acquired→holding→listed→sold`, an `opened` branch spawning child singles, realized P&L) — **kept
strictly distinct from the observation ledger**; **sell-side helper** (net-per-channel, sell-now-vs-hold
signal, listing draft — never auto-listed); **grading screen** (raw → grade-worthiness gate using
gem-rate + live grading cost); **Holdings dashboard** (unrealized value at live comps, per-lot
recommendation, running self-funding P&L). **Depends on:** A (comps, gem-rate), independent of B.

## Phase E — Automation / product surface *(always-on)*

**Goal:** make it run itself and speak with one voice.
**Components:** scheduled sweeps + comp refresh (cron), watchlist **target-hit alerting** (Discord/ntfy),
one **unified dashboard** (stock + comps + appreciation + opportunities + holdings).
**Depends on:** B/C/D outputs to automate.

---

## Build order & first target

Dependency order **A → B → C → D → E**; D's inventory ledger is the one piece independent of A.
**First detailed build:** a vertical slice — the **Live sealed deal board**
(`2026-06-28-poke-live-sealed-slice-design.md`) — which produces a real dashboard on the sealed comps
that already work and pulls in only the Phase-A bit it needs (`ppt_id` seeding). Everything else is
added when a consumer arrives.

## Cross-cutting invariants (all phases)

- Price-accuracy STOP gate + confidence tiers on every number; never fabricate; EST-label estimates.
- Two ledgers stay distinct: **observation** (market data seen) vs **inventory** (what you own).
- Credit governance: on-demand enrichment + daily cap; `limit=1` for single lookups; never speculative
  full-catalog enrichment (bulk CSV is the full-catalog tool, Business-only).
- Doctrine: human-in-the-loop for every buy/sell; no auto-checkout/listing; demote-never-hide.
- Full existing test suite stays green; each phase is TDD with its own tests.
