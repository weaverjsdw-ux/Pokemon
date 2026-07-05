# Session D — Raw + Graded Source Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development. Steps use
> checkbox (`- [ ]`) syntax for tracking. This plan is a design record + task/test map executed
> inline in the authoring session (the operator handed a complete spec to execute, not hand off).

**Goal:** Add first-class raw + graded card support to the owned `/api/poke` layer — a separate
asset catalog, honest source adapters, per-identity history/momentum, owned asset endpoints, and
conservative (never-live) raw/graded WATCH opportunities — without changing any existing sealed
behavior.

**Architecture:** A new asset catalog (`data/poke/assets.yaml`) + loader (`catalog.py`) sits beside
the sealed product catalog. Raw comps route through the existing in-house resolver
(`comps/model.resolve → to_legacy_row`) so the confidence ladder and "no source → no number" rule
are reused verbatim. Graded comps pass PPT `smartMarketPrice` through 1:1. Item identity reuses the
ledger's existing `variant`/`grade`/`condition` key slots so raw NM / raw LP / PSA 10 / PSA 9 /
sealed never collide. New endpoints + WATCH-only asset opportunities are additive; sealed paths are
untouched.

**Tech Stack:** Python 3, PyYAML, `requests` (dormant PPT `/cards` client — no live calls this
session), pytest (network-mocked).

## Global Constraints (verbatim from spec + project STOP rules)

- Price accuracy is STOP-class: no exact source → `estimate: null`, confidence `none`. Never
  fabricate/guess/extrapolate. Never treat MSRP, a listing title, or fallback text as a comp.
- Every price carries its source URL + capture date.
- PPT bills on requested `limit` → `limit=1` is mandatory on every by-id `/cards` call.
- Optional PPT `/cards` only when `cfg.market_preferred and cfg.market_api_key` (flattened attrs).
- No live network calls this session (ask operator first). All adapter tests inject fakes.
- No dependency installs, no scheduler work, no remote push, no auto-buy/cart/checkout.
- Do not rewrite `price_history.jsonl`, `paper_decisions.jsonl`, `verified_candidates.jsonl`
  (append-only). Do not create duplicate discovery-layer taxonomy/paper-ledger systems.
- Existing sealed behavior (`/api/poke/products`, `/sealed-products`, sealed opportunities,
  activation/signals) must remain **exactly** unchanged.
- `price_history.jsonl` stays read-only on the API read path (0 credits, no network).
- Do NOT build Session E (no rankings, decision packets, grading-EV, gem-rate, auto-buy).

## Design decisions (locked; several are advisor-flagged correctness blockers)

1. **Raw confidence via the in-house resolver.** Build `CompSourceQuote`s (tcg=sold_derived,
   pc=sold_derived, ebay=active_ask) → `comps/model.resolve()` → `to_legacy_row()`. Never read
   `NormalizedComp.confidence` directly (it returns `"unknown"` for no-source, which is not in
   `config.VALID_CONFIDENCE`); `to_legacy_row` maps the no-comp case to `"none"`. Unmapped raw
   asset ⇒ `confidence == "none"`, `estimate is None`.
2. **Graded eBay ask can NEVER become the comp.** Graded `estimate` comes only from PPT
   `smartMarketPrice.price` or the PriceCharting graded fallback. eBay active ask is validator/
   context only. Make the graded resolver *structurally* unable to source `estimate` from an ask.
3. **Graded confidence = PPT pass-through.** `smartMarketPrice.confidence` maps 1:1 (a PPT "high"
   stays high). The "single source → medium/low" logic applies ONLY to the PriceCharting-only
   fallback, never to the PPT smart price. (ppt-v2-notes is the tiebreaker over the spec's
   ambiguous "medium/high → medium" phrasing.)
4. **`limit=1` on both card calls.** Raw `/cards?tcgPlayerId=…&limit=1`; graded
   `/cards?tcgPlayerId=…&includeEbay=true&limit=1`.
5. **Dedicated `item_key_for_asset(asset)`** — leave the sealed `item_key_for_product` hot path
   untouched. `grade_key` ("psa10") in the grade slot, `card_number` in the variant slot,
   `condition` ("nm"/"lp") in the condition slot. Lock the sealed key string with a regression test.
6. **`PokeApiDeps.assets` defaults to `{}`** so every existing (asset-less) test is unchanged.
   Asset opportunities enter the `/opportunities` listing + `summary()` only when assets are
   present. `activation_report` / `signals` stay **sealed-scoped** (assets are never live-eligible;
   the dormancy wire is sealed-arbitrage math).
7. **Injectable `assets_path` in `build_deps`**, tolerant of a missing file. Tests inject their own
   assets; the shipped seed file is honest (unmapped ⇒ `estimate: null`/`none`).
8. **`/api/poke/cards` (conditional deliverable)** — resolve by `tcgPlayerId` + a `condition`
   (raw) or `grade`/`grade_key` (graded) discriminator, since one id maps to several assets.
   Defined ambiguous-case behavior (multiple matches, no discriminator → `ambiguous` payload,
   never a wrong pick). Keep dispatch minimal; don't contort the router.
9. **Card client dormant by default**, gated on `cfg.market_preferred and cfg.market_api_key`.

## File Map

**Create:**
- `data/poke/assets.yaml` — seed raw/graded asset catalog (honest example rows).
- `scanner/poke_api/catalog.py` — `load_assets(path)`, `validate_asset(key, asset)`,
  `normalize_grade_key(grader, grade)`, `asset_summary(key, asset)`, `item_key_for_asset(asset)`.
- `scanner/poke_api/sources.py` — adapter interface + `PptCardClient` (dormant `/cards`),
  `resolve_raw_comp(asset, client, *, checked_at)`, `resolve_graded_comp(...)`, honest
  no-source/degrade behavior.
