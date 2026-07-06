# Phase G — Population / GemRate + Grading-EV Credibility Result

**Date:** 2026-07-06
**Status:** BUILT + verified against **fixtures** (network-mocked suite). **No live pop
capture was run** — a live `gem-rate record` against PriceCharting is a live-network call
and awaits explicit operator go-ahead (0 PPT credits, but still live network + operator-run
per the roadmap's record-path discipline). This doc is the durable proof of the Phase G
build and its fixture-verified behavior; the runtime ledger `data/poke/gem_rates.jsonl` is
gitignored, so a committed result doc is the evidence (mirrors the F / F.1 result docs).
**Spec:** [G–M roadmap §G](../superpowers/specs/2026-07-06-poke-api-ladder-g-through-m-roadmap.md)
· **Supersedes** the "operator-assumption first" premise in
[phase-g-handoff-notes](phase-g-handoff-notes-2026-07-06.md).
**Credits:** 0 PPT (the pop path never constructs a PPT client, by construction).

## What Phase G makes true

Raw→graded grading EV was already correct but **blocked on a missing gem rate**. G supplies
that input honestly, so grading EV now produces a **PAPER-only number with full provenance
OR blocks with named missing inputs** — and never invents a rate.

- **Sourced pop present + above floor →** PAPER-only grading-EV number, with break-even +
  sensitivity band + a `sourced` gem-rate provenance row (0 PPT credits).
- **Pop missing / grader absent / below the sample floor (`>= 300`) →** named block, or an
  explicit `operator_assumption` (fallback, still capped PAPER_BUY). Never a guess.
- **Read paths →** ledger-only, 0 network, 0 PPT credits.

## Policy decisions locked (code + docs)

| Decision | Value | Where |
|---|---|---|
| Gem-rate formula | `{GRADER}10 / total {GRADER} population`, **grader-specific** (label names the row's own grader) | `gem_rates.gem_rate_formula` / `gem_rate_from_counts` |
| PSA + CGC combined? | **Never** — separate series | `gem_rate_from_counts(grader=...)` |
| Index→grade map | 10 elements, grade 10 = **last**, pinned | `gem_rates.POP_GRADE_LADDER` |
| Sample-size floor | `total_pop >= 300` (below → block / assumption) | `gem_rates.SAMPLE_FLOOR_DEFAULT` |
| Grading-EV cap | **PAPER_BUY, never LIVE** (population proxy) | `grading_ev` / endpoint `capped_at` |

## Index→grade map — CONFIRMED, not assumed

The 10-element `VGPC.pop_data` array is grades 1..10 (no half/Authentic offset), so the last
element is grade 10. Confirmed by cross-checking the parsed Umbreon PSA array against
PriceCharting's **independently published** PSA figures:

| Check | Array-derived | Published (roadmap §3.3) | Match |
|---|---:|---:|:--:|
| PSA total (Σ array) | 17,990 | 17,990 | ✓ |
| PSA-10 (last element) | 5,487 | 5,487 | ✓ |
| Gem rate = PSA10 / total | **30.5 %** | ≈ 30.5 % | ✓ |

`psa = [1, 2, 4, 15, 43, 161, 428, 2654, 9195, 5487]` → `5487 / 17990 = 0.3049`.
CGC is a **separate** series: `cgc = [0,0,0,1,0,2,16,122,259,366]` → `366 / 766 = 0.4778`
(never folded into the PSA rate). Test: `test_index_map_pins_last_element_as_grade_10_via_published_totals`.

## The F.1 set — published sourced gem rates (roadmap §3.3, for reference)

All four F.1 cards carry `VGPC.pop_data` in initial HTML (0 credits). Only Umbreon's full PSA
array is exercised as a committed **fixture** here
(`tests/fixtures/comps/pricecharting_pop_umbreon_ex_161.html`); the other three rows are the
roadmap's published totals, recorded for when a live capture is operator-approved:

| Card | Set | PSA total | PSA-10 | Sourced PSA-10 gem rate |
|---|---|---:|---:|---:|
| Umbreon ex #161 | Prismatic Evolutions | 17,990 | 5,487 | 30.5 % (fixture-verified) |
| Charizard ex #199 | Scarlet & Violet 151 | 97,426 | 27,631 | ≈ 28.4 % (published) |
| Pikachu ex #238 | Surging Sparks | 27,298 | 9,263 | ≈ 33.9 % (published) |
| Sylveon ex #156 | Prismatic Evolutions | 11,401 | 3,320 | ≈ 29.1 % (published) |

A tight 28–34 % band — but a **population** rate, a broad proxy over *all* graded submissions,
not a specific-copy prediction. That is exactly why grading EV stays capped at PAPER_BUY.

## Gem-rate evidence ledger (`data/poke/gem_rates.jsonl`, gitignored)

Append-only, idempotent by a sha256 `entry_id` over (asset_key, grader, source_url,
capture_date, formula, label). Row shape:

```json
{"entry_id": "…", "kind": "gem_rate", "asset_key": "umbreon_ex_161_raw_nm",
 "grader": "PSA", "counts_by_grade": {"1": 1, …, "10": 5487},
 "gem_rate": 0.3049, "gem_rate_formula": "PSA10 / total PSA population",
 "label": "sourced", "source": "pricecharting_pop",
 "source_url": "https://www.pricecharting.com/game/…/umbreon-ex-161",
 "capture_date": "2026-07-06", "sample_size": 17990, "sample_floor": 300, "status": "ok",
 "basis": "PriceCharting PSA population census (monthly), pop-blob sourced"}
```

`label` ∈ `sourced | operator_assumption`. `gem_rate_formula` is **grader-specific** — a CGC
row stores `CGC10 / total CGC population`, never a PSA figure. `sample_floor` records the floor
the row was captured against, so read-time provenance judges sufficiency against **that**, not
the current default. A sourced row is only written **above** its floor (below → `record_sourced`
raises; the operator records an assumption instead).

## Surfaces (all verified in the network-mocked suite)

- **Parser** `independent_sources.pricecharting_pop_from_html` — extracts `VGPC.pop_data`;
  missing / malformed / challenge / grader-absent / nonnumeric all degrade honestly (no crash,
  no guess). `PriceChartingPopSource.fetch_pop` fetches the same 0-credit detail page (plain
  requests; **no PPT client** — asserted).
- **CLI** `edge_cli gem-rate record | record-assumption | list | show`. `record` is gated on
  `poke.independent_sources` + `--yes`, prints `credits_spent=0`, blocks below floor / on
  absent grader; `record-assumption` / `list` / `show` are network-free.
- **Read endpoint** `GET /api/poke/grading-ev/<raw_asset_key>` — ledger-only, 0 network,
  `capped_at: PAPER_BUY`, `gem_rate_provenance` (label + sample-size status), break-even +
  sensitivity. A gem rate + comps but **no verified entry** → blocks on the entry (WATCH,
  never a buy).
- **Provenance fix (F carry-over):** graded PriceCharting `basis` now persists the grade-cell
  note (`PriceCharting PSA 10 column (PSA-exact)` / `…Grade 9 column (grader-agnostic proxy)`),
  not the generic `pricecharting graded page` — PSA-exact vs proxy is ledger-standalone.

## Tests

New: `test_poke_gem_rates.py` (21), `test_poke_pop_data.py` (13), `test_poke_grading_ev_api.py`
(7), plus gem-rate CLI (9) in `test_poke_edge_cli.py`, break-even/sensitivity (8) in
`test_poke_grading_ev.py`, and basis-provenance (2) in `test_poke_asset_sources.py`. Full suite:
**1012 passed** (baseline 952, +60), network-mocked, 0 PPT credits.

## What this build does and does NOT do

- **Does:** source a gem rate honestly (0 credits) or block/label an assumption; expose
  break-even + sensitivity; keep grading EV PAPER-capped; keep every read ledger-only.
- **Does NOT (by design / boundary):** no live pop capture without operator go-ahead; no
  auto-promotion off a gem rate or comp (verified entry is the only buy wire — unchanged);
  no broad pop crawl; no read-path live fetch; no PPT calls; no H–M work.

## Next step (operator-gated)

A **live** `gem-rate record --asset-key <raw> --source pricecharting --yes` (with
`poke.independent_sources: true`) captures the real PSA/CGC pop for a mapped asset at 0 PPT
credits and appends a `sourced` ledger row. Deferred to explicit operator go-ahead; this doc
records the fixture-verified behavior so the live run is a one-command confirmation.
