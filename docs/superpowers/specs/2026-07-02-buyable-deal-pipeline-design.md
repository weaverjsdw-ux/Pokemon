# Buyable-Deal Pipeline — Design Spec

**Date:** 2026-07-02
**Status:** Draft — awaiting operator review
**Supersedes nothing; extends:** the live sealed deal board
(`2026-06-28-poke-live-sealed-slice-design.md`) and executes the Phase-B + Phase-E slices of
the A–E roadmap (`2026-06-28-resale-engine-program-roadmap.md`).
**Operator problem being solved:** "it hasn't found me really anything to buy." Diagnosis
(confirmed from `data/poke/2026-07-01-sealed.json`): every board row carries
`retailer: "MSRP"`, `stock_status: "unknown"`, `stock_evidence: ""` — the system computes
hypothetical margins at MSRP but never verifies that anything is purchasable, where, or at
what live price. This design closes that gap end-to-end: **discover → verify buyable →
comp (in-house) → verdict → alert**, always-on.

**Decision recorded:** the PPT paid tier ($9.99/mo) is **rejected**. Comp data moves to an
in-house engine built on sources we reach directly (TCGplayer product pages, PriceCharting,
eBay Browse). PPT stays available on the free tier as an optional spot-check validator only.
The one operator unlock this design assumes is the **eBay developer keyset** (free, ~15 min,
`docs/poke/ebay-keyset-setup.md`); every eBay-dependent piece degrades cleanly until it lands.

---

## 1. Current-state grounding

All claims below were verified by reading the named files this session (2026-07-02, repo at
`65c4b78`) unless marked **[inferred]**.

### What exists and is load-bearing

| Concern | Where it lives | Confirmed state |
| --- | --- | --- |
| Product catalog | `data/products.yaml` | ~26 sealed products; per-retailer ids (`target_tcin`, `walmart_item_id`, `bestbuy_sku`, `costco_item_id`, `gamestop_pid`, `pokemoncenter_slug`), `ppt_id` (= TCGplayer product id), `msrp`, `resale_query`. 7 products have verified `ppt_id`s; 6 unseeded. |
| Comp clients | `scanner/resale.py` | `EbayResaleClient` (Browse API, client-credentials OAuth, active fixed-price median), `PublicEbaySearchClient` (HTML parse), `PriceChartingSearchClient` (requests + Chrome UA — worked live 2026-07-01, produced 7 comps), `PublicFallbackResaleClient` (chain). Common interface: `estimate(product_key, product, checked_at) -> quote dict`. `annotate_quote` assigns confidence: high = sold basis + sample ≥ 8; medium = API active median sample ≥ 3 OR single-source market summary; `premiumRatio ≥ 4.0` forces low (kept per Phase-0 closure — do not tighten). |
| PPT client | `scanner/market.py` | v2 by exact `tcgPlayerId` only, `limit=1` pinned (billing trap: bills on requested limit, default 50). `MarketFallbackClient` wraps PPT→resale. `comp_from_row` extracts (comp, confidence). |
| Sweep/board | `scanner/discovery/sweep.py` | `build_sealed_sweep` iterates catalog, `retailer="MSRP"` hardcoded (line 101), stock fields never populated. `LiveCompLookup` guards PPT credits. Ledger append + STOP gate + golden gate + manifest all working (live run 2026-07-01: 13/22 comped, 6 STEAL). |
| Row schema + STOP gate | `scanner/discovery/schema.py` | `DealRow` already has `stock_status` (default `"unknown"`) and `stock_evidence` (default `""`) — fields exist, nothing fills them. `validate_row` enforces price-accuracy invariants; `row_from_dict` ignores unknown keys (schema is forward-extensible). |
| Scoring | `scanner/discovery/score.py` | STEAL requires `price_confidence=="verified"` + pct ≥ `steal_pct`; lens tags; `fake_markdown_flags`; dedup keeps cheapest per identity. |
| Margin/verdict | `scanner/margin.py`, `scanner/verdict.py` | Pure fee-adjusted math (eBay FVF + fixed + shipping; local haircut), BUY/THIN/SKIP gated on net $ AND ROI; low-confidence comp caps BUY→THIN. Docstring doctrine: "Resale comps are context for MSRP-protection decisions, not a scalping target." |
| Restock scanner | `scanner/main.py` | Route-corridor store discovery; `run_pass` polls enabled retailers, dedupes via `State.should_alert`, sends `StockAlert`. **`comp_lookup` hook exists in `run_pass` but `main()` never passes one — live restock alerts currently carry NO verdict.** Loop mode exists (`python -m scanner`, default 180 s + jitter). |
| Retailer adapters | `scanner/retailers/` | `base.Retailer.check/inventory -> StockResult(status, url, price)`; statuses `IN_STOCK/LIMITED/OUT/ONLINE_IN_STOCK/ONLINE_OUT`. Target = RedSky per-store fulfillment (plain HTTP, public token); Walmart/BestBuy/PokemonCenter online-only; Costco supported; Sam's Club declared unsupported. All plain `requests` via shared `retailers/http.py` (retry/backoff, honors Retry-After, **"never mutate cart or purchase state" contract in its docstring**). |
| Dedupe/state | `scanner/state.py` | SQLite `data/state.db`: `last_alert` (re-alert on status change or 6 h cooldown), `stock_history` (restock memory), `source_health`. |
| Alerts | `scanner/notify.py` | `StockAlert` + `Notifier` → console, Discord embed, ntfy push. |
| Source-state taxonomy | `scanner/confidence.py` | `NOT_IMPLEMENTED/DISABLED/NEEDS_API_KEY/NEEDS_ID/BLOCKED/PARSER_SUSPECT/ID_SUSPECT/DEGRADED/READY/WORKING` with severity + actionable flags. **Reused as-is for new sources — no parallel taxonomy.** |
| Observation ledger | `scanner/discovery/ledger.py` | Append-only JSONL, idempotent on `(kind, item_key, source_url, capture_date)`; kinds `{deal, market_comp}`. 26 entries exist from the 2026-07-01 sweep — own price history is already accumulating. |
| Health | `scanner/health.py` | **[inferred from call sites]** `record_check/record_success/record_failure/note_http_status/snapshot`. |
| Config | `scanner/config.py` | Full surface incl. `deal_intelligence` (fees/thresholds), `resale_prices.ebay` (keyset fields — currently unset per Phase-0), `market` (PPT), `poke` block. `config.yaml` gitignored. |
| Tests | `tests/` (31 files) | Network-mocked, inline HTML/JSON payloads (no fixtures dir). Suite at 276 passed (be4a469). |
| Dependencies | `requirements.txt` | `requests`, `PyYAML`, `polyline` only. **No Playwright package** — Phase-0's Playwright probes used the session MCP browser, which is NOT available to a scheduled headless run. |

