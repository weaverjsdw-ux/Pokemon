# 03 — Service Strategy

*Four service shapes evaluated against the doctrine and the durability reality from [02](02_MARKET_AND_RETAILER_MAP.md). Recommendation + the source-policy fork at the end.*

---

## The four shapes

### Option 1 — Personal Local Command Center  ★ RECOMMENDED (near-term)

- **Who:** you (and anyone technical enough to clone + configure). One operator, one machine.
- **Pain solved:** "I keep missing MSRP restocks of the products I actually open." Truthful liveness, fast alerts, a verified catalog, and a weekly research brief.
- **Data:** local `config.yaml` (addresses, webhook, keys), `data/products.yaml` (catalog), SQLite state. Live sources: Best Buy + eBay APIs (durable); Target/Walmart/etc. opt-in (personal-use, may break).
- **Runs locally:** everything. **Could be centralized:** nothing that touches secrets. **Never centralize:** addresses, webhook, route coordinates, API keys, store-level history.
- **Automated vs human:** scanning/alerting automated; ID gathering + catalog curation human-in-the-loop (correct — keeps catalog quality high).
- **Risks:** personal-use adapters can break without notice (mitigate via `source_mode` + polite cadence + truthful health); public OSRM/Nominatim fragility; Windows-centric scheduler.
- **Build cost:** **low** — it's ~80% built. Phases 0–4 are hardening + catalog + UX, not green-field.
- **First viable version:** the current repo + Phase 0 (clean baseline) + Phase 1 (reliability) = a tool you can trust to run unattended.
- **Monetization:** none intended; this is the hobby tool. That's fine.
- **Doctrine fit:** ✅ perfect. Single-user, polite, local-first, secrets stay home.

### Option 2 — Power-User Local App

- **Who:** non-coders who want the same workflow without the terminal.
- **Pain solved:** setup friction. A config wizard, source-health view, catalog "packs," release watch, alert setup — all GUI.
- **Data:** same as Option 1, but the app must make secret-handling foolproof (never display/log webhook or keys; local-only binding by default).
- **Runs locally:** all. **Centralized:** only the *optional* catalog packs (Option 3). **Never:** user secrets.
- **Automated vs human:** same split; the app lowers the human-effort cost of catalog curation with better UI.
- **Risks:** packaging/signing per-OS; support burden; users opening the dashboard to non-loopback hosts without auth. Distribution turns a personal tool into something that enables *many* people to poll the same endpoints — at scale that drifts toward exactly the distributed-traffic pattern the doctrine forbids, regardless of intent.
- **Build cost:** **medium-high** — packaging (PyInstaller/Tauri), auto-update, onboarding, cross-platform scheduler.
- **First viable version:** a packaged build of Option 1 with a first-run wizard and `source_mode` defaulted to durable.
- **Monetization:** weak/none clean; a paid "pro" GUI wrapped around fragile scraping isn't defensible (and edges toward scalper-tooling optics). Keep free/OSS if pursued.
- **Doctrine fit:** ⚠️ acceptable **only** if `source_mode` defaults to durable + the personal-use adapters require explicit per-user acknowledgment. Distribution raises the stakes on every boundary in [04](04_DOCTRINE_AND_SAFETY.md).

### Option 3 — Maintained Research / Catalog Service  ★ RECOMMENDED (the one shareable piece)

