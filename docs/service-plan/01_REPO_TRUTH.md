# 01 — Repo Truth (Current Capability)

*Every row verified by reading the module and/or running the suite on 2026-06-14. `pytest` = 170 passed offline in ~2.0s. `--check-config` and `python -m scanner.coverage` both run clean.*

---

## Capability matrix

Legend: ✅ implemented & solid · 🟡 partial/fragile · 🔴 stub/placeholder · Wiring = CLI / UI / both.

| Capability | Module(s) | State | Wiring | Tested? | Safe offline? | Key failure modes | What makes it service-grade |
|---|---|---|---|---|---|---|---|
| Scan loop + CLI | `main.py`, `__main__.py` | ✅ | both (`--once/--dry-run/--safe-demo/--check-config`) | yes (`test_main.py`) | yes (`--safe-demo`, `--check-config`) | outer `while True` has no try/except → unhandled exception kills process; store discovery is startup-only | crash-backoff + heartbeat + periodic store re-discovery |
| Persisted state | `state.py` | ✅ | both | yes (`test_state_history.py`) | yes (tmp SQLite) | no WAL mode (web+CLI lock contention); no schema migrations; dedupe + history in separate txns | WAL + migration table + single-txn writes |
| Config + validation | `config.py`, `main.py::check_config` | ✅ | both | yes (`test_config.py`) | yes | unknown keys silently ignored; no Google-key-present check when engine=google | warn on unknown keys; pydantic-style typing |
| Notifications | `notify.py` | ✅ | both | yes (`test_notify_alert.py`) | yes (mocked) | **no `.raise_for_status()` → dead webhook fails silently**; no retry; ntfy base URL hardcoded | raise_for_status + retry + local alert log |
| Geocode + route + store discovery | `geocode.py`, `route.py`, `geo.py`, `main.py` | ✅ | both | partial (`test_geo.py` math only; `build_corridor`/OSRM untested) | yes (mocked) | **public OSRM demo server** not production-reliable; silent Google→OSRM fallback; geocode cache has no TTL | self-host/swappable routing; cache TTL; fallback logging |
| Coverage score | `coverage.py` | ✅ | both | yes (`test_coverage.py`) | yes | swallows config error into 0%; no trend persistence | persist snapshots; name non-actionable products |
| Source health | `health.py` | ✅ | both | yes (`test_health.py`) | yes | process-local (SQLite snapshot only in scan loop); thresholds hardcoded; `BLOCKED` vs `ERROR` naming split | persist on every write; config thresholds; unify status vocab |
| Source confidence (readiness) | `confidence.py` | ✅ | UI | yes (`test_confidence.py`) | yes | hardcoded `target` slug branch; no snapshot timestamp | move slug-specific text into retailer class; add timestamp |
| Work queue | `workqueue.py` | ✅ | UI | **no dedicated test** | yes | arbitrary scoring formula; assumes web-payload product shape; `BLOCKED` items have no action hint | add tests; severity as first-class sort key |
| Provenance sidecar | `provenance.py`, `data/id_provenance.json` | ✅ | both | yes (`test_provenance.py`) | yes | full file read+write per record (slow at scale); no file lock; load() swallows corruption | batch writes; lock; staleness TTL |
| Resale context cache | `resale.py` (891 ln) | ✅ | UI | yes (`test_resale.py`) | yes (fixtures) | **memory-only (restart blanks all)**; HTML-scrape tiers (eBay/PriceCharting) are fragile (may break); OAuth token not persisted | disk persistence; prefer Browse API; drop/curtail scrape tiers |
| ID verifier ("ID Doctor") | `verify_ids.py` | 🟡 | CLI only (no UI button) | yes (`test_verify_ids.py`) | yes (injected `get`) | Walmart/Costco/GameStop checks only confirm URL returns 200, **not identity**; Target uses scraped REDSKY_KEY | real identity checks; `/api/verify-ids` endpoint; show `verifiedAt` |
| Add-ID flow | `add_id.py`, `identifiers.py` | ✅ | both (`POST /api/product-id`) | yes (`test_identifiers.py`) | yes | can't add a *missing* field line (KeyError); bare IDs unvalidated | auto-add field; validate bare IDs via format checks |
| Local web dashboard | `web.py` (1310 ln), `web_assets/*` | ✅ | UI | yes (`test_web.py`, 19) | yes | loopback default (good); **no auth** if `--host` opened; 5s poll | optional token auth if non-loopback host |
| Scheduler (unattended) | `scripts/install-scheduled-task.ps1` | ✅ | n/a | n/a | n/a (dry-run default) | Windows-only; logon trigger; restart×999 | cross-platform note; liveness proof |
| Product catalog | `data/products.yaml` | ✅ (22 SKUs) | both | n/a | yes | **stale — stops ~Destined Rivals; missing 2026 block** | catalog refresh + provenance discipline |
| CI | `.github/workflows/ci.yml` | ✅ | n/a | n/a | n/a | no lint/type/coverage gate | add ruff + coverage threshold |

### Retailer adapter sub-matrix

