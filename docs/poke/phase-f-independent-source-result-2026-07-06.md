# Phase F — Independent Sold-Source Recording + Cross-Source Audit Result

**Date:** 2026-07-06
**Status:** PASS — independent PriceCharting comps recorded; `divergence-audit --local`
is now a **true cross-source validation** (0 PPT credits).
**Spec:** [2026-07-05-phase-f-independent-sold-source-validation-design.md](../superpowers/specs/2026-07-05-phase-f-independent-sold-source-validation-design.md)
**Follows:** [edge-asset-divergence-audit-result-2026-07-05.md](edge-asset-divergence-audit-result-2026-07-05.md)
(whose "Remaining next step" was exactly this — an independent local sold source so the
local audit stops comparing PPT-against-PPT).

## Why this doc exists (gitignored ledger)

`data/poke/price_history.jsonl` is **gitignored** (untracked), so the recorded rows below are
not committed anywhere in git. **This doc is the durable, reviewable evidence** that the Phase F
independent-source ledger writes happened — mirroring the prior audit-result docs.

## Recorded rows (0 PPT credits — live PriceCharting via `record-asset-comp --refresh-independent`)

Command (per asset), with `poke.independent_sources: true`:

```text
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli record-asset-comp \
  --asset-key <asset> --refresh-independent
```

Each fetch hit `https://www.pricecharting.com/game/pokemon-prismatic-evolutions/umbreon-ex-161`
(plain requests, browser UA) and spent **0 PPT credits** (PriceCharting is not PPT).

| asset_key | asset_class | comp | conf | source | capture_date | ledger item_key | basis |
|---|---|---:|---|---|---|---|---|
| `umbreon_ex_161_raw_nm` | raw | $1,425.00 | low | pricecharting | 2026-07-06 | `prismatic evolutions\|umbreon ex 161\|161\|\|nm` | pricecharting uncorroborated |
| `umbreon_ex_161_psa10` | graded | $7,013.08 | low | pricecharting | 2026-07-06 | `prismatic evolutions\|umbreon ex 161\|161\|psa10\|` | pricecharting graded page |
| `umbreon_ex_161_psa9` | graded | $1,554.05 | low | pricecharting | 2026-07-06 | `prismatic evolutions\|umbreon ex 161\|161\|psa9\|` | pricecharting graded page |

Source URL for all three: `https://www.pricecharting.com/game/pokemon-prismatic-evolutions/umbreon-ex-161`.

**Confidence is `low` by design (locked).** A single independent sold-derived source is `low`
regardless of cell — the PSA-exact `manual_only_price` (PSA 10) included. Confidence is **not**
lifted by an eBay ask (context, not corroboration). Cross-source validation is supplied by the
divergence audit agreeing (below), **not** by the comp's confidence field.

**Provenance note (honest):** the persisted `basis` for the graded rows is
`pricecharting graded page`. The PSA-exact vs grader-agnostic distinction (`psa10` → the
PSA 10 column, PSA-exact; `psa9` → the generic Grade 9 column, **grader-agnostic proxy**) is
recoverable from `grade_key` + the documented cell map, and is surfaced in the CLI/edge-packet
row `detail` — it is not encoded in the persisted `basis` string. (Follow-up: persist the
grade-cell note as `basis` for full ledger-standalone provenance.)

## Cross-source `divergence-audit --local` result (0 PPT credits)

Command:

```text
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli divergence-audit --local \
  --assets umbreon_ex_161_raw_nm,umbreon_ex_161_psa10,umbreon_ex_161_psa9
```

| subject | ours (source) | theirs (`ppt_cards`) | delta | category | cross-source validated |
|---|---:|---:|---:|---|:--:|
| `umbreon_ex_161_raw_nm` | $1,425.00 (pricecharting) | $1,528.09 | 7.23% | `agree` | **yes** |
| `umbreon_ex_161_psa10` | $7,013.08 (pricecharting) | $6,925.50 | 1.26% | `agree` | **yes** |
| `umbreon_ex_161_psa9` | $1,554.05 (pricecharting) | — | — | `no_external_reference` | no |

`failed: false`, `credits_spent: 0`, `hard_stopped: false`.

## Decision — PASS

- The raw single and the PSA 10 slab now compare a **genuinely independent** local sold source
  (PriceCharting) against the recorded `ppt_cards` reference and **agree within the 20%
  tolerance** (7.23% and 1.26%). This is the true cross-source validation the 2026-07-05 audit
  could not claim (that one was PPT-against-PPT consistency only).
- `umbreon_ex_161_psa9` honestly reports `no_external_reference` — no `ppt_cards` PSA 9 comp was
  ever recorded, so there is nothing to cross-check. This is correct behavior, not a failure; a
  material **unexplained** divergence is the only thing that fails the audit, and none occurred.

## What this PASS does and does not prove

- **Proves:** a non-PPT, sold-derived local comp now exists for these singles/slabs, and the
  `--local` audit numerically cross-validates it against the PPT reference at 0 credits.
- **Does NOT prove / unchanged by design:** these assets remain **WATCH** — a comp is not a
  buy. No verified entry exists, so nothing is live/paper-eligible (the E verified-entry route is
  untouched). PPT external mode stays audit-only. No broad catalog import happened.

## TCGplayer render probe (Task 9) — CONDITIONAL, resolved to "keep the shell"

Operator-approved one-off headless render probe of the TCGplayer product page for the same
card (`https://www.tcgplayer.com/product/610516`, id 610516 — the mapped `tcgplayer_id`). Run
via the session's browser tool (no scanner dependency installed).

**Fetchability: CLEAN.** The page renders a parseable price with **no bot-wall / challenge** —
title hydrated to "Umbreon ex - 161/131 - SV: Prismatic Evolutions", `challengePresent: false`.
So TCGplayer is renderable (Playwright would work).

**But two findings make it the wrong source to wire — so Playwright was NOT installed:**

1. **TCGplayer is not independent of PPT.** The tracked printing's TCGplayer market price is
   **Holofoil = $1,528.09**, *identical to the cent* to the recorded PPT (`ppt_cards`) comp
   $1,528.09. PPT resells the TCGplayer market number, so wiring TCGplayer as an "independent
   cross-check" is circular — it is the same source. The genuinely independent source is
   **PriceCharting** ($1,425.00, ~7% off), whose distinct methodology is what makes the
   cross-source audit meaningful.
2. **The naive parser grabs the wrong printing.** The page carries ~10 "Market Price" strings
   (the tracked printing plus a "related products" rail: $129.40, $0.85, …). A first-match
   regex (`_tcg_market_price` as built in Task 8) returns **$750.00** — an adjacent/wrong-context
   value, not the tracked Holofoil $1,528.09. A trustworthy TCGplayer adapter would have to
   target the specific printing's market node; the first-"Market Price" heuristic is unreliable.

**Decision (operator, 2026-07-06): keep the built `blocked` shell; do not install Playwright.**
`TcgPlayerRenderedSource` remains built + unit-tested but dormant (returns `blocked` with no
`render` callable). No `playwright` dependency, no chromium download. The `_tcg_market_price`
first-match heuristic is a **latent bug** that is harmless while the shell is dormant — it must
be replaced with printing-specific targeting before TCGplayer is ever enabled live. Phase F's
required PriceCharting gate is unaffected and complete.

## Config note

`poke.independent_sources: true` was set in the gitignored `config.yaml` to permit the CLI live
fetch. The flag defaults to `false`; read endpoints never fetch regardless (read-first stays
offline). The PPT API key was not used on this path (0 PPT credits).
