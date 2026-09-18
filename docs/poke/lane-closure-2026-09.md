# Pokémon singles lane — closure note (2026-09)

**Status: CLOSED by operator decision, 2026-09-17 — not because it failed.**
The lane works and is measurably covered. It is being stood down because attention
moved elsewhere, so this note is written for whoever picks it up cold, not as a
handover to an in-flight successor. There is no next phase and none is proposed.

## What the singles lane does today

* **Catalog** — `data/poke/assets.yaml`, **57** raw/graded assets across Prismatic
  Evolutions, Scarlet & Violet 151, Surging Sparks, Journey Together, Paldean
  Fates and Crown Zenith. Loaded and validated by
  `scanner/poke_api/catalog.py:load_assets` (a mis-specified asset is a hard load
  error, never a silent skip).
* **Comps** — live via `poke.independent_sources` (PriceCharting + TCGplayer,
  keyless, **0 PPT credits**), persisted to the append-only
  `data/poke/price_history.jsonl`. **51 of 57 assets carry a persisted comp**;
  6 are honest catalog gaps (below). Every read path afterwards is offline: the
  ledger is the source, not a live fetch.
* **API surface** — `/api/poke/assets`, `.../comp`, `.../history`, `.../momentum`,
  plus WATCH-grade opportunities via `poke_api/opportunities.build_asset_opportunity`.
  Assets are **never live-eligible**: there is no verified-entry buy wire for
  singles, so the decision is a fixed `WATCH` regardless of the numbers.
* **Discovery** — `scanner/discovery/assets_feed.py` (added at closure) feeds the
  catalog into the board and the pipeline behind `poke.singles_board`
  (**default off**). On: the sweep gains an `asset_watch` collection and a
  `Singles watch` dashboard section, and a discovered listing that matches exactly
  one asset becomes a real `DealRow` carrying its true `asset_class` /
  `condition` / `grade` / `grader`.

### The 6 catalog gaps are deliberate, not TODOs

| asset | why it has no comp |
| --- | --- |
| `charizard_ex_199_151_cgc10` | CGC 10 — unsupported-grade prover |
| `mamoswine_ex_174_jt_raw_nm` / `_psa10` / `_psa9` | PriceCharting page exposes five priced cells, not the six this file's verification bar requires → honest none |
| `sylveon_ex_156_raw_lp`, `umbreon_ex_161_raw_lp` | LP caveat-skip |

Several `assets.yaml` rows look wrong on purpose — they are fixtures that prove a
refusal path (the CGC-10 prover, the LP skips, the intentionally unmapped
`leafeon_ex_144` slug, the Phase-F.1 anti-overfit block). **Do not "fix" them.**

## What is deliberately NOT done, and why

* **No singles buy wire.** A raw/graded asset has no MSRP and no verified-entry
  price, so it is never a priced deal row on the catalog-sourced board — it is a
  WATCH record carrying a market comp. Giving it a `deal_price` would mean
  inventing the one number nobody has. A single only becomes a `DealRow` when a
  real listing at a real verified price is discovered for it.
* **No fuzzy matcher.** Rejected 2026-09-17. At this catalog size deterministic
  exact-id mapping is 100% precision. `assets_feed.match_asset` refuses an
  ambiguous title rather than guessing: raw NM and PSA 10 of one card share a
  name and are 10x different money, so with no grade/condition token in the title
  there is no evidence for either.
* **No guessed ids.** A missing `tcgplayer_id` / `tcgcsv_group_id` /
  `pricecharting_slug` is left absent. Absent is correct; a guess is a wrong number.
* **No catalog extension.** 57 assets is where it stops.
* **`set: "151"` in `data/products.yaml` was NOT renamed.** See below.

## The cross-catalog set-name join

`data/products.yaml` labels the set `"151"`; `data/poke/assets.yaml` labels it
`"Scarlet & Violet 151"`. A join comparing those strings drops the rows silently.

The fix is `scanner/setname.py` — a **comparison key, never a stored value**:

```python
set_identity("151") == set_identity("Scarlet & Violet 151") == "scarlet violet 151"
```

Renaming the catalog string was rejected on evidence: ledger identity
(`ledger.item_key`) is built from the catalog's own `set`, and
`price_history.jsonl` holds **8 observations keyed `set: "151"`** (the sealed
products) and **3 keyed `"Scarlet & Violet 151"`** (the singles). A rename — or
normalizing on the way into a row
— changes the item_key and orphans exactly the history the fix exists to protect.
Join on `set_identity`; persist what the catalog said.

## Operational gotchas — read these before running anything

**PriceCharting throttles a burst, and the failure is SILENT and LOSSY.**
A 45-asset `record-asset-comps --refresh-independent --yes` run recorded only 19.
The rest degraded to `skipped_no_source` although the same assets resolved fine
seconds later in a small batch. A throttled fetch records nothing rather than
erroring, so a big run quietly under-records and the summary still looks fine.

* ✗ one `--assets <45 keys>` run
* ✓ chunks of ~6 keys with a ~12s pause, then **audit the ledger**: count rows in
  `data/poke/price_history.jsonl` by `item_key`. A batch summary is not proof of
  coverage.

**Never rewrite `config.yaml` with a PowerShell pipeline.**
`(Get-Content f) -replace ... | Set-Content f -Encoding utf8` prepends a UTF-8
BOM; PyYAML then parses the first key as `﻿locations` and the app reports
`locations.home and locations.work are required`. **`config.yaml` is gitignored —
there is no git backup.** Use an editor for a one-token change. Diagnose a
suspected BOM with `head -c 12 config.yaml | xxd`.

## Known data defect (reported, not fixed)

Five comped singles carry an eBay **sealed**-search page as their comp
attribution URL, written by the `ppt_cards` source:
`umbreon_ex_161_raw_nm`, `sylveon_ex_156_raw_nm`, `charizard_ex_199_151_raw_nm`,
`pikachu_ex_238_ss_raw_nm`, `leafeon_ex_144_raw_nm`. The price is a single's
price; the URL attributes a sealed search, so it does not attribute the number it
accompanies. For `umbreon_ex_161_raw_nm` the mis-attributed $1514.25 is also the
latest non-tcgcsv observation, so it displaces the correctly-attributed
PriceCharting $1425.00 as the served headline.

Impact is bounded: these rows carry `confidence: low`, so `sweep._provenance`
marks them `est` and the STOP gate forbids them from minting a STEAL. Left as-is
— the ledger is append-only and rewriting history was out of scope. Anyone
reopening this should re-record those five from an exact source before trusting
the headline.

## Where things live

| Thing | File |
| --- | --- |
| Asset catalog + validation | `scanner/poke_api/catalog.py`, `data/poke/assets.yaml` |
| Ledger identity (read + write must agree) | `scanner/poke_api/history.py:asset_identity` |
| Read-first asset comp (offline) | `scanner/poke_api/lab.py:resolve_asset_comp_row` |
| WATCH classification | `scanner/poke_api/opportunities.py:classify_asset_trade` |
| Discovery feed + listing match | `scanner/discovery/assets_feed.py` |
| Cross-catalog set join | `scanner/setname.py` |
| Tests for the above | `tests/test_poke_singles_feed.py` |
| Independent comp sources | `scanner/poke_api/independent_sources.py` |
