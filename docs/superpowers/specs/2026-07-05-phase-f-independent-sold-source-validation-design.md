# Phase F — Independent Singles/Slabs Sold-Source Validation (Design)

**Date:** 2026-07-05 (rev. 2026-07-06)
**Status:** Design — revised per operator review; ready for the implementation plan.
**Repo:** `Pokemon-main` (package `scanner/`; price-API ladder `scanner/poke_api/`)
**Ladder position:** the next rung on the **private price-API ladder** (A → B → C → D/D.5 →
E → **F**). Not the discovery-slice roadmap. See
[`docs/poke/private-price-api.md`](../../poke/private-price-api.md).

## Revision note (2026-07-06 operator review)

1. **PriceCharting exact-slug adapter (raw + graded) is the required Phase F completion
   gate** — F is "done" when the PC adapter resolves + persists a non-PPT comp and the local
   audit becomes cross-source. TCGplayer is explicitly **not** on the completion path.
2. **TCGplayer/Playwright is now conditional + non-blocking:** attempt the dependency install +
   render **only if a render probe is approved and comes back clean**; if it is blocked (or the
   probe/install is declined), the adapter ships as an honest `blocked` shell and F still
   completes. It never blocks the gate.
3. **PriceCharting graded confidence is locked at `low`** unless *independently* corroborated —
   the confidence field is never lifted just because a cell is PSA-exact. **Cross-source
   validation is supplied by the divergence audit agreeing** (ours vs `ppt_cards`), not by the
   comp's own confidence.
4. **Result-doc acceptance for gitignored ledger rows:** `data/poke/price_history.jsonl` is
   gitignored (untracked), so the recorded independent comps are captured in a **committed
   result doc** as the durable, reviewable evidence (mirrors the prior audit-result docs).

---

## The system in one line

Add a **genuinely non-PPT, sold-derived** comp for raw singles and graded slabs — from
**PriceCharting (plain requests, the required completion gate)** and optionally TCGplayer
(rendered, conditional + non-blocking) — persisted into the *same* asset ledger, so
`edge_cli divergence-audit --local` stops comparing PPT-against-PPT and becomes a **true
independent cross-source validation**. PPT external mode stays audit-only. No verified entries,
no live-eligibility, no broad card-database import.

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

## Operator decisions (this session, as revised 2026-07-06)

1. **PriceCharting exact-slug adapter is the required completion gate.** F is complete when the
   PC raw+graded adapter resolves + persists a non-PPT comp and the local audit is cross-source.
2. **TCGplayer/Playwright is conditional + non-blocking:** attempt the dependency install +
   render **only if a render probe is approved and clean**; if blocked/declined, ship the honest
   `blocked` shell — F still completes. Never on the completion path.
3. **Graded PriceCharting:** build the adapter, **probe-gate the data** — probe done, **PASS**.
4. **Graded confidence is locked at `low`** unless independently corroborated; cross-source
   validation comes from the divergence audit agreeing, not from the confidence field.
5. **Mapping:** **exact slug/id only, never fuzzy.** Seeding the `pricecharting_slug` onto the
   Umbreon assets is in F's scope.
6. **Probe:** run the confirmatory PriceCharting GET this session — **done, PASS** (table above).
7. **Independent fetch trigger:** **CLI-only, operator-run**
   (`record-asset-comp --refresh-independent`). Read endpoints never fetch — read-first stays
   offline.
