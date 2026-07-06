# Phase F — Independent Singles/Slabs Sold-Source Validation (Design)

**Date:** 2026-07-05
**Status:** Design — awaiting operator review before build.
**Repo:** `Pokemon-main` (package `scanner/`; price-API ladder `scanner/poke_api/`)
**Ladder position:** the next rung on the **private price-API ladder** (A → B → C → D/D.5 →
E → **F**). Not the discovery-slice roadmap. See
[`docs/poke/private-price-api.md`](../../poke/private-price-api.md).

---

## The system in one line

Add a **genuinely non-PPT, sold-derived** comp for raw singles and graded slabs — from
PriceCharting (plain requests) and TCGplayer (rendered) — persisted into the *same* asset
ledger, so `edge_cli divergence-audit --local` stops comparing PPT-against-PPT and becomes a
**true independent cross-source validation**. PPT external mode stays audit-only. No verified
entries, no live-eligibility, no broad card-database import.

## Why now (the gap this closes)

The 2026-07-05 asset divergence audit
([`edge-asset-divergence-audit-result-2026-07-05.md`](../../poke/edge-asset-divergence-audit-result-2026-07-05.md))
passed only as a **same-provider consistency** check: `ours` was derived from `ppt_cards`,
`theirs` was a fresh `ppt_cards` call. Its own "Remaining next step" names this build exactly:

> map + configure an independent sold-derived adapter (TCGplayer / PriceCharting) for these
> singles. Once a non-`ppt_cards` comp is persisted, the **local** audit will compare two
> independent sources numerically and the external PASS becomes a true cross-source validation.

The audit *logic* and the *persistence writer* already exist. `divergence._local_ours` already
selects the latest **non-`ppt_cards`** local comp; `sources.record_asset_comp` already persists
a `pricecharting`-slugged `market_comp`; the raw/graded resolvers even declare `tcg_source` /
`pc_source` injection slots. **The one missing piece is the adapter that produces the
independent number** — those slots are wired to `None` today, so the only real asset source is
the PPT `/cards` client (`ppt_cards`). F builds the missing adapters and wires them.

## What already exists (do NOT rebuild)

- **Persistence writer** — `sources.build_asset_comp_observation` / `record_asset_comp`
  (commit `f48e9a8`): a provenance-honest `market_comp` writer keyed on
  `history.asset_identity` so the persisted `item_key` byte-matches read-first. Already refuses
  a non-positive/absent comp and any ask source (`_ASK_SOURCES = {"ebay"}`). Already accepts an
  arbitrary `source` slug (e.g. `pricecharting`).
- **Local audit comparison** — `divergence.audit_local` / `_local_ours` / `_local_theirs`.
  `_EXTERNAL_SLUGS = {"ppt_cards"}`; `ours` = latest non-`ppt_cards` `market_comp`, `theirs` =
  latest `ppt_cards` `market_comp`. 0 network, 0 credits.
- **Resolver injection slots** — `sources.resolve_raw_comp(..., tcg_source=None, pc_source=None,
  ebay_source=None)` and `resolve_graded_comp(..., pc_source=None, ebay_source=None)`. The
  in-house confidence ladder (`comps.model.resolve` → `to_legacy_row`) is already the number
  producer; adapters just feed it `CompSourceQuote`s.
- **CLI** — `edge_cli record-asset-comp` (0-credit from-value default; operator-gated billed
  `--refresh` against PPT) and `divergence-audit` (dry/local default; external only with `--yes`
  + key).
- **PriceCharting HTML machinery (sealed)** — `resale.pricecharting_quote_from_html` +
  `PriceChartingSearchClient` (browser UA, plain requests, proven in production). **Not directly
  reusable** for assets (sealed `fetch(product_key, product, checked_at)` 3-arg signature vs the
  asset `fetch(asset, checked_at)` 2-arg; and it parses the *search-products* `used_price`
  column, not the *detail-page* graded table). The parsing *technique* is the reusable part.
- **CompSourceQuote / SOLD_DERIVED / comps.model.resolve** — the confidence ladder and quote
  type the adapters emit.

## Load-bearing fetchability constraints (evidence-backed)

