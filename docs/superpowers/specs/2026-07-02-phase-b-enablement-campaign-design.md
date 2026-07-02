# Phase-B Enablement Campaign — Design

**Date:** 2026-07-02
**Status:** Approved design, pending implementation plan
**Authorization trail:** operator chose "Approach A, full" — the ~42-credit seeding run is
explicitly authorized this session; the Phase-0 sweep ends at an operator sign-off gate; the
eBay keyset is an operator-only action receiving an instructions doc.

## Problem

Phase B (live `/poke` discovery) is blocked by three unrelated open items:

1. **7 sealed products lack verified `ppt_id`s** — the PPT comp path skips them (prior plan's
   Task 6 stopped PARTIAL at 5/12 when credits ran low; `docs/poke/ppt-id-seeding.md` holds
   the live checklist).
2. **The Phase-0 exhaustive source-fetchability sweep is not signed off** — the roadmap
   (`2026-06-28-resale-engine-program-roadmap.md`, Phase B "Prereq") hard-gates all of Phase B
   on it. `docs/poke/sources.md` still carries PENDING rows and one now-falsified claim
   (line 20: "scanner already holds eBay Browse tokens" — empirically false as of 2026-07-02:
   `config.yaml` has no ebay block and the env vars are empty, so the resale chain silently
   runs on the PriceCharting fallback).
3. **No eBay API credentials exist** — `EbayResaleClient` is ~80% built
   (`scanner/resale.py`: client-credentials OAuth at :609, cred resolution at :94-107) but has
   never run live in this repo.

## Goal

Clear all three gates in one campaign so the eBay Browse DISCOVER adapter (Phase B's first
build) can be brainstormed against signed-off source intelligence and working credentials.

## Non-goals (out of scope)

- The eBay Browse DISCOVER adapter itself — separate spec → plan → build cycle after the
  sweep sign-off (roadmap: "each phase gets its own spec").
- The Phase-B runtime `/poke` OPENER persona / command — reserved, untouched.
- Any change to `scanner/` code, the roadmap, or the test suite.
- Touching secret values: the campaign never reads, prints, or commits a key. WP3 is
  instructions only.

## Shape

Three independent work packages, executed WP1 → WP2 → WP3 (cheapest-risk first). One WP
failing does not block the others. Write set: `data/products.yaml`,
`docs/poke/ppt-id-seeding.md`, `docs/poke/sources.md`, `docs/poke/PHASE0_FINDINGS.md`, new
`docs/poke/ebay-keyset-setup.md`, plus the git-ignored progress ledger.

## WP1 — Seed the 7 remaining `ppt_id`s (~42 credits, authorized)

**Targets (from the checklist):** `destined_rivals_etb`, `surging_sparks_etb`,
`surging_sparks_booster_bundle`, `scarlet_violet_151_etb`,
`scarlet_violet_151_booster_bundle`, `paldean_fates_etb`, `crown_zenith_etb`.

**Procedure per product (exactly `docs/poke/ppt-id-seeding.md`):**

1. Name search: `GET /api/v2/sealed-products?search=<clean name>&limit=5` (~5 credits).
2. Pick the row whose `name` is the **standalone product in the right set** — exclude
   "… and Pokeball", "… Case", "(Sam's Club)", "(Dollar General Exclusive)",
   sticker/tech collections. Ambiguous → record `NOT_FOUND` with the candidate list; never
   force a guess (a wrong id poisons comps silently).
3. Add `ppt_id: "<tcgPlayerId>"` to that product in `data/products.yaml` (surgical edit).
4. Verify: by-id GET with **`limit=1` explicitly** (1 credit) — confirm name + plausible
   `unopenedPrice`; record price + date in the checklist.

**Credit governance:** read `X-RateLimit-Daily-Remaining` from every response and log it.
**Hard-stop the run when remaining < 15** (headroom for the steady-state ~1 credit/product
cache refresh). Budget expectation ~6 credits/product, ~42 total; authorized ceiling 50.

**Error handling:** any 4xx/5xx or ambiguous match → skip that product, record why, continue.
**Circuit-breaker: 2 consecutive API errors abort the whole run** (never burn credits
retrying). NOT_FOUND is a valid terminal state per the checklist's done-criteria (product
stays on the resale fallback).

