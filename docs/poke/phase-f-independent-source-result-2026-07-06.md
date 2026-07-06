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

## Config note

`poke.independent_sources: true` was set in the gitignored `config.yaml` to permit the CLI live
fetch. The flag defaults to `false`; read endpoints never fetch regardless (read-first stays
offline). The PPT API key was not used on this path (0 PPT credits).
