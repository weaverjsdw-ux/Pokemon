# TCGplayer product-page probe — Slice 1 Task 1 (2026-07-03)

Method: plain requests GET, Chrome UA, 3 product pages (593355, 624676, 610930),
1.5s spacing. Script: scripts/probe_tcgplayer.py. Raw responses saved to
tests/fixtures/comps/ (no trim needed; see below).

| id | HTTP | bytes | parseable market price? | evidence excerpt |
| --- | --- | --- | --- | --- |
| 593355 | 200 | 46587 | no | `<title>\n      Your Trusted Marketplace for Collectible Trading Card Games - TCGplayer\n    </title>` |
| 624676 | 200 | 46587 | no | `<title>\n      Your Trusted Marketplace for Collectible Trading Card Games - TCGplayer\n    </title>` |
| 610930 | 200 | 46587 | no | `<title>\n      Your Trusted Marketplace for Collectible Trading Card Games - TCGplayer\n    </title>` |

All three fixtures are byte-identical (sha256
`08225dc53413bb74706816f8847dd59533e39e9e33b015bdd5e808242a55de40`) despite requesting
three distinct product ids — the server returned the same response body for every id.
The page is a client-rendered SPA shell: generic marketplace `<title>`, a bare
`<div id="app">` mount point plus bundled JS asset references (`ItemDetails-*.js`, etc.),
and no server-side-rendered product/price data. There is no `__NEXT_DATA__` or similar
SSR JSON blob, and `text-hits=0` / `json-hits=0` for both the `Market Price` text pattern
and the `"marketPrice"` JSON pattern in all three responses. The only `$`-adjacent
substrings found are Subresource Integrity hashes (`sha256-...`) in `<script integrity="...">`
tags, not currency values. No Cloudflare or other bot-wall challenge markers were present
— this is a normal 200 response, just one whose price data loads client-side via XHR/API
calls that a plain-requests GET never triggers.

**DECISION: STUB** — HTTP 200 returns an identical client-rendered SPA shell for all three
distinct product ids with zero market-price tokens (text or JSON) and no SSR data blob, so
no market price is parseable from plain-requests static HTML.
If STUB: spec section 4.2 ladder continues with Probe B (supervised devtools
observation) or the Playwright dependency decision; the engine ships TCGplayer-degraded
(PriceCharting + eBay only, max MEDIUM) and remains fully functional. Because this is a
client-hydrated shell (not a hard bot-wall/403), a headless-browser approach (Playwright)
is more likely to succeed than for a hard-blocked target — that plausibility assessment is
for the Probe B / Task 5 decision, not this task.
