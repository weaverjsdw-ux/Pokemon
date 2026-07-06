# PPT-vs-Ours Capability Gap Matrix

**Date:** 2026-07-06 (Phase F.1)
**Purpose:** a durable, decision-bearing map of what PokemonPriceTracker (PPT — our external
card-price provider / audit oracle) does vs what **our owned `/api/poke` program** does, with
an explicit build/defer/reject decision per capability. This is the F.1 "gap matrix" deliverable
and the reference for prioritising post-F work.
**Companion:** [private-price-api.md](private-price-api.md) (the A→F.1 ladder),
[phase-f1-independent-source-result-2026-07-06.md](phase-f1-independent-source-result-2026-07-06.md).

## Frame

Our program is **not a PPT clone**. It is an owned, read-first, STOP-class-honest price-and-edge
layer where **external/PPT output is an optional adapter or an off-hot-path audit oracle only**.
So a "missing" capability is only a gap if it serves *our* goal (defensible, source-attributed
comps + an explainable edge decision); several PPT features are **intentionally refused** because
adopting them would violate price-accuracy discipline or the program's identity. Some *refusals*
are **advantages**, not gaps.

Legend — **gap status:** `closed` (we have it) · `partial` (have it, with a named limitation) ·
`missing` (don't have it) · `refused` (intentionally not built). **decision:** `build` (done or
do it) · `defer` (worth doing later) · `reject` (out of scope by design).

## Matrix

| # | Capability | PPT | Ours (today) | Gap status | Risk if missing | Recommended phase | Decision |
|---|---|---|---|---|---|---|---|
| 1 | **Local API / facade** | Hosted `/cards`, `/sealed-products` API | Owned read-first `/api/poke` (`/products`, `/assets`, comp/history/momentum, `/cards` + `/sealed-products` compat facades, `/edge-*`) | **closed** | — | A/B/D (built) | **build ✓** |
| 2 | **Provider-neutral boundary** | *is* the provider | `ExternalCardPriceClient` (pluggable; `PptCardClient` deprecated alias); neutral `CARD_PRICE_API_KEY` env | **closed** | vendor lock-in | D.5 (built) | **build ✓** |
| 3 | **Read-path credit accounting** | Bills per call | Reads report `apiCallsConsumed.total = 0`; asset `refresh=true` reports a bounded upper bound (1 raw / 2 graded) | **partial** | money-honesty; the legacy *sealed* refresh path does not yet emit `apiCallsConsumed` (honest silence, documented) | D.5 built; sealed-refresh instrumentation follow-up | **build** (finish sealed path) |
| 4 | **Raw + graded catalog** | Huge card DB | `data/poke/assets.yaml` + `catalog.py` (raw/graded, exact ids/slugs, identity) | **closed** (small set) | — | D (built) | **build ✓** |
| 5 | **Independent PriceCharting validation** | Single-source (PPT resells TCGplayer market) | PriceCharting exact-slug raw+graded adapters, 0 PPT credits; **F.1** generalized to 4 cards / 3 sets | **closed** | comp rests on one provider | F / **F.1** (built) | **build ✓** |
| 6 | **Divergence audit** | n/a | `divergence.py` local + external (money-class) + **F.1 multi-asset gap matrix**; material *unexplained* gap fails | **closed** | can't tell "ours wrong" from "theirs wrong" | E / **F.1** (built) | **build ✓** |
| 7 | **Catalog breadth** | Effectively every set | ~10 hand-mapped assets | **missing** (breadth) | can only reason about mapped cards | post-G (broad ingestion) | **defer** (F.1 is per-mapped-asset, never bulk) |
| 8 | **Automated mapping** (name → id/slug) | Search-resolves | **Exact manual mapping only; no fuzzy** | **refused** (fuzzy) / `missing` (auto) | manual effort per card | a *verified-slug* resolver (redirect-confirmed, never fuzzy) is a possible future | **defer** (reject fuzzy; verified-redirect resolver could be built) |
| 9 | **Title / listing normalization** | eBay title → card identity | none (exact-id only) | **missing** | can't ingest free marketplace listings | post-G | **defer** |
| 10 | **Population / gem-rate** | Pop data available | metadata slots only (`gem_rate` / `gem_rate_source`), **no engine** | **missing** (intentional) | grading-EV blocks without a gem rate (never invented) | **G** | **build in G** (defer from F.1) |
| 11 | **Parse-title support** | `parse-title` endpoint | none | **missing** | no free-text card resolution | post-G | **defer** |
| 12 | **Bulk export / history depth** | Deep history + CSV export | ledger-depth history/momentum (shallow, grows with sweeps); no export | **partial** | shallow trend confidence | accrues over time; export is a follow-on | **defer** |
| 13 | **Portfolio / wishlist UX** | Portfolio UI | none | **refused** | — (not our identity) | — | **reject** |
| 14 | **Public API polish** | Polished public product | local-only, read-first, never hosted | **refused** | — (local by design) | — | **reject** |
| 15 | **Ask-only comp refusal** | May blend active asks | **STOP-class: an ask is context, never a comp** (`_ASK_SOURCES`, `allow_ask_only=False`) | **closed** (advantage) | laundering asks into sold truth | built | **build ✓** (keep — an edge over PPT) |
| 16 | **Fake-entry refusal** | n/a | **No verified entry / no live off a comp alone**; writer refuses non-positive/absent/ask comps | **closed** (advantage) | fabricated buys | E / built | **build ✓** (keep) |
| 17 | **TCGplayer/PPT same-source issue** | TCGplayer market == PPT to the cent | **Structurally excluded**: `_INDEPENDENT_OF_PPT = {pricecharting}` — a tcgplayer comp is never counted cross-source-validated | **closed** | false confidence from a correlated "second" source | **F.1** (built) | **build ✓** |

## Summary

- **Closed / built (11):** local facade, provider-neutral boundary, raw/graded catalog,
  independent PriceCharting validation, divergence audit + gap matrix, ask-only refusal,
  fake-entry refusal, TCGplayer/PPT same-source guard — plus the two accounting/history *partials*
  that are largely done. Several of these (15, 16, 17) are **disciplines PPT lacks** — kept as
  advantages, not gaps.
- **Partial (2):** read-path credit accounting (sealed-refresh path not yet instrumented) and
  history depth (accrues with sweeps). Both have honest, documented limitations.
- **Build next — Phase G (1):** population / gem-rate. The metadata slots exist and are never
  invented; the engine is G. See [phase-g-handoff-notes-2026-07-06.md](phase-g-handoff-notes-2026-07-06.md).
- **Defer (5):** catalog breadth, automated (verified-only) mapping, title normalization,
  parse-title, bulk export — all post-G, all subordinate to keeping mappings exact and honest.
- **Reject (3):** fuzzy auto-mapping, portfolio/wishlist UX, public API polish — out of scope by
  design (they would either violate exact-id discipline or change the program's identity).

**Bottom line:** the price-intelligence spine (owned facade + independent validation + honest
divergence + STOP-class refusals) is **built and now generalized**. The one capability that
directly unblocks new *decisions* (grading-EV) is **population/gem-rate → Phase G**. Breadth items
are deferred on purpose: F.1's value is that every mapped card is *exactly* mapped and
*independently* validated, not that many cards are approximately covered.