### Phase-0 source verdicts (signed off 2026-07-02, `docs/poke/PHASE0_FINDINGS.md`)

- **fetchable-plain:** Target search, Slickdeals search.
- **fetchable-playwright:** TrackaLacker (strongest curator), TCGplayer search, Best Buy
  search, Costco search, PriceCharting (403 to WebFetch — but the existing
  `PriceChartingSearchClient` with a browser UA works via plain requests, confirmed live).
- **API-only:** eBay (design choice: Browse API), Reddit (hard bot-block), Pokémon Center
  (Imperva/hCaptcha wall — use the scanner's existing product-`.js` stock endpoint instead;
  **never** attempt bot-wall evasion).

### What is genuinely unknown (probe before building on it)

- **TCGplayer product-page acquisition path.** Phase-0 verdicted the *search* page
  JS-required. Whether the *product* page (`tcgplayer.com/product/<id>`) serves usable
  embedded JSON/market price to plain requests is **unprobed**. Slice 1 includes an
  evidence-captured probe with a defined fallback ladder (§4.2).
- Whether Discord webhook / ntfy topic are configured in the operator's `config.yaml`
  (gitignored; not readable claims). Alert channels degrade to console if unset.

---

## 2. Doctrine / boundary guardrails (all load-bearing, none new)

1. **This is an MSRP/source-truth/operator-usefulness system, not a scalping or auto-buy
   bot.** The human transacts; the tool advises. Margin math frames MSRP-protection
   decisions (`scanner/margin.py` docstring) — resale/market data is decision context, not
   the product's identity. No "profit engine" framing in code, docs, or dashboards.
2. **No auto-checkout, no cart automation, no purchase-state mutation** — the existing
   `retailers/http.py` contract ("stock-query requests only") extends verbatim to every new
   adapter and the verifier.
3. **No proxy polling, no login-wall or bot-wall scraping, no CAPTCHA evasion.** Pokémon
   Center and Reddit stay on their sanctioned paths (product `.js` endpoint; API-only).
   Polling rates stay polite: reuse `retailers/http.py` backoff; per-source minimum
   intervals (§3.2).
4. **Price accuracy (STOP-class):** never fabricate/guess/extrapolate a price; every price
   carries source URL + capture date; EST badged, never presented as a comp. The existing
   STOP gate stays mandatory pre-render and is **extended** (§5) so a positive stock claim
   without evidence is also a gate violation. No fake confidence: a comp the engine can't
   support is `unknown` and produces **no number**.
5. **No alert without verified purchasability** (§5). "MSRP, stock unknown" rows may render
   in a non-alert reference section of the board; they must never push.
6. **PPT credit rules stand** (free tier only, `limit=1` pinned, operator go-ahead before
   any live PPT call). The validator is off the hot path and disabled by default.
7. **`/poke` runtime persona stays untouched** — this build ships adapters, pipeline,
   schemas, dashboards. No `/poke` command, persona file, or mode dispatch is created.
8. **Git/env:** never push; no new dependency without an explicit operator yes (the one
   candidate is Playwright — an open question in §10, NOT assumed).

---

## 3. Architecture — workstream contracts

Pipeline shape (one-shot per scheduled invocation; every stage pure-testable, I/O injected):

```
DISCOVER (adapters) ──> CandidateDeal[]
      │ normalize + catalog-match + dedupe (state.db seen-listings)
      ▼
VERIFY (purchasability) ──> VerifiedDeal[]   (stock_status + verified_price + evidence)
      ▼
COMP (in-house engine, cached) ──> NormalizedComp per item
      ▼
VERDICT (existing margin/verdict backbone, at verified price)
      ▼
EMIT ──> DealRow[] → STOP gate → board (buyable-now section) + ledger
     └─> DealAlert → dedupe (state.db) → Notifier (console/Discord/ntfy)
```

### 3.1 WS1 — In-house comp engine (`scanner/comps/`)

| Contract item | Definition |
| --- | --- |
| Inputs | `(product_key, product dict)` from catalog, or an ad-hoc `(item_name, set, variant)` triple for discovered non-catalog items. |
| Outputs | `NormalizedComp` (§4.1) AND a legacy-shaped quote dict (same keys `annotate_quote` emits: `status/estimate/low/high/sampleSize/url/sourceUrl/confidence/...`) so `market.comp_from_row`, `sweep._provenance`, and `main.verdict_for_alert` consume it **unchanged**. |
| Persistent | `comp_cache` table in `state.db`: `(item_key TEXT PRIMARY KEY, payload_json TEXT, fetched_at INTEGER)`. Ledger: one `market_comp` observation **per source per day** (extends current one-per-chosen-comp behavior; same idempotency key). |
| Source states | Per-source `CompSourceQuote.status`: `ok / no_match / blocked / error / not_configured / skipped`. Engine-level state per source mapped onto `scanner/confidence.py` states for the health panel (e.g. eBay without keyset → `NEEDS_API_KEY`). |
| Failure/degraded | Any subset of sources may fail; confidence degrades per §4.3 — never a run failure. All-sources-failed → comp `unknown`, row skipped from deal math, counted in manifest (`no_comp`). Cached comp served while fresh (§4.4). |
| Rate-limit/caching | Cache TTL `comps.cache_ttl_seconds` (default 21600 = 6 h). Per-source politeness: ≥ 1 s between requests to the same host (existing `time.sleep(0.2)` pattern, raised), `retailers/http.py` backoff on 429/5xx. eBay Browse: one search per item per refresh. PPT validator: **never called in the pipeline**; only by the explicit `--validate` CLI flag with operator go-ahead, `limit=1`. |
| Evidence per result | Each `CompSourceQuote` stores: exact URL fetched, ISO timestamp, parsed price, `raw_excerpt` (≤ 200 chars of the matched title/price text), sample size where applicable. The chosen comp records `comp_basis` (which sources, which rule). |
| Done-tests | Unit: normalization from saved static payloads per source (HTML/JSON fixtures under `tests/fixtures/comps/`); confidence matrix (§4.3) exhaustively table-tested; agreement/disagreement/floor-sanity cases; cache TTL hit/miss/expiry; all-degraded → `unknown` with no invented number; legacy-dict shape asserted key-by-key against what `comp_from_row` + `_provenance` need. Parser-drift canaries (§8). |

### 3.2 WS2 — Discovery adapters (`scanner/discovery/adapters/`)

