# Phase F.1 — Independent-Source Generalization Result

**Date:** 2026-07-06
**Status:** PASS — the independent PriceCharting layer is proven **not overfit to Umbreon**:
a batch 0-PPT-credit record + gap matrix now spans **four cards across three sets**, and the
Umbreon rows remain a **true cross-source validation** (independent PriceCharting vs recorded
PPT). **0 PPT credits.**
**Spec:** [2026-07-06-phase-f1-independent-source-generalization-design.md](../superpowers/specs/2026-07-06-phase-f1-independent-source-generalization-design.md)
**Follows:** [Phase F result](phase-f-independent-source-result-2026-07-06.md) (Umbreon-only).

## Why this doc exists (gitignored ledger)

`data/poke/price_history.jsonl` is **gitignored** (untracked), so the rows recorded below are
not committed anywhere in git. **This doc is the durable, reviewable evidence** that the F.1
independent-source ledger writes happened — mirroring the Phase F result doc.

## Recorded rows (0 PPT credits — live PriceCharting via `record-asset-comps --refresh-independent --yes`)

Command (`poke.independent_sources: true` for the run; reset to `false` at close):

```text
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli record-asset-comps \
  --refresh-independent \
  --assets umbreon_ex_161_raw_nm,umbreon_ex_161_psa10,umbreon_ex_161_psa9,\
charizard_ex_199_151_raw_nm,charizard_ex_199_151_psa10,charizard_ex_199_151_cgc10,\
pikachu_ex_238_ss_raw_nm,pikachu_ex_238_ss_psa9,sylveon_ex_156_raw_lp --yes
```

Every fetch was a plain `requests` GET of a PriceCharting **detail** page (browser UA) and spent
**0 PPT credits** (PriceCharting is not PPT). Batch summary: **4 recorded, 3 already-recorded
(Umbreon, idempotent), 2 honest skips**.

### New independent comps written this run

| asset_key | class | comp | conf | source | capture_date | ledger item_key | basis |
|---|---|---:|---|---|---|---|---|
| `charizard_ex_199_151_raw_nm` | raw | $399.99 | low | pricecharting | 2026-07-06 | `scarlet & violet 151\|charizard ex 199\|199\|\|nm` | pricecharting uncorroborated |
| `charizard_ex_199_151_psa10` | graded | $1,575.00 | low | pricecharting | 2026-07-06 | `scarlet & violet 151\|charizard ex 199\|199\|psa10\|` | pricecharting graded page |
| `pikachu_ex_238_ss_raw_nm` | raw | $325.50 | low | pricecharting | 2026-07-06 | `surging sparks\|pikachu ex 238\|238\|\|nm` | pricecharting uncorroborated |
| `pikachu_ex_238_ss_psa9` | graded | $330.14 | low | pricecharting | 2026-07-06 | `surging sparks\|pikachu ex 238\|238\|psa9\|` | pricecharting graded page |

Source URLs: `https://www.pricecharting.com/game/pokemon-scarlet-&-violet-151/charizard-ex-199`
and `https://www.pricecharting.com/game/pokemon-surging-sparks/pikachu-ex-238`.

### Honest skips (recorded nothing — by design)

| asset_key | outcome | why |
|---|---|---|
| `charizard_ex_199_151_cgc10` | `skipped_no_source` | **CGC 10 has no exact PriceCharting cell** (only PSA 10 has a graded-10 column) → honest `no_match`, never a nearest-cell guess. |
| `sylveon_ex_156_raw_lp` | `skipped_condition` | **PriceCharting "Ungraded" is not condition-exact**; a non-NM (LP) raw is not auto-recorded off it (would over-value LP). 0 network — the guard fires before the fetch. |

### Controls (Phase F rows, unchanged — idempotent already-recorded)

