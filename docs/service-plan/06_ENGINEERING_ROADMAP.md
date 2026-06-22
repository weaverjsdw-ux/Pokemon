# 06 — Engineering Roadmap (Phases 0–5)

*Each phase: goal · concrete changes · files · tests · acceptance · risks · NOT-yet · first move · done-evidence. Every phase keeps the 170-test suite green and the doctrine intact. Slices are PR-sized.*

---

## Phase 0 — Repo truth & clean baseline  *(no features)*

- **Goal:** a known-good, committed baseline so all later work is reviewable; confirm current behavior.
- **Changes:** add `*.bak` (and any stray patterns) to `.gitignore`; delete scratch files (`sprint*.txt`, `iddoctor_offline.txt`, `test_baseline.txt`) and oversized `.tmp_web_*.err.log`; commit the untracked modules (`confidence/provenance/resale/verify_ids/workqueue` + `test_confidence`) and docs as one reviewed baseline commit; verify `--check-config`, `--safe-demo`, `pytest`, and `python -m scanner.web` all start.
- **Files:** `.gitignore`; housekeeping only — **no logic changes**.
- **Tests:** none new; **run** the full suite (170) + manual smoke (`--check-config`, `--safe-demo`, web boot).
- **Acceptance:** `git status` clean after commit; 170 tests pass; dashboard boots on `127.0.0.1:8765`; no secret/`.bak`/scratch file staged.
- **Risks:** accidentally committing a `.db`/`.bak`/secret — mitigate by reviewing `git status` and the new ignore rules first.
- **NOT yet:** any feature, any adapter change, any doctrine change.
- **First move:** `git status` → write the ignore rules → `git add` only intended files → commit.
- **Done evidence:** clean `git status`; CI green; screenshot-free confirmation that `--safe-demo` renders.

## Phase 1 — Service-grade local reliability

- **Goal:** "runs unattended and never lies about its state." No silent unknowns.
- **Changes:**
  1. `notify.py`: add `.raise_for_status()` + one retry w/ backoff in `_discord()`/`_ntfy()`; append every alert to a local alert-log (state table or file) so drops are recoverable; make ntfy base URL configurable.
  2. `main.py`: wrap the outer `while True` in try/except with exponential backoff; write a **heartbeat** (last-loop ts) to state each cycle; add SIGTERM/KeyboardInterrupt graceful shutdown; periodic store re-discovery (e.g., every N cycles).
  3. `state.py`: enable `PRAGMA journal_mode=WAL`; add a `heartbeat`/`runner_meta` row; wrap dedupe+history in one transaction.
  4. `health.py`: persist health on every write (not only in the scan loop); make thresholds config-driven.
  5. `resale.py`: persist the quote cache to disk so a restart doesn't blank prices.
  6. Dashboard: real **Liveness** indicator (live/stale/down from heartbeat).
- **Files:** `scanner/notify.py`, `scanner/main.py`, `scanner/state.py`, `scanner/health.py`, `scanner/resale.py`, `scanner/web.py`, `web_assets/app.js`; tests alongside.
- **Tests:** webhook failure → retry → logged; loop survives a thrown exception and backs off; heartbeat advances each cycle and goes stale when stopped; WAL doesn't break existing state tests; resale cache survives a simulated restart.
- **Acceptance:** kill the network mid-run → process stays up, backs off, dashboard shows *degraded/stale* truthfully; revoke the webhook → alert is logged + surfaced, not silently dropped; restart → prices and health reappear from disk.
- **Risks:** WAL + concurrent web/CLI access edge cases (test both); over-aggressive backoff hiding a real outage (cap + surface it).
- **NOT yet:** new sources, catalog work, ML, multi-channel routing rules.
- **First move:** `notify.py` `raise_for_status` + retry (smallest, highest-value); then the heartbeat.
- **Done evidence:** new tests green; a documented manual "pull the plug" run showing stale→recover.

## Phase 2 — Catalog & research intelligence

- **Goal:** the catalog reflects the real 2026 market and IDs are trustworthy; encode the source policy.
- **Changes:**
  1. **Catalog refresh** ([02/F]): add Mega Evolution block, Pitch Black, 30th Celebration, First Partner S1–S3, Destined Rivals tins; verify Best Buy SKUs via API; record provenance.
  2. **Release-watch model:** a structured record (set, date, products, IDs-needed, retailers) in YAML/JSON + loader; feeds the inbox + cadence.
  3. **ID Doctor truthfulness:** relabel Walmart/Costco/GameStop checks as "URL-resolves only"; add real identity checks where an official API path exists (Best Buy API).
  4. **`source_mode`** setting (`durable_only` / `all_sources`) + enforcement in the scan loop + acknowledgment gate.
  5. **Catalog packs (Option 3):** a `catalog-packs/` convention + importer.
