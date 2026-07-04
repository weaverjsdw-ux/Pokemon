# Live Slickdeals Smoke Approval Packet - 2026-07-04

## Purpose

Run one isolated live Slickdeals discovery pass to validate that the Slice 6B resolver can resolve current Slickdeals thread markup to merchant pages and that the pipeline classifies every candidate honestly.

## What Will Touch Network

- `slickdeals.net` search/thread pages through the discovery pipeline.
- Resolved merchant pages from Slickdeals candidates.

## What Will Not Happen

- No PPT calls.
- No credit spend.
- No cart, checkout, login, proxy polling, or bot-wall evasion.
- No scheduler registration.
- No `comps.engine` cutover.
- No remote push.

## Isolation

- State database: `%TEMP%\poke-smoke\state.db`
- Output root: `%TEMP%\poke-smoke`
- Repo `data/poke/` remains untouched by this smoke.

## Command

```powershell
$env:POKEMON_SCANNER_STATE_DB = "$env:TEMP\poke-smoke\state.db"
.\.venv\Scripts\python.exe -m scanner.discovery.pipeline `
  --once --sources slickdeals --out "$env:TEMP\poke-smoke"
Remove-Item Env:\POKEMON_SCANNER_STATE_DB
```

## Success Criteria

- Exit code `0`, unless golden intentionally halts dashboard writing while preserving JSON evidence.
- Manifest count reconciliation holds.
- Every candidate has exactly one `outcomes[]` terminal bucket and reason.
- At least one Slickdeals candidate shows a resolver method like `slickdeals_resolve:u2_param+page_fetch`, `slickdeals_resolve:direct_href+page_fetch`, or `slickdeals_resolve:redirect_chain+page_fetch`, or every candidate honestly explains why it could not resolve.
- No silent drops.
- No PPT credits used.

## Decision After Run

- If resolver selectors work and merchant pages parse: keep 6B, consider scheduler dry-run.
- If resolver selectors drift: capture one live thread fixture and make a narrow selector-repair plan.
- If merchant pages are mostly JS shells/blocked/price_mismatch: keep the lane as honest low-yield and prioritize eBay keyset or catalog coverage instead of loosening parsers.
- If Ring-2/Ring-3 candidates verify but land in `no_comp`: next feature slice is ad-hoc non-catalog comps, not a parser change.
