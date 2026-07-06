# Phase G Handoff Notes (authored during F.1 — G is NOT built)

**Date:** 2026-07-06
**Status:** Handoff only. **F.1 builds no population/gem-rate engine.** It *preserves* the
metadata G will consume and records the PSA-access research so G starts informed.
**Source:** [ppt-vs-ours-gap-matrix](ppt-vs-ours-gap-matrix-2026-07-06.md) row 10
(population/gem-rate = the one capability that directly unblocks new decisions).

> ## ⛔ SUPERSEDED WHERE IT SAYS "OPERATOR-ASSUMPTION FIRST" — READ THIS BOX FIRST
>
> **G is BUILT (2026-07-06).** The premise below that "population is login-gated + unstable
> → operator-supplied gem rate is the *safe default*" is **WRONG and reversed** by the live
> probe recorded in the [G–M roadmap §3.3](../superpowers/specs/2026-07-06-poke-api-ladder-g-through-m-roadmap.md#3-refreshed-public-source-assumptions-verified-live-2026-07-06)
> and now implemented:
>
> - **PRIMARY gem-rate source = sourced PriceCharting `VGPC.pop_data`.** The card detail page
>   the F.1 adapter already fetches (plain `requests`, **0 PPT credits**) embeds PSA + CGC
>   population as a plain-HTML JSON blob in the *initial* HTML — no login, no Playwright, no
>   paid API. Parsed by `independent_sources.pricecharting_pop_from_html`; formula
>   `PSA10 / total PSA population` (grader-specific, PSA and CGC **never** combined) in
>   `gem_rates.gem_rate_from_counts`; captured via `edge_cli gem-rate record` (operator-run,
>   `--yes`-gated, prints `credits_spent=0`).
> - **Operator-assumption is the FALLBACK only** — for assets with no pop blob, a grader
>   absent from the blob, or a total pop below the sample floor (`>= 300`). Recorded via
>   `gem-rate record-assumption`, labeled `operator_assumption`, capped PAPER_BUY.
> - **Everything below about the PSA *cert* API (no public pop endpoint) is still correct** —
>   only the "so operator-assumption is the safe default" conclusion is superseded. The
>   reachable, dated, 0-credit source is the **PriceCharting pop blob**, not the PSA API.
>
> Result doc: [phase-g-population-gemrate-result-2026-07-06.md](phase-g-population-gemrate-result-2026-07-06.md).

## What Phase G is (scope, for when it starts)

The raw→graded **grading-EV** path (`scanner/poke_api/grading_ev.py`) already exists and is
correct, but it **blocks** on a missing gem rate — it *never invents one*. Phase G's job is to
**source a gem rate / population signal honestly** so grading-EV can produce a number (still
capped at PAPER_BUY, never LIVE, because a gem rate is an assumption). **G is a sourcing +
break-even layer, not a new money model.**

## Fields G should consume (already present in the F.1 data spine)

Per asset and per recorded comp — all of these exist today and are byte-stable:

| Field | Where it lives now | Notes for G |
|---|---|---|
| `asset_key` | `assets.yaml` key | stable identity |
| `grade_key` | derived (`catalog.normalize_grade_key`) | e.g. `psa10`, `psa9`, `cgc10` |
| `grader` | asset field | `PSA` / `CGC` / `BGS` |
| `grade` | asset field | `10`, `9`, … |
| `condition` | asset field (raw) | `NM` / `LP` … (raw sibling of a graded target) |
| comp `source` | ledger `market_comp.source` | `pricecharting` (independent) / `ppt_cards` (audit) |
| `source_url` | ledger `market_comp.source_url` | exact page, attribution |
| `capture_date` | ledger `market_comp.capture_date` | freshness / staleness |
| **raw↔graded sibling** | matched on `tcgplayer_id` **+** target `grade_key` (as `grading_ev` already pairs them) | G needs the raw comp + the graded-target comp for the *same* card; today the F.1 cards omit `tcgplayer_id` (unverified) — **G must map exact `tcgplayer_id`s to pair siblings**, or pair on `(name,set,card_number)` identity |
| `sample_size` | **placeholder** (`CompSourceQuote.sample_size`, currently `None`) | PriceCharting's detail page shows a completed/recent-sales section (`id="completed"`, `chart_data`) but **no clean numeric count** in the initial HTML — see research below. G should treat sample size as unknown unless a real source provides it. |
| **population / gem-rate source** | `gem_rate` + `gem_rate_source` asset slots (optional, **never invented**) | absent → grading-EV blocks (correct). G fills these from a *sourced* rate or an explicit `operator_assumption` label. |
| break-even / gem-rate inputs | `grading_ev.grading_ev(...)` args: raw entry, raw comp, graded comp, grading fee (`poke.grading_cost_all_in`), resale fees, **gem rate** | G supplies the gem rate; everything else already flows. |

## PSA / population access research (2026-07-06) — the G blocker to plan around

- **No public PSA population-report API.** The PSA Public API (`psacard.com/publicapi`) is
  **login-gated** (OAuth2 password grant using PSA credentials, **100 calls/day** free) and is
  centered on **cert verification** (cert number → what PSA graded), **not** population counts.
- **Population data** is available as **browsable HTML** (`psacard.com/Pop`) or via **third-party
  scrapers** (e.g. Apify) only — no official, stable, keyed pop feed.
- **Implication for G:** population/gem-rate sourcing is **login-gated + unstable**. Options, in
  order of honesty/robustness:
  1. **Operator-supplied gem rate** as an explicit `operator_assumption` (works today; capped
     PAPER_BUY) — the safe default.
  2. A **sourced** pop-derived gem rate from a documented capture (HTML pop page or a keyed
     third-party feed), stamped with `gem_rate_source` + capture date — never a live hot-path call.
  3. The PSA cert API (login-gated) is useful for **cert verification**, not pop — do not plan a
     pop feed on it.
- **Do NOT** put any pop/gem-rate fetch on a read path, and **never invent** a gem rate — the
  STOP-class block (`grading_ev` returns `blocked` with a named blocker) is the correct behavior
  until a real source is wired.

## Explicit non-goals carried out of F.1 (do not let them creep into G silently)

- No move off **WATCH** for singles/slabs off a comp alone (the E verified-entry route is the only
  buy wire; unchanged).
- No broad catalog / set ingestion, no fuzzy mapping, no title normalization (see the gap matrix —
  those are post-G defers).
- Grading-EV stays **capped at PAPER_BUY** (gem rate is an assumption, not verified-data confidence).

## First concrete G step (suggested)

Map exact `tcgplayer_id`s for the F.1 raw↔graded siblings (Charizard 199, Pikachu 238) so grading-EV
can pair them, then wire an **operator-assumption** gem rate + a break-even readout — proving the
grading-EV number end-to-end on a *sourced* raw comp + independent graded comp before touching any
pop feed.
