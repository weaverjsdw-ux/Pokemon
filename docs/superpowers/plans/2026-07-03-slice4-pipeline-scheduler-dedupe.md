# Slice 4 — Discovery Pipeline + Scheduler + Dedupe: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development
> (red→green per task). Normative contracts: spec §3.4 (WS4 pipeline/scheduler/alerting),
> §5.2 (alert gate), §9.2 (state/config schema), §9.3 (candidate/adapter interfaces), plus
> the two Slice-4 contract notes recorded in `.superpowers/sdd/progress.md`.

**Goal:** one-shot, production-shaped discovery pipeline connecting
DISCOVER → VERIFY → COMP/VERDICT → DEDUPE → BOARD/MANIFEST → ALERT DECISION. Manually
callable (`python -m scanner.discovery.pipeline --once`), fully testable with fake injected
stages, zero live network in `--dry-run`, and **no alert without a fresh same-run
`StockVerification` passing `verify.assert_alertable()`**.

**Architecture:** `pipeline.run_once(cfg, *, sources, verifier, comp_lookup, notifier, state,
now_ts, now_dt, dry_run, ...)` — every I/O stage injected (same DI style as
`build_sealed_sweep`). Each unique candidate lands in exactly ONE terminal bucket; the
manifest reconciles `candidates == sum(buckets)` with zero silent drops. Alert dedupe uses a
new additive `deal_alerts` table; `min_interval_seconds` uses a new additive
`discovery_runs` table. Quiet-hours is a pipeline-level `push` flag on the notifier seam.

**Tech Stack:** Python 3, dataclasses, stdlib sqlite (`scanner.state`), pytest
(network-mocked). No new dependencies.

## Global constraints (STOP-class + boundaries — all load-bearing)

- **No alert without verified purchasability:** only `VERIFIED_BUYABLE` with a fresh same-run
  `StockVerification` (present `verified_price`, `buy_url`, `evidence`, `checked_at`) may
  alert; `verify.assert_alertable(v)` is called on the object (never approximated from a row
  dict — Slice-2 contract note).
- **No live PPT usage:** the pipeline's comp lookup is structurally PPT-free
  (`resale.resale_client_from_config` or inhouse `CompEngine`, never `MarketFallbackClient`).
- **No silent drops:** every candidate gets a terminal reason in the manifest.
- **Additive-only SQLite** (`CREATE TABLE IF NOT EXISTS`, no destructive migration).
- `comps.engine: legacy` default untouched; `/poke` runtime untouched; restock lane
  (`main.run_pass`) untouched. No auto-checkout / cart / login-wall / proxy / CAPTCHA
  evasion. No dependency installs. Never push. `register_tasks.ps1` is written but run only
  by the operator.
- **Deliberate scope calls (advisor-reviewed):** (a) default verifier routes by candidate
  *origin* and honestly degrades every current live source to `unverifiable` (a slickdeals
  URL is a deal-thread, not a merchant page; `verify_catalog_product` would check a
  *different* retailer than the discovered listing — both wrong); the VERIFIED_BUYABLE path
  is proven by tests with fake verifiers and lands live at Slice 6. (b) HTML dashboard render
  + golden is deferred to Slice 5 (which restructures the board with "Buyable now"); Slice 4
  still runs `schema.assert_sweep` on constructed rows as the STOP-gate belt and writes the
  board JSON. (c) `notify.py` is NOT touched — the notifier is an injected seam
  (`send_deal(deal, *, push)`), default console-only; `DealAlert` + channels are Slice 5.

## Terminal buckets (manifest reconciliation)

`candidates == alerted + suppressed_dupe + out_of_stock + price_mismatch + unverifiable +
no_comp + below_min_discount + below_confidence`

| Bucket | When |
| --- | --- |
| `alerted` | VERIFIED_BUYABLE + comp + pct≥min_discount + (Ring-3 conf≥min_alert_confidence) + dedupe says fire |
| `suppressed_dupe` | as above but dedupe suppresses (same price in cooldown, no status flip) |
| `out_of_stock` | verify state OUT_OF_STOCK |
| `price_mismatch` | verify state PRICE_MISMATCH |
| `unverifiable` | verify state PAGE_UNAVAILABLE / PARSER_SUSPECT / SOURCE_BLOCKED / UNKNOWN_NO_ALERT |
| `no_comp` | VERIFIED_BUYABLE but comp engine returns no usable comp |
| `below_min_discount` | comped but pct_off < `poke.min_discount_pct` |
| `below_confidence` | Ring-3 wildcard comped but `comp_confidence` < `discovery.min_alert_confidence` |

Quiet-hours does NOT create a bucket: a fired alert is still `alerted`; quiet only flips
`push=False` (ntfy suppressed, board/manifest still written).

