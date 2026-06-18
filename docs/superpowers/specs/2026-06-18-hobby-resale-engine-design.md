# Hobby-Funded-Resale Engine — Design Spec

**Date:** 2026-06-18
**Status:** Approved design, Phase 1 scoped for implementation
**Repo:** `Pokemon-main` (package `scanner/`)

> This spec was adversarially reviewed (repo-fit, market-claim, and consistency/scope lenses) before handoff. Corrections from that review are folded in; volatile external figures (fees, PSA costs, API limits) are marked as config constants to confirm at implementation time, not hardcoded assumptions.

---

## 1. Purpose & reframe

The scanner today is a buy-side stock monitor governed by a doctrine that explicitly forbids treating it as a resale tool. The owner runs a self-funding hobby: buy sealed TCG product at retail, keep what they collect, sell what they don't. The current doctrine (`DOCTRINE.md`, `ADVISOR_ROLE.md`) treats resale data as "context only, not instruction" — that line is the blocker.

This project promotes resale economics to a **first-class decision input** while keeping the operational guardrails that actually matter (no auto-checkout, no account abuse, human-in-the-loop for every transaction). The scanner's job changes from "find product at MSRP" to "find product whose **fee-adjusted resale margin** clears a threshold, track what I buy, and recommend the smartest exit."

