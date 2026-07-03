# Slice 2 — Purchasability Verifier + Stock-Evidence Gate: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** No candidate can alert without stock and price verified from the actual buy page;
every candidate ends in one of 7 terminal verification states with populated evidence.

**Architecture:** A new pure-core verifier module (`scanner/discovery/verify.py`) owns the
7-state terminal taxonomy, the `StockVerification` evidence record, and the alert gate
(`alert_allowed`/`assert_alertable`). Two verification adapters reuse existing sanctioned
paths: catalog×retailer (wraps `scanner/retailers` adapters' `inventory()`) and a generic
merchant-page fetch (schema.org availability + JSON-LD price, refuses to guess). The
STOP gate in `schema.validate_row` is extended so a positive `stock_status` without
evidence/buy_url/checked_at halts the render — enforcement in code, not UI. The sweep gains
an opt-in `--verify-stock` flag; render gains a Stock column.

**Tech Stack:** Python 3, dataclasses, requests via `scanner/retailers/http.py`, pytest
(network-mocked, fixtures under `tests/fixtures/verify/`).

**Normative spec:** `docs/superpowers/specs/2026-07-02-buyable-deal-pipeline-design.md` §5
(verifier contract), §5.3 (DealRow additions), §4.3 (STEAL basis rule), §8.5 (mandatory
no-alert-without-evidence test). Handoff adds the 7-state terminal taxonomy on top.

## Global Constraints

- STOP-class: never fabricate/guess a price; no source → no number; every price carries
  source URL + capture date.
- No auto-checkout, no cart automation, no login-wall scraping, no proxy polling, no
  CAPTCHA/bot-wall evasion; `retailers/http.py` "stock-query requests only" contract extends
  to the verifier verbatim.
- `comps.engine: legacy` default untouched. `/poke` persona untouched. No new dependencies.
  Never push to any remote.
- Default-config behavior byte-identical: without `--verify-stock` the sweep output must not
  change (existing 326 tests stay green unmodified except where this plan edits them).
- `comp confidence` and `buyability` stay separate — never collapsed into one score.
- Full suite: `.venv/Scripts/python.exe -m pytest -q` green before done.

## Terminal state taxonomy (handoff contract, reconciled with spec §5)

| State | stock_status | Meaning | Alerts? |
| --- | --- | --- | --- |
| `VERIFIED_BUYABLE` | in_stock / limited | stock positive AND observed price read AND (no expectation OR within 5%) AND buy_url + evidence + checked_at | **only this one** |
| `OUT_OF_STOCK` | out_of_stock | page/API affirmatively says out | no |
| `PRICE_MISMATCH` | in_stock / limited | stock positive, observed price differs from expected > 5% | no |
| `PAGE_UNAVAILABLE` | unverifiable | transport error / 404 / 5xx | no |
| `PARSER_SUSPECT` | unverifiable | HTTP 200 but no availability signal parsed — refuse to guess | no |
| `SOURCE_BLOCKED` | unverifiable | 403/429/bot-wall | no |
| `UNKNOWN_NO_ALERT` | unknown (or in_stock w/o price) | catch-all incl. stock-positive-but-priceless; never alerts | **never** |

Evidence record (`StockVerification`, frozen dataclass): `state, stock_status,
verified_price, expected_price, price_matches, buy_url, checked_at, source, method,
evidence (≤300 chars), degraded_reason`.

---

### Task 1: Schema — stock fields + STOP-gate extension

**Files:**
- Modify: `scanner/discovery/schema.py`
- Test: `tests/test_poke_schema.py`

**Interfaces:**
- Produces: `STOCK_STATUSES = {"unknown","in_stock","limited","out_of_stock","unverifiable"}`,
  `POSITIVE_STOCK = {"in_stock","limited"}`; `DealRow` fields `buy_url: str = ""`,
  `stock_checked_at: str = ""`, `stock_method: str = ""`, `comp_basis: str = ""`.
- Gate rules added to `validate_row`: (a) `stock_status` must be in `STOCK_STATUSES`;
  (b) `stock_status in POSITIVE_STOCK` requires non-empty `stock_evidence`, `buy_url`,
  `stock_checked_at`.

- [x] Step 1: Write failing tests in `tests/test_poke_schema.py`: invalid vocab value is a
  violation; positive status missing each of evidence/buy_url/checked_at is a violation
  (one assert per field); fully-evidenced positive row passes; default `unknown` row passes
  unchanged.
- [x] Step 2: Run `pytest tests/test_poke_schema.py -q` → new tests FAIL (unknown fields).
- [x] Step 3: Implement fields + gate rules in `schema.py`.
- [x] Step 4: Run → PASS.
- [x] Step 5: Commit `feat(verify): DealRow stock-evidence fields + STOP-gate extension`.

### Task 2: Score — STEAL requires sold-derived comp basis

**Files:**
- Modify: `scanner/discovery/score.py` (in `assign_badges`)
- Test: `tests/test_poke_score.py`

**Interfaces:**
- Consumes: `DealRow.comp_basis` (Task 1).
- Rule: `steal_ok` additionally requires `"active_ask" not in basis and "asking" not in
  basis` where `basis = row.comp_basis.lower()` ("asking" also catches the legacy eBay
  fallback basis string "active fixed-price asking median" — belt over the existing
  verified-only rule).

- [x] Step 1: Failing tests: verified row + threshold pct + `comp_basis="ebay active_ask
  median (n=6)"` → no STEAL; same with `comp_basis="min(tcgplayer,pricecharting)
  agree@20%"` → STEAL kept; `comp_basis="active fixed-price asking median"` → no STEAL.
- [x] Step 2: Run `pytest tests/test_poke_score.py -q` → FAIL.
- [x] Step 3: Implement in `assign_badges`.
- [x] Step 4: Run → PASS.
- [x] Step 5: Commit `feat(verify): STEAL badge requires sold-derived comp basis`.

### Task 3: Verifier core — taxonomy, StockVerification, classify, alert gate

**Files:**
- Create: `scanner/discovery/verify.py`
- Test: `tests/test_poke_verify.py`

**Interfaces (produces):**
- Constants: the 7 states + `TERMINAL_STATES`, `ALERTABLE_STATES = {VERIFIED_BUYABLE}`,
  `PRICE_MATCH_TOLERANCE_PCT = 5.0`.
- `StockVerification` frozen dataclass (fields above).
- `classify_stock(stock_status, verified_price, expected_price, tolerance_pct) ->
  tuple[state, price_matches, degraded_reason]` — pure decision table.
- `AlertGateError(Exception)`; `alert_allowed(v) -> bool`;
  `assert_alertable(v) -> None` (raises with the exact failed condition).
- `from_stock_result(result, *, source, expected_price, checked_at)` — maps retailer
  adapter statuses `IN_STOCK/ONLINE_IN_STOCK→in_stock`, `LIMITED→limited`,
  `OUT/ONLINE_OUT→out_of_stock`; parses `result.price` via `scanner.main._price_to_float`;
  method `f"retailer_adapter:{source}"`; evidence carries raw status+price text.

- [x] Step 1: Failing tests: classify matrix reaching every terminal state; status-mapping
  table (5 adapter statuses); gate: `alert_allowed` parametrized over all 7 states — True
  only for VERIFIED_BUYABLE; hand-built VERIFIED_BUYABLE records missing price / buy_url /
  evidence / checked_at each raise `AlertGateError`; **spec §8.5**: high-margin
  high-confidence candidate with `stock_status="unknown"` → `alert_allowed` False AND
  STOP gate rejects a hand-built positive-status DealRow missing evidence.
- [x] Step 2: Run `pytest tests/test_poke_verify.py -q` → FAIL (module missing).
- [x] Step 3: Implement verify.py core (no I/O yet).
- [x] Step 4: Run → PASS.
- [x] Step 5: Commit `feat(verify): 7-state stock taxonomy + StockVerification + alert gate`.

### Task 4: Verification adapters — catalog×retailer + merchant page fetch

**Files:**
- Modify: `scanner/discovery/verify.py`
- Create: `tests/fixtures/verify/{instock_jsonld.html, outofstock_jsonld.html,
  mismatch_jsonld.html, garbage.html}`
- Test: `tests/test_poke_verify.py`

**Interfaces (produces):**
- `verify_catalog_product(cfg, product_key, product, *, registry=None, expected_price=None,
  checked_at=None, health_lookup=None) -> StockVerification` — fans over enabled+supported
  `online_only` retailers holding an id for the product, calls `inventory({key: prod}, [])`;
  picks best by rank (`in_stock` > `limited` > `out_of_stock` > `unverifiable` > `unknown`,
  tiebreak: has price). Exceptions → SOURCE_BLOCKED on 403/429 text, else PAGE_UNAVAILABLE.
  ID'd product yielding zero rows → consult health `last_http_status`: 403/429 →
  SOURCE_BLOCKED, 5xx → PAGE_UNAVAILABLE, else PARSER_SUSPECT. Nothing attempted →
  UNKNOWN_NO_ALERT with degraded_reason naming why (store-based adapters are skipped in
  sweep context — no stores; recorded in degraded_reason when nothing else answers).
- `verify_page(url, *, expected_price=None, checked_at=None, http_get=None) ->
  StockVerification` — one polite GET (browser UA, via `retailers/http.py`); schema.org
  availability marker + JSON-LD/itemprop price; OutOfStock → OUT_OF_STOCK; InStock+price →
  classify; InStock w/o price → UNKNOWN_NO_ALERT; no signal → PARSER_SUSPECT; 403/429 →
  SOURCE_BLOCKED; 404/5xx/transport → PAGE_UNAVAILABLE. Evidence = matched snippet ≤300.

- [x] Step 1: Failing tests with a fake registry (Retailer subclasses yielding scripted
  StockResults) + fixture-driven `verify_page` cases: VERIFIED_BUYABLE, PRICE_MISMATCH,
  OUT_OF_STOCK, PARSER_SUSPECT (garbage.html), SOURCE_BLOCKED (403), PAGE_UNAVAILABLE
  (timeout + 404), stock-positive-priceless → UNKNOWN_NO_ALERT with `stock_status ==
  "in_stock"`; evidence completeness asserted field-by-field (source, url, seen_at,
  observed, expected, stock status, method, snippet).
- [x] Step 2: Run → FAIL.
- [x] Step 3: Implement both adapters.
- [x] Step 4: Run → PASS.
- [x] Step 5: Commit `feat(verify): catalog-retailer + merchant-page verification adapters`.

### Task 5: Sweep `--verify-stock` + render Stock column

**Files:**
- Modify: `scanner/discovery/sweep.py`, `scanner/discovery/render.py`
- Test: `tests/test_poke_sweep.py`, `tests/test_poke_render.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- `build_sealed_sweep(..., stock_verifier=None)`: `stock_verifier(key, product,
  expected_price) -> StockVerification`. When provided and a row is comped: populate
  `stock_status/stock_evidence/buy_url/stock_checked_at/stock_method`; positive stock also
  sets `retailer` to the verified source and, when `verified_price` present, `deal_price =
  verified_price` (pct_off/badges/lenses/verdict computed at the verified number);
  mismatch beyond tolerance → `warn_reason = "PRICE_CHANGED: observed $X vs MSRP $Y"`.
  Rows also carry `comp_basis` from the comp row (`compBasis` or `basis`). Sweep dict gains
  `"stock"` state-count summary only when a verifier ran; manifest passes it through.
  CLI flag `--verify-stock` builds the default verifier over `verify_catalog_product`.
- `render.py`: table gains a Stock column — `unknown` renders muted; verified statuses
  render label + checked-at + evidence (escaped, title attr) + `buy` link through
  `_safe_href` (XSS posture identical to source_url).

- [x] Step 1: Failing tests: fake verifier → rows carry all five stock fields + retailer
  flip + buy_url; verified-price mismatch → WARN + PRICE_CHANGED + pct_off recomputed at
  observed price; no-verifier build → rows byte-identical to today (stock_status
  `unknown`, empty buy_url, no `stock` key); render: stock column shows evidence and
  scheme-filters a `javascript:` buy_url.
- [x] Step 2: Run `pytest tests/test_poke_sweep.py tests/test_poke_render.py -q` → FAIL.
- [x] Step 3: Implement sweep + render changes.
- [x] Step 4: Run → PASS (plus `tests/test_poke_schema.py tests/test_poke_verify.py`).
- [x] Step 5: Commit `feat(verify): sweep --verify-stock + dashboard stock evidence column`.

### Task 6: Full suite + final review

- [x] Step 1: `.venv/Scripts/python.exe -m pytest -q` (output to file, read back) → all green.
- [x] Step 2: Final review pass over `019d3b6..HEAD` (multi-dimension, lean profile);
  fix Critical/Important findings; log Minors.
- [x] Step 3: Update `.superpowers/sdd/progress.md` with the Slice-2 ledger entry (gitignored,
  no commit). Report: changed files, tests run, pass/fail counts, findings count, blockers,
  next-slice safety.

## Self-review (against spec + handoff)

- Handoff req 1–7 → Tasks 3/4 (gate + evidence), 1 (STOP gate), 5 (dashboard exposure). ✓
- 7 terminal states each test-covered → Tasks 3/4. ✓
- UNKNOWN_NO_ALERT never alerts → gate parametrized test (Task 3). ✓
- Evidence field completeness → Task 4 Step 1 field-by-field assert. ✓
- comp-confidence ≠ buyability → §8.5 test (Task 3) + est/low rows keep rendering with
  honest stock fields (Task 5; nothing hides weak comps with verified stock). ✓
- Restock lane (`main.run_pass`) intentionally untouched: its alerts already require a live
  adapter-confirmed positive status (`ALERTABLE_STATUSES`) from the sanctioned endpoint —
  the deal-alert path that must call `assert_alertable` is born in Slice 4 (pipeline), per
  spec §5.2-1 ("enforced in pipeline.py, the only alert emitter" + STOP gate). Recorded as
  a Slice-4 planner note in progress.md. ✓
- No placeholder steps; types consistent across tasks (checked). ✓
