# Private Sealed Price API v1 (Tracks A + B)

A local, read-first, PokemonPriceTracker-class API over **our own** comp engine
and evidence ledger. It exposes sealed comps + price history/momentum through
stable endpoints so callers never need to know which source a number came from.

**Structurally PPT-free.** No endpoint here calls PokemonPriceTracker. Every
response reports `apiCallsConsumed.total = 0`. This is the first two rungs of the
north-star ladder:

- **A — Private Sealed API v1** (this doc): stable sealed comp + catalog endpoints.
- **B — History + Momentum Engine** (this doc): `price_history.jsonl` becomes a
  queryable time-series (latest, source history, freshness, momentum).
- **C — Opportunity + Paper-Trade Lab** — BUILT; see
  [`money-hypothesis-lab.md`](money-hypothesis-lab.md). Adds opportunity scoring
  + an append-only paper-trade ledger with outcome replay + signals, and the
  `/api/poke/opportunities`, `/paper-decisions`, `/signals` endpoints.
- **D — Raw + Graded source expansion** — BUILT; see *Track D* below. Adds a
  separate raw/graded asset catalog, honest source adapters, per-identity
  history/momentum, owned asset endpoints, and conservative (never-live)
  raw/graded WATCH opportunities.
- E — Better-than-PPT personal edge layer *(future; strategy/ranking/decision
  packets — deliberately NOT built in D)*.

Code: `scanner/poke_api/` — `history.py` (pure ledger reads/index/momentum),
`model.py` (response shaping + PPT facade), `router.py` (dispatch + read-first
comp policy). Served by `scanner/web.py` (`python -m scanner.web`, default
`http://127.0.0.1:8765`).

---

## Endpoints

All are `GET`. Field names are camelCase where they mirror PPT (`tcgPlayerId`,
`unopenedPrice`, `checkedAt`); the URL/product identifier is `product_key`.

### `GET /api/poke/products`
Catalog product list.
```json
{
  "ok": true,
  "count": 22,
  "products": [
    {"product_key": "journey_together_booster_bundle",
     "name": "Journey Together Booster Bundle", "set": "Journey Together",
     "type": "Booster Bundle", "msrp": 26.94,
     "tcgPlayerId": "610953", "ppt_id": "610953"}
  ]
}
```
`tcgPlayerId` / `ppt_id` are `null` for products without a mapped id.

### `GET /api/poke/products/{product_key}/comp?refresh=false`
Latest sealed comp for one product, in owned shape.
```json
{
  "ok": true,
  "product_key": "journey_together_booster_bundle",
  "name": "Journey Together Booster Bundle",
  "tcgPlayerId": "610953",
  "status": "ok",
  "estimate": 49.94,
  "unopenedPrice": 49.94,
  "confidence": "medium",
  "confidenceReason": "latest recorded market_comp (no fresh comp cache)",
  "compBasis": "ledger latest",
  "sources": [{"source": "tcgplayer", "status": "ok", "price": 49.94, "url": "..."}],
  "sourceUrl": "https://www.tcgplayer.com/product/610953",
  "checkedAt": "2026-07-03",
  "cacheHit": false,
  "stale": false,
  "detail": ""
}
```
Comp-source policy (`refresh`, default `false`):
- **`refresh=false`** — never touches the network. Serves, in order: (1) the
  in-house comp cache (offline), (2) the latest ledger `market_comp` (offline),
  (3) an honest `no_history` payload with `estimate: null`.
- **`refresh=true`** — runs `CompEngine.estimate` for that product (may fetch its
  PPT-free sources: TCGplayer, PriceCharting, eBay ask). Still 0 PPT credits.

A harmless browser GET never triggers slow/network work unless you pass
`refresh=true`.

### `GET /api/poke/products/{product_key}/history`
Ledger-backed observations for the product, grouped by source and kind.
```json
{
  "ok": true,
  "product_key": "journey_together_booster_bundle",
  "item_key": "journey together|journey together booster bundle|||",
  "observations": 4,
  "byKind": {"market_comp": 2, "deal": 2},
  "bySource": {"tcgplayer": [{"date": "2026-07-01", "price": 48.81, "confidence": "medium"}]},
  "priceHistory": [{"date": "2026-07-01", "price": 48.81, "source": "tcgplayer", "confidence": "medium"}]
}
```

