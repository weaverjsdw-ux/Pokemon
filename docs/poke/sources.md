# `/poke` Sources (tiered by fetchability — evidence-backed, append-only)

Probe each before relying on it. A "Just a moment…" / challenge page is NEVER data;
record it blocked. Removals require a dated entry + reason (sources never silently shrink).

## Candidates to probe (Phase 0)
- r/PKMNTCGDeals (reddit.com/r/PKMNTCGDeals) — deal feed
- TCG deal blogs / curators (record specific URLs as found)
- Target weekly / clearance pages — retailer sale
- Best Buy deals pages — retailer sale
- Costco TCG pages — retailer sale
- Pokémon Center sale pages — retailer sale
- eBay (sold + active listings) — marketplace
- TCGplayer (market + listings) — marketplace

## Tier results (filled by probe — 2026-07-02, full sweep, Phase-0 completion)

Verdict enum: `fetchable-plain | fetchable-playwright | API-only | dead-for-now`.

| Source | Method that worked | Status (verdict) | Notes (evidence, 2026-07-02) |
|---|---|---|---|
| Target search (`target.com/s?searchTerm=pokemon+trading+cards`) | WebFetch | fetchable-plain | Plain WebFetch returned a full product/price list on first try (10 items shown, e.g. Prismatic Evolutions ETB $219.99; "497 results"). |
| Best Buy search (`bestbuy.com/site/searchpage.jsp?st=pokemon+trading+cards`) | Playwright | fetchable-playwright | WebFetch timed out (60s) then ECONNRESET on retry. Playwright rendered full product grid: 646 results, prices visible (e.g. Chaos Rising Booster Box $160.99, ETB $105.00). |
| Costco search (`costco.com/CatalogSearch?dept=All&keyword=pokemon+cards`) | Playwright | fetchable-playwright | WebFetch ECONNRESET twice. Playwright initially showed a "Loading" shell; after a short wait it rendered "1 - 11 of 11 results for 'pokemon cards'" with prices (e.g. TOPPS box $35.99, LEGO Pokémon set $229.99). |
| Pokémon Center new releases (`pokemoncenter.com/category/new-releases`) | none (blocked) | API-only — needs PC product `.js` stock endpoint | WebFetch returned empty content. Playwright hit an Imperva/hCaptcha "Additional security check is required" wall (observation only, not evaded) — a bot-check block, not a timeout. Scanner already reads Pokémon Center product `.js` endpoints for stock (see live-sealed-board.md); that endpoint, not this HTML category page, is the acquisition path. |
| r/PKMNTCGDeals (`reddit.com/r/PKMNTCGDeals/`) | none (blocked) | API-only — needs Reddit API | WebFetch: "Claude Code is unable to fetch from www.reddit.com" (policy-layer block). Playwright: page redirected to a `js_challenge=1` URL and returned "You've been blocked by network security." — confirmed policy/bot block, not a timeout. Needs the Reddit API (or equivalent), not scraping. |
| eBay search (`ebay.com/sch/i.html?_nkw=pokemon+elite+trainer+box`) | Playwright (rendered, but acquisition path is the API) | API-only — needs eBay Browse keyset | WebFetch timed out (60s). Playwright rendered a full listing grid with prices (e.g. $97.88, $92.99-with-coupon, $20.00). The scanner's chosen acquisition path is the eBay Browse API, not HTML scraping — eBay Browse creds NOT configured as of 2026-07-02 (no config.yaml ebay block; env vars empty); see docs/poke/ebay-keyset-setup.md. |
| TCGplayer search (`tcgplayer.com/search/pokemon/product?q=elite+trainer+box`) | Playwright | fetchable-playwright | WebFetch returned only the page header, no products. Playwright (after ~4s render wait) showed "318 results for 'elite trainer box' in Pokémon" with prices and market prices (e.g. Prismatic Evolutions ETB 242 listings from $1.99, Market Price $177.59). |
| Slickdeals Pokémon TCG search (`slickdeals.net/newsearch.php?q=pokemon+tcg&searcharea=deals`) | WebFetch | fetchable-plain | Plain WebFetch returned real deal listings with prices on first try (655 results; e.g. Mega Evolution—Perfect Order ETB $59.99, Destined Rivals Booster Bundle $52.49). |
| TrackaLacker Pokémon tracker (`trackalacker.com/category/toys-and-games/trading-cards/pokemon`) | Playwright | fetchable-playwright | WebFetch returned HTTP 403. Playwright rendered a free, no-login product/price tracker: "Page 1 of 9 · 406 results" with per-product prices (e.g. Prismatic Evolutions ETB $50, Chaos Rising Booster Display Box $160). Strongest curator candidate. |
| PriceCharting Elite Trainer Box prices (`pricecharting.com/search-products?q=elite+trainer+box&type=prices`) | Playwright | fetchable-playwright | WebFetch returned HTTP 403. Playwright rendered a structured price list (e.g. Surging Sparks Costco 2-Pack $225.00, Phantasmal Flames ETB $107.99). Scanner already uses PriceCharting as its resale-fallback comp source (see PHASE0_FINDINGS.md Probe A). |
| Poke Alerts (`poke-alerts.com`) | Playwright | fetchable-playwright — marketing page, live feed paywalled | WebFetch returned HTTP 403. Playwright rendered the landing/marketing page for a paid Discord alert service ("17,009+ successful checkouts", "Sign Up" → checkout); ETB prices shown are illustrative feature examples, not a live deal feed — the actual restock/deal data is gated behind a paid subscription. |

**Directional read (updated 2026-07-02):** every fixed retailer/marketplace source is now
fetchable — either directly via plain WebFetch (Target, Slickdeals) or via Playwright
(Best Buy, Costco, TCGplayer, eBay's HTML, TrackaLacker, PriceCharting, Poke Alerts's landing
page). The only genuine `API-only` blocks are policy/bot walls that resist both WebFetch and
Playwright without evasion: Pokémon Center (Imperva/hCaptcha — use the scanner's existing `.js`
stock endpoint instead), Reddit (network-security block — needs the Reddit API), and eBay's
chosen acquisition path (Browse API, by design, even though the HTML itself renders). This
sharpens the June "everything resists WebFetch" read: WebFetch alone is thin, but
**Playwright clears most of the fixed set**; only PC/Reddit/eBay-as-API remain
credential/API-gated.