| Contract item | Definition |
| --- | --- |
| Inputs | Adapter-specific config block (`discovery.sources.<slug>`), catalog + set-watch list for matching. |
| Outputs | `list[CandidateDeal]` (§9.3), already normalized; adapter never decides alert-worthiness. |
| Persistent | `seen_listings` table in `state.db`: `(source TEXT, listing_id TEXT, price REAL, status TEXT, first_seen INTEGER, last_seen INTEGER, PRIMARY KEY (source, listing_id))` — powers both dedupe and later "how long has this listing sat" context. Ledger: `listing` observations (new kind, §9.2). |
| Source status states | Reuses `scanner/confidence.py` verbatim: a keyset-less eBay adapter reports `NEEDS_API_KEY`; HTTP 403/429 → `BLOCKED`; HTTP 200 with zero parsed rows → `PARSER_SUSPECT`; transient errors → `DEGRADED`; producing rows → `WORKING`. Reported into `health.record_*` under slug `disc:<source>`. |
| Failure/degraded | One adapter failing never stops the pipeline; its absence is recorded in the run manifest (`sources` array, same shape the sweep manifest already uses). |
| Rate-limit/caching | Each adapter declares `min_interval_seconds` (Target search / Slickdeals: 900; eBay Browse: 300; defaults conservative). The pipeline skips an adapter whose interval hasn't elapsed (`last_run` kept in `state.db` `source_health`). Plain-fetch adapters send the repo's standard browser UA; all HTTP through `retailers/http.py`. |
| Evidence per result | Every `CandidateDeal` carries `evidence_excerpt` (raw title + price text as parsed), `url` (direct listing/product URL), `seen_at` (ISO datetime). |
| Done-tests | Per adapter: parse from ≥ 2 saved real HTML/JSON fixtures (a populated page + an empty/no-results page); title→catalog matching precision cases (right variant chosen, `NEGATIVE_TITLE_PARTS`-style exclusions honored — reuse `resale._title_allowed` machinery); `NEEDS_API_KEY` degradation for eBay; malformed-HTML → `PARSER_SUSPECT` not crash. |

**Launch adapters (wave 1 — no new dependencies):**

| Adapter | Method | Basket role |
| --- | --- | --- |
| `target_search` | plain fetch (Phase-0: fetchable-plain) | Big-box sale/clearance discovery beyond tracked TCINs |
| `slickdeals` | plain fetch (Phase-0: fetchable-plain) | Community deal signal; candidates point at merchant URLs |
| `ebay_browse` | Browse API (keyset-gated; `NEEDS_API_KEY` until provisioned) | Underpriced-active-listing lane — one lane, not the product |
| (existing scanner adapters) | already live | Restock lane for tracked catalog — Target/Walmart/BestBuy/Costco/GameStop/Pokémon Center via their sanctioned endpoints |

**Wave 2 (gated on the Playwright dependency decision, §10):** `trackalacker` (strongest
curator per Phase-0), TCGplayer search, Best Buy/Costco search pages. Adapter interface is
identical; only the fetch layer differs.

### 3.3 WS3 — Purchasability verifier (`scanner/discovery/verify.py`)

Full contract in §5 (it is the design's centerpiece).

### 3.4 WS4 — Pipeline, scheduling, alerting (`scanner/discovery/pipeline.py`, `notify.py`, `state.py`)

| Contract item | Definition |
| --- | --- |
| Inputs | Config; adapters registry; comp engine; verifier; `State`; `Notifier`. CLI: `python -m scanner.discovery.pipeline [--once] [--sources a,b] [--dry-run]`. |
| Outputs | Board JSON + manifest + dashboard (existing sweep output conventions, `sweep_id = <date>-discovery`), `DealAlert` pushes, ledger appends, health records. |
| Persistent | `deal_alerts` table: `(source TEXT, listing_id TEXT, price REAL, status TEXT, ts INTEGER, PRIMARY KEY (source, listing_id))`. Re-alert only if: status changed, or price dropped ≥ `alerts.price_drop_realert_pct` (default 5 %), or `alerts.cooldown_hours` (default 24) elapsed. |
| Failure/degraded | Stage-isolated: adapter failure → skip + record; verify failure → candidate demoted to `unverifiable` (no alert, board reference section); comp `unknown` → no verdict, no alert, board reference section with explicit "no comp" note; notifier failure → printed to console/stderr (existing pattern). Golden gate halts the dashboard write exactly as the sweep does today. |
| Rate-limit/caching | The pipeline is a **one-shot** run under Windows Task Scheduler (crash-proof; no long-lived daemon beyond the existing scanner loop). Discovery lane default every 2 h (`discovery.interval_seconds`); restock lane = existing `python -m scanner` loop (180 s polls). `scripts/register_tasks.ps1` registers both tasks (at-logon scanner loop + repeating pipeline). Quiet hours `alerts.quiet_hours` (default `"23:00-08:00"`): ntfy pushes suppressed, Discord still posted (silent history), board always updated. |
| Evidence per result | The run manifest records per-source counts, per-stage drop reasons, and every alert's dedupe decision. |
| Done-tests | Scheduler-independent: pipeline unit-tested with fake adapters/verifier/engine (dependency injection, same style as `build_sealed_sweep(comp_lookup=...)`). Dedupe matrix (new listing / same price / price drop / status flip / cooldown). Quiet-hours suppression. No-alert-without-evidence (§8, mandatory). Manifest reconciliation (candidates = alerted + suppressed + unverifiable + no_comp + below_floor). |

---

## 4. Comp engine v1 — concrete

### 4.1 Normalized objects

```python
# scanner/comps/model.py  (pure; no I/O)

@dataclass(frozen=True)
class CompSourceQuote:
    source: str            # "tcgplayer" | "pricecharting" | "ebay_api" | "ebay_public" | "ppt"
    kind: str              # "sold_derived" | "active_ask" | "validator"
    status: str            # "ok" | "no_match" | "blocked" | "error" | "not_configured" | "skipped"
    price: float | None    # None unless status == "ok"
    url: str               # exact page/listing/search URL fetched (attribution)
    fetched_at: str        # ISO datetime
    sample_size: int | None  # eBay: matched listings; sold-derived summaries: None
    detail: str = ""       # error text / parse note (query strings redacted)
    raw_excerpt: str = ""  # <=200 chars of matched title+price text (evidence)

@dataclass(frozen=True)
class NormalizedComp:
    item_key: str            # ledger identity (set|item|variant|grade|condition)
    comp: float | None       # None when confidence == "unknown" — never invented
    comp_basis: str          # e.g. "min(tcgplayer,pricecharting) agree@20%"
    confidence: str          # "high" | "medium" | "low" | "unknown"
    confidence_reason: str   # human-readable rule that fired
    sources: tuple[CompSourceQuote, ...]  # EVERY source consulted, incl. failures
    ebay_floor: float | None       # cheapest matched active listing total (context)
    ebay_active_count: int | None  # matched active listings (velocity context)
    spread_pct: float | None       # |tcg - pc| / min(tcg, pc) * 100 when both ok
    captured_at: str         # ISO date
    stale: bool
```

**Source semantics** (`kind` is load-bearing — ask prices are never silently treated as
sold-derived):

| Source | kind | What it is | Acquisition |
| --- | --- | --- | --- |
| `tcgplayer` | sold_derived | TCGplayer "Market Price" for the exact product id (the number PPT resells) | §4.2 ladder |
| `pricecharting` | sold_derived | PriceCharting ungraded market summary (eBay-sold aggregate) | existing `PriceChartingSearchClient`, reused |
| `ebay_api` | active_ask | Browse API matched active fixed-price listings: median + floor + count | existing `EbayResaleClient` machinery, extended to also return floor + count |
| `ebay_public` | active_ask | HTML-parse fallback of public search (weakest) | existing `PublicEbaySearchClient` |
| `ppt` | validator | PPT free-tier by exact id, `limit=1` | existing client; `--validate` CLI only, never pipeline |

### 4.2 TCGplayer acquisition ladder (unknown → resolved by probe, evidence-first)

The seeded `ppt_id` **is** the TCGplayer product id (confirmed: sweep rows link
`tcgplayer.com/product/593355` etc.), so no search/resolution step is needed for catalog
items — direct product-URL fetch by id.

1. **Probe A (Slice 1, ~30 min):** plain `requests` GET of 2–3 product pages with the
   repo's standard browser UA. Grep response for embedded state (`__NEXT_DATA__`-style JSON
   or a marketPrice field). Save the raw responses under `tests/fixtures/comps/` as both
   evidence and parser fixtures.