- **TCGplayer product pages are a client-rendered SPA.** The 2026-07-03 probe
  ([`tcgplayer-probe.md`](../../poke/reference/tcgplayer-probe.md)) found plain `requests`
  returns an identical empty SPA shell for every product id — zero parseable price. Its sealed
  adapter (`comps/tcgplayer.py`) is a permanent `blocked` stub. **Only a headless browser
  (Playwright) can extract a price.** It is *not* a hard bot-wall (normal 200, no challenge
  markers), so rendering reads a normally-served page — within doctrine, not evasion.
- **Playwright is not currently a scanner dependency** (deps: `requests`, `PyYAML`, `polyline`).
  **Operator approved adding it** for this build (see Operator decisions).
- **PriceCharting detail pages ARE plain-requests-fetchable** — confirmed by this session's
  operator-approved probe (0 PPT credits; PriceCharting is not PPT):

### Confirmed probe evidence (2026-07-05, read-only, 0 credits)

Query `umbreon ex 161 prismatic evolutions` on `search-products` **auto-redirects** to the
canonical detail page `https://www.pricecharting.com/game/pokemon-prismatic-evolutions/umbreon-ex-161`
(HTTP 200, no challenge page). The `#price_data` table exposes six cells, mapped to grade
labels and (live) values:

| PriceCharting cell id | Grade label | Live value (Umbreon ex 161) | Our asset mapping |
|---|---|---:|---|
| `used_price` | Ungraded | $1,425.00 | **raw** (any condition; NM/LP proxy) |
| `complete_price` | Grade 7 | $1,270.00 | grade 7 (grader-agnostic) |
| `new_price` | Grade 8 | $1,286.91 | grade 8 (grader-agnostic) |
| `graded_price` | Grade 9 | $1,554.05 | **`psa9`** (grader-agnostic proxy) |
| `box_only_price` | Grade 9.5 | $3,112.50 | grade 9.5 (grader-agnostic) |
| `manual_only_price` | PSA 10 | $7,013.08 | **`psa10`** (PSA-exact) |

**Cross-source sanity vs the ledger's recorded PPT values:** raw $1,425.00 vs PPT $1,528.09
(~7.2% delta) and PSA 10 $7,013.08 vs PPT $6,925.50 (~1.3% delta) — both inside the 20%
agreement tolerance. So once persisted, `--local` yields a genuine **cross-source PASS on real
independent data**. (Raw fixture captured in scratchpad this session; build Task 1 persists it
under `tests/fixtures/comps/`.)

**Provenance nuance (STOP-class honesty):** the `PSA 10` column is PSA-exact; the middle
columns (`Grade 7/8/9/9.5`) are **grader-agnostic** PriceCharting grades. A `psa9` comp taken
from the `Grade 9` column must be labelled a *grader-agnostic proxy* (basis + capped
confidence), never presented as PSA-specific. Non-PSA-10 top grades (`cgc10`, `bgs10`) have **no**
generic Grade-10 cell in this primary table → honest `no_match` (an extended multi-grader table
is a deferred follow-on, not F).

## Operator decisions (this session)

1. **TCGplayer:** build the adapter **and add Playwright now** — a real rendered adapter with
   live data this build (not a dormant shell).
2. **Graded PriceCharting:** build the adapter, **probe-gate the data** — probe done, **PASS**.
3. **Mapping:** **exact slug/id only, never fuzzy.** Seeding the `pricecharting_slug` onto the
   Umbreon assets is in F's scope.
4. **Probe:** run the confirmatory PriceCharting GET this session — **done, PASS** (table above).
5. **Independent fetch trigger:** **CLI-only, operator-run**
   (`record-asset-comp --refresh-independent`). Read endpoints never fetch — read-first stays
   offline.
6. **TCGplayer timing:** **full build incl. Playwright this pass.**

---

## Scope

### F1 — PriceCharting asset adapters (real independent source; plain requests, 0 PPT credits)

New module `scanner/poke_api/independent_sources.py`.

- **Shared parser** `pricecharting_card_prices_from_html(body) -> dict`:
  `{ "cells": {cell_id: price}, "grades": {grade_label: price}, "url": ... }`. Type-defensive
  (malformed HTML → empty dict, never a crash). Detects a challenge page
  (`"Just a moment"` / `cf-browser-verification`) and signals `blocked`.
