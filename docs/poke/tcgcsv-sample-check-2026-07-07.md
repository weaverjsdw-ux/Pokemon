# TCGCSV Sample-Check Result — 2026-07-07

**Status:** FAIL
**Gate:** fixed >= 5 raw pairs, <= 2% max diff (spec T1, not per-run tunable)
**Credits:** 0 PPT (reads only already-recorded `ppt_cards` rows; TCGCSV is free/keyless)
**Provenance:** the machinery (`tcgcsv_check.build_pairs` + `sample_check`, wired as the
`tcgcsv-check` CLI) is verified against mocked fixtures in the test suite. This specific
result runs that same code against the REAL asset catalog + REAL price-history ledger +
a live TCGCSV capture taken during this build session (group `23821` "SV: Prismatic
Evolutions" fetched from `tcgcsv.com` 2026-07-07; `productId 610516` → one `Holofoil`
row, `marketPrice $1528.09`) — not a fresh `poke.tcgcsv: true` CLI invocation (the flag
stays `false` in committed config; a routine live re-run is the operator's one-command
next step once more `ppt_cards` raw comps are recorded).

## Verdict

insufficient sample: n=1 below minimum 5

- n = 1
- max diff = 0.00%

## Pairs compared

| asset_key | tcgplayer_id | ppt_price | tcgcsv_price | diff_pct |
|---|---|---:|---:|---:|
| umbreon_ex_161_raw_nm | 610516 | $1528.09 | $1528.09 | 0.00% |

## Skipped (honest, never guessed)

_none_

## Scope note

Only **raw** assets are eligible for a pair. TCGCSV `marketPrice` is an ungraded-card price with no graded-slab (PSA/CGC) counterpart in the catalog — comparing a graded asset's `ppt_cards` comp (a different quantity, e.g. a PSA10 smart price) against it would fail on tolerance for a reason that has nothing to do with TCGCSV-vs-PPT agreement. Graded assets are honestly skipped, never compared.