2. **Probe B (same session):** if the page is a JS shell, observe (browser devtools via the
   session's Playwright MCP, supervised, no evasion) which XHR endpoint the page calls for
   price data, and test whether that endpoint answers plain requests.
3. **Fallback 1:** Playwright Python package (operator dependency decision, §10) fetching
   the product page on the pipeline's schedule.
4. **Fallback 2 (always safe):** `tcgplayer` source marked `blocked`; the engine runs on
   PriceCharting + eBay — max confidence MEDIUM (per §4.3), system fully functional.

The probe's outcome is recorded in the spec's implementation notes and in
`docs/poke/reference/` before Slice 1 is marked done. **No TCGplayer parsing code is
written until the probe fixes the acquisition path.**

### 4.3 Confidence resolution (exact rules, in precedence order)

Let `TCG` and `PC` be the sold-derived quotes, `EB` the eBay active-ask quote.
`tol = comps.agreement_tolerance_pct` (default **20**). "Agree" means
`|a - b| / min(a, b) * 100 <= tol`. Floor sanity: `EB.floor >= comp * (comps.ebay_floor_sanity_pct/100)`
(default **50 %** — an active floor at less than half the claimed comp means the market is
walking the price down; the sold-derived number is behind).

| Tier | Rule (first match wins) | comp value |
| --- | --- | --- |
| **HIGH** | TCG ok AND PC ok AND agree AND (EB absent/failed OR floor sane) | `min(TCG, PC)` (conservative) |
| **MEDIUM** | (a) TCG ok AND PC ok AND agree BUT floor insane → flag `floor_below_comp`; (b) exactly one sold-derived ok AND EB ok AND EB median within tol of it (ask-side corroboration); (c) TCG ok AND PC ok but disagree beyond tol → flag `source_spread`, comp = `min` | per rule |
| **LOW** | exactly one sold-derived ok, uncorroborated; OR only `ebay_api` ok with `sample_size >= 3` (comp = active median, basis explicitly `active_ask`); OR `premiumRatio >= 4.0` (existing guard — caps anything above to LOW, kept as-is per Phase-0 closure) | single source / median |
| **UNKNOWN** | nothing above fired (all failed; or only `ebay_public`/thin samples) | **None — no number, row carries no comp** |

Mapping to the existing row contract (so the STOP gate and STEAL logic behave): HIGH/MEDIUM
with an exact product URL → `price_confidence="verified"` eligible (unchanged
`sweep._provenance` logic); LOW/ask-basis → `est` + EST badge; UNKNOWN → row skipped from
deal math exactly like today's `no_comp`.

An `active_ask`-based comp **never** produces a STEAL badge: STEAL additionally requires a
sold-derived basis. Mechanism: `DealRow` gains a `comp_basis` field (§5.3) and
`score.assign_badges` adds `"active_ask" not in row.comp_basis` to the STEAL conditions,
keeping the existing verified-only rule too (owned by Slice 2).

### 4.4 Staleness rules

- Fresh: `fetched_at` within `comps.cache_ttl_seconds` (default 6 h) → serve from cache, no
  network.
- Aging: TTL exceeded → refetch; on refetch failure serve cached value with confidence
  **degraded one tier** and `stale=false` until 24 h old.
- Stale: > 24 h and unrefreshable → `stale=true` (renders with the existing stale flag),
  confidence capped LOW.
- Dead: > `poke.staleness_days` (30) → treated as UNKNOWN; never used in a verdict.

### 4.5 History maturation (observation ledger → momentum, later)

Every engine resolution appends one `market_comp` observation **per ok source per day**
(idempotent on the existing `(kind, item_key, source_url, capture_date)` key — per-source
URLs differ, so per-source rows coexist). Under the 2-hourly pipeline this yields ≥ 1
observation/source/item/day. **Momentum/trend signals are explicitly out of scope for this
build**; the maturation criterion for a future phase is recorded now: an item becomes
trend-eligible when it has ≥ 14 distinct capture dates for at least one sold-derived
source. The PPT paid tier's "6-month history" advantage decays to zero as this accrues.

### 4.6 PPT validator (optional, off hot path)

`python -m scanner.comps.validate --products key1,key2` — compares the engine's comp vs a
PPT `limit=1` lookup for the named products, prints deltas, appends nothing. Guarded by:
requires `market.api_key`, requires explicit operator go-ahead per repo CLAUDE.md (surfaced
credit estimate = 1/product), refuses to run if `X-RateLimit-Daily-Remaining < 15`
(the seeding hard-stop convention).

---

## 5. Purchasability verification (mandatory gate)

### 5.1 Contract (`scanner/discovery/verify.py`)

Input: `CandidateDeal` (or catalog product × retailer for board rows). Output:

```python
@dataclass(frozen=True)
class StockVerification:
    stock_status: str      # "in_stock" | "limited" | "out_of_stock" | "unverifiable"
    verified_price: float | None   # price READ FROM the live check, not the candidate ad
    price_matches: bool | None     # |verified - candidate| / candidate <= 5% (None if no price read)
    buy_url: str           # the URL a human clicks to buy — never empty on positive status
    checked_at: str        # ISO datetime of the live check
    method: str            # "retailer_adapter:target" | "ebay_api_item" | "page_fetch" | "none"
    evidence: str          # what was seen: raw status/price text or API field, <=300 chars
    degraded_reason: str   # why unverifiable, when it is ("no adapter for merchant X", "HTTP 403", ...)
```

Verification method by lane (all existing sanctioned paths — no new access patterns):

| Candidate origin | Method |
| --- | --- |
| Tracked catalog × big-box retailer | The retailer's existing adapter (`RedSky product_fulfillment` for Target, product `.js` for Pokémon Center, etc.) by product id. Statuses map: `IN_STOCK/ONLINE_IN_STOCK → in_stock`, `LIMITED → limited`, `OUT/ONLINE_OUT → out_of_stock`. |
| `ebay_browse` candidate | Browse API get-item by `listing_id` — the API response IS live availability + price. |
| `target_search` candidate | Resolve TCIN from the search result → same RedSky check as above. |
| `slickdeals` candidate | Points at a merchant URL. If the merchant has an adapter + resolvable id → adapter check. Else one plain GET of the product page: parse price + add-to-cart/in-stock signal; if the page resists parsing → `unverifiable` with `degraded_reason` (honest, no guessing). |

### 5.2 Hard rules

1. **No alert without:** `stock_status ∈ {in_stock, limited}` AND `verified_price` present
   AND `buy_url` present AND `evidence` non-empty AND `checked_at` set. Enforced twice:
   in `pipeline.py` (the only alert emitter) and by a **STOP-gate extension** in
   `schema.validate_row`: a row with positive `stock_status` missing
   `stock_evidence`/`buy_url`/`stock_checked_at` is a gate violation (halts the render, same
   as a fabricated price).
2. **Verdict runs on `verified_price`, never the advertised price.** If
   `price_matches is False` the row carries a `PRICE_CHANGED` warn flag and the margin is
   recomputed at the verified number.
3. "MSRP, stock unknown" rows (today's board) remain legal **board** content in a clearly
   separated "reference — not verified buyable" section, and remain alert-illegal.
4. Verification is rate-limited like everything else (per-retailer politeness via
   `retailers/http.py`); at most one verification per candidate per pipeline run; positive
   results re-verified only on the alert path (a push always reflects a check from its own
   run, never a cached one).

### 5.3 DealRow schema additions (backward-compatible; `row_from_dict` already ignores unknowns)

```python
buy_url: str = ""           # click-to-buy link (distinct from source_url = comp attribution)
stock_checked_at: str = ""  # ISO datetime of the stock check
stock_method: str = ""      # verification method slug
comp_basis: str = ""        # NormalizedComp.comp_basis passthrough (STEAL basis check, §4.3)
```

`stock_status` vocabulary widens from freeform to
`{"unknown", "in_stock", "limited", "out_of_stock", "unverifiable"}` (validated by the gate).

---

## 6. Discovery breadth — source × product basket strategy

Not overfit to named examples: coverage is defined by **rings**, and every ring is
config-driven, not hardcoded.

**Ring 1 — tracked catalog (`data/products.yaml`).** Full treatment: restock lane
(existing adapters), discovery lanes, comp engine, verification, alerts. Includes Pokémon
Center exclusives once their `pokemoncenter_slug`s are seeded (data task, §10 — the adapter
already exists).

**Ring 2 — set-watch (`discovery.set_watch` config list, e.g. current + last ~6 sets).**
Adapters match any sealed listing whose title resolves to a watched set (token matching
reuses `resale._title_allowed` + `NEGATIVE_TITLE_PARTS` exclusions). Non-catalog matches get
ad-hoc comps (item-key by parsed set/type), render + alert on the same rules, and the
pipeline emits a **catalog-addition proposal** into the run manifest (operator adds to
products.yaml manually — never auto-added).

**Ring 3 — wildcard Pokémon sealed.** Anything else Pokémon-sealed an adapter surfaces:
board "discovered" section only, alert **only** when verification passes AND comp
confidence ≥ `discovery.min_alert_confidence` (default `medium`). This keeps the eBay lane
one lane among several — a wildcard ask-basis listing can never out-shout a verified
big-box restock.

**Source basket at launch:** restock lane = Target, Walmart, Best Buy, Costco, GameStop,
Pokémon Center (existing adapters, sanctioned endpoints); discovery lane = Target search +
Slickdeals (plain fetch) + eBay Browse (keyset-gated); curator lane (TrackaLacker) + heavy
search pages (TCGplayer/BestBuy/Costco search) staged behind the Playwright decision.
Reddit stays out (API-only, no credentials, bot-wall doctrine).

---

## 7. Implementation phasing — independently shippable slices

Every slice: full suite green before merge (`.venv/Scripts/python.exe -m pytest -q`),
conventional commits, review gates per SDD flow. No slice depends on a later slice.

### Slice 1 — Comp engine v1 (contracts + 3 sources + validator)
- **Files:** new `scanner/comps/{__init__,model,tcgplayer,pricecharting,ebay,ppt_validator,engine}.py`;
  new `tests/test_comps_{model,engine,tcgplayer,pricecharting,ebay}.py`;
  new `tests/fixtures/comps/*`; edit `scanner/config.py` (+`comps` block),
  `config.example.yaml`; edit `scanner/state.py` (+`comp_cache` table);
  edit `scanner/discovery/sweep.py` (`LiveCompLookup` gains `comps.engine: inhouse|legacy`
  switch; default **legacy** until Slice 6 flips it); edit `scanner/discovery/ledger.py`
  only if per-source observations need a field (`source` key inside obs — no schema break).
- **Also in-slice:** the TCGplayer acquisition probe (§4.2) with evidence saved; outcome
  recorded before parser code is written.
- **Acceptance:** engine returns legacy-shaped rows consumable by `comp_from_row` +
  `_provenance` byte-compatibly for the fields they read; confidence matrix table-test
  passes (≥ 12 cases: each tier + each degradation edge); UNKNOWN yields no number
  anywhere; cache honors TTL; `--validate` refuses without key/go-ahead/credit floor;
  suite green.
- **Test commands:** `.venv/Scripts/python.exe -m pytest tests/test_comps_model.py tests/test_comps_engine.py -q` then full suite.
- **Rollback risk:** **Low.** New package + additive config; sweep default stays `legacy`
  (one-line revert of the switch).

### Slice 2 — Purchasability verifier + stock evidence fields
- **Files:** new `scanner/discovery/verify.py`; new `tests/test_poke_verify.py`; edit
  `scanner/discovery/schema.py` (4 new DealRow fields + gate extension §5.3, widened
  `stock_status` vocabulary); edit `scanner/discovery/score.py` (STEAL additionally
  requires a non-`active_ask` `comp_basis`, §4.3); edit `tests/test_poke_schema.py` +
  `tests/test_poke_score.py` (gate + badge cases); edit `scanner/discovery/sweep.py`
  (optional `--verify-stock` flag: catalog rows get verified stock via enabled retailer
  adapters; board gains truthfully-filled stock columns); edit
  `scanner/discovery/render.py` (render stock column when present).
- **Acceptance:** gate rejects positive-status rows lacking evidence/buy_url/checked_at
  (unit-proven); verifier maps every adapter status correctly (table test); merchant-page
  fallback returns `unverifiable` + reason on unparseable HTML (fixture-proven);
  `--verify-stock` sweep on mocked adapters produces rows with populated
  `stock_status/stock_evidence/buy_url`; an `active_ask`-basis row can never carry STEAL
  (badge test); suite green.
- **Test commands:** `.venv/Scripts/python.exe -m pytest tests/test_poke_verify.py tests/test_poke_schema.py tests/test_poke_sweep.py -q` then full.
- **Rollback risk:** **Low-medium.** Schema fields are default-valued (old JSON loads fine);
  the gate extension only fires on rows claiming positive stock, which nothing produces
  until this slice's own flag is used.

### Slice 3 — Discovery adapters emitting normalized candidates
- **Files:** new `scanner/discovery/candidates.py` (CandidateDeal + matching); new
  `scanner/discovery/adapters/{__init__,base,target_search,slickdeals,ebay_browse}.py`;
  new `tests/test_disc_{candidates,target_search,slickdeals,ebay_browse}.py` + fixtures
  (saved real HTML from the fetchable-plain sources; recorded Browse JSON); edit
  `scanner/config.py` (+`discovery` block); edit `scanner/state.py` (+`seen_listings`).
- **Acceptance:** each adapter parses its populated fixture to ≥ N expected candidates with
  exact prices/URLs and its empty fixture to zero rows without error; catalog/set-watch
  matching resolves the right product for ≥ 5 tricky titles (bundle-vs-ETB,
  exclusive-vs-standalone) and rejects `NEGATIVE_TITLE_PARTS` cases; eBay adapter without
  keyset reports `NEEDS_API_KEY` and yields `[]`; `listing` ledger kind appends
  idempotently; suite green.
- **Test commands:** `.venv/Scripts/python.exe -m pytest tests/test_disc_candidates.py tests/test_disc_target_search.py tests/test_disc_slickdeals.py tests/test_disc_ebay_browse.py -q` then full.
- **Rollback risk:** **Low.** Pure additive; nothing calls the adapters until Slice 4.

### Slice 4 — Pipeline + scheduler + dedupe
- **Files:** new `scanner/discovery/pipeline.py` (one-shot orchestrator + CLI); new
  `scripts/register_tasks.ps1` (+ unregister); new `tests/test_poke_pipeline.py`; edit
  `scanner/state.py` (+`deal_alerts` + adapter `last_run` usage); edit `scanner/config.py`
  (+`alerts` block: quiet_hours, price_drop_realert_pct, cooldown_hours).
- **Acceptance:** with fake stages injected, the pipeline: respects per-adapter
  `min_interval_seconds`; dedupes per §3.4 matrix (5 cases); enforces
  no-alert-without-evidence; suppresses ntfy in quiet hours but writes the board; produces
  a manifest whose counts reconcile
  (`candidates == alerted + suppressed_dupe + unverifiable + out_of_stock + no_comp + below_floor`);
  `--dry-run` makes zero network calls (asserted via a spy session); suite green.
  `register_tasks.ps1` is reviewed but only **run manually by the operator**.
- **Test commands:** `.venv/Scripts/python.exe -m pytest tests/test_poke_pipeline.py tests/test_state_history.py -q` then full.
- **Rollback risk:** **Medium.** Touches `state.db` schema (additive `CREATE TABLE IF NOT
  EXISTS` — same pattern as existing tables, no migration needed) and introduces the
  scheduled entry point. Rollback = unregister tasks + revert; tables are inert if unused.

### Slice 5 — Alert payloads + dashboard "Buyable now" section
- **Files:** edit `scanner/notify.py` (+`DealAlert` dataclass + `Notifier.send_deal`,
  mirroring `StockAlert`/embed patterns); edit `scanner/discovery/render.py` +
  `template.html` (new top section **"Buyable now"** — only rows with positive verified
  stock, ordered by verdict tier then pct_off; existing sections become the reference
  board); edit `scanner/discovery/golden.py` (golden checks for the new section: it must
  never contain a row without stock evidence — belt over the STOP-gate suspenders); new/edit
  `tests/test_notify_deal.py`, `tests/test_poke_render.py`, `tests/test_poke_golden.py`.
- **DealAlert payload (fields):** `item, retailer, buy_url, verified_price, msrp, comp,
  comp_confidence, comp_basis, pct_off, verdict_headline, stock_status, stock_evidence,
  checked_at, source_adapter, listing_id, badges, warn_flags`.
- **Acceptance:** Discord embed + ntfy body contain buy_url, verified price, comp with
  confidence label, verdict, and evidence timestamp (string-asserted); a
  below-`min_alert_confidence` Ring-3 candidate renders on the board but produces no
  `send_deal` call; golden fails a buyable-now row lacking evidence; suite green.
- **Test commands:** `.venv/Scripts/python.exe -m pytest tests/test_notify_deal.py tests/test_poke_render.py tests/test_poke_golden.py -q` then full.
- **Rollback risk:** **Low.** Additive alert type + template section.

### Slice 6 — Hardening, drift canaries, docs/runbook, cutover
- **Files:** new `tests/test_parser_drift.py` (§8); new `docs/poke/buyable-pipeline-runbook.md`
  (operate/inspect/rollback/quiet-hours/how-to-add-a-source/how-to-read-degradations);
  edit `scanner/discovery/sweep.py` (flip `comps.engine` default → `inhouse` after the
  side-by-side check passes); edit repo `CLAUDE.md` **only if** operator approves adding
  the no-alert-without-evidence line to the always-on guardrails; final review wave per
  SDD flow.
- **Acceptance:** side-by-side run (mocked): legacy vs inhouse comp rows for the seeded
  catalog produce verdict-compatible outputs or documented deltas; degraded-matrix test
  (each source down in turn → pipeline completes with honest downgrades); **final live
  smoke run with operator go-ahead** (§8.3) proving ≥ 1 candidate flows through as verified
  or honestly degraded end-to-end; suite green; runbook reviewed.
- **Test commands:** full suite + the live smoke checklist in the runbook.
- **Rollback risk:** **Low-medium** (the cutover flag flip is one line; live smoke is
  read-only network).

---

## 8. Testing & verification requirements (cross-slice, non-negotiable)

1. **Fixture-based scraper tests:** every parser (comp sources, adapters, verifier page
   fallback) ships with saved real payloads under `tests/fixtures/` — a populated case and
   an empty/no-results case minimum. No test touches the network (existing repo rule).
2. **Parser drift canaries** (`tests/test_parser_drift.py`): for each HTML parser, a
   structural assertion set (e.g. "fixture contains ≥ N price-bearing blocks the selector
   matches") plus a runtime canary already patterned in the repo (`PARSER_SUSPECT` on
   HTTP-200-zero-rows) — asserted to fire on a deliberately gutted fixture.
3. **API-absent/degraded tests:** eBay keyset missing → comp source `not_configured`,
   adapter `NEEDS_API_KEY`, pipeline completes, confidence caps honored. Same for each
   source individually down (403 / timeout / garbage HTML / empty JSON).
4. **Scheduler dedupe tests:** the §3.4 matrix — new listing alerts; unchanged listing
   within cooldown doesn't; ≥ 5 % price drop re-alerts; status flip re-alerts; cooldown
   expiry re-alerts.
5. **No-alert-without-stock-evidence test (the design's reason to exist):** construct a
   maximal-margin, high-confidence candidate with `stock_status="unknown"` → assert zero
   notifier calls AND the row lands in the reference section AND the STOP-gate extension
   rejects a hand-built positive-status row missing evidence.
6. **Dashboard/API contract tests:** buyable-now section ordering; stock column rendering;
   `_safe_href` applied to `buy_url` (untrusted input, same XSS posture as `source_url`);
   golden checks for the new section.
7. **Ledger/history tests:** per-source `market_comp` idempotency; new `listing` kind
   round-trip; `price_history.jsonl` grows exactly one row per (source, item, day).
8. **Final smoke run (operator-gated, live network, zero PPT credits):** run
   `python -m scanner.discovery.pipeline --once --sources target_search,slickdeals` live;
   success = manifest shows ≥ 1 candidate reaching `verified` (alert fires with buy link)
   **or** every candidate honestly classified (`unverifiable`/`out_of_stock`/`no_comp`)
   with evidence strings — no silent drops, counts reconcile. This is the definition of
   "the pipeline tells the truth" and gates calling the build done.

---

## 9. Final deliverables reference

### 9.1 Module layout (new/changed)

```
scanner/
  comps/                    # NEW — in-house comp engine (WS1)
    __init__.py
    model.py                # CompSourceQuote, NormalizedComp, confidence resolution (pure)
    tcgplayer.py            # sold-derived source (acquisition per §4.2 probe)
    pricecharting.py        # wraps existing resale.PriceChartingSearchClient
    ebay.py                 # active-ask source: median + floor + count (wraps Browse machinery)
    ppt_validator.py        # off-hot-path spot check (+ validate CLI)
    engine.py               # fan-out, triangulate, cache, ledger, legacy-dict emit
  discovery/
    candidates.py           # NEW — CandidateDeal + catalog/set-watch matching (WS2)
    adapters/               # NEW — discovery sources (WS2)
      __init__.py           # registry {slug: class}, mirrors retailers/__init__.py
      base.py               # DiscoverySource interface
      target_search.py, slickdeals.py, ebay_browse.py
      trackalacker.py       # wave-2, Playwright-gated (stub w/ NOT_IMPLEMENTED until then)
    verify.py               # NEW — purchasability verifier (WS3)
    pipeline.py             # NEW — one-shot orchestrator + CLI (WS4)
    schema.py               # EDIT — +buy_url/stock_checked_at/stock_method, gate extension
    sweep.py                # EDIT — engine switch, --verify-stock
    render.py, template.html, golden.py   # EDIT — buyable-now section + goldens
  notify.py                 # EDIT — +DealAlert + send_deal
  state.py                  # EDIT — +comp_cache, seen_listings, deal_alerts tables
  config.py                 # EDIT — +comps/discovery/alerts blocks
scripts/register_tasks.ps1  # NEW — Task Scheduler registration (operator-run)
docs/poke/buyable-pipeline-runbook.md   # NEW — Slice 6
```

### 9.2 Data schema changes

- `DealRow`: `+buy_url, +stock_checked_at, +stock_method, +comp_basis`; `stock_status`
  vocabulary fixed; STOP-gate extension (§5.2-1). Backward compatible (defaults;
  `row_from_dict` tolerant).
- `state.db`: `+comp_cache(item_key, payload_json, fetched_at)`;
  `+seen_listings(source, listing_id, price, status, first_seen, last_seen)`;
  `+deal_alerts(source, listing_id, price, status, ts)`. All `CREATE TABLE IF NOT EXISTS`,
  no migrations.
- Ledger `VALID_KINDS`: `+{"listing"}`; `market_comp` observations gain a `source` field
  inside the obs dict (non-breaking; identity key unchanged).
- `config.yaml` (example additions):

```yaml
comps:
  engine: legacy            # flips to inhouse in Slice 6
  agreement_tolerance_pct: 20
  ebay_floor_sanity_pct: 50
  cache_ttl_seconds: 21600
discovery:
  enabled: true
  interval_seconds: 7200
  sources: [target_search, slickdeals, ebay_browse]
  set_watch: ["Prismatic Evolutions", "Destined Rivals", "Journey Together",
              "Surging Sparks", "Scarlet & Violet 151", "Paldean Fates", "Crown Zenith"]
  min_alert_confidence: medium
alerts:
  quiet_hours: "23:00-08:00"
  price_drop_realert_pct: 5
  cooldown_hours: 24
```

### 9.3 Adapter interface + candidate schema

```python
# scanner/discovery/adapters/base.py
class DiscoverySource:
    slug: str = ""
    min_interval_seconds: int = 900
    requires: str = ""        # "" | "ebay_keyset" | "playwright"
    def discover(self, cfg, catalog, set_watch) -> list[CandidateDeal]: ...
    # raises nothing; degradations are returned via health/status, not exceptions

# scanner/discovery/candidates.py
@dataclass(frozen=True)
class CandidateDeal:
    source: str               # adapter slug
    listing_id: str           # stable id (eBay itemId, TCIN, else sha256(url))
    item_name: str            # raw title as parsed
    price: float              # advertised item price, USD
    shipping: float | None
    url: str                  # direct listing/product URL
    retailer: str             # merchant name
    seen_at: str              # ISO datetime
    evidence_excerpt: str     # raw title+price text, <=200 chars
    matched_product_key: str | None   # catalog key when resolved (Ring 1)
    matched_set: str          # set-watch resolution (Ring 2), "" for Ring 3
    asset_class: str = "sealed"
    variant: str = ""
    condition_note: str = ""
```

### 9.4 Taxonomies (single source of truth each)

- **Comp confidence:** `high / medium / low / unknown` (§4.3) — feeding the existing
  `verified/est` row provenance unchanged.
- **Stock:** `unknown / in_stock / limited / out_of_stock / unverifiable` (§5).
- **Source operational state:** `scanner/confidence.py` states, reused (§3.2).
- **Per-source quote status:** `ok / no_match / blocked / error / not_configured / skipped`.

### 9.5 Implementation order & rationale

1 (comps) → 2 (verify) → 3 (adapters) → 4 (pipeline/scheduler) → 5 (alerts/board) →
6 (hardening/cutover). 1–3 are independent of each other in code but this order front-loads
the two contracts everything else consumes (comp shape, verification gate). Each slice
ships value alone: after 2, even the existing board stops saying "stock unknown" for
catalog items; after 4+5, the phone buzzes with verified buyables.

### 9.6 Open questions / blockers (operator)

1. **eBay keyset** — provision per `docs/poke/ebay-keyset-setup.md` (~15 min, free).
   Until then: `ebay_browse` adapter and `ebay` comp source run `NEEDS_API_KEY`/degraded
   (HIGH-tier comps still reachable via TCG+PC agreement).
2. **Playwright Python dependency** (gates TrackaLacker + heavy search pages + TCGplayer
   fallback-1): ~1 package + ~300 MB browser download. **Recommend yes, decided by the
   time Slice 3 lands** — but nothing in Slices 1–6 hard-requires it (TCGplayer has the
   probe ladder; wave-2 adapters stay stubbed `NOT_IMPLEMENTED`).
3. **Discord webhook / ntfy topic** — confirm at least one is set in `config.yaml`
   (alerts otherwise land console-only; pipeline still works).
4. **Pokémon Center slugs** — seed `pokemoncenter_slug` for catalog items + wanted
   exclusives (data task, no credits; enables the PC restock lane for exclusives).
5. **Task Scheduler go-live** — operator runs `scripts/register_tasks.ps1` after Slice 4
   review (script is written by the build, executed by the human).
6. **Live smoke go-ahead** at Slice 6 (network-touching; zero PPT credits).
7. *(closed this session)* PPT paid tier — rejected; free-tier validator only.

### 9.7 Definition of done (whole build)

- Full suite green including all new tests; every parser fixture-backed; drift canaries in.
- A scheduled pipeline run on this machine produces: an updated dashboard whose
  **Buyable now** section contains only stock-evidenced rows; pushes (when channels
  configured) that each contain buy link + verified price + evidenced stock + comp with
  honest confidence + fee-adjusted verdict; a manifest whose counts reconcile with zero
  silent drops.
- The comp engine serves catalog comps from ≥ 2 independent sources with the §4.3 tiers,
  PPT nowhere in the hot path, and per-source history accruing in the ledger.
- The no-alert-without-evidence invariant is enforced at both the pipeline and STOP-gate
  layers and covered by tests.
- Runbook exists; rollback for every slice documented above; nothing pushed to any remote.

---

## Appendix A — Builder prompt for Slice 1 (verbatim build packet)

Hand the following to a `/pokebuild` session as the build packet (or to any builder with
repo access). It is self-contained but assumes the builder reads this spec.

> **Build Slice 1 of `docs/superpowers/specs/2026-07-02-buyable-deal-pipeline-design.md`:
> the in-house comp engine v1.**
>
> **Read first (in this order):** the spec §4 (comp engine — normalized objects,
> confidence rules, staleness, validator), §3.1 (workstream contract), §9.2 (config/schema
> additions), §2 (guardrails); then `scanner/resale.py` (quote-dict shape, `annotate_quote`,
> existing eBay/PriceCharting clients), `scanner/market.py` (`comp_from_row`, PPT client,
> `limit=1` invariant), `scanner/discovery/sweep.py` (`LiveCompLookup`, `_provenance`),
> `scanner/state.py` (table patterns), `scanner/config.py` (config wiring patterns),
> `scanner/discovery/ledger.py`.
>
> **Step 0 — TCGplayer acquisition probe (do this before writing any TCGplayer parser):**
> per spec §4.2. Plain-requests GET of 2–3 `tcgplayer.com/product/<ppt_id>` pages for
> seeded catalog ids with the repo's standard browser UA. Save raw responses to
> `tests/fixtures/comps/`. If usable embedded price JSON exists → that is the parse target.
> If not, STOP and report the probe evidence to the operator with the §4.2 ladder options —
> do not improvise scraping approaches, do not add dependencies, do not evade anything.
> Build the rest of the slice regardless (the engine must run TCGplayer-degraded).
>
> **Build (new package `scanner/comps/`):**
> 1. `model.py` — `CompSourceQuote`, `NormalizedComp` (frozen dataclasses, fields exactly
>    per spec §4.1) + `resolve_confidence(quotes, msrp, cfg) -> NormalizedComp` implementing
>    the §4.3 precedence table verbatim (tolerance/floor-sanity formulas as specified;
>    `min()` comp selection; premium ≥ 4.0 caps LOW; UNKNOWN → comp None). Pure, no I/O.
> 2. `pricecharting.py`, `ebay.py` — wrap the existing `resale.PriceChartingSearchClient`
>    and eBay Browse machinery into `CompSourceQuote` producers; `ebay.py` additionally
>    returns floor + matched count and reports `not_configured` when
>    `resale.auth_configured(cfg)` is false. Do not duplicate parsing logic — call into
>    `resale`.
> 3. `tcgplayer.py` — per probe outcome (or a `blocked`-status stub if the probe deferred
>    to the operator).
> 4. `engine.py` — `CompEngine.estimate(product_key, product, checked_at) -> dict`: fan out
>    to sources (politeness ≥ 1 s/host), resolve, cache in the new `state.db` `comp_cache`
>    table (TTL `comps.cache_ttl_seconds`), append per-source `market_comp` ledger
>    observations, and return a **legacy-shaped quote dict** carrying every key
>    `market.comp_from_row` and `sweep._provenance` read (`status/estimate/url/sourceUrl/
>    confidence/confidenceReason/source/basis/...`) plus the new
>    `comp_basis/ebay_floor/ebay_active_count/sources` extras.
> 5. `ppt_validator.py` — `python -m scanner.comps.validate` per spec §4.6 (refuses without
>    key, prints credit estimate and requires explicit `--yes`, hard-stops below 15
>    remaining, `limit=1` pinned).
> 6. Config: `comps` block (`engine: legacy` default, tolerances, TTL) in `config.py` +
>    `config.example.yaml`; `LiveCompLookup` honors `comps.engine` (`inhouse` swaps the
>    engine in; default `legacy` — behavior today must not change).
> 7. Tests (network-mocked, fixtures under `tests/fixtures/comps/`): confidence matrix
>    ≥ 12 cases; per-source normalization from fixtures; cache TTL hit/miss/expiry;
>    all-degraded → UNKNOWN with no number; legacy-dict key-compat asserted against a real
>    `_provenance` + `comp_from_row` round-trip; validator refusal paths.
>
> **Guardrails (STOP-class):** never fabricate a price; UNKNOWN means no number; every
> quote carries URL + timestamp; `limit=1` on any PPT call; no live PPT calls in tests or
> without operator go-ahead; no new dependencies; never push.
>
> **Done when:** `.venv/Scripts/python.exe -m pytest -q` fully green; default-config
> behavior byte-identical for existing tests; probe evidence committed; conventional
> commits (`feat(comps): ...`, `test(comps): ...`, `docs(poke): ...` for probe notes);
> `.superpowers/sdd/progress.md` gains a Slice-1 ledger entry.
