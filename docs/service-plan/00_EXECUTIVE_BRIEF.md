# 00 — Executive Brief

*Produced 2026-06-14. Grounded in a full read of the code (verified, tests run) plus dated web research. Labels: [verified] / [inferred] / [needs validation] / [blocked].*

---

## 1. Executive verdict — can this become a real service, and what kind?

**Yes, but the honest answer is "a personal local command center first," not a hosted service.** Three findings drive that:

1. **The code is already most of the way there.** [verified] ~6,300 lines of scanner code, ~3,000 lines of tests, **170 tests passing offline in ~2s**. It has a working scan loop, a real local web dashboard, SQLite state with dedupe + restock history, a coverage/health/confidence/work-queue intelligence layer, a resale-context cache, an ID verifier, an add-ID flow, a Windows scheduler, and CI. This is not a prototype. The engineering bottleneck to "service-grade" is reliability hardening, not green-field building.

2. **Source durability + doctrine — not engineering — set the shape.** [verified] The retailers that matter most (Target, Walmart, Pokémon Center; also Costco, GameStop) only expose **undocumented internal endpoints** that can change without notice. The only **official, durable** live sources are **Best Buy's Developer API** (products + in-store availability) and **eBay's Browse API** (resale context). Two consequences: (a) lean on the official APIs where reliability matters, because scraped endpoints break; (b) a *hosted, multi-user* version is off the table — centralizing other people's restock-scraping is scalper-scale infrastructure your doctrine rejects, plus a privacy liability. A polite single-user local tool is the right niche.

3. **The market need is real and durable.** [verified] The Pokémon TCG has been structurally undersupplied since the TCG Pocket launch (Oct 2024). The Pokémon Company printed ~10 billion cards in 2025 and still fell short; new print capacity (Millennium Print Group) isn't online until ~end of 2028. Hot ETBs and Pokémon Center exclusives routinely sit at 2–8× MSRP on the secondary market. A tool that catches product at MSRP delivers genuine, recurring value to an opener through at least 2028.

**So: build the personal command center to service-grade. Treat a "maintained research/catalog pack" (verified IDs, release watchlists, MSRP baselines, source-status notes — no secrets, no live scraping) as the one shareable artifact. Do not build a hosted scanner.**

---

## 2. Current repo truth (one-screen summary)

Full detail in [01_REPO_TRUTH.md](01_REPO_TRUTH.md). Verified highlights:

- **Working & solid (do not rebuild):** scan loop + CLI (`--once/--dry-run/--safe-demo/--check-config`), SQLite state/dedupe/history (`scanner/state.py`), config validation, coverage/health/confidence/work-queue (`coverage.py`, `health.py`, `confidence.py`, `workqueue.py`), provenance sidecar, add-ID + URL parsing, the whole local dashboard (`web.py` + `web_assets/`), safe-demo, scheduler, 170-test suite.
- **Real adapters:** Best Buy (official API ✅), Target (RedSky internal ⚠️), Costco (internal endpoints ⚠️), Pokémon Center (Shopify `.js` ⚠️). **Partial:** Walmart (online-only page scrape, fragile ⚠️), GameStop (HTML-fragment regex ⚠️). **Stub:** Sam's Club.
- **Coverage today:** [verified] 86% active (19/22 products) via Target; Best Buy 17/22 (needs key); Walmart 1/22; others 0.
- **Top reliability gaps:** notifications never call `.raise_for_status()` (a dead Discord webhook fails silently); the outer scan loop has no crash-backoff; OSRM uses the public demo server; the resale cache is memory-only.