### `GET /api/poke/products/{product_key}/momentum`
Latest/trend summary from ledger data.
```json
{
  "ok": true,
  "product_key": "journey_together_booster_bundle",
  "momentum": {
    "status": "ok",
    "latest": 49.94, "previous": 48.81,
    "delta_abs": 1.13, "delta_pct": 2.32,
    "observations": 2, "distinct_dates": 2,
    "sources": ["tcgplayer"],
    "first_seen": "2026-07-01", "last_seen": "2026-07-03",
    "latest_confidence": "medium",
    "stale_days": 1, "stale": false
  }
}
```

### `GET /api/poke/sealed-products?tcgPlayerId=<id>`
PPT-compatible facade for local drop-in use. Resolves the id against catalog
`ppt_id`. Shape mirrors PPT's `/sealed-products` closely enough to swap for it
locally:
```json
{
  "data": {
    "tcgPlayerId": "610953",
    "tcgPlayerUrl": "https://www.tcgplayer.com/product/610953",
    "name": "Journey Together Booster Bundle",
    "setName": "Journey Together",
    "unopenedPrice": 49.94,
    "priceHistory": [{"date": "2026-07-01", "price": 48.81, "source": "tcgplayer", "confidence": "medium"}],
    "lastScrapedAt": "2026-07-03",
    "updatedAt": "2026-07-03",
    "confidence": "medium",
    "confidenceReason": "...",
    "sources": [...],
    "momentum": {...}
  },
  "metadata": {"source": "local", "apiCallsConsumed": {"total": 0}}
}
```
An unmapped `tcgPlayerId` returns a well-formed empty facade (`data.status =
"no_match"`, `unopenedPrice: null`) with HTTP 200 — a miss is data, not an error.
A missing `tcgPlayerId` param is HTTP 400.

---

## Source & confidence meanings

- **`sources[]`** — the contributing source quotes behind a comp (tcgplayer,
  pricecharting, ebay ask). Each carries its own `url` for attribution.
- **`confidence`** — from the in-house comp resolver (`scanner/comps/model.py`):
  `high` (two sold-derived sources agree within tolerance), `medium` (single
  sold-derived source with ask corroboration, or a source spread), `low`
  (single/uncorroborated or ask-only), `none` (no usable source — comp is
  `null`, never invented).
- **`compBasis`** — how the number was derived (e.g. `min(tcgplayer,pricecharting)
  agree@20%`, or `ledger latest` when served from history).
- **`cacheHit` / `stale`** — whether the comp came from the in-house cache and
  whether it exceeded the staleness ladder.

**Price accuracy is STOP-class.** No source → no number. Every price carries its
source URL and capture date. Estimates are never presented as sold comps.

## How history & momentum are computed

- The reader (`history.read_ledger`) parses `data/poke/price_history.jsonl`
  line-by-line. Malformed / non-object lines are **skipped and counted**
  (`malformed`), never fatal. A missing file reads as empty.
- A product maps to a ledger `item_key` as `set|name|||` (lowercased) — identical
  to how `comps/engine.py` and `discovery/sweep.py` stamp observations, verified
  against the live ledger.
- **Source** for an observation is its explicit `source` field when present
  (engine-written rows), else derived from the `source_url` host
  (sweep-written rows).
- **Momentum** collapses observations to **one canonical value per capture_date**
  (last-appended wins), then compares the two most recent *distinct dates*.
  `previous` is the value on the most recent earlier date, so `delta` is genuine
  day-over-day movement — a same-day multi-source write can never fake a delta.
  `status`: `no_history` (0 obs), `single_observation` (one date; latest surfaced,
  no delta), `ok` (≥2 dates). `stale_days` = `today − last_seen`; `stale` when it
  exceeds `poke.staleness_days` (default 30).

The ledger is **read, never rewritten** by this layer.

---

## Track D — Raw + Graded source expansion

First-class raw single + graded slab support through the **owned** `/api/poke`
layer. Source/data expansion, not strategy: no rankings, decision packets,
grading-EV, or buy logic (that is Session E).

**Catalog.** Raw/graded assets live in a **separate** `data/poke/assets.yaml`
(the sealed `data/products.yaml` is never touched). Loaded by
`scanner/poke_api/catalog.py`:

- `raw` needs `name`, `set`, `condition` (`card_number` when known); optional
  `tcgplayer_id` / `pricecharting_slug` / `ebay_query`.