- **Who:** the community of Option 1/2 operators.
- **Pain solved:** every operator otherwise re-does the same catalog research (TCINs, SKUs, slugs, MSRPs, release dates, which sources are healthy). Centralize the **non-secret, non-scraping** knowledge.
- **Data published:** verified product packs (per-set IDs by retailer), release watchlists, MSRP baselines, source-durability notes. **Sourced from official APIs + human curation only.** No user data, no live inventory, no scraped output.
- **Runs locally:** consumers import packs. **Centralized:** the catalog repo/feed itself (e.g., a versioned `catalog-packs/` GitHub repo or a read-only JSON feed). **Never centralize:** anything scraped from an internal endpoint, anything user-specific.
- **Automated vs human:** Best Buy API can auto-suggest SKUs; **a human verifies and signs off** before a pack is published (provenance discipline).
- **Risks:** stale packs if not maintained; accidental inclusion of scraped data (governance needed); MSRP accuracy.
- **Build cost:** **low-medium** — it's mostly a publishing convention + a small importer in the app.
- **First viable version:** a `catalog-packs/2026-mega-evolution.yaml` published in the repo that any operator can drop into `data/products.yaml`.
- **Monetization:** the only faintly viable path — donations/sponsorship for maintenance. Treat as community good, not a business.
- **Doctrine fit:** ✅ strong. Resale data stays context; no secrets; respects every retailer boundary.

### Option 4 — Hosted / Semi-Hosted Scanner  ✗ NOT RECOMMENDED

- **Who:** users who want zero setup.
- **Pain solved:** convenience — but at the cost of the doctrine.
- **Why it fails:** (a) **It becomes scalper-scale infrastructure** — a central server polling these endpoints for many users *is* distributed scraping at scale, which your doctrine forbids (proxies/distributed polling) and which is exactly what scalper bots do. (b) **Privacy** — hosting means custodying users' home/work addresses, webhooks, and route data; a massive liability the local-first design exists to avoid. (c) **Anti-scalper optics** — a hosted multi-user restock service is indistinguishable from the scalper infrastructure the community (and TPC) is fighting. (d) **The durable sources can't be centralized anyway** — Best Buy's API is meant for a single operator, so a hosted service would be left centralizing only the fragile scraped endpoints.
- **Only conceivable safe sliver:** a hosted *catalog/release feed* (Option 3) — which needs no scraping and no user secrets. That's Option 3, not a scanner.
- **Doctrine fit:** ✗ fails on multiple non-negotiables. **Do not build.**

---

## Recommendation

**Build Option 1 to service-grade; ship Option 3 as the shareable artifact; keep Option 2 as a possible later packaging of Option 1; explicitly reject Option 4.**

Rationale: Option 1 is ~80% done and the only shape that fully satisfies the doctrine; Option 3 is the single piece that can be safely shared/centralized because it never touches secrets or scraped inventory; Option 4 is incompatible with the doctrine (scalper-scale traffic) and a privacy liability.

---

## The source-policy fork (operator decision #1)

This is about **reliability and your doctrine**. The tool polls a mix of durable official APIs and fragile internal endpoints; make that split a first-class setting instead of an implicit default.

**Proposed `source_mode` setting (in `config.yaml`):**

- `all_sources` *(recommended default)* — poll everything politely: Best Buy + eBay (durable) **plus** Target/Walmart/Costco/GameStop. Maximum coverage for personal use. Internal-endpoint signals are labeled "may break" so you know which to trust.
- `durable_only` — live scanning limited to **Best Buy API + eBay Browse + geocode/route**; the internal-endpoint retailers become **manual-watch** (the tool surfaces "go check this yourself" with the URL). Use this when you want maximum reliability, or if you ever share the setup with someone else.

**Hard bright lines in both modes (your doctrine, encoded in code + docs):** queues/invites are **alert-only** (Pokémon Center Queue-it, Best Buy invites — never cut ahead of other openers), no login-wall scraping, no proxies/distributed polling, no auto-checkout, no CAPTCHA solving, polling floor ≥60s (default 180s — keep it).

**Why this is the right call:** it makes the durable/fragile split explicit so you know which alerts to trust, keeps your doctrine load-bearing in code (not just a markdown file), and makes `durable_only` available as the share-safe configuration (it's also what Option 3 publishes from).

See [04_DOCTRINE_AND_SAFETY.md](04_DOCTRINE_AND_SAFETY.md) for the full Allowed / Caution / Never matrix, secret-handling, privacy, and retention rules.
