# Slice 3 — Discovery Adapters Emitting Normalized Candidates: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Normative
> contracts: spec §3.2 (workstream), §9.3 (interfaces, copied verbatim below), §6 (rings).

**Goal:** discovery sources emit normalized `CandidateDeal`s (item, source, price, buy URL,
seen_at, evidence) with catalog/set-watch matching; every adapter degrades honestly.

**Probe outcome (2026-07-03, `docs/poke/target-search-probe-2026-07-03.md`):** Target
search is a JS shell + captcha-walled API to plain requests → `target_search` ships as a
declared `NOT_IMPLEMENTED` stub (`requires="playwright"`, wave 2), exactly like
`trackalacker`. Slickdeals is fully fetchable-plain (real fixtures captured). eBay Browse
is keyset-gated (`NEEDS_API_KEY` until provisioned; parse layer tested against
recorded-shape Browse JSON, same shape as `tests/test_resale.py`).

## Global Constraints

Same STOP-class + boundary rules as Slices 1–2 (no fabricated prices; evidence on every
candidate; no bot-wall evasion; no new dependencies; `comps.engine: legacy` untouched;
never push). Adapters raise nothing — degradations are states, not exceptions. All HTTP
via `retailers/http.py`. Junk titles (`resale.NEGATIVE_TITLE_PARTS`) are dropped, never
emitted as candidates.

### Task 1: `candidates.py` — CandidateDeal + ring matching
- Create `scanner/discovery/candidates.py`; test `tests/test_disc_candidates.py`.
- `CandidateDeal` frozen dataclass exactly per spec §9.3 (source, listing_id, item_name,
  price, shipping, url, retailer, seen_at, evidence_excerpt, matched_product_key,
  matched_set, asset_class="sealed", variant="", condition_note="").
- `junk_title(title) -> bool` — NEGATIVE_TITLE_PARTS substring check (reuses resale).
- `match_title(title, catalog, set_watch) -> (product_key | None, set_name_or_"")`:
  Ring 1 via `resale._title_allowed` per product, most-specific win (largest satisfied
  required-token set); Ring 2 = all tokens of a watched set present (via `resale._tokens`)
  + "pokemon" family token + not junk; Ring 3 = (None, "").
- `stable_listing_id(url)` = sha256(url) fallback.
- ≥5 tricky-title cases: ETB-vs-bundle, etb-token expansion, PC-exclusive falls to Ring 2,
  empty-box/japanese junk rejected, non-pokemon unmatched.

### Task 2: adapters base + registry + slickdeals (real fixtures)
- Create `scanner/discovery/adapters/{__init__,base,slickdeals,target_search,trackalacker}.py`;
  test `tests/test_disc_slickdeals.py`; fixtures `tests/fixtures/discovery/slickdeals_*.html`
  (captured live 2026-07-03, trimmed contiguous real regions).
- `DiscoverySource` base per §9.3: slug, min_interval_seconds, requires, `discover(cfg,
  catalog, set_watch) -> list[CandidateDeal]`, plus `state/state_detail` set during
  discover (confidence.py vocabulary: WORKING/BLOCKED/PARSER_SUSPECT/DEGRADED/
  NEEDS_API_KEY/NOT_IMPLEMENTED).
- Slickdeals parser: card root `<div class="dealCardListView…" data-threadid=`, skip
  `--expired`, title from `__title … title="…"`, price from `__finalPrice title="$N"`,
  store from `__store`, listing_id=threadid, url=absolute `/f/…` href (query stripped),
  evidence=title+price ≤200. Zero cards on HTTP 200 → PARSER_SUSPECT (standing query
  should never be empty); 403/429 → BLOCKED; transport error → DEGRADED. Junk dropped.
- `target_search`/`trackalacker`: declared stubs, NOT_IMPLEMENTED + reason, `discover`
  returns [] (probe doc linked).
- Registry `ALL = {slug: class}` mirroring `retailers/__init__.py`.

### Task 3: `ebay_browse` adapter (keyset-gated)
- Create `scanner/discovery/adapters/ebay_browse.py`; test `tests/test_disc_ebay_browse.py`.
- Without keyset (`resale.auth_configured(cfg)` false): state NEEDS_API_KEY, returns [].
- With keyset: one Browse search per set-watch entry (query `Pokemon TCG <set> sealed`),
  via injected `search_fn(query) -> payload` defaulting to `resale.EbayResaleClient`
  machinery; parse itemSummaries → CandidateDeal (listing_id=itemId, url=itemWebUrl,
  price=price.value, shipping=first shippingCost, retailer="eBay"); junk dropped;
  matching applied. min_interval_seconds=300.
- Tests use recorded-shape Browse JSON (test_resale.py shape + itemId/itemWebUrl); a
  live-recorded payload is impossible until the operator provisions the keyset (blocker).

### Task 4: config `discovery` block + state `seen_listings` + ledger `listing` kind
- Edit `scanner/config.py` (+`DiscoveryCfg`: enabled=True, interval_seconds=7200,
  sources=[target_search, slickdeals, ebay_browse], set_watch per spec §9.2 list,
  min_alert_confidence="medium" validated against VALID_CONFIDENCE), `config.example.yaml`.
- Edit `scanner/state.py`: `seen_listings(source, listing_id, price, status, first_seen,
  last_seen, PK(source, listing_id))` + `record_listing()` upsert + `listing_history()`.
- Edit `scanner/discovery/ledger.py`: VALID_KINDS += "listing".
- Tests: config defaults/validation (test_config.py), seen_listings upsert
  (test_state_history.py), listing-kind idempotent append (test_poke_ledger.py).

### Task 5: full suite + lean review + ledger entry
- `.venv/Scripts/python.exe -m pytest -q` green; lean review workflow over the slice diff;
  fix highs; log the rest; progress.md entry.
