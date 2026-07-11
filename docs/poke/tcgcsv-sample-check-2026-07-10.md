# TCGCSV Sample-Check Result — 2026-07-10

**Status:** PASS
**Gate:** fixed >= 5 raw pairs, <= 2% max diff (spec T1, not per-run tunable)
**Credits:** 0 PPT (reads only already-recorded `ppt_cards` rows; TCGCSV is free/keyless)

## Verdict

5 pairs all within 2%

- n = 5
- max diff = 0.11%

## Pairs compared

| asset_key | tcgplayer_id | ppt_price | tcgcsv_price | diff_pct |
|---|---|---:|---:|---:|
| umbreon_ex_161_raw_nm | 610516 | $1514.25 | $1514.25 | 0.00% |
| charizard_ex_199_151_raw_nm | 517045 | $401.29 | $400.85 | 0.11% |
| pikachu_ex_238_ss_raw_nm | 590027 | $362.30 | $362.30 | 0.00% |
| sylveon_ex_156_raw_nm | 610511 | $558.57 | $558.57 | 0.00% |
| leafeon_ex_144_raw_nm | 610499 | $332.86 | $332.86 | 0.00% |

## Skipped (honest, never guessed)

| asset_key | reason |
|---|---|
| umbreon_ex_161_psa10 | graded asset — TCGCSV marketPrice is ungraded-only, not comparable to a graded ppt_cards comp |

## Scope note

Only **raw** assets are eligible for a pair. TCGCSV `marketPrice` is an ungraded-card price with no graded-slab (PSA/CGC) counterpart in the catalog — comparing a graded asset's `ppt_cards` comp (a different quantity, e.g. a PSA10 smart price) against it would fail on tolerance for a reason that has nothing to do with TCGCSV-vs-PPT agreement. Graded assets are honestly skipped, never compared.
