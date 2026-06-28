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

## Tier results (filled by probe — 2026-06-27, representative sample)
| Source | Method that worked | Status | Notes |
|---|---|---|---|
| r/PKMNTCGDeals | none via WebFetch | needs Playwright / Reddit API | `reddit.com` blocked at the WebFetch policy layer (not Cloudflare) |
| eBay sold/completed search | none via WebFetch | needs Playwright / eBay Browse API | plain fetch timed out (60s); scanner already holds eBay Browse tokens |
| TCGplayer search | none via WebFetch | JS-required → needs Playwright / TCGplayer API | only the page header returned, no product/price content |
| Target / Best Buy / Costco / Pokémon Center sale pages | not yet probed | PENDING (full sweep) | left for the focused Phase-0 completion pass |
| TCG deal blogs / curators | not yet probed | PENDING (full sweep) | specific URLs to be identified during the full sweep |

**Directional read:** the marketplace/aggregator candidates all resist plain WebFetch
(blocked / timeout / JS-required), matching the gun-pipeline lesson — live DISCOVER will rely on
**Playwright** (available here as an MCP browser) and/or **official APIs** (eBay Browse,
TCGplayer). This shapes the follow-on plan's acquisition design.
