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
  2. **Comp value looked unreliable** ($163.75 for a ~$50-MSRP ETB). **← THIS WAS WRONG, see the
     2026-06-28 closure below.** Prismatic Evolutions is a hyped set and sealed genuinely trades
     ~$160-200; the $163.75 was a legitimate comp, not a mismatch. My "expected ~$60" was the error.
- **Original implication (partially WITHDRAWN — see closure):** obtain the PPT key; ~~sanity-check
  comps that are a large multiple of MSRP and downgrade them to EST~~ — **withdrawn**: a 3-4x-MSRP
  comp is *real* for a hyped set, so that heuristic would suppress legitimate comps. The existing
  `HIGH_PREMIUM_RATIO=4.0` guard is the right backstop and needs no change.

### Probe A CLOSED — 2026-06-28 (live, key configured)
- Key configured in `config.yaml` (`market.preferred=true`); probe re-run live.
- **Result:** `client=MarketFallbackClient`, `source='PokemonPriceTracker'` (NOT the fallback),
  `comp=199.14`, `confidence_tier='medium'`, `price_confidence='verified'`. **PPT v2 works
  end-to-end; sealed yields a verified-tier comp. Probe A is closed.**
- **The real Phase-0 lesson (resolution, not value):** a bare PPT name search returns the WRONG
  variant — `search="Prismatic Evolutions Elite Trainer Box"&limit=1` surfaced *"…and Pokeball
  (Sam's Club)"* ($178.91), a *Case* ($1865), and a *Dollar General Exclusive* ($201) before the
  standalone ETB; the verbose `resale_query` ("Pokemon TCG … sealed") returned **0 matches**.
  Silently returning a wrong-variant price is a fabrication risk.
- **Fix (implemented):** resolve PPT sealed comps by **exact `tcgPlayerId`** only (`?tcgPlayerId=<id>`,
  1 credit). Products without a mapped `ppt_id` skip the API (0 credits) and fall back to resale —
  no risky search. Proof: `prismatic_evolutions_etb` mapped to `ppt_id: 593355` → live $199.14 medium.
- **Remaining data task:** seed `ppt_id` for the rest of the sealed catalog (see
  `docs/poke/ppt-id-seeding.md`). Credit budget: 1 credit/product/refresh; ~26 products on a 24h
  cache = ~26 credits/day, well within the Free tier's 100/day.

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
  (`/api/v1/prices?q=`). Rewritten to v2 `GET /sealed-products?tcgPlayerId=<ppt_id>` → `data.unopenedPrice`
  (resolution by **exact id only** — bare name search returns wrong variants, see Probe A closure above),
  with the TCGplayer market price treated as a **medium**-confidence single-source market summary
  (`resale.annotate_quote`, mirroring the PriceCharting fallback). Unit-tested against mocked v2 responses
  **and validated live** (id 593355 → $199.14). **Singles + graded `/cards` (`includeEbay`) remain the
  follow-on.** Reference: `docs/poke/reference/ppt-v2-notes.md`.
- **Premium sanity-check — WITHDRAWN.** Earlier I proposed downgrading comps that are a large multiple of
  MSRP. Live data disproved it: a 3-4× MSRP sealed comp is *legitimate* for a hyped set (Prismatic ETB
  $199 ≈ 4× MSRP). Such a heuristic would suppress real comps. The existing `HIGH_PREMIUM_RATIO=4.0` guard
  stays as-is; no tightening.
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

## Phase-0 completion sweep — 2026-07-02

**Method:** WebFetch-first, Playwright-MCP fallback, two-timeout rule, verdicts + evidence
per source (full table in sources.md).

| Source | Verdict | Evidence (2026-07-02) |
| --- | --- | --- |
| Target search | fetchable-plain | Plain WebFetch returned a full product/price list on first try (10 items shown, e.g. Prismatic Evolutions ETB $219.99; "497 results"). |
| Best Buy search | fetchable-playwright | WebFetch timed out (60s) then ECONNRESET on retry. Playwright rendered full product grid: 646 results, prices visible (e.g. Chaos Rising Booster Box $160.99, ETB $105.00). |
| Costco search | fetchable-playwright | WebFetch ECONNRESET twice. Playwright initially showed a "Loading" shell; after a short wait it rendered "1 - 11 of 11 results for 'pokemon cards'" with prices (e.g. TOPPS box $35.99, LEGO Pokémon set $229.99). |
| Pokémon Center new releases | API-only — needs PC product `.js` stock endpoint | WebFetch returned empty content. Playwright hit an Imperva/hCaptcha "Additional security check is required" wall (observation only, not evaded) — a bot-check block, not a timeout. Scanner already reads Pokémon Center product `.js` endpoints for stock; that endpoint, not this HTML category page, is the acquisition path. |
| r/PKMNTCGDeals | API-only — needs Reddit API | WebFetch: "Claude Code is unable to fetch from www.reddit.com" (policy-layer block). Playwright: page redirected to a `js_challenge=1` URL and returned "You've been blocked by network security." — confirmed policy/bot block, not a timeout. |
| eBay search | API-only — needs eBay Browse keyset | WebFetch timed out (60s). Playwright rendered a full listing grid with prices (e.g. $97.88, $92.99-with-coupon, $20.00), but the scanner's chosen acquisition path is the eBay Browse API, not HTML scraping — eBay Browse creds NOT configured as of 2026-07-02 (no config.yaml ebay block; env vars empty); see docs/poke/ebay-keyset-setup.md. |
| TCGplayer search | fetchable-playwright | WebFetch returned only the page header, no products. Playwright (after ~4s render wait) showed "318 results for 'elite trainer box' in Pokémon" with prices and market prices (e.g. Prismatic Evolutions ETB 242 listings from $1.99, Market Price $177.59). |
| Slickdeals Pokémon TCG search | fetchable-plain | Plain WebFetch returned real deal listings with prices on first try (655 results; e.g. Mega Evolution—Perfect Order ETB $59.99, Destined Rivals Booster Bundle $52.49). |
| TrackaLacker Pokémon tracker | fetchable-playwright | WebFetch returned HTTP 403. Playwright rendered a free, no-login product/price tracker: "Page 1 of 9 · 406 results" with per-product prices (e.g. Prismatic Evolutions ETB $50, Chaos Rising Booster Display Box $160). Strongest curator candidate. |
| PriceCharting Elite Trainer Box prices | fetchable-playwright | WebFetch returned HTTP 403. Playwright rendered a structured price list (e.g. Surging Sparks Costco 2-Pack $225.00, Phantasmal Flames ETB $107.99). Scanner already uses PriceCharting as its resale-fallback comp source (Probe A, above). |
| Poke Alerts | fetchable-playwright — marketing page, live feed paywalled | WebFetch returned HTTP 403. Playwright rendered the landing/marketing page for a paid Discord alert service ("17,009+ successful checkouts"); ETB prices shown are illustrative feature examples, not a live deal feed — actual restock/deal data is gated behind a paid subscription. |

**Changed since June:**
- The June sample called Target/Best Buy/Costco/Pokémon Center "not yet probed" — all four are now
  verdicted. Target and Best Buy/Costco resolve cleanly to fetchable (plain and Playwright,
  respectively); Pokémon Center is the one retailer that is a genuine bot-wall (Imperva/hCaptcha),
  re-bucketed to `API-only` pointing at the scanner's existing product `.js` stock endpoint rather
  than this HTML page.
- Reddit and eBay were "needs Playwright" in June; re-probing on 2026-07-02 shows Playwright
  clears eBay's HTML (full listing grid renders) but Reddit still hard-blocks even via Playwright
  ("blocked by network security") — so Reddit stays `API-only`, while eBay is `API-only` for a
  different reason (design choice: Browse API is the intended acquisition path, not scraping).
- TCGplayer was "JS-required, header only" in June; on 2026-07-02, Playwright (with a short render
  wait) clears it fully — 318 results with prices, confirming Playwright is sufficient without
  needing the TCGplayer API for basic search/price data.
- **Corrected eBay-creds claim:** earlier findings (lines above) described the scanner as already
  holding eBay Browse tokens. That is not accurate as of 2026-07-02: eBay Browse creds are NOT
  configured (no `ebay` block in `config.yaml`, no `EBAY_*` env vars set, and no eBay credential
  file exists anywhere in the repo). See `docs/poke/ebay-keyset-setup.md` for the setup path (authored later the same day; the doc now exists in the tree).
- Four curators were identified and probed (Slickdeals, TrackaLacker, PriceCharting, Poke Alerts) —
  none existed in the June sample, which had no curator candidates at all.

**Recommendation:** DISCOVER should target, in priority order: (1) **TrackaLacker** first — free,
no-login, 406 Pokémon products with live prices, clears Playwright cleanly, closest thing to a
ready-made curator feed; (2) **Target + Slickdeals** next — both `fetchable-plain`, cheapest to
poll (no browser needed), good for a fast/low-cost polling tier; (3) **Best Buy / Costco /
TCGplayer** via Playwright — all render fully, just costlier per-poll than plain fetch; (4)
**PriceCharting** as the existing comp-source, keep using it for sealed pricing validation rather
than as a deal feed; (5) defer **eBay Browse API** and **Reddit API** integration until credentials
are obtained (eBay keyset per `ebay-keyset-setup.md` using that doc; Reddit API app registration);
(6) for **Pokémon Center**, skip the HTML category page entirely and use the scanner's existing
product `.js` stock-endpoint path, matching current scanner behavior. Do not attempt to bypass the
Pokémon Center or Reddit bot-walls with CAPTCHA-solving or similar evasion.

**Operator: does this complete Phase-0 Probe B — signed off? (yes → Phase B unblocked;
this packet does not self-certify.)**

**SIGNED OFF — operator, 2026-07-02.** Phase-0 Probe B complete; Phase B unblocked. Remaining
operator items tracked elsewhere: eBay keyset provisioning (`docs/poke/ebay-keyset-setup.md`) and
resuming the 6 remaining `ppt_id` seeds after the credit-window reset.
