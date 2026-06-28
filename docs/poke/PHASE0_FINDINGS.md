# Phase 0 Findings — `/poke` pipeline

## Probe A — sealed comp verification (Task 1)
- Date run: 2026-06-27
- Client used: **PublicFallbackResaleClient** (PPT is NOT configured — `market_preferred=false`
  / no key, so `market_client_from_config` returned the resale fallback, not the PPT
  `MarketFallbackClient`).
- Sealed product: `prismatic_evolutions_etb`
- Result: `status=ok`, `source='PriceCharting market fallback'`, `comp=163.75`,
  `confidence_tier='medium'` → under the render gate, medium = **verified-tier** (non-EST).
- **Verdict:** **QUALIFIED YES.** Sealed yields a *medium*-confidence, verified-tier comp
  today, so under the §3.3 gate sealed can render as a non-EST deal. **But two caveats make
  this necessary-not-sufficient:**
  1. **PPT is not active.** The best sealed comp source (PokemonPriceTracker) is unconfigured;
     today's comp comes from the PriceCharting *fallback*.
  2. **Comp value looks unreliable.** $163.75 for an ETB with ~$50 MSRP is almost certainly a
     loose/mismatched fallback match (expected sealed street ~$60). The "medium" tier label
     does **not** guarantee the number is right.
- **Implication for follow-on plan:**
  - Obtain + enable the **PPT key** before the live-acquisition phase; treat it as the gating
    prereq for trustworthy sealed comps (and the only native source for raw/graded).
  - The live RESEARCH stage must **sanity-check fallback comps against an expected range**
    (e.g. flag a comp that is a large multiple of MSRP as suspect / downgrade to EST), so a
    loose PriceCharting match never produces a confident STEAL. This is a concrete addition to
    the follow-on plan's comp-routing task, surfaced only because this probe ran live.

## Probe B — source fetchability (Task 2)
- Date run: 2026-06-27 (representative sample, not exhaustive — see below)
- Fetchable via plain WebFetch: **none of the sampled sources** returned usable deal/price data.
- Results observed live:
  - r/PKMNTCGDeals — `reddit.com` blocked at the WebFetch policy layer (needs Playwright / Reddit API).
  - eBay sold/completed search — plain WebFetch timed out at 60s (needs Playwright / eBay Browse API;
    the scanner already holds eBay Browse tokens).
  - TCGplayer search — JS-required: only the page header returned, no products/prices (needs
    Playwright / TCGplayer API).
- Not yet probed (deferred to the focused completion pass): Target / Best Buy / Costco / Pokémon
  Center sale pages; TCG deal blogs / curators.
- **Verdict:** **Feeds are thin for plain fetch.** The marketplace/aggregator candidates all resist
  WebFetch, matching the gun-pipeline lesson. Live DISCOVER will rely on **Playwright** (available
  here as an MCP browser) and/or **official APIs** (eBay Browse, TCGplayer), not plain fetch.
- **Implication for follow-on plan:** design DISCOVER around (1) Playwright for aggregators/marketplaces,
  (2) the eBay Browse API (tokens already present) as the most reliable structured marketplace source,
  and (3) a focused completion sweep of retailer sale pages + deal blogs to find any plain-fetchable
  curators before the live build. **CHECKPOINT for operator:** the exhaustive fetchability sweep
  (retailer pages, blogs, and Playwright re-tries of the blocked sources) is the remaining Phase-0
  item; it was sampled here, not completed, to avoid a long autonomous web sweep without sign-off.

## Handoff to follow-on plan (live acquisition + raw/graded + regression hardening)
Phase-1 deterministic core is built and green on the fixture (config `poke` block,
`DealRow` + STOP gate, observation ledger, scorer with Flipper via `scanner.margin`,
renderer + golden test). The follow-on plan (written after these findings) covers, per spec §5/§7:
- DISCOVER adapters (Playwright + eBay Browse API + WebSearch) per Probe B's verdict.
- RESEARCH comp routing wired to live `scanner.market`/`resale`, **plus the new expected-range
  sanity-check on fallback comps** that Probe A surfaced (a comp that is a large multiple of MSRP
  downgrades to EST, never a confident STEAL).