| Adapter | State | Method | ID field | Store-aware? | Durability | Notes |
|---|---|---|---|---|---|---|
| Best Buy | ✅ | **official API (key)** | `bestbuy_sku` | online + in-store via API | **durable** | the flagship official-API source; yields nothing if key empty |
| Target | ✅ | RedSky internal JSON | `target_tcin` | yes | **personal-use (internal)** | hardcoded `REDSKY_KEY` (env-overridable); 86% of current coverage |
| Costco | ✅ | internal ecom/gdx endpoints | `costco_item_id` | yes (4-step chain) | **personal-use (internal)** | most fragile multi-step chain; any step fails → silent None |
| Pokémon Center | ✅ | Shopify `.js` | `pokemoncenter_slug` | online-only | **alert-only (queue)** | alert-only is the only doctrine-safe use |
| Walmart | 🟡 | page scrape (`__NEXT_DATA__`) | `walmart_item_id` | online-only (find_stores dead code) | **personal-use (internal)** | bot walls; 1/22 coverage |
| GameStop | 🟡 | SFCC HTML fragment regex | `gamestop_pid` | yes | **personal-use (internal)** | no true "unknown" state; disabled by default |
| Sam's Club | 🔴 | none | `samsclub_item_id` | no | n/a | acknowledged placeholder |

Shared HTTP layer (`retailers/http.py`): ✅ retry on {429,500,502,503,504}, honors `Retry-After`, exponential backoff (1.5→3→6s), per-adapter polite sleeps, query-string redaction in error text. No global rate limiter; UA string duplicated per adapter.

---

## "Do NOT rebuild" list

These are done and tested. Extend, don't replace:

1. The scan-loop/CLI surface and flag set.
2. SQLite state: dedupe, 6h cooldown, restock counting, health snapshot, fallback DB path.
3. Config loading + `--check-config` validation + secret-from-env fallback.
4. The coverage / health / confidence / work-queue intelligence layer.
5. Provenance sidecar concept and `id_provenance.json` schema.
6. Add-ID URL→ID extraction for all six retailers and the comment-preserving YAML writer.
7. The entire local dashboard (`web.py` routes + `web_assets`) and its `/api/status` payload shape.
8. The safe-demo path (genuinely valuable for demos and tests with zero network).
9. The scheduler script (dry-run-by-default is the right default).
10. The 170-test suite and the offline-by-default testing discipline.

## "Next leverage point" list (what to build on top)

1. **Reliability spine:** notification `raise_for_status`+retry+log; crash-backoff loop; persisted heartbeat/liveness; resale cache on disk. (Phase 1)
2. **Green-source flagship:** make Best Buy API the first-run happy path; verify the in-store-availability field for route-aware alerts. (Phase 1/2)
3. **Catalog intelligence:** refresh to mid-2026; add a structured **release-watch** model; surface the **ID Doctor** in the UI. (Phase 2/3)
4. **Doctrine-in-code:** `source_mode` switch + clear durable/personal-use labels everywhere. (Phase 2)
5. **Alert quality:** rank by MSRP-protection value; release-window cadence; quiet hours. (Phase 4)

---

## Dirty worktree — exact state (preserved, untouched)

On branch `main`, up to date with `origin/main`, **dirty**. I edited nothing.

**Untracked (new work not yet committed):**
`ADVISOR_ROLE.md`, `DOCTRINE.md`, `ROADMAP.md`, `data/id_provenance.json`,
`scanner/confidence.py`, `scanner/provenance.py`, `scanner/resale.py`, `scanner/verify_ids.py`, `scanner/workqueue.py`, `tests/test_confidence.py`,
plus scratch/backup files: `data/state.db*.bak`, `iddoctor_offline.txt`, `sprint1.txt`, `sprint1_full.txt`, `sprint2.txt`, `sprint3a.txt`, `test_baseline.txt`.

**Modified (tracked):** `.gitignore`, `README.md`, `config.example.yaml`, `data/products.yaml`,
`scanner/{add_id,config,geocode,identifiers,priority,web}.py`,
`scanner/retailers/{base,costco,http}.py`, `scanner/web_assets/{app.js,index.html,styles.css}`,
`tests/{test_config,test_coverage,test_http,test_identifiers,test_main,test_retailers,test_web}.py`.

**Secret hygiene = good** (verified in `.gitignore`): `config.yaml`, `*.db`, `*.db-journal`, `.tmp_costco_*` (cookies), `.tmp_web_*.log`, `data/*.cache.json` are all ignored. **I did not read `config.yaml`, the cookie file, or any `.db`.**

**Two mild risks before any commit:**
1. `*.bak` is **not** gitignored → the `data/state.db*.bak` backups (which may contain store/observation data) would be committed by `git add -A`. Add `*.bak` to `.gitignore`.
2. Scratch files (`sprint*.txt`, `iddoctor_offline.txt`, `test_baseline.txt`) are dev detritus — delete them.

This cleanup is **Task #1 / Phase 0** and should precede all other work so there is a known-good baseline to branch from.