**Done:** all 7 boxes resolved (verified id or recorded NOT_FOUND) in
`docs/poke/ppt-id-seeding.md`; `data/products.yaml` updated; one `data(poke):` commit; full
suite green (`.venv/Scripts/python.exe -m pytest -q` — products.yaml is load-bearing for
config tests); credits spent + remaining logged in the progress ledger.

## WP2 — Phase-0 completion sweep (no PPT credits; ends at operator sign-off)

**Probe set:**

- PENDING retailer sale pages: Target, Best Buy, Costco, Pokémon Center (deal/clearance/sale
  URLs — identify the concrete URLs during the sweep).
- Deal blogs / curators: identify candidates via WebSearch first (e.g. TCG deal roundups),
  then probe each.
- Re-verify the three known-blocked paths so the sign-off reflects 2026-07-02, not June:
  r/PKMNTCGDeals (WebFetch policy block?), eBay search (timeout?), TCGplayer (JS wall?).

**Method:** plain WebFetch first; where JS-walled or blocked, Playwright MCP browser probe.
A source that times out twice is recorded `dead-for-now` with the evidence — no heroics.

**Verdict enum (one row per source):** `fetchable-plain | fetchable-playwright | API-only |
dead-for-now`, each with evidence (what actually returned) and a capture date.

**Also fixes:** `docs/poke/sources.md` line 20's stale claim — corrected to "eBay Browse
creds NOT configured as of 2026-07-02 (no config.yaml ebay block; env vars empty); see
`docs/poke/ebay-keyset-setup.md`".

**Done:** `sources.md` fully re-verdicted (no PENDING rows left); a short **sign-off packet**
appended to `docs/poke/PHASE0_FINDINGS.md` (date, method, verdict table, what changed since
June, explicit recommendation), committed `docs(poke):`. The packet ends with the explicit
question to the operator — **the sweep is complete only when the operator says "signed off";
the campaign does not self-certify the Phase-B gate.**

## WP3 — eBay keyset instructions (operator handoff)

**Deliverable:** new `docs/poke/ebay-keyset-setup.md` containing:

1. Provisioning steps: developer.ebay.com → register (free) → create a **production** keyset
   → copy **App ID (client id)** and **Cert ID (client secret)**. Note eBay's application
   approval can take time; sandbox keys do NOT serve production Browse data.
2. Wiring (matches `scanner/resale.py:94-107` resolution order — config first, env fallback):
   put `ebay_client_id: "<App ID>"` and `ebay_client_secret: "<Cert ID>"` in the gitignored
   `config.yaml`; env alternative `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`. No token handling
   needed — the client mints its own OAuth token via client-credentials (`resale.py:609`).
   `ebay_marketplace_id` defaults to `EBAY_US`; leave unset.
3. Verification: run one comp lookup and confirm the quote's provenance is the eBay Browse
   client rather than `public_ebay_search`/PriceCharting fallback flags; the doc gives the
   exact one-liner (mirroring the seeding doc's probe pattern).
4. Security notes: the values are secrets — never commit, never print; `config.yaml` is
   already gitignored; rotating a leaked keyset happens on the eBay developer console.

**Done:** doc committed `docs(poke):`; operator handed a 3-step action card (provision →
paste two values → run verify one-liner).

## Cross-cutting guardrails

- Credit ceiling 50 this session; `limit=1` on every by-id call; remaining-count logged.
- Price plausibility check on every seeded id (a $5 "ETB" is a wrong variant).
- Never push; commits stay on local `main` in the repo's conventional style.
- No secret values read, printed, or committed anywhere in the campaign.

## Error handling summary

WP1: skip-and-record per product; 2-consecutive-error circuit-breaker; hard-stop below 15
credits. WP2: two timeouts → `dead-for-now` verdict, move on; a policy-blocked source is a
verdict, not a failure. WP3: pure documentation — the only failure mode is inaccuracy, checked
against `resale.py`'s actual resolution code before commit.

## Verification / campaign-done criteria

1. WP1: 7/7 boxes resolved; suite green; spend ≤ 50 logged.
2. WP2: zero PENDING rows in `sources.md`; sign-off packet present and ends with the
   operator question; stale claim corrected.
3. WP3: setup doc exists and matches the code's cred-resolution order.
4. Progress ledger closes the campaign with per-WP outcomes.
5. The Phase-B gate state after this campaign: **open pending exactly two operator actions**
   (sweep sign-off + keyset provisioning) — nothing else.