- **`PriceChartingRawSource`** — `fetch(asset, checked_at) -> CompSourceQuote`. Resolves the
  `used_price` (Ungraded) cell for the asset's `pricecharting_slug`. Sold-derived, slug
  `pricecharting`. Ungraded ≈ raw loose/NM: recorded as a raw comp with an honest basis note
  ("PriceCharting Ungraded market summary"). No slug → `skipped` (0 network). Non-200 /
  challenge → `blocked`. No `used_price` cell → `no_match`.
  - **Condition caveat (STOP-class honesty):** PriceCharting "Ungraded" is a *single* loose
    price that does **not** distinguish raw condition (NM vs LP). The adapter treats it as an
    **NM-ish loose proxy**; the basis note records "condition not distinguished (Ungraded)". F5
    therefore records the independent comp for `umbreon_ex_161_raw_nm` only; `raw_lp` gets the
    slug mapped (so it *can* resolve later) but is **not** auto-recorded off Ungraded, because
    that would over-value LP — an explicit, honest deferral, not a silent one.
- **`PriceChartingGradedSource`** — `fetch(asset, checked_at) -> CompSourceQuote`. Maps the
  asset's `grade_key` → cell id via an explicit, verified table:

  | grade_key pattern | cell id | provenance |
  |---|---|---|
  | `psa10` | `manual_only_price` | PSA-exact |
  | `*9.5` (e.g. `cgc9.5`, `bgs9.5`, `psa9.5`) | `box_only_price` | grader-agnostic proxy |
  | `*9` (e.g. `psa9`, `cgc9`) | `graded_price` | grader-agnostic proxy |
  | `*8` | `new_price` | grader-agnostic proxy |
  | `*7` | `complete_price` | grader-agnostic proxy |
  | other (`cgc10`, `bgs10`, `*6`…) | — | `no_match` (no exact cell) |

  Sold-derived, slug `pricecharting`. Confidence: PSA-exact cell → `medium` (single
  sold-derived source; `low` if an eBay ask is absent to corroborate per the existing graded
  ladder), grader-agnostic proxy → capped at `low` with the proxy basis note. No slug →
  `skipped`; challenge → `blocked`; unmapped grade → `no_match`.
- **Exact-slug only.** Both adapters resolve strictly by `pricecharting_slug` (the canonical
  `/game/...` path). No fuzzy name search — a missing/unmatched slug is honest `no_match`/`skipped`,
  never a guessed variant (STOP-class, mirrors "resolve by exact `tcgPlayerId` only").
- **Doctrine.** Browser UA (the proven sealed UA), polite timeout; a 403/429/challenge is
  recorded `blocked`, never evaded.

### F2 — TCGplayer rendered adapter (Playwright; operator-approved; 0 PPT credits)

- **`TcgPlayerRenderedSource`** — `fetch(asset, checked_at) -> CompSourceQuote`. Renders the
  product page (`https://www.tcgplayer.com/product/{tcgplayer_id}`) headless, waits for the
  market-price node to hydrate, extracts the market price. Sold-derived, slug `tcgplayer`. No
  `tcgplayer_id` → `skipped`. Challenge/anti-bot page → `blocked` (never evaded). Render
  timeout / no price node → `no_match`.
- **Dependency.** Add `playwright` to `requirements.txt`; build step runs
  `playwright install chromium`. **Guarded import** — if Playwright (or the browser binary) is
  unavailable, the adapter degrades to a `blocked` quote and never raises. The pytest suite
  **never launches a browser**: the render call is injectable and mocked; a marker-gated
  optional live test may exist but is skipped by default (suite stays network-free per repo
  contract).
- **Positioning.** Heavier/riskier path; the design keeps PriceCharting sufficient for F on its
  own, so a flaky TCGplayer render never blocks the independent-source validation.

### F3 — Resolver + persistence wiring

- Wire the real adapters into `resolve_asset_source_row` → `resolve_raw_comp` /
  `resolve_graded_comp` (`tcg_source` / `pc_source` slots), gated by config + mapping. The
  in-house ladder still produces the number; adapters only supply sold quotes.
- **New config surface** `poke.independent_sources` (bool, default **false**). When true, the
  CLI independent-refresh path is permitted to make live PriceCharting/TCGplayer fetches (0 PPT
  credits). Read endpoints ignore it (read-first stays offline).
- **New CLI path** `edge_cli record-asset-comp --refresh-independent [--source pricecharting|tcgplayer]`:
  a **0-PPT-credit** live fetch from the independent source, resolved through the ladder and
  persisted with the **correct** slug. Distinct from the PPT `--refresh` (billable) path.