- raw + graded comp paths (PPT graded/singles endpoints — confirm shapes; obtain the PPT key first).
- the in-session OPENER + `/poke` command + mode dispatch.
- regression hardening: watchlist continuity write-path, manifest delta, persona self-test,
  prompt-durability sidecar (`.poke-opener-verified.json`).

### Operator action items before the follow-on plan
1. **Obtain + configure the PokemonPriceTracker API key** (gates trustworthy sealed comps and is the
   only native source for raw/graded). Probe A confirmed it is not currently active.
2. **Sign off on the exhaustive source-fetchability sweep** (Probe B was a representative sample).

## Probe A addendum — confirmed PPT v2 API contract (2026-06-28, from operator-supplied docs)
This closes spec §13.1 ("PPT graded/singles endpoint shapes + credit cost"). Build the follow-on on these:
- **Base URL `https://www.pokemonpricetracker.com/api/v2`**, `Authorization: Bearer <key>`. Endpoints
  include `/cards` (singles, incl. graded prices) and `/sealed-products` (ETBs/boxes/bundles).
- **REQUIRED FIX — DONE (sealed) 2026-06-28:** `scanner/market.py` was on a stale **v1** URL
  (`/api/v1/prices?q=`) — almost certainly why Probe A fell back to PriceCharting even though the call
  ran. Rewritten to v2 `GET /sealed-products?search=…&limit=1` → `data[].unopenedPrice`, with the
  TCGplayer market price treated as a **medium**-confidence single-source market summary
  (`resale.annotate_quote`, mirroring the PriceCharting fallback). Unit-tested against mocked v2
  responses. **Singles + graded `/cards` (`includeEbay`) remain the follow-on.** Once the operator
  adds the key + `market.preferred=true`, re-run `scripts/poke_phase0_comp_probe.py` to confirm a live
  verified-tier sealed comp. Reference: `docs/poke/reference/ppt-v2-notes.md`.
- **Still open (follow-on tuning):** the premium sanity-check. `HIGH_PREMIUM_RATIO` is 4.0×, so the
  $163.75-vs-$50-MSRP junk comp (3.27×) was NOT flagged. A tighter market-summary-specific ratio
  (downgrade an implausible multiple of MSRP to EST/low) is the planned fallback-sanity-check task —
  not changed here to avoid an unvetted global threshold change.
- **BILLING TRAP (load-bearing):** requests bill on the requested `limit` (default 50), NOT results
  returned — a default `/cards`/`/sealed-products` call = **50 credits**. **Always pass `limit=1`** for
  single-product lookups -> 1 credit basic (+1 eBay data, +1 price history). Read the exact charge from
  `metadata.apiCallsConsumed` / `X-API-Calls-Consumed`; balance from `X-RateLimit-Daily-Remaining`.
- **Plans:** Free 100 credits/day (~50-100 single lookups with `limit=1`; history window only 3 days,
  1 key) - API $9.99/mo 20,000 credits/day, 6-mo history, 5 keys - Business $99/mo 200k credits/day.
  60 calls/min on Free+API, 500 on Business.
- **Graded prices (PSA/CGC/BGS/SGC) are available on EVERY plan** (+1 credit/card) — graded can ship in
  v1, contrary to the earlier "graded = Business" assumption. Only **eBay sold auction/BIN detail** and
  **GemRate population data (2 credits, Phase-3 grade screen)** require Business.
- **Parse-title costs 2 credits (+surcharges)** — too expensive on a 100/day budget; the follow-on
  should resolve products via direct `limit=1` `/cards`/`/sealed-products` lookups keyed off our own
  catalog, and reserve parse-title for genuinely unmapped items.
- **Recommended tier:** start **Free** to validate + run small curated sweeps (with `limit=1`); move to
  **API ($9.99)** for real coverage feeding both `/poke` sweeps and the scanner's background comp cache.