---

### Task 1: Config — `alerts` block + validation

**Files:** `scanner/config.py`, `config.example.yaml`; test `tests/test_config.py`.

**Interfaces:** `AlertsCfg(quiet_hours="23:00-08:00", price_drop_realert_pct=5.0,
cooldown_hours=24.0)` on `Config.alerts`. `from_mapping` parses/validates:
`quiet_hours` must be `HH:MM-HH:MM` (wrap allowed); `price_drop_realert_pct`/`cooldown_hours`
numeric. Bad values → `SystemExit` with a clear message. A helper `parse_quiet_hours(s) ->
(start_min, end_min)` exposed for the pipeline + validation.

- [ ] Step 1: Failing tests — default `AlertsCfg`; valid custom values parsed; malformed
  `quiet_hours` (`"nope"`, `"25:00-08:00"`) → SystemExit; non-numeric pct/hours → SystemExit.
- [ ] Step 2: Run `pytest tests/test_config.py -q` → FAIL.
- [ ] Step 3: Implement `AlertsCfg` + parse/validate + wire into `Config` + example.yaml.
- [ ] Step 4: Run → PASS.
- [ ] Step 5: Commit `feat(disc): alerts config block (quiet_hours/realert/cooldown)`.

### Task 2: State — `deal_alerts` + `discovery_runs` dedupe

**Files:** `scanner/state.py`; test `tests/test_state_history.py`.

**Interfaces (additive tables):**
- `deal_alerts(source, listing_id, price, status, ts, PRIMARY KEY(source, listing_id))`.
- `discovery_runs(source TEXT PRIMARY KEY, last_run INTEGER)`.
- `should_deal_alert(source, listing_id, price, status, *, now, cooldown_hours,
  price_drop_realert_pct) -> tuple[bool, str]` — reads the baseline (last *alerted*),
  decides: new / status-flip / price-drop≥pct / cooldown-expiry → `(True, reason)`; else
  `(False, "within cooldown, no change")`. **Does NOT write** (read-only decision).
- `record_deal_alert(source, listing_id, price, status, ts)` — upsert baseline; called ONLY
  when an alert actually fires.
- `get_last_run(source) -> int | None` / `set_last_run(source, ts)`.

- [ ] Step 1: Failing tests — the §3.4 dedupe matrix: (a) new listing → fire; (b) same
  price+status within cooldown → suppress; (c) price drop ≥ pct → fire; (d) status flip →
  fire; (e) cooldown expiry → fire. **Baseline-integrity test:** repeated suppressed
  sightings must NOT push the cooldown/price baseline (record only on fire), then
  cooldown-expiry still fires. `discovery_runs` get/set roundtrip + None-when-absent.
- [ ] Step 2: Run `pytest tests/test_state_history.py -q` → FAIL.
- [ ] Step 3: Implement tables (in `_init_schema`) + the four methods.
- [ ] Step 4: Run → PASS.
- [ ] Step 5: Commit `feat(disc): deal_alerts dedupe + discovery_runs interval state`.

### Task 3: Pipeline core — orchestration, gate, dedupe, quiet-hours, manifest

**Files:** create `scanner/discovery/pipeline.py`; test `tests/test_poke_pipeline.py`.

**Interfaces (produces):**
- `run_once(cfg, *, sources=None, verifier=None, comp_lookup=None, notifier=None,
  state=None, catalog=None, source_slugs=None, now_ts=None, now_dt=None, dry_run=False,
  http_get=None) -> dict` (the manifest; also holds the board under a key). Pure-ish: all
  I/O injected. Validates `source_slugs` (or `cfg.discovery.sources`) against `adapters.ALL`
  → `PipelineConfigError` on unknown slugs.
- Per unique `(source, listing_id)` candidate: record_listing + listing ledger append (unless
  dry-run) → VERIFY (hold object) → bucket per table above → COMP (PPT-free) → verdict/gates
  → DEDUPE via `state.should_deal_alert` → `assert_alertable(v)` → `notifier.send_deal(deal,
  push=not quiet)` → `record_deal_alert`.
- `default_verifier(candidate)` routes by `candidate.source`; every current live source →
  `unverifiable` with an honest per-source `degraded_reason` (no network). Extensible hook
  for the Slice-6 merchant resolver / eBay item lookup.
- `default_comp_lookup(cfg)` → PPT-free; Ring-1 (matched_product_key in catalog) → estimate
  via resale/inhouse; else `{"status": "no_match"}`.
