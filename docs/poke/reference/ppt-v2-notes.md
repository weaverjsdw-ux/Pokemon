# PokemonPriceTracker API v2 — distilled contract (from the OpenAPI doc, 2026-06-28)

Canonical reference for `scanner/market.py` and the `/poke` follow-on. Source: operator-supplied
OpenAPI 3.1.0 document (`Pokemon Price Tracker API` v2.0.0).

## Base + auth
- Base URL: `https://www.pokemonpricetracker.com/api/v2`
- `Authorization: Bearer <API_KEY>` (free key at pokemonpricetracker.com/api).

## Credit budget (the load-bearing constraint)
- Requests bill on the requested `limit` (**default 50**), NOT results returned. A default
  `/cards` / `/sealed-products` call = **50 credits**. **ALWAYS pass `limit=1`** for single lookups.
- Costs: basic 1/card; `includeHistory` +1; `includeEbay` +1 (graded); `includeCardmarket` +1
  (Pro/Business); population 2 (Business); parse-title 2 (+surcharges).
- Plans: Free 100 credits/day (3-day history, 1 key) · API $9.99/mo 20k/day (6-mo history, 5 keys)
  · Business $99/mo 200k/day. 60 calls/min (Free+API), 500 (Business).
- Every response: `metadata.apiCallsConsumed.total` + header `X-API-Calls-Consumed`; balance in
  `X-RateLimit-Daily-Remaining`. Read these to guard spend.

## Sealed products — `GET /sealed-products`  (this is what the scanner catalog needs)
- Requires ≥1 filter: `tcgPlayerId` | `setId` | `set` | `search` | `minPrice` | `maxPrice`.
- **Resolve by `?tcgPlayerId=<id>` (1 credit) — NOT a name search.** Confirmed live: a bare
  `search=<name>&limit=1` returns the WRONG variant (a single set's ETB has multiple TCGplayer
  products: standalone, "… and Pokeball (Sam's Club)", "… Case", "(Dollar General Exclusive)").
  Map each product to its exact `tcgPlayerId` (`ppt_id`); see `docs/poke/ppt-id-seeding.md`.
- Response: `{ "data": <SealedProduct | SealedProduct[]>, "metadata": {...} }`
  (single object when by `tcgPlayerId`, else array).
- `SealedProduct`: `{ tcgPlayerId, tcgPlayerUrl, name, setId, setName, unopenedPrice (number USD|null),
  imageCdnUrl*, priceHistory[], lastScrapedAt, updatedAt }`.
- **The comp = `data.unopenedPrice`** (TCGplayer market price for the sealed product).
- No per-sale confidence field — treat a TCGplayer market price as **medium** confidence
  (a single-source daily market summary, same tier as the PriceCharting fallback).
- Real prices run high for hyped sets (Prismatic Evolutions ETB ≈ $199 ≈ 4× the $49.99 MSRP) — do
  NOT treat a large MSRP-multiple as a junk comp; it's legitimate.

## Cards / singles + graded — `GET /cards`  (FOLLOW-ON: /poke raw + graded)
- Single by `tcgPlayerId` → `data` is one Card; else `search`/`set`/filters → array. Use `limit=1`.
- Raw singles comp = `data.prices.market` (USD; `data.prices.low` = lowest listing).
  Per-condition prices need `includeHistory=true` (deprecated `prices.conditions` → use `priceHistory`).
- **Graded** needs `includeEbay=true` (+1 credit): `data.ebay.salesByGrade["psa10"|"psa9"|"cgc9.5"|...]`
  → each grade has `medianPrice`, `averagePrice`, `marketPrice7Day`, `marketTrend`, and
  `smartMarketPrice.{price, confidence ("high"|"medium"|"low"), method, daysUsed}`.
  **Use `smartMarketPrice.price` as the graded comp and `smartMarketPrice.confidence` directly as our
  comp_confidence** (it maps 1:1). Grade keys are `{company}{grade}` lowercased, e.g. `psa10`, `cgc9.5`.
- Per-listing `soldListings[...]` (individual eBay sales) is **Business-tier only**; the aggregate
  `salesByGrade` (incl. medianPrice / smartMarketPrice) is available on **all plans** with `includeEbay`.
- Response caps: 200 basic / 100 with history-or-ebay / 25 with both.

## Other endpoints (not needed for v1)
- `GET /sets` (set metadata; `tcgPlayerNumericId` → use as `setId` on `/cards`).
- `POST /parse-title` (2+ credits; reserve for genuinely unmapped eBay titles — prefer direct lookups).
- `GET /population` (GemRate; **Business only**, 2 credits — Phase-3 grading economics).
- `GET /export` (daily bulk CSV; **Business only**; 302 → gzip blob; best for full-catalog sync).

## Mapping to our schema
- sealed: `estimate = unopenedPrice`, `source = "PokemonPriceTracker"`, `basis = "TCGplayer sealed market"`,
  confidence → medium (single-source market summary).
- graded (follow-on): `estimate = ebay.salesByGrade[gradeKey].smartMarketPrice.price`,
  `confidence = smartMarketPrice.confidence` (pass through), grade/grader from the key.
- raw (follow-on): `estimate = prices.market`, condition from `condition` filter.
- 401 → bad key; 429 → rate/credit exhausted; both must fall through to the resale fallback, never error a run.
