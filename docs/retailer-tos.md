# Per-retailer ToS notes

The scanner's stated stance (README, "Scope of this build") is that
**aggressive polling, login-walled scraping, and proxy/distributed
networks are fine *only when not against ToS*.** What's actually
permitted varies per retailer. This file is the source of truth for
that judgement and should be updated when a retailer changes their
terms, an adapter is added, or a contributor asks "is X allowed here?"

This is best-effort. It is not legal advice. When in doubt, default to
the more conservative interpretation.

---

## Target

- **API**: undocumented public RedSky aggregator (`redsky.target.com`).
- **ToS**: target.com's terms prohibit "automated means" to access
  the site. The RedSky endpoints are technically public (the browser
  hits them), but Target has been known to rate-limit or shadow-ban
  aggressive callers.
- **Adapter policy**: identify with a real browser User-Agent; cap at
  the global `poll_interval_seconds` (default 180s) with sleep
  between per-store calls. **Do not** parallelize, proxy-rotate, or
  scrape behind login.
- **If they ask us to stop**: disable in `config.yaml`, no questions
  asked. Reach out via the developer-relations email if they want a
  documented integration path instead.

## Walmart

- **API**: undocumented; we hit the same product-page HTML the
  browser does.
- **ToS**: Walmart explicitly prohibits scraping in their terms.
  Their store-inventory feed is also unreliable for TCG specifically
  (often misreports). We surface *online* availability only, which is
  what walmart.com itself publishes openly.
- **Adapter policy**: one product-page hit per product per pass; no
  per-store fan-out. Sleep 0.6s between products. If they tighten the
  block we drop the adapter, not work around it.

## Best Buy

- **API**: official, documented at https://developer.bestbuy.com.
  Free key, 50k req/day, 5 req/sec.
- **ToS**: explicitly permits this kind of inventory polling. This
  is the only retailer where aggressive (within the documented rate
  limit) polling is unambiguously allowed.
- **Adapter policy**: free to poll up to the documented rate limit.
  We sleep 0.25s between calls (= 4 req/s) to leave headroom.

## GameStop

- **API**: undocumented Demandware/Salesforce Commerce Cloud
  endpoints (same as the site).
- **ToS**: gamestop.com terms prohibit "use of robots or other
  automated means." The endpoints are public but they reserve the
  right to block.
- **Adapter policy**: same as Target — real UA, polite cadence, sleep
  between calls, no parallelism. Drop the adapter rather than evade a
  block.

## Pokémon Center

- **API**: Shopify storefront; `/products/<slug>.js` is documented
  and intended for client-side use.
- **ToS**: shop.pokemoncenter.com terms don't prohibit reading
  publicly published product JSON. They *do* prohibit using the site
  to "interfere with the purchase of products" — which is one reason
  the scanner has no auto-checkout and never will.
- **Adapter policy**: one JSON hit per product per pass, sleep 0.4s
  between products.

## Costco / Sam's Club (stubbed, disabled by default)

- Both prohibit scraping in their ToS. The adapter scaffolding exists
  but is **disabled by default** for that reason. Enable at your own
  judgement; if either retailer publishes an official feed (members'
  area JSON, an affiliate program) the adapter should be rewritten
  against that.

---

## Adding a new retailer

When a contributor proposes a new adapter, the PR description must
include:

1. Where the stock signal comes from (documented API? Public JSON?
   Page HTML?).
2. The retailer's posted ToS link and the relevant clause.
3. Estimated request volume per scan pass under default config.
4. Whether the retailer offers an official feed/affiliate program
   that would obviate scraping, and why we're not using it.

Adapters that require login, proxy rotation, or captcha solving are
out of scope and will not be merged.