`umbreon_ex_161_raw_nm` $1,425.00 · `umbreon_ex_161_psa10` $7,013.08 · `umbreon_ex_161_psa9`
$1,554.05 (all `pricecharting`, `low`, 2026-07-06). Umbreon also keeps its recorded `ppt_cards`
references (raw $1,528.09, PSA10 $6,925.50, 2026-07-05) — the only PPT references in the ledger.

## Gap matrix (`divergence-audit --local --matrix`, 0 PPT credits)

```text
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli divergence-audit --local --matrix \
  --assets <the nine F.1 assets> --json
```

| asset | class / id | ours (source, date) | ppt ref (date) | delta | classification | cross-source |
|---|---|---|---|---:|---|:--:|
| `umbreon_ex_161_raw_nm` | raw / NM | $1,425.00 (pricecharting, 07-06) | $1,528.09 (07-05) | 7.23% | `agree` | **yes** |
| `umbreon_ex_161_psa10` | graded / psa10 | $7,013.08 (pricecharting, 07-06) | $6,925.50 (07-05) | 1.26% | `agree` | **yes** |
| `umbreon_ex_161_psa9` | graded / psa9 | $1,554.05 (pricecharting, 07-06) | — | — | `no_external_reference` | no |
| `charizard_ex_199_151_raw_nm` | raw / NM | $399.99 (pricecharting, 07-06) | — | — | `no_external_reference` | no |
| `charizard_ex_199_151_psa10` | graded / psa10 | $1,575.00 (pricecharting, 07-06) | — | — | `no_external_reference` | no |
| `charizard_ex_199_151_cgc10` | graded / cgc10 | — (unsupported grade) | — | — | `no_external_reference` | no |
| `pikachu_ex_238_ss_raw_nm` | raw / NM | $325.50 (pricecharting, 07-06) | — | — | `no_external_reference` | no |
| `pikachu_ex_238_ss_psa9` | graded / psa9 | $330.14 (pricecharting, 07-06) | — | — | `no_external_reference` | no |
| `sylveon_ex_156_raw_lp` | raw / LP | — (condition-skip) | — | — | `no_external_reference` | no |

`failed: false`, `credits_spent: 0`, `material_count: 0`.

## Live ledger state — stated plainly

- **Only Umbreon has PPT references** (raw + PSA10, recorded in Phase F). Minting a PPT reference
  is a **billed** call, out of F.1 scope — so the three new cards, honestly, have **no external
  reference** and classify `no_external_reference`. That is a **documented limitation, not a
  failure**: a material *unexplained* divergence is the only failing outcome, and none occurred.
- The two Umbreon rows are a **genuine cross-source validation** — an independent PriceCharting
  number agreeing with a recorded PPT number within tolerance (7.23% raw, 1.26% PSA10). This is
  what F.1 generalizes: the same honest pipeline now runs across three sets.
- **`raw_condition_difference` and `grade_mapping_difference` did NOT fire on live data** — raw
  LP is guarded from recording, and the new cards lack PPT references. They are **demonstrated
  via constructed observations in tests** (`tests/test_poke_f1_generalization.py`), and are in
  the matrix vocabulary + logic so they *can* fire — labeled honestly, never presented as
  live-observed.

## What this PASS does and does not prove

- **Proves:** the independent PriceCharting adapters + batch recorder + gap matrix generalize
  cleanly to **four cards across three sets** (Prismatic Evolutions, Scarlet & Violet 151,
  Surging Sparks) at **0 PPT credits**; unsupported grades and non-NM raw degrade **honestly**;
  the wrong-slug guard was verified against all four real pages (extracts #161/#199/#238/#156).
- **Does NOT prove / unchanged by design:** all assets remain **WATCH** — a comp is not a buy;
  no verified entry exists; the E verified-entry route is untouched; PPT external mode stays
  audit-only; no PPT credits were spent; no broad catalog import happened.

## Config note

`poke.independent_sources` was set `true` only for the batch run and **reset to `false`** at
close (verified). Read endpoints never fetch regardless (read-first stays offline). The PPT API
key was not used on this path (0 PPT credits).