**Market context driving the design (June 2026):** The Pokémon Company is flooding reprints to crush scalper premiums (Costco + Sam's reportedly pushing on the order of 1–2M+ units of Prismatic-era product). The naive "buy hyped box, relist 2×" play is dying. The durable edge is **math and selectivity**, not speed-buying — which is exactly what software does well.

### Doctrine v2 (replaces current `DOCTRINE.md` / `ADVISOR_ROLE.md`)

- **Kept (these are moat, not moralizing):** no auto-checkout / cart automation, no account abuse or login-wall scraping, no proxy/distributed polling, no hidden per-LGS scraping, no sub-60s latency arms race. A human reviews and executes every buy and every sell — by principle, not just because a given site blocks automation.
- **Changed:** resale comps graduate from "context" to **instruction-grade input**. Margin, fees, and sell-timing are objectives, not just warnings.
- **Kept truthfulness rule:** when a price source is weak, stale, or fallback-derived, label it with its confidence tier instead of presenting false confidence. (Reuses the existing `resale.py` confidence model.)

---

## 2. Architecture

**Approach: extend in-place.** All new code lives inside the existing `scanner/` package and web UI. New modules are pure-derivation in the established style (`confidence.py`, `workqueue.py`, `priority.py`, `provenance.py`). Stateful data uses the existing SQLite store (`scanner/state.py`, `data/state.db`, with the `state.runtime.db` fallback added in `d2f117d`). No second application to run.

**Forward-compatibility is anchored at an interface, not a vendor.** Phase 1 depends only on `market.py` conforming to the existing `resale.py` price-client contract. The specific data vendor (PokemonPriceTracker, below) sits behind that interface and is swappable; adopting it early is a convenience that avoids a later migration, not a lock-in.

### The full loop (north star)

```
ALERT  →  [Phase 1: is this worth buying?]  →  human buys
                                                   ↓
HOLDINGS  ←  [Phase 2: track cost basis]    ←  ledger entry
   ↓
[Phase 3: open / sell sealed / grade a pull?]  →  sell-side draft  →  human lists
```

### Phasing

- **Phase 1 — Deal intelligence.** Detailed below; **this is the implementation scope for the immediate plan.**
- **Phase 2 — Inventory ledger + sell-side helper.** Documented at lower resolution (§5); architecture must accommodate it but it is *not* in the first plan.
- **Phase 3 — Open-vs-flip EV + opportunity surfacing.** Documented at lower resolution (§6); not in the first plan.

Phases 2 and 3 are recorded here so Phase 1's interfaces don't paint them into a corner. Each later phase gets its own spec → plan cycle.

---

## 3. Phase 1 — Deal intelligence (implementation scope)

Turns every in-stock alert into a fee-adjusted **BUY / THIN / SKIP** verdict, and activates the owner's three buyable retailers.

### 3.1 Why: gross ≠ net

The naive read of an alert is a trap. Illustrative Costco Prismatic bundle (numbers illustrative; the tool computes them live):

| | Value |
|---|---|
| Buy (incl. ~7% tax) | $43.00 |
| eBay sale price | $60.00 |
| eBay fee (~13.5%, incl. payment processing) | −$8.10 |
| eBay fixed per-order fee | −$0.40 |
| Shipping (~2 lb) | −$8.00 |
| **Net proceeds** | **$43.50** |
| **Actual margin** | **~$0.50 (breakeven, not a flip)** |

The gap between gross and net is the entire reason Phase 1 exists.

### 3.2 New modules

**`scanner/market.py` — price-data backbone.**
Implements the **PokemonPriceTracker API** as a price client conforming to the *existing* `resale.py` client interface:
`estimate(product_key: str, product: dict, checked_at: int) -> dict` returning the same quote-row shape (`status`, value, confidence tier, source label) that `EbayResaleClient` / `PublicFallbackResaleClient` already produce (`resale.py:618-735`). It slots into `resale_client_from_config` (`resale.py:738`) as the preferred client, with the existing eBay/PriceCharting clients kept as fallback. Caching, staleness, and refresh cadence reuse **`ResalePriceCache`** (`scanner/resale.py:744`, instantiated in `web.py:55`) and `DEFAULT_INTERVAL_SECONDS` (`resale.py:17`).

*Vendor capabilities (verify exact limits at implementation):* PokemonPriceTracker provides **daily-updated** (≈24h cadence, not real-time) TCGplayer + eBay-sold comps, native **PSA/CGC/BGS graded comps**, and a **Parse-Title API**. The graded data and title parsing are required by Phase 3, so adopting it now avoids a later migration. CardMarket (EUR) data is Beta and paid-plan-only — not used in Phase 1. The **free tier is ~100 credits/day**, which is likely insufficient to poll the full catalog across multiple retailers; sizing request volume against the free-tier ceiling is a planning prerequisite (§7), and a paid tier may be required.

*Product-key → API-query mapping (load-bearing — resolved here, not deferred):* each catalog product gains an optional `ppt_query` (or `ppt_id`) field, provenance-gated like other retailer IDs. Resolution order in `market.py`: (1) use `ppt_query`/`ppt_id` if present; (2) else attempt the Parse-Title API against the existing `resale_query`; (3) on a low-confidence parse or no match, downgrade the confidence tier and fall through to the existing scrape path. This makes the comp behavior deterministic for both a mapped and an unmappable product.

*Failure handling:* a missing API key, a rate-limit response, or quota exhaustion are all treated identically — fall back to the scrape path with a labeled confidence downgrade; **never error the scan run.**

**`scanner/margin.py` — fee-adjusted margin math (pure).**
`net_margin(cost_incl_tax, comp, channel, est_shipping) -> MarginResult` where `MarginResult` carries net proceeds, dollar margin, % ROI, and breakeven price. Channel fee models:
- **eBay:** ~13–14% all-in (eBay's final value fee, which already includes payment processing) plus the fixed per-order fee (~$0.40). Parameterized.
- **Local (LGS / FB Marketplace):** 0% platform fee, zero shipping. Phase 1 has **no independent local comp feed** — Local is the online comp minus a configured haircut, labeled as a *derived estimate* (local sells below online comp).
Fee/haircut/shipping/tax constants live in config so they can be tuned without code edits. Pure functions, fully unit-testable, no I/O.

**`scanner/verdict.py` — fused buy verdict (pure).**
`buy_verdict(product, observed_price, comp, source_state) -> Verdict` fusing three existing signals with an explicit, non-ambiguous rule:
- **Margin determines the tier.** Two config constants define the bands: below `skip_floor` → **SKIP**; between `skip_floor` and `buy_floor` → **THIN**; above `buy_floor` → **BUY**. (Cutoffs are evaluated on net dollar margin; % ROI is displayed alongside. Whether ROI also gates is a config flag, default off.)
- **Priority/hype** (`product_priority`, `priority.py:32`) affects **only within-tier ranking** — it never promotes a product across a margin tier.
- **Confidence** (`confidence.py` source health + the comp's own tier) affects the **displayed label and caps the tier**: a comp below a configured confidence floor **cannot produce BUY** — it is capped at THIN and labeled with its tier. This is where "demote-never-hide" meets the truthfulness rule.

Verdict policy is **demote-never-hide**: below-floor and low-confidence alerts still appear, ranked low and labeled, never suppressed. Emits the tier plus the headline number (e.g. "BUY · +$18 net, 42% ROI" or "THIN · +$1 net (low-confidence comp)").

### 3.3 Integration points (grounded in current code)

- **Alert construction** (`scanner/main.py:361-374`): after building the `StockAlert`, compute the comp via the market cache and attach a `verdict` to the alert. The `prod` dict and `result.price` are already in scope. **Cost basis for the margin calc = scraped observed price × (1 + `tax_rate`)**, where `tax_rate` is a single global config constant. Per-purchase tax/actual-cost capture is deferred to the Phase 2 ledger.
- **Alert rendering — two touch points** (`scanner/notify.py`):
  - Add an optional `verdict: str = ""` field to the `StockAlert` dataclass (`notify.py:26-40`), rendered only when present — the same pattern `priority` follows.
  - Surface it in `_context_bits()` (`notify.py:42-50`) → this covers **console** and the **ntfy** body (both go through `StockAlert.line()`, posted at `notify.py:124`).
  - Separately add a guarded `embed['fields']` entry (`if alert.verdict`) in `_discord()` (`notify.py:78-118`), because Discord builds its own embed and does **not** call `line()`/`_context_bits()`.
- **Web board** (`scanner/web.py`, `web_assets/`): show the verdict label and net-margin number per product row, and sort by verdict strength (reuses the board's existing priority sort hook).
- **Catalog** (`data/products.yaml`): adds the optional `ppt_query`/`ppt_id` field (§3.2). No other schema change for verdicts (uses existing `msrp`, `resale_query`).

### 3.4 Retailer activation (owner's buyable set: Costco, Best Buy, Pokémon Center)

- **Costco** — adapter exists (`scanner/retailers/costco.py`, 4-endpoint chain) but has **zero item IDs** (`costco_item_id` empty across the catalog). Populate IDs via the ID Doctor pipeline (`scanner/verify_ids.py` + provenance sidecar). Warehouse-club below-market bundle pricing was the standout 2026 arbitrage, so this is the highest-value activation. ID sourcing is treated as a **separate, enumerated data task** (see AC4 / §7), decoupled from the pure-module software work.
- **Best Buy** — adapter built; **17 of the 22 catalog products already carry a `bestbuy_sku`**, disabled pending the free Best Buy API key. Enable in config when the key is in hand; absent key leaves the adapter cleanly disabled (graceful degradation, same doctrine as the PokemonPriceTracker key — it does not fail the build). No membership needed.
- **Pokémon Center** — adapter built, **zero IDs** (`pokemoncenter_slug` empty). Seed slugs. Stays **alert-only / human checkout by doctrine** (and PC's queue would forbid automation regardless). Earns inclusion because PC exclusives are **currently the most durable flip** (~1.8–2.4× year-one premium, decaying to ~1.3–1.6× by year 3) in the reprint-flood era — though that premium is largely **promo-card-driven**, so it is exposed to the promo later being reprinted or mass-graded. Treat the single-source backtest behind these numbers as indicative, not proven.

All new IDs flow through the existing verify → provenance gate; no unverified IDs enter the catalog.

### 3.5 Phase 1 acceptance criteria

1. For an in-stock catalog product, a BUY/THIN/SKIP verdict with a fee-adjusted net-margin number is **populated on the alert and included by the shared `_context_bits()` renderer** (unit-tested via string assertion). A manual spot-check confirms it surfaces in Discord, ntfy, and the web board.
2. Margin math is correct for eBay and Local channels and covered by unit tests (fees incl. fixed fee, tax, shipping, haircut, breakeven).
3. PokemonPriceTracker comps populate via `market.py` for a **mapped** product; an **unmappable** product (no `ppt_query`, failed Parse-Title) degrades gracefully to the scrape path with a labeled confidence downgrade. Missing key / rate-limit / quota all take the same graceful path. The low-confidence → verdict-cap path (a low-confidence comp cannot emit BUY) is unit-tested.
4. **Best Buy** enabled when the key is present; absent key leaves it cleanly disabled without failing the suite. **Costco/PC ID seeding** is scoped as an enumerated target list of catalog keys (a small dedicated sub-task), verified through the provenance gate; the core engine does not fail if a given external item ID can't be sourced at implementation time.
5. Below-floor and low-confidence alerts are demoted and labeled, never hidden.
6. Doctrine v2 committed (`DOCTRINE.md`, `ADVISOR_ROLE.md` updated).
7. Full existing test suite stays green; new modules (`market`, `margin`, `verdict`) have their own tests.

---

## 4. Out of scope / preserved anti-goals

No auto-checkout. No marketplace bots or auto-listing. No sub-60s latency race. No unverified IDs (ID Doctor stays the gate). No "AI price prediction" — every number traces to a real sold comp with a confidence tier. The tool advises; the human transacts. These hold across all phases.

---

## 5. Phase 2 — Inventory ledger + sell-side helper (future phase, design recorded)

**`scanner/ledger.py`** — each acquisition is a *lot* (product, source, unit cost incl. tax, qty, date, state). State machine `acquired → holding → listed → sold`, with an `opened` branch where a sealed lot spawns child items (raw singles / slabs) and cost basis flows from box to cards. Realized P&L per lot; running "hobby self-funding" aggregate.

*Tax spine (corrected):* the federal 1099-K threshold for 2026 is **$20,000 in gross payments AND 200+ transactions** — OBBBA repealed the previously scheduled $600 floor and restored the pre-ARPA rule, so most casual sellers will **not** receive a 1099-K. The ledger's value is therefore not "you'll get a form" urgency but that (a) the form, when issued, reports **gross, not profit**, (b) some state thresholds are lower, and (c) income is reportable regardless of whether a form arrives — so cost-basis records remain the difference between owing tax on revenue vs. on margin. Exports a COGS/proceeds CSV. New tables in the existing `data/state.db` schema (`scanner/state.py:_init_schema`); YAML catalog stays clean (provenance pattern).

**`scanner/sellside.py`** — given a held lot + current comp: net proceeds per channel, recommended channel, and a **sell-now-vs-hold** signal. The signal encodes the appreciation research: retail/warehouse sealed grinds up slowly (hold); **PC-exclusive premium is front-loaded** (~2.4× yr1 → ~1.5× yr3, promo-card-driven) so it flags "sell into the year-1 window." Output is a listing **draft** (suggested price, channel, title seeded from `resale_query`) — never auto-listed. May require catalog flags for `release_date` and `exclusive` to drive sell-window logic.

**UI:** a "Holdings" tab — open lots, unrealized value at live comps, per-lot sell recommendation, running self-funding P&L.

---

## 6. Phase 3 — Open-vs-flip EV + opportunity surfacing (future phase, design recorded)

**`scanner/opening.py` — open-vs-flip EV.** For a sealed product, compute (a) net if sold sealed and (b) expected value of opening = Σ(pull probability × singles comp) − selling friction. When (b) > (a) by a margin, flag "worth more opened." This is the lever for "I opened a pack and got something I don't want to keep."

**`scanner/grade_screen.py` — singles + grading screen.** For a pull entering the ledger as a single to sell: raw comp (TCGplayer/eBay sold), then a grade-worthiness gate.

*Grading cost (corrected):* PSA's cheap **value tiers (~$40–45 all-in) are PAUSED as of June 2, 2026** (≈10M-card backlog; PSA projects a multi-month reopen contingent on the backlog clearing). The cheapest currently-available tier is **Regular at $79.99/card (~$95–100+ all-in** with insured two-way shipping and supplies). The gate must use the **live available tier cost as a config constant**, not the paused bulk rate, and should re-enable bulk economics only when value tiers return.

*Gem rate (corrected):* modern Scarlet & Violet PSA-10 rates **vary widely by card and centering** — roughly ~25% for tougher/chase/SIR cards up to 80%+ for clean, well-centered commons. The gate should be **card-specific** (ideally driven from PokemonPriceTracker population data), not a single blanket rate. Net effect: grading is only suggested when raw value clears the live all-in cost after the card's own gem-rate odds and clean centering; otherwise "sell raw."

**Opportunity scanner.** A periodic pass surfacing **undervalued** situations across sealed, singles, and graded as their own alert class — e.g. a retail product whose live comp has drifted above a still-in-stock retail price (live arb), a held lot crossing its sell-window trigger, or an opened single whose raw comp spiked. Output: "Opportunity: X looks undervalued — here's the spread."

---

## 7. Open items for the implementation plan

External prerequisites to obtain **early** so the plan can sequence around them:
- **PokemonPriceTracker API key** and **Best Buy API key** (both free-tier to start). Both degrade gracefully if absent, but acquiring them unblocks AC3/AC4.

Details to confirm during planning:
- PokemonPriceTracker exact endpoints, auth, rate limits, and free-tier credit ceiling vs. expected request volume (decides free vs. paid tier; gates whether it can be the *preferred* client).
- eBay fee model precision: confirm current all-in rate and whether to model store-subscription vs. casual-seller rates.
- Costco/PC item-ID discovery method (manual seeding vs. semi-automated within the verify pipeline) and the **enumerated target list** of catalog keys to seed.

(Resolved and therefore removed from this list: the product-key → API-query mapping is specified in §3.2; the cost-basis/tax-rate rule is specified in §3.3.)

---

## 8. Sources

- 1099-K 2026 threshold restored to $20,000/200 by OBBBA — IRS Form 1099-K FAQ updates (RSM summary): https://rsmus.com/insights/services/business-tax/irs-updates-obbba-new-reporting-thresholds.html ; IRS page: https://www.irs.gov/businesses/understanding-your-form-1099-k
- PSA 2026 pricing & June value-tier pause — https://www.psacard.com/info/submission-updates
- Selling platforms & fees 2026 (PokemonPriceTracker) — https://www.pokemonpricetracker.com/blog/posts/selling-pokemon-cards-in-2026-best-platforms-pricing
- PC-vs-retail resale backtest (single-vendor, indicative) — https://ravaver.com/blogs/article/pokemon-center-exclusives-vs-retail-etb-2026
- Costco/Sam's reprint flood (order-of-magnitude) — https://www.trackalacker.com/articles/news/the-ultimate-guide-to-pokemon-drops-at-sam-s-club
- PokemonPriceTracker pricing API — https://www.pokemonpricetracker.com/pokemon-card-pricing-api