8. **Result-doc acceptance:** because the ledger is gitignored, the recorded independent comps
   are captured in a committed result doc as durable evidence.

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

  | grade_key pattern | cell id | column semantics (basis note) |
  |---|---|---|
  | `psa10` | `manual_only_price` | PSA-exact column |
  | `*9.5` (e.g. `cgc9.5`, `bgs9.5`, `psa9.5`) | `box_only_price` | grader-agnostic Grade 9.5 |
  | `*9` (e.g. `psa9`, `cgc9`) | `graded_price` | grader-agnostic Grade 9 |
  | `*8` | `new_price` | grader-agnostic Grade 8 |
  | `*7` | `complete_price` | grader-agnostic Grade 7 |
  | other (`cgc10`, `bgs10`, `*6`…) | — | `no_match` (no exact cell) |

  Sold-derived, slug `pricecharting`. **Confidence is LOCKED at `low`** — a single independent
  sold-derived source is `low` *regardless of which cell it came from*. The confidence field is
  **never** lifted to `medium`/`high` just because a cell is PSA-exact; it rises above `low`
  **only** with genuine independent corroboration (a second independent sold source agreeing
  within tolerance — not an eBay ask, which is context, and not the PPT number, which is the
  audit's counter-party). The PSA-exact vs grader-agnostic distinction is recorded in the
  **basis note** (provenance), not in the confidence. **Cross-source validation is a separate
  signal supplied by the divergence audit** (F4) when `ours` (PriceCharting) agrees with
  `theirs` (`ppt_cards`) — it does not mutate the stored comp's confidence. No slug →
  `skipped`; challenge → `blocked`; unmapped grade → `no_match`.
- **Exact-slug only.** Both adapters resolve strictly by `pricecharting_slug` (the canonical
  `/game/...` path). No fuzzy name search — a missing/unmatched slug is honest `no_match`/`skipped`,
  never a guessed variant (STOP-class, mirrors "resolve by exact `tcgPlayerId` only").
- **Doctrine.** Browser UA (the proven sealed UA), polite timeout; a 403/429/challenge is
  recorded `blocked`, never evaded.

### F2 — TCGplayer rendered adapter (Playwright; CONDITIONAL + NON-BLOCKING; 0 PPT credits)

**Not on the completion path.** The `TcgPlayerRenderedSource` adapter (with its guarded import
and honest-degrade contract) is **always built**; whether the Playwright dependency is installed
and a live render is attempted is **gated on an operator-approved, clean render probe**. If the
probe/install is declined, or the render comes back blocked, the adapter ships as an honest
`blocked` shell and **F completes anyway on PriceCharting alone**.

- **`TcgPlayerRenderedSource`** — `fetch(asset, checked_at) -> CompSourceQuote`. When rendering
  is enabled: renders the product page (`https://www.tcgplayer.com/product/{tcgplayer_id}`)
  headless, waits for the market-price node to hydrate, extracts the market price. Sold-derived,
  slug `tcgplayer`. No `tcgplayer_id` → `skipped`. Challenge/anti-bot page → `blocked` (never
  evaded). Render timeout / no price node → `no_match`.
- **Gated dependency + render probe (build-time gate).** Adding `playwright` to
  `requirements.txt` and running `playwright install chromium` happens **only after** an
  operator go-ahead on a **render probe** (a one-off supervised headless fetch of the Umbreon
  TCGplayer product page confirming a parseable market price, no challenge wall). Clean probe →
  install + wire live rendering. Declined/blocked probe → **no dependency added**, adapter stays
  a `blocked` shell, recorded honestly in the result doc. This keeps the repo's "never install a
  dependency without asking" doctrine intact even though the operator pre-approved the *intent*.
- **Guarded import (always).** With or without the install, the adapter's import is guarded — if
  Playwright/chromium is unavailable it degrades to a `blocked` quote and never raises. The
  pytest suite **never launches a browser**: the render call is injectable and mocked; any
  marker-gated live test is skipped by default (suite stays network-free per repo contract).
- **Positioning.** Heavier/riskier path, deliberately off the gate: PriceCharting alone
  satisfies F, so a declined install or flaky render never blocks the independent-source
  validation.

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
- When `ours` (independent) and `theirs` (`ppt_cards`) agree within tolerance, the audit
  annotates the row as a **cross-source validation** (distinct, stronger note than the
  same-provider consistency the last audit could claim). **This audit agreement — not the
  comp's confidence field — is what supplies the cross-source validation signal**; the persisted
  PriceCharting comp keeps its locked `low` confidence untouched. No change to the blocking rule
  — only `unexplained_material_divergence` still fails the command.
- **PPT external mode unchanged and audit-only** (money-class refuse-without-key/`--yes`,
  hard-stop floor). F adds no new external/billable surface.

### F5 — Seed the mappings + record independent comps

- `data/poke/assets.yaml`: add `pricecharting_slug: pokemon-prismatic-evolutions/umbreon-ex-161`
  to `umbreon_ex_161_raw_nm`, `umbreon_ex_161_raw_lp`, `umbreon_ex_161_psa10`,
  `umbreon_ex_161_psa9` (all the same card; the graded cell differs by `grade_key`). `tcgplayer_id`
  `610516` is already present on the mapped assets.
- Record the independent PriceCharting comps into `data/poke/price_history.jsonl` (0 PPT
  credits) via `record-asset-comp --refresh-independent` for **`raw_nm`, `psa10`, `psa9`** so the
  local audit has independent data on day one. **`raw_lp` is slug-mapped but not recorded** (the
  Ungraded cell doesn't distinguish condition — F1 condition caveat). Values are captured from
  the live source at record time (never hand-typed as comps except through the audited from-value
  path).
- **Durable evidence (gitignored ledger).** `data/poke/price_history.jsonl` is **gitignored**
  (untracked), so the recorded rows are not committed. Write a **committed result doc**
  `docs/poke/phase-f-independent-source-result-2026-07-06.md` recording each written row (asset,
  comp, confidence, source, capture_date, source URL, basis) plus the resulting
  `divergence-audit --local` cross-source outcome — mirroring
  `edge-asset-divergence-audit-result-2026-07-05.md`. This result doc is the reviewable proof
  that F's ledger writes happened, since the ledger itself is not in git.

### F6 — Tests, fixture, docs

- **Fixture:** persist the captured PriceCharting Umbreon detail page under
  `tests/fixtures/comps/pricecharting_umbreon_ex_161.html` (build Task 1).
- **Unit tests** (network-free, per repo contract):
  - Parser: raw `used_price` + every graded cell (`psa10→manual_only_price`,
    `psa9→graded_price`, `9.5→box_only_price`, …) from the fixture; malformed HTML → empty;
    challenge page → `blocked` signal.
  - Adapters: `ok` / `skipped` (no slug/id) / `no_match` (missing cell) / `blocked`
    (challenge/403) / grader-agnostic-proxy provenance on middle columns.
  - **Graded confidence lock:** every graded PriceCharting comp resolves to `low` confidence
    regardless of cell (PSA-exact `manual_only_price` included), and is **not** lifted absent
    independent corroboration — assert `confidence == "low"` and the basis note carries the
    column semantics.
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
  (`docs/poke/pricecharting-detail-probe-2026-07-05.md`) capturing the evidence table above; and
  the F5 **result doc** (`docs/poke/phase-f-independent-source-result-2026-07-06.md`) recording
  the gitignored ledger writes + the cross-source audit outcome. The TCGplayer render-probe
  outcome (clean → installed, or declined/blocked → shell) is recorded in the result doc too.

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
- **Dependency:** Playwright is added **only** after an operator-approved, clean render probe
  (conditional, non-blocking); guarded so its absence — the default until that gate passes —
  degrades honestly. A declined/blocked probe means no dependency is added and F still completes.

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

## Completion gate vs. conditional work

**Phase F is COMPLETE when the required gate below is green — independent of TCGplayer.**

- **Required (the completion gate):** the PriceCharting exact-slug adapter (raw + graded)
  resolves + persists a non-PPT comp for the mapped Umbreon assets; the graded confidence is
  locked `low`; `divergence-audit --local` becomes a true cross-source check; the result doc
  captures the (gitignored) ledger writes + audit outcome; full suite green.
- **Conditional + non-blocking:** the TCGplayer rendered adapter yielding live data. Gated on an
  approved, clean render probe. A declined/blocked probe leaves it a `blocked` shell and does
  **not** hold up completion — that outcome is simply recorded in the result doc.

## Acceptance criteria

**Required (the completion gate):**

1. `independent_sources.py` exists with the shared parser + the two PriceCharting adapters
   (raw, graded) + a TCGplayer adapter (shell or live), each degrading honestly per the matrix.
2. The captured PriceCharting fixture parses to the exact grade→value table above in tests.
3. `record-asset-comp --refresh-independent` persists a `pricecharting` comp — **never**
   `ppt_cards` — at **0 PPT credits** (asserted).
4. Every graded PriceCharting comp resolves at **`low` confidence** (PSA-exact cell included),
   not lifted absent independent corroboration; the PSA-exact vs grader-agnostic distinction
   lives in the basis note (asserted).
5. After recording, `divergence-audit --local --assets umbreon_ex_161_raw_nm,umbreon_ex_161_psa10`
   compares independent `ours` vs `ppt_cards` `theirs`, surfaces `ours_source`, and annotates a
   **cross-source** agreement (0 credits) — the audit agreement, not the confidence, being the
   validation signal.
6. The Umbreon assets carry `pricecharting_slug`; the graded map resolves `psa10`→`manual_only_price`
   (PSA-exact) and `psa9`→`graded_price` (grader-agnostic proxy) with honest basis notes.
7. The **committed result doc** records each gitignored ledger row written (asset, comp,
   confidence, source, capture_date, URL, basis) + the `--local` cross-source outcome.
8. Guardrails proven by test: 0 PPT credits on the independent path; ask never a comp; assets
   stay WATCH; no verified-entry fabrication.
9. Full suite green (`.venv/Scripts/python.exe -m pytest -q`); docs updated (Track F, runbook,
   sources.md, probe-result doc, result doc).

**Conditional (TCGplayer; only if the render probe is approved + clean):**

10. Playwright added; suite stays network-free and green; the render adapter yields a
    `tcgplayer` comp on a live probe. If the probe is declined/blocked, the adapter remains a
    guarded `blocked` shell (suite still green) and the result doc records that outcome — this
    does **not** block completion.

## Build task outline (for the plan)

**Required gate — PriceCharting first, complete before any TCGplayer work:**

1. Capture the PC fixture; write the shared parser + parser tests (TDD).
2. `PriceChartingRawSource` + `PriceChartingGradedSource` (+ grade_key→cell map, **confidence
   locked `low`**) + adapter tests.
3. Resolver wiring (PC `pc_source` slot) + `poke.independent_sources` config + wiring tests.
4. CLI `--refresh-independent` + the `_record_billed` slug-fallback fix + CLI tests.
5. `divergence._local_ours` sharpen + `ours_source` + cross-source annotation + audit tests.
6. Seed `pricecharting_slug`; record the independent comps for `raw_nm`/`psa10`/`psa9`
   (0 credits); guardrail tests; write the **result doc** capturing the gitignored ledger rows +
   `--local` cross-source outcome.
7. Docs: Track F, runbook, sources.md, probe-result doc. **At this point the completion gate is
   green** — full suite green + review.

**Conditional (non-blocking) — only after the gate is green:**

8. `TcgPlayerRenderedSource` shell + guarded import + mocked-render tests (no dependency yet).
9. Operator render-probe on the TCGplayer product page. If approved + clean: add `playwright`,
   run `playwright install chromium`, wire live rendering, record a `tcgplayer` comp, and note
   it in the result doc. If declined/blocked: leave the `blocked` shell and record that outcome.
   Either way the suite stays network-free and green.