- `graded` needs `name`, `set`, `grader`, `grade`; a normalized `grade_key`
  (`psa10`, `cgc9.5`) is derived if omitted; same optional source ids.

**Identity.** `history.item_key_for_asset` fills the ledger key's
`variant`/`grade`/`condition` slots (`card_number` → variant, `grade_key` →
grade, `condition` → condition), so raw NM, raw LP, PSA 10, PSA 9, and the
all-empty sealed key never collide. Sealed `item_key_for_product` is unchanged.

**Sources (`scanner/poke_api/sources.py`).** A small, strategy-free interface:

- **Raw** routes through the in-house confidence ladder
  (`comps.model.resolve` → `to_legacy_row`): sold-derived quotes (TCGplayer /
  PriceCharting card, plus the PPT `/cards` market price when configured) + an
  optional eBay active ask. Two agreeing sold sources → `high`; one → `medium`/
  `low`; ask-only → `low`; none → `none`. An ask can never be more than `low`.
- **Graded** uses PPT `/cards?...&includeEbay=true&limit=1` →
  `smartMarketPrice.price` as the comp with `smartMarketPrice.confidence` passed
  through 1:1; PriceCharting graded page is the fallback. The eBay ask is
  validator/context — **structurally it can never become the graded comp**.
- The PPT `/cards` client is **dormant by default**: built only when
  `market.preferred` + a key are set, always requests `limit=1`, and degrades to
  no-price on 401/429/transport error rather than crashing.

**Endpoints (all GET, read-first, 0 credits):**

- `GET /api/poke/assets` — the raw/graded catalog + which source ids are mapped.
- `GET /api/poke/assets/{asset_key}/comp?refresh=false` — read-first (ledger
  latest, offline) asset comp; `refresh=true` runs the source resolver (honest
  `none` unless a source is mapped **and** configured). **Money-class caveat:**
  `refresh=true` is the *only* asset surface that can spend PPT credits — when
  `market.preferred` + a key are set it makes a live billed `/cards` call (1 raw,
  2 graded). Dormant by default (`market.preferred: false`), so the read path is
  0 credits; get operator go-ahead before enabling it.
- `GET /api/poke/assets/{asset_key}/history` — per-identity ledger observations.
- `GET /api/poke/assets/{asset_key}/momentum` — per-identity movement summary.
- `GET /api/poke/cards?tcgPlayerId=<id>&condition=NM` (raw) or `&grade=psa10`
  (graded) — PPT-`/cards`-compatible facade. One id maps to several assets, so an
  id with no discriminator matching >1 asset returns `status: "ambiguous"` with
  the candidate list — never a guessed variant.

**Lab integration.** Raw/graded assets appear in `/api/poke/opportunities` as
**WATCH-grade evidence rows** with the conservative trade types `raw_catalog_gap`
/ `raw_market_watch` / `graded_catalog_gap` / `graded_market_watch`. **None are
live-eligible** — an asset opportunity is always `WATCH`, never
`LIVE_PACKET_ELIGIBLE`, regardless of the numbers (there is no verified-entry buy
wire for singles in D). The sealed dormancy / activation report (`/signals`,
`/candidates/report`) stays **sealed-scoped**.

Honest by default: with unmapped/unconfigured assets every asset reports
`estimate: null`, confidence `none` — no source, no number (STOP-class).

---

## Current limitations

- **Raw/graded are source-expansion only (Track D).** Assets resolve comps and
  surface as WATCH rows, but have no verified-entry buy wire and are never
  live-eligible; strategy/ranking/decision packets are Session E.
- **Raw/graded comps resolve only when a source is mapped AND configured.** With
  the dormant PPT `/cards` client (default), assets report honest `none`.
- **No paper-trade / outcome loop.** Opportunity scoring and paper trades are
  Phase C (recommended next session).
- **History depth = ledger depth.** Momentum is only as deep as
  `price_history.jsonl` has grown. This is **not** a claim of months of mature
  history — as of this writing the ledger holds a handful of capture dates, so
  most products show `single_observation` or short series. Depth accrues as
  sweeps run.
- **Read-first by design.** Cross-product comp freshness depends on the in-house
  cache (`data/state.db`, gitignored) and the ledger; a clean checkout with an
  empty DB serves comps from the ledger latest, or honest `no_history`.
- **PPT facade is a local compatibility shim**, not a re-hosting of PPT data. It
  never calls PPT and never claims PPT provenance.