**Dirty-state / safety warning:** [verified] The worktree is **dirty** on `main` and I changed nothing. Entire new modules are **untracked** (`confidence.py`, `provenance.py`, `resale.py`, `verify_ids.py`, `workqueue.py`, `tests/test_confidence.py`) plus `DOCTRINE.md`, `ADVISOR_ROLE.md`, `ROADMAP.md`, `data/id_provenance.json`; many tracked files are modified. **Secret hygiene is good** — `config.yaml`, `*.db`, Costco cookies, and tmp logs are all gitignored. **Two mild risks:** the untracked `data/state.db*.bak` backups and scratch `.txt` files are *not* ignored, so a careless `git add -A` would commit them. **Recommended first action before any other commit:** gitignore `*.bak`, delete the scratch `.txt`/log files, then commit the new modules as a clean baseline (see Task #1 below).

---

## 3. Market headline (detail in [02](02_MARKET_AND_RETAILER_MAP.md))

- **Catch right now / next 90 days (chase-but-ethical):** Mega Evolution **Pitch Black** (ETB/Bundle/box, releases Jul 17, 2026; PC-exclusive ETB already sold out at preorder), **30th Celebration** (worldwide simultaneous Sep 16, 2026 — likely the single hardest 2026 product), **First Partner Illustration Collection Series 2** ($14.99, Jun 19), and continued **Chaos Rising** restocks. [verified / inferred for unannounced MSRPs]
- **Catalog gaps to add:** your catalog stops around Destined Rivals; it is **missing the entire 2026 Mega Evolution block** (Ascended Heroes, Perfect Order, Chaos Rising, Pitch Black) plus **30th Celebration**, **First Partner Illustration Collections**, and **Destined Rivals Team Rocket tins**. This is the highest-value catalog work.
- **MSRP-protection value ranking:** Pokémon Center exclusive ETB (extreme) > standard ETB (high) > Surprise Box / booster box (moderate-high) > booster bundle (moderate) > tins/blisters (low-moderate) > single packs (low). Alert priority should follow this.

---

## 4. The decision that shapes the roadmap: source policy (durability)

This is **operator decision #1** — about reliability and your doctrine. Full analysis in [03](03_SERVICE_STRATEGY.md) and [04](04_DOCTRINE_AND_SAFETY.md).

- **Durable / official sources:** Best Buy API, eBay Browse API, Nominatim/OSRM (low-volume, swappable), Discord/ntfy. These don't break — make them the *flagship*.
- **Personal-use polled sources:** Target, Walmart, Costco, GameStop, Pokémon Center. Undocumented internal endpoints; fine to poll **politely for personal use**, but they can change without notice and shouldn't anchor a shared/hosted setup.
- **Bright lines (your doctrine, kept):** no queue/invite jumping ahead of other openers (Pokémon Center, Best Buy), no login-wall scraping, no proxies/distributed polling, no auto-checkout, no CAPTCHA solving.

**Recommended:** add a `source_mode` setting — `all_sources` (default: poll everything politely) and `durable_only` (Best Buy + eBay live, others manual) for when you want maximum reliability or to share the setup. Make Best Buy the first-run **happy path** because it's the most *reliable* source and the only one with store-level availability data.

---

## 5. First 10 concrete tasks, ranked by leverage

Leverage = (durable value + unblocks other work) ÷ effort. Each maps to a Phase-0/1 issue in [07](07_DELIVERY_AND_KNOWLEDGE.md).

| # | Task | Why it's high-leverage | Effort |
|---|------|------------------------|--------|
| 1 | **Clean the worktree to a committed baseline** — gitignore `*.bak`, delete scratch `.txt`/log files, commit the 5 untracked modules + docs. | Nothing else is safe or reviewable until the ~25 uncommitted changes are a known-good commit. Pure unblocker. | S |
| 2 | **Harden notifications** — add `.raise_for_status()` + one retry + a local alert-log fallback in `scanner/notify.py`. | A silently-dead webhook means the tool looks alive but never alerts — the worst failure for a restock tool. | S |
| 3 | **Crash-proof the scan loop** — wrap the outer `while True` in `main.py` with try/except + exponential backoff + heartbeat write. | Turns "runs until it doesn't" into "runs unattended." Core service-grade reliability. | S |
| 4 | **Make Best Buy the first-run happy path** — onboarding copy + `--check-config` nudge to get a free key; verify in-store availability path. | The most durable live source, and the only one with an official store-level availability feed. Highest-reliability coverage. | M |
| 5 | **Catalog refresh to mid-2026** — add the Mega Evolution block, 30th Celebration, First Partner S1–S3, Destined Rivals tins; verify Best Buy SKUs via API. | Coverage is "the single best signal of whether this tool is doing anything" (your README). Directly drives utility. | M |
| 6 | **Persist health + a real liveness/heartbeat surface** — write last-loop timestamp to state; dashboard shows live/stale/down truthfully. | "Is it actually running?" is the #1 operator question. No silent unknowns. | M |
| 7 | **Add the `source_mode` switch + source-durability labels** (decision #1). | Encodes source policy in code; makes the durable/personal-use split explicit. | M |
| 8 | **ID Doctor in the UI** — `/api/verify-ids` endpoint + a verification queue surface; show `verifiedAt` per product. | Verification is CLI-only today; surfacing it closes the catalog-quality loop and kills "fake confidence." | M |
| 9 | **Release-watch model** — a structured upcoming-release record (date, products, IDs-needed) feeding a release-week cadence. | Converts the market map into an in-tool workflow; this is where MSRP protection is won or lost. | M |
| 10 | **Persist the resale cache to disk** + clearer confidence labels. | Stops a restart from blanking all price context; makes the distortion signal trustworthy. | S |

---

## 6. Operator decisions needed (concise)

1. **Source policy** (the big one): add a `source_mode` switch (`all_sources` default / `durable_only` option), Best Buy as the first-run happy path for reliability? (Recommended: yes.) → §4 above, [03](03_SERVICE_STRATEGY.md).
2. **Best Buy + eBay keys:** are you willing to register free developer keys? They're the most durable live sources (and the only official store-availability feed). (Recommended: yes.)
3. **Pokémon Center stance:** accept "alert-only, never automate the queue" — i.e., the tool tells you to go enter the queue yourself? (Recommended: yes; the alternative violates doctrine.)
4. **Scope of "service":** confirm we are building the **personal command center** (Option 1) and the **shareable research/catalog pack** (Option 3), and explicitly **not** the hosted scanner (Option 4)? (Recommended: yes.)
5. **Deliverable follow-through:** do you want me (in a follow-up) to actually (a) open the GitHub issues, (b) create the Notion workspace, and/or (c) generate the Phase-0 cleanup branch? These are ready to execute but I have not touched GitHub/Notion or your git history.
6. **MTG depth:** keep MTG as a light secondary (current 9 SKUs) or expand it? (Recommended: keep light — Best Buy/Target carry it, but Pokémon is the demand engine.)

---

## 7. Research backlog for follow-up Cowork sessions

Tracked so nothing is lost; details and templates in [07](07_DELIVERY_AND_KNOWLEDGE.md).

- **[needs validation]** Confirm English MSRPs + SKUs for 30th Celebration and Storm Emerald once officially announced; promote Storm Emerald to Tier-1 watch when an English date lands.
- **[needs validation]** PriceCharting "Legendary" current price and whether single-user use fits its "internal" clause.
- **[needs validation]** Whether Best Buy's in-store-availability API field is reliable enough to drive route-aware alerts (test against known stock).
- **[blocked until announced]** 2027 set calendar (likely Legends Z-A tie-in) — do not track until official.
- **Ongoing:** weekly release-calendar refresh; monthly source-drift re-check (internal endpoints change without notice; TCGplayer access is fluid).

---

## 8. Next steps

The two ready-to-run coding-agent prompts are in [08_CODING_AGENT_HANDOFF.md](08_CODING_AGENT_HANDOFF.md): **Phase 0** (repo truth + clean baseline, no features) and **Phase 1** (service-grade local reliability). Phase 0 is safe to run immediately and is gated to *not* start feature work. Everything downstream waits on operator decisions #1–#4 above.
