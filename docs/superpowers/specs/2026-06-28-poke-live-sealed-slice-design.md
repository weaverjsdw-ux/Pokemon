# `/poke` First Slice — Live Sealed Deal Board — Design Spec

**Date:** 2026-06-28
**Status:** Approved design, ready for implementation plan
**Repo:** `Pokemon-main` (package `scanner/`, discovery subsystem `scanner/discovery/`)
**Program context:** first vertical slice of the A–E roadmap
(`2026-06-28-resale-engine-program-roadmap.md`). Pulls in only the Phase-A bit it needs
(`ppt_id` seeding); everything else is added when a consumer arrives.

---

## 1. Purpose

The `/poke` deterministic core (schema, ledger, scorer, renderer, golden test) exists but only
renders a hand-authored **fixture** today. This slice makes it produce a **real dashboard from
live data**, sealed-only: for each sealed product in the catalog, fetch a live comp (PPT v2 by
`ppt_id`, falling back to eBay/PriceCharting), compute the fee-adjusted margin + verdict + lens
tags, and render a dated dashboard ranking the sealed catalog by **appreciation headroom** —
"which sealed boxes are most worth grabbing at retail right now." It is the on-ramp to full
`/poke` discovery, **not** the market-wide web sweep (that is Phase B).

The CLI built here (`python -m scanner.discovery.sweep`) becomes the `scan`-mode engine the
Phase-B `/poke` OPENER later drives — so it is forward-compatible with the full pipeline.

## 2. Buy basis