- **Bug fix (wiring):** `edge_cli._record_billed` defaults `_row_primary_source(row) or "ppt_cards"`.
  The independent path must derive its slug from the actual source (never fall back to
  `ppt_cards`), so an independent number is never mislabeled as provider-derived. (The billed
  PPT path keeps its `ppt_cards` default.)

### F4 — `divergence-audit --local` as a true cross-source check

- Sharpen `divergence._local_ours` to prefer a **sold-derived independent** slug
  (`pricecharting` / `tcgplayer`) for `ours`, and carry `ours_source` onto each row so the
  report names which independent source backed the number.
- When `ours` (independent) and `theirs` (`ppt_cards`) agree, classify/annotate it as a
  **cross-source validation** (distinct, stronger note than the same-provider consistency the
  last audit could claim). No change to the blocking rule — only
  `unexplained_material_divergence` still fails the command.
- **PPT external mode unchanged and audit-only** (money-class refuse-without-key/`--yes`,
  hard-stop floor). F adds no new external/billable surface.

### F5 — Seed the mappings + record independent comps

- `data/poke/assets.yaml`: add `pricecharting_slug: pokemon-prismatic-evolutions/umbreon-ex-161`
  to `umbreon_ex_161_raw_nm`, `umbreon_ex_161_raw_lp`, `umbreon_ex_161_psa10`,
  `umbreon_ex_161_psa9` (all the same card; the graded cell differs by `grade_key`). `tcgplayer_id`
  `610516` is already present on the mapped assets.
- Record the independent PriceCharting comps into `data/poke/price_history.jsonl` (0 PPT
  credits) via `record-asset-comp --refresh-independent` so the local audit has independent data
  on day one. Values are captured from the live source at record time (never hand-typed as
  comps except through the audited from-value path).

### F6 — Tests, fixture, docs

- **Fixture:** persist the captured PriceCharting Umbreon detail page under
  `tests/fixtures/comps/pricecharting_umbreon_ex_161.html` (build Task 1).
- **Unit tests** (network-free, per repo contract):
  - Parser: raw `used_price` + every graded cell (`psa10→manual_only_price`,
    `psa9→graded_price`, `9.5→box_only_price`, …) from the fixture; malformed HTML → empty;
    challenge page → `blocked` signal.
  - Adapters: `ok` / `skipped` (no slug/id) / `no_match` (missing cell) / `blocked`
    (challenge/403) / grader-agnostic-proxy provenance on middle columns.
  - TCGplayer: mocked render `ok`; Playwright-absent → `blocked` (no crash); challenge → `blocked`.
  - Resolver wiring: independent adapter feeds the ladder; correct slug persisted; slug is
    outside `_EXTERNAL_SLUGS`.
  - Audit: independent `ours` vs `ppt_cards` `theirs` → cross-source `agree`; `ours_source`
    surfaced; a material unexplained gap still fails.
  - CLI: `--refresh-independent` persists `pricecharting`/`tcgplayer` (never `ppt_cards`);
    from-value path unchanged.
- **Guardrail tests (belt-and-suspenders):** the independent path spends **0 PPT credits**
  (counting/failing PPT client asserts no `/cards` call); an ask source is refused; assets stay
  **WATCH** (never live-eligible); no verified-entry fabrication (edge packets unchanged in
  decision class — comp added, decision still WATCH without verified entry).
- **Docs:** new **Track F** section in `private-price-api.md`; update the edge-layer runbook
  (`record-asset-comp --refresh-independent` + cross-source audit); add
  `sources.md` verdict row (PriceCharting detail page = **fetchable-plain**); a probe-result doc
  (`docs/poke/pricecharting-detail-probe-2026-07-05.md`) capturing the evidence table above.

---

## Data flow

```text
asset (+ pricecharting_slug / tcgplayer_id)
  -> independent adapter .fetch(asset, checked_at)
       PriceCharting: plain-requests GET detail page  (0 PPT credits)
       TCGplayer:     headless render                 (0 PPT credits)
  -> CompSourceQuote(SOLD_DERIVED, status, price, url, slug in {pricecharting, tcgplayer})
  -> comps.model.resolve -> to_legacy_row            (in-house confidence ladder)
  -> record_asset_comp(source="pricecharting"|"tcgplayer")  -> price_history.jsonl
  -> read-first serves it at 0 credits (source: local)
  -> divergence-audit --local: ours(independent) vs theirs(ppt_cards)  -> cross-source result
```

## Error handling / degrade matrix

