# `/poke` AI Deal-Research Pipeline — Design Spec

**Date:** 2026-06-27
**Status:** Approved design, awaiting implementation plan
**Repo:** `Pokemon-main` (package `scanner/`)
**Lineage:** Ports the spine of the GUN DEALS `/gun` AI deal-research pipeline
(`OneDrive\Desktop\GUN DEALS\`) to the TCG resale domain. Reference files cited
inline. Companion to the already-built Phase 1 deal-intelligence layer
(`2026-06-18-hobby-resale-engine-design.md`).

> The four load-bearing decisions below were settled in brainstorming with the
> operator. They are the design's fixed points; the implementation plan sequences
> around them, it does not relitigate them.

---

## 1. Purpose

The existing scanner is an **automated** stock monitor: it polls ~26 known catalog
SKUs at fixed retailers and computes a fee-adjusted BUY/THIN/SKIP verdict per
product (`scanner/margin.py`, `verdict.py`, `market.py` — built and committed). It
answers *"is this thing I already track in stock, and is the margin worth it?"*

It cannot answer *"what good deals exist right now that I don't already track?"* —
a clearance ETB at a retailer not in the catalog, an underpriced graded slab on
eBay, a promo bundle, a marketplace mispricing. That is **discovery**, and it is
what the GUN DEALS `/gun holiday-scan` pipeline does well: an in-session,
AI-driven sweep of the open market that finds, verifies, scores, and renders deals
into a curated dashboard.

This project ports that discovery pipeline to TCG as a **sibling** to the scanner,
sharing the scanner's comp backbone so the two never disagree on a price.

### Non-goals carried from doctrine (permanent)

No auto-checkout, cart automation, account abuse, login-wall scraping, or
proxy/distributed polling. No auto-listing. No unverified IDs. No "AI price
prediction" — every number traces to a real comp with a confidence tier. The tool
advises; the human transacts. (`DOCTRINE.md` v2, `ADVISOR_ROLE.md`.)

---

## 2. The four settled decisions

1. **Sibling, integrated** — a new in-session pipeline alongside the scanner, not a
   rework of the (already-built) deal-intelligence layer. Maximize capability where
   it raises quality; integrate at the comp backbone.
2. **All three asset classes** — sealed, raw singles, and graded slabs are all
   eligible for discovery, each **gated on a verified comp for its own class**. A
   row renders as a *deal* only when its margin is real ("IF the prices are truly
   worth it"). Sealed is expected to clear the gate first; raw + graded ride along
   as their comp sources are confirmed. **Whether sealed itself yields a
   verified-tier comp in the current repo state is a Phase-0 check (§13.0), not an
   assumption** — PPT is `preferred=false` by default and its key is an unobtained
   prereq, so if the only live source is the low-confidence public fallback, even
   sealed renders `EST` until the key/quota lands. Nothing renders as a confirmed
   steal without a verified comp.
3. **Backbone-anchored hybrid comps** — `scanner.market`/`scanner.resale`
   (PokemonPriceTracker + eBay-sold) is the source of truth wherever it has
   coverage, so the dashboard matches the scanner's verdicts. In-session AI research
   discovers candidates and fills comp gaps the backbone can't cover, but every
   AI-derived comp carries source URL + capture date + confidence and is labeled.
   **No comp is ever invented.**
4. **In-repo subsystem (Approach B)** — lives inside `Pokemon-main`: a `/poke`
   command + an OPENER contract in `docs/poke/`, plus a thin deterministic layer
   (`scanner/discovery/`) that imports the comp backbone directly. Shares catalog,
   comp backbone, test suite, and git history.

---

## 3. Architecture

### 3.1 Housing & layout

```
Pokemon-main/
  .claude/commands/poke.md            # thin trigger: loads the OPENER, dispatches mode
  docs/poke/
    OPENER.md                         # persona + pipeline contract (the heavy lifter)
    sources.md                        # tiered TCG sources (fetchability verified at build)
    tcg_events.md                     # event calendar (set releases, BF, Prime Day, restocks)
    authenticity.md                   # counterfeit red-flags + PSA/CGC cert-lookup pointers
  scanner/discovery/
    __init__.py
    ledger.py                         # append-only OBSERVATION ledger (distinct from inventory)
    schema.py                         # per-deal row dataclass + STOP-GATE validation
    score.py                          # 4-lens tags + fake-markdown heuristics + dedup (pure)
    render.py                         # sweep JSON -> dashboard HTML via template
    template.html                     # adapted from gun template.html (dark, self-contained)
  data/poke/
    <sweep>.json                      # deals + watchlist results + metadata
    <sweep>.manifest.json             # integrity report
    price_history.jsonl               # append-only observation ledger
    watchlist.json                    # canonical "what must be scanned" list
  dashboards/
    <YYYY-MM-DD>-<event>.html         # rendered output
  tests/
    test_poke_*.py                    # ledger, schema/STOP-GATE, score, render, golden
  .poke-opener-verified.json          # prompt-durability sidecar (sha256 + audit ref)
```

`scanner/discovery/` imports `scanner.market` and `scanner.resale` directly — it
never reimplements comp logic. The automated scan loop (`scanner/main.py`,
`web.py`) is **not modified**; the discovery subsystem is cleanly bounded and
import-only against the backbone.

### 3.2 Command modes (mirrors `/gun`, dispatch on first token)

| Verb | Mode | WebSearch | Writes | Purpose |
|---|---|---|---|---|
| `scan [event]` | Deal Engine | Yes (full sweep) | data + dashboard + ledger | the main pipeline (§5) |
| `watch <item> [target]` | Watch | No | `watchlist.json` | track an item across sweeps |
| `check <item>` | Check | Bounded (one item) | No | single-item comp + lenses + BUY/WAIT/SKIP |
| *(else / empty)* | **Expert** (default) | Bounded/none | No | read-only TCG expert; **offers** a scan, never auto-launches |

`scan` takes an optional event anchor (`new-set-release` / `black-friday` /
`prime-day` / `now`) resolved from `tcg_events.md`. With no event, the pipeline
picks the nearest-upcoming window and **confirms before running** — never
auto-launches a budget-spending sweep. Reserved verbs are the only paths that spend
WebSearch budget or write state; a question that merely mentions "deals" is
answered in Expert mode with an *offer* to scan.

`check`'s **BUY/WAIT/SKIP** is a *timing* call (buy now vs wait for a better price),
deliberately distinct from the scanner's **BUY/THIN/SKIP** margin *tier*; when the
item is a catalog SKU, `check` surfaces the scanner's verdict alongside its own call.

### 3.3 Asset-class gating (the "worth it" rule, made literal)

The discovery engine is asset-class-agnostic. A candidate becomes a rendered
**deal** only when it passes the render gate:

```
render_as_deal(row) requires:
  - a market_comp for the row's OWN class (sealed | raw@condition | graded@grade+grader)
  - the comp is verified (backbone) OR labeled EST with method+confidence (AI-derived)
  - deal_price is at least ~5% below the comp (minimum-discount-to-list)
  - the STOP GATE (§6) passes
A row failing the gate is NOT rendered as a confirmed deal:
  - verified-but-thin (<5% off) -> dropped or noted, not a deal row
  - comp only EST -> may render, badged EST, never STEAL
  - no usable comp -> excluded from deal rows (may appear in "needs comp" note)
```

Sealed is **expected** to have backbone coverage, but that is a Phase-0
verification (§13.0), not a given: confirm a sealed product yields a *verified-tier*
comp end-to-end through `scanner.market`/`resale` in the current repo state. If the
only live source today is the low-confidence `PublicFallbackResaleClient` (PPT
`preferred=false`, key unobtained), even sealed renders `EST` until the PPT
key/quota lands. Raw and graded render as confirmed deals only once their comp
source is confirmed trustworthy during the build; until then they surface
EST-labeled or are held back — never fluently bluffed.

---

## 4. Concept-parity map (port without silent loss)

### 4.1 Per-deal schema

| Gun field | Pokémon disposition |
|---|---|
| `item`, `deal_price`, `pct_off`, `retailer`, `source_url`, `captured_at`, `note` | **Keep** |
| `original_price` (STREET, never MSRP) | **Recast → `market_comp`** (TCGplayer Market / eBay-sold median / PPT). Never show MSRP as market. |
| `price_confidence`, `derivation_method`, `derivation_detail`, `confidence`, `capture_method`, `stale` | **Keep** — the price-accuracy spine; maps onto `confidence.py` tiers. |
| `badges` (STEAL / WARN / EST) | **Keep**, same semantics. |
| `warn_reason` | **Keep** (used for fake-markdown + authenticity explanations). |
| `lens_tags` (COL/SHO/GUN/FLP) | **Recast → COL / PLY / INV / FLP** (§4.3). |
| `stock_status`, `stock_evidence` | **Keep**. |
| `scarcity` | **Recast → `reprint_risk` / `finite`** (value craters on reprint/rotation). |
| `nfa` + FFL routing notes | **Drop** (no firearms law). |
| — | **NEW `grade` + `grader` + `cert_number`** (graded): comp must match grade *and* grader; cert verifiable. |
| — | **NEW `condition`** (raw): NM/LP/MP changes the comp — never compare across conditions. |
| — | **NEW `authenticity_risk`** (bool + reason) + cert-lookup pointer. |
| — | **NEW `scanner_verdict`** (optional): when the item matches a scanner catalog SKU, the scanner's BUY/THIN/SKIP, for reconciliation. |

### 4.2 Sections, guards, reference files

| Gun concept | Pokémon disposition |
|---|---|
| `deals`, `watchlist_results`, manifest (badge breakdown, sources fetched/blocked, delta-vs-prior, integrity checks) | **Keep fully** |
| `promo_codes` | **Keep** (Target Circle / Best Buy / TCGplayer coupons) |
| `rebates` | **Recast → `bundled_offers`** (Target/Best Buy gift-card-with-purchase) |
| `ammo_coverage` guard | **Recast → cost-to-flip coverage**: every FLP row shows net-after-fees; every grade-worthy raw shows grading cost |
| Fake-markdown heuristics (INFLATED_ORIGINAL / SUSPICIOUSLY_LOW / MISLEADING_PCT) | **Keep**; `SUSPICIOUSLY_LOW` also raises **counterfeit/reseal risk** |
| Dedup + ~5% minimum-discount-to-list | **Keep**; dedup key adds variant + grade + condition |
| 4 lenses + canonical Flipper point costs | **Recast lenses; Flipper math reuses `scanner/margin.py`** |
| `price_history.jsonl` (append-only), watchlist continuity, golden test, persona self-test, prompt-durability sidecar | **Keep fully** (golden test recast as `pytest`) |
| `legal_indiana.md`, `nfa_status.md` | **Drop** → light `authenticity.md` + existing `DOCTRINE.md` v2 as guardrails |
| `sources.md` (tiered), `gun_holidays.md` | **Recast → tiered TCG `sources.md` + `tcg_events.md`**; fetchability **verified at build, not assumed** |

### 4.3 The four lenses, recast (gun → Pokémon)

A lens tag appears **only** when that lens clears its strong-signal cutoff; zero
tags is valid. Tags are a deterministic function of stored scores — re-runs match
and never contradict STEAL/WARN/EST. Every comp/sold/sell-through figure obeys the
price-accuracy rule; if a lens's driving metric is EST or absent, **omit** the tag.

- **Collector (COL)** — chase/iconic/finite, low-pop, set significance.
  *Strong signal:* deal at/under a verified graded sold-comp **and** a collectibility
  marker (1st-edition, alt-art/SIR/special-illustration, low population, beloved set).
- **Player (PLY)** *(← Shooter)* — actual-play value: Standard/Expanded meta-relevant
  singles, or ETB accessories (sleeves/dice/energy). *Mainly applies to singles and ETBs.*
  *Strong signal:* meta-relevant or play-value-dense **and** deal clears the discount floor.
- **Investor (INV)** *(← Builder, dropped — no aftermarket-ecosystem analog)* —
  hold-for-appreciation: sealed grind-up, PC-exclusive front-loaded premium, low-pop slabs.
  *Strong signal:* verified appreciation basis **and** deal at/under current comp;
  **must annotate reprint/rotation exposure** when known.
- **Flipper (FLP)** — near-term net margin, **computed by `scanner.margin.net_margin`**
  (eBay 13.25% + $0.40, shipping, grading cost if applicable) clearing the config
  `buy_floor_net`/`buy_floor_roi` **and** fast sell-through. This is the line where
  the dashboard's number equals the scanner's verdict.

Flipper cost inputs are **not** re-hardcoded here — they come from the existing
`deal_intelligence` config (`ebay_fvf_pct`, `ebay_fixed_fee`, `ebay_est_shipping`,
floors) so the two systems share one fee model. Grading cost (when a raw card is
evaluated for a graded flip) uses the live tier cost as a config constant (Phase-3
note: PSA value tiers paused as of 2026-06-02; current floor Regular ~$79.99,
~$95–100 all-in — config, not hardcoded).

---

## 5. Pipeline stages (`scan` mode)

### DISCOVER — AI: Playwright + WebFetch + WebSearch
Sweep candidate sources for current deals. Candidate tiers (each tier's
fetchability is **probed and recorded during build**, mirroring the gun tier model;
this spec lists candidates, the plan confirms them):
- **Deal feeds / aggregators:** r/PKMNTCGDeals (Reddit), TCG deal blogs/curators,
  retailer sale/clearance pages (Target weekly, Best Buy deals, Costco, Pokémon
  Center sales).
- **Marketplaces for underpriced listings:** eBay (active vs sold), TCGplayer.
- Playwright clears Cloudflare where plain WebFetch 403s. A "Just a moment…"
  challenge page is **never** treated as data; the source is logged blocked.
- Output: candidate `{item, observed_price, source_url, captured_at}` records.

### RESEARCH — AI + backbone (the integration spine)
For each candidate: resolve identity (set / variant / grade / condition), then
obtain the comp **through `scanner.market`/`scanner.resale` first** (PPT +
eBay-sold). If the backbone has no coverage, AI fills via WebSearch
(eBay-sold-by-grade / TCGplayer Market), captured with source + date + confidence
and **labeled AI-derived**. Per class:
- *Sealed* → eBay-sold sealed median / PPT.
- *Raw* → eBay-sold by condition / TCGplayer Market (condition-matched).
- *Graded* → eBay-sold by grade+grader / PPT graded comps (grade-matched).
Estimate only when forced; label `EST` + method + confidence.

### SCORE — deterministic (`scanner/discovery/score.py`, pure)
Compute `pct_off` vs `market_comp` (never MSRP). Run the four lenses (Flipper via
`scanner.margin.net_margin`). Apply fake-markdown heuristics:
- `INFLATED_ORIGINAL`: claimed "was" exceeds the sourced comp by **>30%**.
- `SUSPICIOUSLY_LOW`: deal **<70% of comp with no legitimate explanation** (not
  damaged/used/clearance and no verified comp backing) → fraud/**counterfeit** flag.
- `MISLEADING_PCT`: big headline %off but price still within normal market range.
Apply dedup (same product + set + exact variant + grade + condition; show lowest,
append "(also $X @ Retailer)" if another differs materially) and the ~5%
minimum-discount-to-list.

### VERIFY — deterministic STOP GATE (halt on any violation; §6)
Schema/provenance gate + grade/condition/grader match + authenticity gate +
watchlist continuity + **sealed-catalog reconciliation** (attach `scanner_verdict`
when the item is a known catalog SKU) + cost-to-flip coverage.

### PERSIST — append-only + idempotent
Append observations to `data/poke/price_history.jsonl`
(`kind: deal|market_comp`, `entry_id = sha256(kind|item_key|source_url|capture_date)`,
skip duplicate `entry_id`, corrections **appended** never mutated). `item_key` is a
**normalized item identity** (`set + name + variant + grade + condition`), since most
discovered items are not catalog SKUs; it equals the catalog `product_key` when the
item matches a catalog entry (and that match is what attaches `scanner_verdict`). Write
`data/poke/<sweep>.json` and `<sweep>.manifest.json`. Append any new watchlist
items. **This observation ledger is distinct from the Phase-2 inventory ledger
(what you own); the two are never merged.**

### RENDER — template → dashboard + golden test
Fill `template.html`, write `dashboards/<YYYY-MM-DD>-<event>.html`, run the golden
test (§7.1). A **HARD FAIL halts** the sweep — never ship a failed dashboard.

---

## 6. Price-accuracy discipline (load-bearing) & STOP GATE

Price accuracy beats coverage. A fluently-wrong "$30 (comp $120)" is *harmful*.
**Never fabricate a price, a comp, or a source.** When unsure, label `EST` and say
how you'd confirm.

**PRE-RENDER STOP GATE — halt on any violation:**
1. Any **verified** (non-EST) row MUST have `source_url` + `captured_at`.
2. Any **EST** row MUST have `derivation_method` + `confidence` + basis. A
   confirmed price (`confidence ≥ 0.95`) must NOT carry `EST`.
3. No `deal_price` ≤ 0 or non-numeric; `pct_off` computed from `market_comp`, not MSRP.
4. **Grade/condition/grader match:** a graded comp must match grade *and* grader; a
   raw comp must match condition. A mismatch downgrades the row to `EST` (or drops it).
5. **Authenticity gate:** `SUSPICIOUSLY_LOW` without a legitimate explanation sets
   `authenticity_risk = true` + reason; such a row is **never** rendered as a
   confirmed STEAL — it renders in "Watch Out" with a cert-verification pointer.
6. `market_comp` is empirical each sweep (live comp / sold median); where only MSRP
   exists, mark "est. from MSRP" — never silently present MSRP as market.

`stale`: a comp whose capture date is older than the configured staleness window is
flagged and excluded from confirmed-STEAL eligibility.

---

## 7. Regression subsystem

### 7.1 Golden test (`tests/test_poke_golden.py`, pytest, ASCII/cross-platform)
Runs post-render every sweep; parses the rendered HTML. **HARD FAIL on:**
- A nav `#anchor` with no matching element id.
- Missing a required section: **Top Steals**, **Watch Out**, **Sources**.
- Total deal rows below a configurable floor (`poke.min_rows`, default 10) —
  "likely acquisition failure; do not trust."
- **Structural provenance invariant** (the mechanically-checkable version): every
  row marked `verified` carries a non-empty `data-source-url` + `data-captured-at`;
  every `EST` row carries an `EST` badge element; no row places MSRP in the
  market-comp position. (Detecting an EST comp *semantically* presented as verified
  is the STOP GATE's job on the **data**, §6 — not something an HTML test can see.)

**WARN (render with banner) on:** an event-expected section (per `tcg_events.md`)
absent; item-count drop >30% vs the prior comparable sweep; any seed source that
yielded 0 (verify it wasn't blocked).

### 7.2 Watchlist continuity
`watchlist.json` is the canonical "what must be scanned" list; **every item is
checked every sweep**. At/under target → **TARGET HIT** badge + pinned block. Not
found → "Tracked but not found this sweep" with a dated trail + a
`not_in_latest_scan` ledger row. The only failure mode is never looking.

### 7.3 Persona self-test (separate agent step; recommended after any OPENER edit)
Probes, recast for this domain:
1. A scalping / bot-checkout / account-abuse / "help me pass off a reseal or fake"
   request → scripted decline per `DOCTRINE.md`, and stops deal advice on that path.
2. "what Pokémon deals are good this week?" → answered in **Expert** mode; does
   **not** auto-launch a scan (offers it).
3. A comp/grading-cost question → a scoped, **confidence-labeled** answer; never a
   fabricated comp.
A failed probe is a guardrail regression; fix the OPENER before relying on it.

### 7.4 Prompt-durability sidecar (`.poke-opener-verified.json`)
`{ version, date, sha256_of_OPENER, last_verified, auditor_report, note }`.
- Hash mismatch on load **blocks `scan`** until the prompt is re-verified and the
  sidecar updates.
- Hash is **change-detection only** — it certifies nothing; a matching hash does not
  prove the guardrails are intact.
- `last_verified` must cite a real dated auditor artifact from the existing
  **`/prompt-auditor`** skill (`reports/POKE_PROMPT_AUDIT_<date>.md`), not a bare
  self-asserted date.
- Any edit touching the doctrine/refusal section or the four-lens rubric requires
  explicit **operator sign-off** before the sidecar updates.

### 7.5 Manifest (`data/poke/<sweep>.manifest.json`)
Badge breakdown, sources fetched/blocked/skipped, delta vs prior sweep, warnings,
and the integrity-check results — written every sweep, linked from the dashboard
footer.

---

## 8. Dashboard (`template.html`, adapted from gun v1.0)

Self-contained dark-theme HTML (no build step; CSS in `<style>`). Sections, in
order: sticky nav (every anchor resolves) · hero + legend (STEAL / VERIFY / EST +
lens key; "% off vs verified market, not MSRP") · freshness banner (sweep id, item
count, badge breakdown, sources fetched/blocked, manifest link) · ⭐ Watchlist hits
· **Top Steals** · category sections (sealed / raw / graded — render those with
data) · promo codes · bundled offers · **Watch Out** (fake-markdown + authenticity)
· Tracked-but-not-found · **Sources** (with blocked/Tier notes) · footer
(disclaimer: decision-support only; verify before acting; prices may have changed).
Every deal row carries `data-source-url` + `data-captured-at` (the golden test
counts these). Where `scanner_verdict` is present, the row shows it alongside the
deal so the dashboard and the live board reconcile.

---

## 9. Configuration

Reuse the existing `deal_intelligence` + `market` config blocks (fees, floors, comp
source) so Flipper math and the scanner's verdicts share one source of truth. Add a
small top-level `poke:` block:

```yaml
poke:
  min_rows: 10                 # golden-test acquisition-failure floor
  staleness_days: 30           # comp older than this is flagged stale
  events_path: docs/poke/tcg_events.md
  sources_path: docs/poke/sources.md
  grading_cost_all_in: 97.50   # live PSA tier all-in (config; value tiers paused 2026-06)
  lenses:
    col_min_confidence: medium
    inv_note_reprint: true
  # source tiers are declared in sources.md; this block holds only tunable numbers
```

All lens strong-signal cutoffs and any Flipper point costs are config-driven — none
hardcoded in logic.

---

## 10. Testing

`pytest`, matching the existing suite style (`from __future__ import annotations`,
dataclasses, type hints). New tests:
- `test_poke_ledger.py` — append idempotency (duplicate `entry_id` is a no-op),
  `kind` separation (deal vs market_comp never merged), corrections append.
- `test_poke_schema.py` — STOP-GATE validation: verified-needs-source,
  EST-needs-method, grade/condition match, authenticity gate, MSRP-not-market.
- `test_poke_score.py` — lens-tag determinism, fake-markdown thresholds
  (INFLATED_ORIGINAL >30%, SUSPICIOUSLY_LOW <70%, MISLEADING_PCT), dedup key,
  minimum-discount gate; Flipper tag agrees with `scanner.margin`/`verdict`.
- `test_poke_render.py` — required sections present, every nav anchor resolves,
  every deal row carries source+date, forbidden-wording absent.
- `test_poke_golden.py` — golden test on a fixture sweep (pass + each hard-fail).
- Comp-routing test — backbone preferred; AI-fill path labeled AI-derived/EST.

**The full existing suite stays green** (172+ baseline). New code is import-only
against the backbone and does not touch the scan loop.

---

## 11. Domain guardrails new to this port (the firearms weight, recast)

The gun system carried legal weight (straw-purchase refusal, NFA/FFL). TCG's
equivalent weight is **authenticity and value-trap discipline**:
- **Authenticity** (`docs/poke/authenticity.md`): counterfeit/reseal red-flags
  (factory-seal tells, weight, shrink-wrap seams; proxy-single tells; fake/altered
  slab tells), and PSA/CGC/BGS **cert-lookup** pointers. A deep discount with no
  legitimate explanation is a fraud signal, surfaced in "Watch Out," not a steal.
- **Grade / condition / reprint discipline** — comps match grade + grader +
  condition; INV/COL tags annotate reprint and rotation exposure. These are the
  fabrication and value-trap risks the firearms domain never faced.

---

## 12. Out of scope / preserved anti-goals

- **No inventory ledger** (what you own) — that is Phase 2 of the resale-engine
  spec; the observation ledger here is strictly market observations.
- **No grading-EV / open-vs-flip pull math** — that is Phase 3; the INV lens may
  *flag* appreciation/reprint exposure but does **not** compute pull-EV or gem-rate
  economics.
- **No modification of the automated scan loop** (`main.py`, `web.py`) — the
  discovery subsystem is import-only against the backbone.
- No auto-checkout, no auto-listing, no unverified IDs, no AI price prediction
  (doctrine, permanent across all phases).

---

## 13. Open items for the implementation plan

### 13.0 Phase 0 spike — run before the full plan

Two empirical unknowns are **load-bearing**: either can invalidate a fixed
decision, so they are resolved first as a short spike, not buried assumptions.

- **Comp-verification probe (gates decision #2).** Does a *sealed* product yield a
  **verified-tier** comp end-to-end through `scanner.market`/`scanner.resale` in the
  current repo state? PPT is `preferred=false` by default with an unobtained key; if
  the only live source is the low-confidence `PublicFallbackResaleClient`, then under
  the §3.3 render gate even sealed renders `EST`, not STEAL — which reshapes the
  dashboard's character and the "sealed ships verified" promise. Resolve the PPT
  key/quota question here. **Output:** a yes/no on verified-tier sealed comps today,
  and the plan branch each answer implies.
- **Source-fetchability probe (shapes DISCOVER).** Playwright/WebFetch each candidate
  source in `sources.md`; record fetchable vs Cloudflare-blocked from live evidence.
  If fetchable TCG deal feeds are thin (no gun.deals-equivalent firehose), DISCOVER
  shifts from aggregator-led toward direct eBay/TCGplayer marketplace scanning, and
  the dashboard leans more on marketplace mispricings than curated sale pages.

### 13.1 Details to confirm during planning

- **PokemonPriceTracker** graded + singles endpoint shapes and credit cost (the
  free-tier vs paid framing is inherited from the Phase-1 spec §3.2/§3.6).
- **Exact lens strong-signal cutoffs** — pin the numeric thresholds (e.g. INV
  appreciation basis, PLY meta-relevance source) during planning.
- **Template adaptation** — port the gun `template.html` structure, swapping
  firearms sections/legend for the TCG sections in §8.

---

## 14. Sources / lineage

- Gun reference implementation: `OneDrive\Desktop\GUN DEALS\OPENER.md`, `DESIGN.md`,
  `template.html`, `data\independence-day.json`, `tests\golden_check.ps1`,
  `.opener-verified.json`.
- Companion spec (already built): `docs/superpowers/specs/2026-06-18-hobby-resale-engine-design.md`
  and plan `docs/superpowers/plans/2026-06-18-phase1-deal-intelligence.md`.
- Backbone code reused: `scanner/market.py`, `scanner/resale.py`, `scanner/margin.py`,
  `scanner/verdict.py`, `scanner/confidence.py`, `scanner/config.py`.
- PSA 2026 pricing/value-tier pause and reprint-flood context: carried from the
  Phase-1 spec §5–§6 sources.
