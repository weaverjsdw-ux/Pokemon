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