- **Files:** `data/products.yaml`, new `data/releases.yaml`, `scanner/config.py`, `scanner/verify_ids.py`, `scanner/main.py`, new `scanner/releases.py`, `scanner/web.py`; tests.
- **Tests:** release-watch parse/validate; `source_mode` gates personal-use sources in `durable_only`; catalog-pack import merges without clobbering comments; ID Doctor status labels are accurate.
- **Acceptance:** in `durable_only`, personal-use adapters never make network calls (assert in test); catalog coverage reflects mid-2026 sets; importing a pack adds products with provenance.
- **Risks:** ID drift (verify before commit); MSRP accuracy ([needs validation] items must be labeled).
- **NOT yet:** dashboard polish for these (Phase 3), alert ranking (Phase 4).
- **First move:** add `source_mode` (doctrine-in-code) + the release-watch schema.
- **Done evidence:** test proving `durable_only` makes zero personal-use-source calls; coverage report showing the new sets.

## Phase 3 — Service dashboard & operator workflow

- **Goal:** the surfaces in [05] become usable: triage, release-watch inbox, ID Doctor UI, source cards, privacy review.
- **Changes:** `POST /api/verify-ids` + ID Doctor surface; Release-watch inbox UI; work-queue upgrades (severity-first sort + tests); source cards show source-durability badge + reason codes; Settings "privacy review" panel (what's stored, what's redacted); alert-channel test buttons.
- **Files:** `scanner/web.py`, `web_assets/{index.html,app.js,styles.css}`, `scanner/workqueue.py` (+ first `test_workqueue.py`), `scanner/verify_ids.py`.
- **Tests:** `/api/verify-ids` endpoint; workqueue ordering; release-inbox payload; settings round-trip never leaks secrets.
- **Acceptance:** operator can verify IDs, prep a release, and read source trust **without the CLI**; secrets never appear in any payload.
- **Risks:** UI complexity creep — keep to the four zones in [05].
- **NOT yet:** multi-user, auth-for-remote-host (ask-first), packaging.
- **First move:** `/api/verify-ids` + ID Doctor panel (closes the catalog-quality loop).
- **Done evidence:** `test_web.py` covers the new endpoints; manual run of Flow A end-to-end from the UI.

## Phase 4 — Alert quality & unattended operation

- **Goal:** alerts you trust, ranked by MSRP-protection value, with release-window cadence and quiet hours.
- **Changes:** alert ranking by product MSRP-protection tier ([02/E]); dedupe improvements; per-product/per-window cadence (still ≥60s floor); quiet-hours/urgency routing (urgent → ntfy; digest → Discord); scheduler/liveness proof doc; optional alert digest.
- **Files:** `scanner/notify.py`, `scanner/main.py`, `scanner/state.py`, `scanner/priority.py`, `scanner/config.py`, `scripts/install-scheduled-task.ps1`; tests.
- **Tests:** ranking order matches tiers; quiet-hours suppresses non-urgent; cadence never drops below floor; dedupe across windows.
- **Acceptance:** during a simulated release window, a Tier-1 ETB restock out-prioritizes a Tier-3 single pack; quiet hours hold non-urgent alerts; cadence stays polite.
- **Risks:** over-suppression (missing a real hit) — make urgency rules conservative + visible.
- **NOT yet:** packaging, hosted anything.
- **First move:** ranking + dedupe (improves every alert immediately).
- **Done evidence:** tests for ranking/quiet-hours; a documented release-window dry run.

## Phase 5 — Optional packaging & sharing  *(only after a risk review)*

- **Goal:** make Option 1 easy to run and ship Option 3 (catalog packs); consider GUI packaging — **no hosted components**.
- **Changes:** docs polish; `--safe-demo` public-safe screenshots; GitHub issue templates; the `catalog-packs/` published feed; optional local-app packaging (PyInstaller/Tauri) with `source_mode` defaulted to durable + secret-handling hardened; (only if ever) non-loopback host **with token auth** (ask-first).
- **Files:** `docs/`, `.github/`, `catalog-packs/`, packaging config; no scraping/hosting code.
- **Tests:** packaged build boots + `--check-config`; pack import; demo mode contains no real data.
- **Acceptance:** a fresh machine can run the tool from a packaged build or clear docs; published packs contain zero secrets and zero scraped inventory.
- **Risks:** distribution raises the stakes ([03] Option 2 caveats) — `source_mode` should default to durable and personal-use adapters require explicit acknowledgment.
- **NOT yet / never:** hosted scanner, multi-user scraping, auto-checkout.
- **First move:** publish the first catalog pack (`2026-mega-evolution.yaml`) — value with near-zero risk.
- **Done evidence:** risk-review note signed off; a consumer successfully imports a pack.

---

## Cross-phase test/CI discipline

- Keep tests **offline-by-default** (the suite already is — every network call mocked/injected). New sources get fixture-based tests, never live calls in CI.
- Add a lint/type gate to CI (ruff + a coverage floor) in Phase 1 or 3.
- Every phase ends green on Ubuntu+Windows × Py3.11/3.12 (current matrix).
- A new live-scan source is **blocked** until it's classified in [02/H] and approved per [04] "ask first."