- `scanner/poke_api/asset_model.py` — `asset_comp_response`, `asset_no_comp_response`,
  `card_facade`, `card_ambiguous`, `card_no_match` (reuse `market.comp_from_row`).
- `tests/test_poke_catalog.py`, `tests/test_poke_asset_sources.py`,
  `tests/test_poke_asset_api.py`, `tests/test_poke_asset_opportunities.py`.

**Modify:**
- `scanner/poke_api/history.py` — add `item_key_for_asset` (import into catalog or keep here).
- `scanner/poke_api/router.py` — `PokeApiDeps.assets={}`; routes `/assets`,
  `/assets/{k}/comp|history|momentum`, `/cards`; `build_deps` loads assets + wires card client.
- `scanner/poke_api/opportunities.py` — new trade types (`raw_catalog_gap`, `raw_market_watch`,
  `graded_catalog_gap`, `graded_market_watch`); `Opportunity` gains `condition/grader/grade/
  card_number` (defaults); `classify_asset_trade`, `build_asset_opportunity` (WATCH-only).
- `scanner/poke_api/lab.py` — `build_asset_opportunities`; `/opportunities` = sealed + asset;
  activation/signals stay sealed-only.
- `docs/poke/private-price-api.md` — add a Track D section documenting the new surface.

## Task breakdown (each ends at an independently testable deliverable)

### Task 1 — Asset catalog loader + validation + identity
- [ ] Tests (`test_poke_catalog.py`): raw requires `condition`; graded requires `grader`+`grade`;
      `normalize_grade_key("PSA","10")=="psa10"`; `item_key_for_asset` distinct for raw NM / raw LP
      / PSA10 / PSA9; **regression** — a sealed product's `item_key_for_product` is still exactly
      `"prismatic evolutions|prismatic evolutions elite trainer box|||"`; `load_assets(missing)`→`{}`.
- [ ] Implement `catalog.py` + `history.item_key_for_asset`.

### Task 2 — Raw + graded source adapters (honest, dormant PPT)
- [ ] Tests (`test_poke_asset_sources.py`): unmapped/unconfigured raw → `estimate None`, conf
      `none`; unmapped graded → same; graded with only eBay ask → `estimate None` (ask never comp);
      raw with two agreeing sold-derived (injected) → high; raw ask-only → low (never high); graded
      PPT `smartMarketPrice` high → passes through high, `limit=1` on the call incl. `includeEbay`;
      missing key / 401 / 429 / quota → honest none, never raises.
- [ ] Implement `sources.py` (`PptCardClient` + resolvers) + `asset_model.py`.

### Task 3 — Owned asset endpoints + `/cards` compat
- [ ] Tests (`test_poke_asset_api.py`): `/assets` lists catalog; `/assets/{k}/comp` read-first
      (refresh=false never calls the client); `/assets/{k}/history` + `/momentum` per-identity
      (two assets sharing a name/set but different grade/condition do not cross-read); unknown
      asset_key → 404; `/cards?tcgPlayerId=…` raw (condition) + graded (grade) explicit; missing
      id → 400; unmapped id → no_match (200); ambiguous (id, no discriminator) → defined payload.
      Sealed regressions: `/products`, `/sealed-products` unchanged.
- [ ] Implement router routes + `build_deps` asset load + card-client gating.

### Task 4 — Raw/graded WATCH opportunities (never live)
- [ ] Tests (`test_poke_asset_opportunities.py`): asset with no comp → `*_catalog_gap`, WATCH;
      asset with comp + positive momentum → `*_market_watch`, WATCH; asset opp `live_eligible` is
      False and decision is never `LIVE_PACKET_ELIGIBLE` even with a fabricated high comp; ask-only
      graded cannot mint high/live; `/opportunities` includes asset WATCH rows when assets present;
      `summary` counts them; **activation_report + signals unchanged** (sealed-scoped); existing
      sealed opportunity test count (2) unchanged when no assets injected.
- [ ] Implement opportunity trade types + `Opportunity` fields + `classify_asset_trade` +
      `build_asset_opportunity` + lab wiring.

### Task 5 — Seed catalog + docs + full-suite verification
- [ ] `data/poke/assets.yaml` seed (honest rows). Update `docs/poke/private-price-api.md`.
- [ ] Run each new test module, then the full suite with the Windows basetemp workaround.

## The 10 required proofs → where covered

| # | Proof | Test module |
|---|-------|-------------|
| 1 | Sealed API behavior unchanged | catalog (key regression) + asset_api (sealed regressions) + full suite |
| 2 | Raw asset requires condition | test_poke_catalog |
| 3 | Graded requires grader + grade | test_poke_catalog |
| 4 | Unmapped/unconfigured → `estimate null`, conf `none` | test_poke_asset_sources |
| 5 | Raw/graded/sealed item keys don't collide | test_poke_catalog |
| 6 | History + momentum independent per identity | test_poke_asset_api |
| 7 | Missing key / 401 / 429 / quota degrades, never crashes | test_poke_asset_sources |
| 8 | Optional API calls use `limit=1` (raw + graded) | test_poke_asset_sources |
| 9 | Ask-only cannot mint high confidence or live eligibility | sources + asset_opportunities |
| 10 | Raw/graded opps are WATCH, never `LIVE_PACKET_ELIGIBLE` | test_poke_asset_opportunities |

## Out of scope (Session E) — deliberately not built
Trade hypothesis rankings, operator decision packets, grading-EV / gem-rate models, auto-buy/cart/
checkout, live-purchase behavior, live-source smoke (needs operator go-ahead), scheduler.
