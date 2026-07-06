# PriceCharting Card Detail Probe (2026-07-05)

**Purpose.** Phase F needs an independent (non-PPT) sold-price source for raw
singles + graded slabs, at **0 PPT credits**. This probe checks whether
PriceCharting's per-card **detail** page (as opposed to its search-results page)
is plain-fetchable, and what the redirect / cell layout looks like — evidence
the Task 1–6 adapters (`scanner/poke_api/independent_sources.py`) are built on.

## Method

- Plain `requests.get(...)` with a standard browser `User-Agent` header — no
  Playwright, no JS rendering, no login/session.
- Operator-approved, read-only, single GET. **0 PPT credits** — PriceCharting's
  card page is scraped directly, never through the billed `/cards` API.
- Subject: `umbreon ex 161 prismatic evolutions` (a Prismatic Evolutions single
  already in the asset catalog, cross-checkable against a recorded PPT comp).

## Finding 1 — search auto-redirects to the canonical detail slug

Querying PriceCharting's `search-products` endpoint —

```
https://www.pricecharting.com/search-products?q=umbreon+ex+161+prismatic+evolutions&type=prices
```

— returned an HTTP redirect straight to the canonical per-product detail page:

```
https://www.pricecharting.com/game/pokemon-prismatic-evolutions/umbreon-ex-161
```

HTTP 200, no interstitial/JS challenge page. That redirect target's path segment
(`pokemon-prismatic-evolutions/umbreon-ex-161`) **is** the exact
`pricecharting_slug` value the asset catalog stores and the adapters fetch
directly (`PriceChartingRawSource` / `PriceChartingGradedSource` build the URL
as `https://www.pricecharting.com/game/{slug}` — no search step needed once the
slug is known once).

## Finding 2 — the `#price_data` table, cell → grade → value

The detail page's price table exposes one price per grade in a predictable set
of `<td>` cells, keyed by `id`. Verified for Umbreon ex 161 (Prismatic
Evolutions):

| Cell id | Grade | Value |
|---|---|---|
| `used_price` | Ungraded | $1,425.00 |
| `complete_price` | Grade 7 | $1,270.00 |
| `new_price` | Grade 8 | $1,286.91 |
| `graded_price` | Grade 9 | $1,554.05 |
| `box_only_price` | Grade 9.5 | $3,112.50 |
| `manual_only_price` | PSA 10 | $7,013.08 |

Cell markup shape (each cell nests the dollar figure in a `js-price` span):

```html
<td id="{cell}" ...><span class="price js-price">$X,XXX.XX</span></td>
```

This is exactly the shape `indep.pricecharting_card_prices_from_html` parses
(see `tests/test_poke_independent_sources.py::test_parser_extracts_every_grade_cell`,
which asserts these same six values against the captured fixture
`tests/fixtures/comps/pricecharting_umbreon_ex_161.html`).

## Cross-source sanity check (vs. the recorded PPT comp)

| Asset | PriceCharting (this probe) | PPT (ledger) | Delta |
|---|---|---|---|
| Umbreon ex 161 — raw/ungraded | $1,425.00 | $1,528.09 | ~7.2% |
| Umbreon ex 161 — PSA 10 | $7,013.08 | $6,925.00 | ~1.3% |

Both deltas are well inside the divergence audit's 20% tolerance band — the two
independent sources agree closely enough to cross-validate each other, not
just to exist as a fallback.

## TCGplayer note

TCGplayer product pages remain a **client-rendered SPA**: the initial HTML
response does not contain the price data (it is fetched by client-side JS after
load). A plain `requests` GET cannot read a TCGplayer price this way — it needs
Playwright (headless render) to be fetchable, which is why
`TcgPlayerRenderedSource` ships **dormant** (`render=None` by default) rather
than wired to a live fetch in this phase. See Tasks 8–9 (conditional,
non-blocking) for the rendered-fetch follow-on.

## Conclusion

PriceCharting's **detail** page is plain-fetchable (no Playwright, no
challenge, 0 PPT credits) once the canonical slug is known, and the redirect
behavior means even a name-based search can resolve to that slug without a
render step. This is the evidence basis for the Task 1–6 independent-source
adapters and their `fetchable-plain` verdict in
[`sources.md`](sources.md).