Deal price = **MSRP** (config `poke.buy_basis: "msrp"`). For hyped sealed, MSRP vs a 2–4× live
comp *is* the signal (Prismatic ETB: $49.99 MSRP vs $199.14 live comp). An optional
`"observed"` basis (last-seen retail price from the scanner's state) is left as a future hook,
not built here.

## 3. Architecture

**Approach: extend the discovery subsystem in place.** One new module + a CLI, reusing everything
already built. No change to the automated scan loop.

```text
scanner/discovery/
  sweep.py     (NEW) build_sealed_sweep(cfg, comp_lookup, *, meta) -> sweep dict; + __main__ CLI
  golden.py    (NEW) golden_check(html, min_rows) -> list[str]   # moved out of the test so CLI + test share it
  schema.py    (reuse) DealRow + STOP gate
  score.py     (reuse) assign_badges / lens_tags / compute_pct_off
  render.py    (reuse) render_sweep
  ledger.py    (reuse) append_observation
scanner/market.py   (small add) sealed quote carries sourceUrl (tcgPlayerUrl) for attribution
scanner/config.py   (add) poke.buy_basis, poke.daily_credit_cap
data/products.yaml  (data task) seed ppt_id for the sealed catalog
```

### 3.1 `build_sealed_sweep(cfg, comp_lookup, *, event, sweep_id, captured_at) -> dict`

Pure assembly (no I/O; `comp_lookup` is injected). For each **selected sealed product**
(`config.selected_products(cfg)`):
1. `comp_row = comp_lookup(product_key, product)` — a quote row from the live market client.
2. `comp, comp_confidence = market.comp_from_row(comp_row)`. **If `comp is None`, skip the product**
   (not rankable) and increment a `no_comp` counter — never fabricate a row.
3. `deal_price = _msrp(product)` (parse `product["msrp"]`; skip + count if absent/unparseable).
4. **Provenance mapping (STOP-gate-safe):**
   - `source_url = comp_row.get("sourceUrl", "")` (PPT sealed → `tcgPlayerUrl`).
   - If `source_url` is present **and** `comp_confidence in {high, medium}` → `price_confidence="verified"`.
   - Else → `price_confidence="est"`, `derivation_method = comp_row source/basis`, `confidence_detail`
     set (so an EST row satisfies the gate and never becomes a confirmed STEAL).
5. Build a `DealRow`: `asset_class="sealed"`, `category` from `product["type"]`
   (ETB→`sealed-etb`, Booster Bundle→`sealed-bundle`, else `sealed-other`), `market_comp=comp`,
   `pct_off=score.compute_pct_off(deal_price, comp)`, `retailer="MSRP"`, `captured_at`, `set`,
   `comp_confidence`.
6. Populate derived fields via the **existing scorer/backbone** (dashboard == scanner):
   `badges = score.assign_badges(row, cfg)`, `lens_tags = score.lens_tags(row, cfg)`,
   `scanner_verdict = main.verdict_for_alert(cfg, product, deal_price_str, comp_row)`.
7. Run `schema.assert_sweep(rows)` (STOP gate) before returning.

Returns a sweep dict the renderer already eats: `{event, sweep_id, captured_window, notes, deals[],
promo_codes: [], bundled_offers: [], watchlist_results: [], sources[], manifest fields}`.
`sources[]` records the comp sources used (PPT / fallback) + the `no_comp` count.

### 3.2 CLI — `python -m scanner.discovery.sweep [--out DIR] [--event NAME]`

1. `cfg = config.load()`.
2. Build a **live `comp_lookup`**: wraps `market.market_client_from_config(cfg)`; per product calls
   `.estimate(product_key, product, checked_at)`; **credit guard** (§5) short-circuits to the resale
   fallback when the daily cap/remaining is exhausted. One comp call per product.
3. `sweep = build_sealed_sweep(cfg, comp_lookup, ...)`.
4. Persist: write `data/poke/<sweep_id>.json` + `<sweep_id>.manifest.json`; append the **observation
   ledger** (`data/poke/price_history.jsonl`) — a `market_comp` line per product with a comp, and a
   `deal` line per rendered deal row (idempotent via `ledger.append_observation`).
5. Render `dashboards/<date>-sealed.html` via `render.render_sweep`.
6. Run `golden.golden_check(html, cfg.poke.min_rows)`; **HARD FAIL halts** (don't ship a bad
   dashboard) — exit non-zero, print the failures.
7. Print a summary: products scanned, comped, skipped(no_comp), steals, credits consumed, output path.

## 4. Data flow

```text
selected sealed products
  → live comp (PPT by ppt_id → fallback)        [market.py]
  → margin / verdict / pct_off / badges / lenses [margin, verdict, score.py]
  → DealRow → STOP gate                          [schema.py]
  → sweep dict → render + persist + ledger        [render.py, ledger.py]
  → golden check (hard-fail halts)                [golden.py]
  → dashboards/<date>-sealed.html
```

## 5. Credit governance

- One comp call/product/run, `limit=1` by id ⇒ ~13 credits/run — trivial vs Free's 100/day.
- `poke.daily_credit_cap` (default 90): the live `comp_lookup` tracks credits consumed this run
  (from `metadata.apiCallsConsumed` / the `X-API-Calls-Consumed` header, read via the client) and,
  when the cap/`X-RateLimit-Daily-Remaining` is exhausted, short-circuits remaining products to the
  resale fallback (labeled) instead of erroring. Graceful degradation, same doctrine as a missing key.
- No speculative full-catalog enrichment; no history/eBay includes in this slice (sealed price only).

## 6. `ppt_id` seeding (data task, folded in)

Seed `ppt_id` for the sealed catalog per `docs/poke/ppt-id-seeding.md` (exact `tcgPlayerId`, verify
the standalone variant, exclude bundles/cases/exclusives). Already done: `prismatic_evolutions_etb →
593355`. Products without a verified `ppt_id` fall back to eBay/PriceCharting comps (labeled), so the
board still works — it is just sharper where seeded. Record NOT_FOUND for products absent from PPT.

## 7. Scope fence (this slice)

**In:** sealed only; MSRP buy basis; live comps (PPT + fallback); real dashboard + ledger + manifest;
`ppt_id` seeding; the reusable `golden_check`. **Out (each lands with its consumer):** web acquisition
beyond the catalog (B); graded/raw comps (A-when-B-needs); momentum/velocity (A; noise on Free); the
OPENER persona + `/poke` command + mode dispatch (B); scheduling/alerting (E); inventory ledger (D).

## 8. Error handling

- PPT down / 401 / 429 / quota → `MarketFallbackClient` falls through to resale; never errors the run.
- No usable comp for a product → skipped from deals + counted (not a fabricated row).
- No `source_url` or weak comp → row is `est` (never a confirmed STEAL); STOP gate enforces it.
- Empty/too-small sweep → `golden_check` hard-fails on the `min_rows` floor (acquisition-failure canary).
- STOP-gate violation → `assert_sweep` raises before any HTML is written.

## 9. Testing

- `tests/test_poke_sweep.py`:
  - `build_sealed_sweep` with a small fake catalog + mocked `comp_lookup` (verified-with-URL, est-no-URL,
    and no-comp cases) → sweep dict shape; no-comp product skipped + counted; est mapping correct;
    every deal row's `badges`/`lens_tags` equal the scorer (pinning = dashboard==scanner); STOP gate passes.
  - CLI smoke: `main(["--out", tmp])` with a monkeypatched live client (no network) → writes JSON +
    manifest + dashboard; `golden_check` returns `[]`; ledger appended.
- `tests/test_poke_golden.py`: import `golden_check` from `scanner.discovery.golden` (moved out of the
  test); existing golden assertions unchanged.
- **Manual live spot-check** (documented, not in CI): `python -m scanner.discovery.sweep` → dashboard
  shows Prismatic ETB at the live ~$199 comp with the correct verdict; no secrets/addresses in output.
- Full existing suite stays green.

## 10. Acceptance criteria

1. `python -m scanner.discovery.sweep` produces `dashboards/<date>-sealed.html` from **live** comps,
   ≥ `poke.min_rows` sealed rows, passing `golden_check`; run summary prints credits consumed.
2. Every row's `badges`/`lens_tags`/`scanner_verdict` derive from the existing scorer/backbone,
   enforced by a pinning test (dashboard == scanner).
3. Products with no usable comp are skipped + counted in the manifest; no-URL/weak comps render `EST`,
   never a confirmed `STEAL`.
4. Observation ledger appended idempotently (`market_comp` + `deal` lines); distinct from any inventory ledger.
5. Sealed catalog `ppt_id`s seeded (or recorded NOT_FOUND) via the verify/provenance pattern.
6. Full existing test suite stays green; new modules (`sweep`, `golden`) have their own tests.

## 11. Out of scope / preserved anti-goals

No auto-checkout / auto-listing / account abuse; no unverified IDs; no AI price prediction; no web
acquisition, graded/raw, momentum, OPENER, scheduling, or inventory (later phases). The tool advises;
the human transacts. Demote-never-hide; truthful confidence labelling throughout.