- `_in_quiet_hours(now_dt, quiet_hours)` (pure, wrap-aware).
- `_ConsoleDealSink.send_deal(deal, *, push)` — default notifier seam (console only).
- Adapter `state`/`state_detail` recorded into `health` under `disc:<slug>` +
  `sources` manifest array (same shape sweep uses). `min_interval_seconds` enforced via
  `discovery_runs`; throttled adapters skipped + noted (not counted as candidates).

- [ ] Step 1: Failing tests (fake adapters/verifier/comp/notifier, injected `State(tmp db)`):
  - unknown configured slug → `PipelineConfigError`.
  - a raising/degraded fake adapter does not crash the run (others still processed).
  - pipeline calls `assert_alertable` before alerting (spy/monkeypatch asserts it ran on the
    fresh object); a fabricated no-evidence "verified" verification → no `send_deal`.
  - each non-alert terminal state → zero `send_deal` calls + correct bucket.
  - dedupe matrix end-to-end (new/unchanged/price-drop/status-flip/cooldown) drives
    fire/suppress.
  - quiet-hours: `send_deal` called with `push=False`, board+manifest still produced.
  - manifest counts reconcile (`candidates == sum(buckets)`) across a mixed candidate set.
  - `--dry-run`/`dry_run=True`: monkeypatch `retailers.http.get` + `requests.get/post` to
    raise → run completes (zero network); no `send_deal`; no `deal_alerts`/`seen_listings`
    writes; truthful manifest returned.
- [ ] Step 2: Run `pytest tests/test_poke_pipeline.py -q` → FAIL (module missing).
- [ ] Step 3: Implement `pipeline.run_once` + helpers (no CLI yet).
- [ ] Step 4: Run → PASS.
- [ ] Step 5: Commit `feat(disc): one-shot discovery pipeline core + dedupe + gate`.

### Task 4: Pipeline CLI + board/manifest write

**Files:** `scanner/discovery/pipeline.py` (add `main`); test `tests/test_poke_pipeline.py`.

**Interfaces:** `main(argv=None, cfg=None, ...)` — argparse `--once` (required intent,
one-shot), `--sources a,b`, `--dry-run`, `--out DIR`. Builds live default stages (validated
sources from `adapters.ALL`, PPT-free comp, console sink), calls `run_once`, writes
`data/poke/<date>-discovery.json` (board) + `<date>-discovery.manifest.json` (unless
dry-run), prints a reconciled summary. `schema.assert_sweep` runs on constructed rows before
write (STOP-gate belt).

- [ ] Step 1: Failing tests — `main(["--dry-run"], cfg=...)` returns 0, writes nothing, zero
  network; `main(["--once"], cfg=..., <fakes>)` writes board+manifest whose counts reconcile.
- [ ] Step 2: Run → FAIL.
- [ ] Step 3: Implement `main` + wiring.
- [ ] Step 4: Run → PASS.
- [ ] Step 5: Commit `feat(disc): pipeline CLI (--once/--sources/--dry-run) + board/manifest`.

### Task 5: Scheduler registration script (operator-run only)

**Files:** create `scripts/register_tasks.ps1`.

Registers (a) the at-logon restock loop (`python -m scanner`) and (b) the repeating
discovery pipeline (`python -m scanner.discovery.pipeline --once`, interval from
`discovery.interval_seconds`). Includes `-Unregister` switch + inline reversal guidance,
`-WhatIf`-friendly, no side effects on import. **Not executed this session.**

- [ ] Step 1: Write the script (reviewed, not run).
- [ ] Step 2: Commit `feat(disc): Task Scheduler registration script (operator-run)`.

### Task 6: Full suite + review + ledger

- [ ] Step 1: `.venv/Scripts/python.exe -m pytest -q` (to file, read back) → all green.
- [ ] Step 2: Lean review pass over the Slice-4 diff (multi-dimension); fix
  Critical/Important; log Minors.
- [ ] Step 3: Update `.superpowers/sdd/progress.md` (gitignored). Report: files, tests,
  pass/fail, findings, blockers, Slice-5 safety.

## Self-review (against handoff + spec)

- Handoff reqs 1–8 → Task 3 (pipeline/gate/candidate/dedupe/manifest/dry-run), Task 1
  (config), Task 2 (state), Task 4 (CLI), Task 5 (scheduler). ✓
- Slice-2 contract note (assert_alertable on fresh object, single-pass) → Task 3. ✓
- Slice-3 contract note (slug validation vs `adapters.ALL`; `min_interval` enforcement) →
  Task 3. ✓
- No-alert-without-evidence enforced at pipeline (gate) + STOP-gate belt (`assert_sweep`). ✓
- Dedupe baseline = last alerted (not last seen); quiet_hours wrap-aware → Task 2/3. ✓
- PPT-free comp; comps.engine legacy; /poke + restock lane untouched. ✓