| Condition | Result | Never |
|---|---|---|
| No `pricecharting_slug` / `tcgplayer_id` | `skipped` (0 network) | fuzzy-match |
| HTTP 403 / 429 / challenge page | `blocked` | evade the wall |
| Playwright / chromium unavailable | `blocked` | crash the lookup or suite |
| Missing/mismatched grade cell | `no_match` | guess a nearby grade |
| Malformed HTML | `no_match` / empty parse | raise into the route |
| Adapter/resolver bug | contained by `_safe_fetch` → error quote | persist a number |
| Comp ≤ 0 / absent, or ask source | writer `ValueError` (refused) | launder an ask into a comp |

## Guardrails (STOP-class + doctrine, restated)

- **Comp source + audit input ONLY.** No candidates, no verified entries, no live-eligibility —
  assets remain **WATCH** regardless of the number (the E verified-entry route is untouched;
  `opportunities.py` "assets never live in D" guarantee holds).
- **Per-mapped-asset, not bulk.** No broad card/set ingestion, no public API/DB import.
- **PPT external mode stays audit-only.** F adds no new billable surface.
- **Price accuracy:** exact-id only (never fuzzy); every persisted price carries its source URL +
  capture date + basis; no source → no number; an active ask is context, never a comp.
- **Credits:** independent adapters are **0 PPT credits** (they never call PPT). The only
  billable surfaces in the repo (`--refresh` PPT, external divergence mode) are unchanged.
- **Dependency:** Playwright is added only because the operator approved it; guarded so its
  absence degrades honestly.

## Config surface (new)

- `poke.independent_sources: false` — master gate for the CLI independent live-fetch path.
- (No key required — PriceCharting/TCGplayer are keyless. The gate is purely a "live network is
  allowed here" switch, consistent with the operator-run posture.)

## Out of scope (explicit)

- Verified-entry / candidate creation for assets; any move off WATCH.
- Live-eligibility for singles/slabs.
- Broad card database / set ingestion / bulk import; parse-title matching; CardMarket/JP;
  population/GemRate; portfolio/wishlist UI (these are the larger PPT-parity items — not F).
- Extended multi-grader PriceCharting table (BGS10/CGC10/SGC10 columns) — honest `no_match`
  today; a deferred follow-on.
- Making read endpoints fetch independent sources (read-first stays offline).
- Auto-seeding slugs by fuzzy search.

## Acceptance criteria

1. `independent_sources.py` exists with the shared parser + 3 adapters (PC-raw, PC-graded,
   TCGplayer-rendered), each degrading honestly per the matrix.
2. The captured PriceCharting fixture parses to the exact grade→value table above in tests.
3. `record-asset-comp --refresh-independent` persists a `pricecharting` (and, with a mapped id,
   `tcgplayer`) comp — **never** `ppt_cards` — at **0 PPT credits** (asserted).
4. After recording, `divergence-audit --local --assets umbreon_ex_161_raw_nm,umbreon_ex_161_psa10`
   compares independent `ours` vs `ppt_cards` `theirs`, surfaces `ours_source`, and reports a
   cross-source `agree` (0 credits).
5. The Umbreon assets carry `pricecharting_slug`; the graded map resolves `psa10`→PSA-exact and
   `psa9`→grader-agnostic proxy with honest provenance.
6. Playwright added; suite stays network-free and green; Playwright-absent path degrades to
   `blocked` without failing.
7. Guardrails proven by test: 0 PPT credits on the independent path; ask never a comp; assets
   stay WATCH; no verified-entry fabrication.
8. Full suite green (`.venv/Scripts/python.exe -m pytest -q`); docs updated (Track F, runbook,
   sources.md, probe-result doc).

## Build task outline (for the plan)

1. Capture the PC fixture; write the shared parser + parser tests (TDD).
2. `PriceChartingRawSource` + `PriceChartingGradedSource` (+ grade_key→cell map) + adapter tests.
3. `TcgPlayerRenderedSource` + guarded Playwright + mocked-render tests; add the dependency.
4. Resolver wiring + `poke.independent_sources` config + wiring tests.
5. CLI `--refresh-independent` + the `_record_billed` slug-fallback fix + CLI tests.
6. `divergence._local_ours` sharpen + `ours_source` + cross-source note + audit tests.
7. Seed `pricecharting_slug`; record the independent comps (0 credits); guardrail tests.
8. Docs: Track F, runbook, sources.md, probe-result doc. Full-suite green + final review.
