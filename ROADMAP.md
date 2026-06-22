# Pokémon Scanner — Strategy & Roadmap (developed)

This is the developed version of the "highest-value next moves" brief, re-grounded
in the actual codebase. The original instinct was right: **viability comes from
coverage, truthfulness, and operator workflow — not features.** What follows turns
each idea into something specific to *this* code: where it lives, what's already
half-built, the precise gap, and acceptance criteria.

---

## 0. The one number that reframes everything

The catalog has **13 products**. Real ID coverage today (`data/products.yaml`):

| Retailer       | IDs present | Notes |
|----------------|-------------|-------|
| Best Buy       | 12 / 13     | needs API key + `enabled` to actually fire |
| **Target**     | **11 / 13** | enabled by default, route-based |
| Walmart        | 1 / 13      | online-only signal |
| Costco         | 0 / 13      | adapter works, zero IDs |
| GameStop       | 0 / 13      | adapter works, zero IDs |
| Pokémon Center | 0 / 13      | adapter works, zero IDs |

With the default config (`target` + `walmart` on, Best Buy off/no-key, rest off),
the 85% coverage score you've seen is **almost entirely Target**. Actionable =
"has an ID for an enabled, ready retailer" = every product with a Target TCIN or
the one Walmart ID = 11/13 = **85%**.

That single fact fuses three of your bullets into one thesis:

> **Coverage is a Target monoculture.** If Target 403s — the single most likely
> failure in the whole system (`scanner/retailers/target.py:20` ships a hardcoded
> public RedSky key that Target can rotate at will) — effective coverage collapses
> from 85% to ~8% (Walmart's lone online product). "Fill IDs," "Target dependency
> risk," and "coverage as truth" are the *same problem* viewed three ways.

So the spine of this roadmap is: **break the Target monoculture by making the other
adapters real (they already work — they're just starved of IDs), and make the app
tell the truth about how concentrated and fragile its coverage is.**

---

## 1. Reframe: 9 features → 1 model + 1 maintained asset

Your list reads as nine features. In this codebase they're really **two things plus
their projections**:

1. **A maintained catalog** (verified IDs + MSRP/image + provenance) — the asset.
2. **A single Source-Confidence model** — one function that every panel reads from.

Everything else (work queue, decision-ready board, Costco card, source badges,
alert annotations) is a *projection* of those two. Building the model once and
deriving the rest is the difference between nine half-coupled features and one
coherent system. The current code already proves this is the right shape — it just
has the logic **split across two systems that don't talk to each other**:

- `scanner/health.py` → runtime health (`healthy/degraded/down/unknown`) from
  actual HTTP outcomes.
- `scanner/coverage.py` + `web._retailer_payload` → config readiness
  (`enabled/supported/apiKeyRequired/queryReady/withId`).

Your "source confidence state" list — *working / blocked / needs ID / needs API key
/ parser suspect / not implemented* — is **exactly the union of those two systems**.
Unifying them is the highest-leverage structural move and it unblocks four of your
bullets at once.

---

## Part I — Foundations: make the catalog *true*, not just *full*

> Your #1 ("fill verified product IDs"). The catalog's own stated principle is that
> it "ships intentionally sparse so it never carries stale or guessed identifiers"
> (`README.md:180,273`). A manual research pass that pastes IDs into `products.yaml`
> **violates that principle the moment an ID rots or is mistyped** — and you can't
> tell which IDs are trustworthy by looking.

**Concrete evidence the risk is already live:** `prismatic_evolutions_etb` has
`target_tcin: "1011206804"` (10 digits) while every other TCIN in the file is 8
digits (`93954446`, `88897899`, …). That doesn't prove it's wrong — but it's
exactly the kind of thing a human research pass produces and never catches. The fix
isn't "look harder," it's "make the scanner check its own IDs."

### 1a. ID Doctor — make "verified" a *maintained property*, not a one-time claim

New tool `scanner/verify_ids.py` (CLI: `python -m scanner.verify_ids`; button in
the UI). For each populated `(product, retailer-field)`, do the cheapest possible
resolve against that retailer and classify:

- `CONFIRMED` — endpoint returns the product (Target product_fulfillment 200 with a
  matching TCIN; Costco GDX summary returns a product row; Best Buy SKU resolves).
- `NOT_FOUND` — 200/404 but no such item → the ID is wrong/dead.
- `BLOCKED` — 403/429 → can't tell, retry later (don't punish the ID).
- `AMBIGUOUS` — resolves but name/price looks off vs the catalog `name`.

This reuses the adapters' existing single-item paths — Costco already has
`_summary_for_item` (`costco.py:302`), Target already has its fulfillment call. The
verifier is a thin wrapper that calls the resolve step **without** needing a store
(online resolve where possible) and records the verdict + timestamp.

**Why this is the keystone:** it converts "verified SKU research pass" from a chore
you do once into a property the system re-checks. It then *feeds* the work queue
("2 IDs need re-verification"), the confidence model ("ID_SUSPECT" vs "PARSER_SUSPECT"),
and lets you safely run a verified-catalog expansion sprint — because every ID you
add gets stamped CONFIRMED or rejected before it's trusted.

### 1b. Provenance sidecar — keep the clean catalog clean

Don't nest provenance into `products.yaml` — that would break the elegant
single-line rewriter in `identifiers.set_product_id` (`identifiers.py:64`), which
`add_id` and the UI both depend on. Instead add a **sidecar** `data/id_provenance.json`
keyed by `"<product_key>.<field>"`:

```json
{
  "prismatic_evolutions_etb.target_tcin": {
    "source_url": "https://www.target.com/p/-/A-93954435",
    "verified_at": 1717200000,
    "status": "CONFIRMED"
  }
}
```

`add_id` / the UI write the `source_url` when you paste a URL (it already *has* the
URL — it just throws it away after extracting the digits at `identifiers.py:46`).
The ID Doctor writes `status` + `verified_at`. The human-edited YAML stays flat and
diff-friendly.

### 1c. Catalog schema: add `msrp` and `image` (already consumed, currently starved)

The notifier **already reads** `prod.get("msrp")` and `prod.get("image")`
(`main.py:371-372`) and renders an MSRP-delta + thumbnail in the Discord embed
(`notify.py:55-57, 99-109`). But **no product in `products.yaml` has either field.**
The "price/MSRP delta" alert you want is wired end-to-end and producing nothing
because two fields are missing. Adding `msrp`/`image` to the catalog is a one-line-
per-product change that lights up alert logic that already exists. This is the
cheapest win in the entire roadmap.

**Sprint output:** verified-catalog pass for current sets, but gated on 1a existing,
so every new ID is CONFIRMED before it lands. Add `msrp`/`image` in the same pass
(you're already on the product page). Re-verify the suspicious Prismatic TCIN.

---

## Part II — The Source-Confidence spine

> Your "add source confidence / reliability." This is the model everything else
> reads from. Build it once as a pure, read-only derivation; don't touch adapter
> internals.

New module `scanner/confidence.py` exposing `source_state(slug, cfg, health_row,
selected_products) -> SourceState`. A retailer resolves to exactly one state by
**strict precedence** (first match wins):

| Precedence | State | Condition (from existing fields) | Operator meaning |
|---|---|---|---|
| 1 | `NOT_IMPLEMENTED` | `cls.supported is False` (e.g. Sam's Club, `samsclub.py:18`) | nothing to do; ignore |
| 2 | `DISABLED` | not `rcfg.enabled` | flip it on (if it has IDs) |
| 3 | `NEEDS_API_KEY` | `api_key_required` & key unset (`coverage._retailer_ready`) | get a free key |
| 4 | `NEEDS_ID` | enabled, supported, key ok, but `withId == 0` | **add IDs** (the big one) |
| 5 | `BLOCKED` | health `consecutive_failures ≥ N` w/ last HTTP 403/429 | back off; not your fault |
| 6 | `PARSER_SUSPECT` | repeated `NO_DATA` (HTTP 200, 0 rows) while IDs present (`main._record_empty_query_health:329`) | **code fix needed** |
| 7 | `ID_SUSPECT` | ID Doctor verdict `NOT_FOUND`/`AMBIGUOUS` | re-verify the ID |
| 8 | `DEGRADED` | transient ERROR / staleness (`health.state()` degraded) | self-heals; watch |
| 9 | `WORKING` | healthy + has IDs + produced rows last pass | nothing to do ✅ |

Two design points that make it *fit this project*:

- **Retailer-level state is a roll-up of per-product reality.** A source can be
  `WORKING` for 8 products and `NEEDS_ID` for 5. The confidence badge shows the
  roll-up; the **work queue operates at `(retailer × product)` granularity** (Part
  III) so it can say "add Costco IDs for these 5 specific chase products."
- **It's additive and pure.** Every input already exists in `coverage_report()`,
  `health.snapshot()`, and `_product_payload`. No adapter changes, no new network
  calls. This directly respects your "no huge refactors while adapters are the core
  risk" guardrail.

`source_state` becomes the single backbone for: the summary-strip badge, the board
verdict line (Part IV), the work-queue ranking (Part III), and the alert confidence
tag (Part VIII). Build it once; read it everywhere.

---

## Part III — Coverage as a work queue (not a number)

> Your "turn coverage into a work queue." The data is **already computed** — this is
> a derivation + ranking + one-click, not a new pipeline.

`_product_payload` already produces a per-`(product, retailer)` `blockedReason`
string (`web.py:143-153`): `"missing product ID"`, `"missing API key"`,
`"retailer disabled"`, `"unsupported"`, `"product not selected"`. The work queue is
those reasons, **inverted into ranked actions** and grouped.

### Queue item model

Each item = `{ retailer, product?, action, why, effort, gain, oneClick }`:

- **action** maps from confidence state:
  `NEEDS_ID → "Add ID"`, `NEEDS_API_KEY → "Add API key"`,
  `DISABLED-but-has-IDs → "Enable source"`, `ID_SUSPECT → "Re-verify ID"`,
  `PARSER_SUSPECT → "Fix adapter (dev)"`.
- **effort tier** (drives ordering — do cheap, high-gain work first):
  `paste-an-ID` (easy) < `get-API-key` (external, medium) < `write-adapter` (hard).
- **gain** = how many products / how much coverage % the action unlocks, weighted by
  product priority (`priority.product_priority` — chase items first).

### Ranking

Sort by `gain × ease`, chase products first. So the queue reads like:

```
▸ Add Costco IDs — 13 products, 0/13   (+~? coverage, chase: Prismatic ETB, 151 ETB…)
▸ Add GameStop IDs — 13 products, 0/13
▸ Add Best Buy API key — 12 IDs ready, blocked only by the key
▸ Add Walmart IDs — 12 products missing
▸ Re-verify 1 Target ID — Prismatic ETB TCIN looks malformed (10 digits)
▸ Enable Pokémon Center — 0 IDs (add IDs first)
```

### One-click

Each `NEEDS_ID` item **pre-fills the existing Add-Product-ID form** (`#productIdForm`
in `index.html:85`, backed by `/api/product-id` → `save_product_id_payload`). The
queue item sets `idRetailer` + `idProduct` and focuses the URL box. No new write
path — you already built the safe single-field writer; the queue just routes the
operator to it with context. `NEEDS_API_KEY`/`DISABLED` items deep-link to the
Settings panel.

**Acceptance:** opening the dashboard with the default catalog shows a ranked,
clickable to-do list whose top item is "Add Costco IDs for 13 products," and
clicking it lands you in the Add-ID form with Costco + a chase product preselected.

---

## Part IV — Decision-ready board (answer "what should I do?")

> Your "improve scan output from technical to decision-ready." The board
> (`_stock_board_payload`, `web.py:523`) already separates OUT / BLOCKED /
> NO_DATA / DISCOVERY_FAILED / NOT_CHECKED via `missing_status` (`web.py:539`). The
> missing layer is the **verdict + next action per source.**

Give each retailer section in the board a single **verdict line** generated from
`source_state`:

- `NEEDS_ID` → "Costco is ready, but has 0 IDs. Add `costco_item_id` for your chase
  products to activate it." ← exactly the "Costco ready but disabled; add IDs or
  enable source" line you asked for, generated systematically rather than hand-written.
- `BLOCKED` → "Target blocked (HTTP 403) for 3 cycles; backing off automatically.
  Online sources are unaffected."
- `PARSER_SUSPECT` → "GameStop returned HTTP 200 but 0 rows for 4 cycles — likely a
  parser break. Needs a code fix."
- `WORKING` → suppressed (don't narrate success; show the stock chips).

**Also fix a real truthfulness bug here:** when Target discovery 403s, the board row
currently renders `"No route stores found"` (`web.py:582-590`) — which reads as
"there are no Targets near you," a lie. The discovery diagnostics already know the
difference (`discover_stores` sets `diag["status"]` to `blocked` vs `empty` vs
`filtered_out`, `main.py:266-273`). Thread that status into the board row so
"blocked" and "genuinely no stores in corridor" stop looking identical. This is the
"separate Target-blocked from no-stores" item, made precise.

Keep the Technical Log exactly where it is — collapsed (`index.html:71`). The
verdict line is the headline; the log is the appendix.

---

## Part V — Costco, first-class

> Your #2. Costco is the **most complex adapter** (a 4-endpoint chain) and the one
> with the most invisible failure modes — which is exactly why a "Test Costco item"
> probe is so valuable.

The chain (`costco.py`): warehouse locator (`find_stores:153`) → product summary
(`_summary_for_item:302`) → distribution centers (`_distribution_centers_for_store:351`)
→ inventory batch (`_inventory_for_items:393`). **Every step returns `None`/`[]` on
failure and the reasons collapse together.** A bad `costco_item_id`, a store with no
postal/state, and a 403 all look the same: "nothing."

### 5a. "Test Costco Item" button → a 4-step probe

One product + one warehouse, surfacing **which step passed**:

```
Costco item 4000313298 @ warehouse #347 (Fortune Park):
  ✅ warehouse located (#347, Fortune Park, DC resolved: 1234,5678)
  ✅ product summary resolved → "Pokémon TCG …", $49.99
  ✅ distribution centers → 2 DCs
  ❌ inventory → HTTP 403 (blocked) — retry later
```

This is simultaneously (a) the "Test Costco item" button you wanted, (b) the Costco
arm of the ID Doctor (Part I — step 2 failing = ID is bad), and (c) the answer to
"show Fortune Park / warehouse 347 clearly when discovered" — the probe *names* the
warehouse and the resolved DCs instead of leaving them implicit.

### 5b. Record health on discovery failure

`find_stores` returns `[]` on a non-200 **without recording health** (`costco.py:172`).
Target does record it; Costco silently doesn't. Add a `health.record_failure(
"costco", "DISCOVERY_FAILED", …)` so a blocked Costco warehouse lookup shows up as
`BLOCKED`/`DEGRADED` instead of a mysterious empty board.

### 5c. Coverage-gap + URL helper in the UI

"0 Costco IDs" is the top work-queue item (Part III) with Costco-specific helper
text in the Add-ID form: "Costco URLs look like `…/foo.product.4000313298.html` —
the number after `.product.` is the ID" (the extractor at `identifiers.py:35`
already handles both `.product.` and `/product/` forms; surface that hint).

**Acceptance:** a non-technical operator can paste one Costco URL, click "Test
Costco Item," and get a plain-English report of exactly how far the check got and
why it stopped.

---

## Part VI — Target dependency risk (de-risk the monoculture)

> Your #3, now quantified by Part 0: ~85% of coverage rests on Target, and Target is
> the single most blockable source.

Three concrete, adapter-light changes:

### 6a. Circuit breaker / adaptive backoff

`health.RetailerHealth` already tracks `consecutive_failures` (`health.py:40`).
Today every cycle re-hits a blocked Target, fails again, and re-logs the 403. Add a
breaker in the scan loop: once `consecutive_failures ≥ 3` with HTTP 403/429, **skip
Target for an exponentially growing cooldown** (cap ~30 min), then probe once. This
stops the dashboard from filling with identical Target-blocked warnings every 3
minutes and stops antagonizing RedSky. The HTTP layer already honors `Retry-After`
for single requests (`http.py:41`); this extends the same politeness to the
source level.

### 6b. Auto-deprioritize a chronically blocked source

"Consider lowering Target priority if it blocks too often" → make it automatic, not
a config edit. When Target is in `BLOCKED` cooldown, the board verdict says so and
the work queue surfaces "Target has been blocked for N cycles — your coverage is
effectively X% without it; consider adding Walmart/Best Buy/Costco IDs as backups."
This turns a failure into a *coverage-diversification nudge* — which is the actual
fix.

### 6c. Flag the key-rotation failure mode explicitly

The RedSky key is hardcoded with a `TARGET_API_KEY` env override (`target.py:20`).
When persistent 403s coincide with a key that hasn't been refreshed, the confidence
state should read `BLOCKED` with detail "RedSky key may be rotated — set
`TARGET_API_KEY`" rather than a generic block. This is the difference between the
operator waiting helplessly and the operator knowing the one lever that fixes it.

The deeper mitigation is strategic, not code: **the cure for Target risk is Parts I
+ III** — get Costco/Walmart/Best Buy IDs in so Target stopping isn't catastrophic.
6a–6c make the *symptom* honest; coverage diversification makes the *disease* go away.

---

## Part VII — Truthful background operation ("am I actually running?")

> Your "background operation polish." There's a real architectural gap here worth
> calling out before building UI on top of it.

**The gap:** the README's unattended mode (`README.md:184-201`) installs a Windows
Scheduled Task that runs **`python -m scanner`** (the CLI loop) — a *separate
process* from the web dashboard. But the dashboard's runner state
(`lastScanAt`, `nextScanAt`, `phase`, `scanCount`) lives in an **in-memory
singleton** (`web.RUNNER`, `web.py:1024`). So if you install the background CLI task
*and* open the dashboard to check on it, the dashboard shows **"idle / not
scanning"** even though the task is scanning hard — because they're different
processes with separate in-memory runners. Shared state goes through SQLite
(`source_health`, `stock_history`), but **liveness does not.**

### 7a. Persisted heartbeat (the foundation for everything else here)

Add a `scanner_heartbeat` row to the SQLite state DB (or derive from
`max(source_health.updated_ts)` — `state.py:200` already persists a health snapshot
every pass). Each `run_pass` writes `{pid, last_scan_ts, next_scan_ts, scan_count,
source: "cli"|"web"}`. Now **any** reader — the web UI, or a new `python -m scanner
--status` — can truthfully answer "is something scanning, and when did it last run?"
regardless of which process owns the loop. This makes the whole "am I running"
story honest instead of per-process.

### 7b. Scheduled-task visibility

The dashboard can't see whether the Scheduled Task is installed. Add a
`-Status` mode to `scripts/install-scheduled-task.ps1` (it's already `-Install` /
`-Remove` / dry-run by default) and surface "Background task: installed / not
installed" in the UI. Answers your "startup task installed/not installed" directly.

### 7c. The "running" card

Once 7a/7b exist, the runner card (`renderRunner`, `app.js:120`) becomes truthful:
last scan (from heartbeat, cross-process), next scan, scans completed, recent errors
(`lastError` already exists), background-task install state, and a stale-heartbeat
warning ("last heartbeat 47 min ago — the background scanner may have died").

**Acceptance:** install the background task, close every terminal, open the
dashboard fresh — it correctly shows the scanner as alive with a recent last-scan
time.

---

## Part VIII — Alert tuning (prioritize *action*)

> Your "alert tuning." The notifier is already rich (`StockAlert` carries priority,
> MSRP, image, first-seen, restock-count — `notify.py:37-49`). Two gaps:

### 8a. Feed it data (depends on Part I)

MSRP-delta and thumbnail are dead until `msrp`/`image` exist in the catalog (1c).
Do that first; the alert quality jumps for free.

### 8b. Rank a *batch* of simultaneous hits

When several products pop in one cycle, they currently fire in retailer-registry
order (`run_pass` iterates `RETAILER_REGISTRY`, `main.py:340`). Add a per-cycle
**alert ranking**: high-priority first, then nearest store (distance is already on
the result), then biggest MSRP delta, then restock rarity. A person glancing at
their phone should see the chase-grail-at-the-nearest-store alert on top, not
whichever retailer happened to be checked first. Optionally collapse a flood into a
single ranked digest embed.

### 8c. Richer priority than a keyword on/off

`product_priority` is binary — 100 if a keyword matches, else 10 (`priority.py:31`).
Add **set-release awareness**: products carry a `set` field; a newly released set is
the single highest-yield restock window. A small `data/set_calendar.yaml`
(`set → release_date`) lets priority boost "released in the last N days," so the
scanner naturally leans into fresh drops without you re-tuning keywords each set.

---

## Anti-goals (sharpened for this project)

Keeping your "what I would not do," plus guardrails the code itself implies:

- **No auto-checkout / cart bots.** (Unchanged — `README.md:16`. The adapters are
  read-only by contract; `http.py` GET/POST are stock-query only.)
- **No unverified IDs written to `products.yaml`.** Gate the catalog-expansion
  sprint on the ID Doctor (Part I) existing — otherwise you violate the catalog's
  own "never carry guessed IDs" principle (`README.md:180`).
- **Don't nest the catalog schema** in a way that breaks the single-line rewriter
  (`identifiers.set_product_id`). Use the provenance **sidecar** instead.
- **Don't build the work queue as a new data pipeline.** It's a pure derivation over
  payloads that already exist (`coverage_report`, `_product_payload`, `health`).
- **No new retailers without a verified endpoint.** Sam's Club stays a declared-
  unsupported placeholder (`samsclub.py:18`) until a real signal exists — that
  pattern is correct; keep it.
- **Don't chase sub-60s latency.** The edge is coverage × diversity, not polling
  speed (`README.md:253,273`). The breaker in Part VI moves *away* from aggressive
  polling, not toward it.
- **No per-LGS scraping.** (Unchanged — `README.md:256`.)
- **No "AI prediction" before the ID Doctor + heartbeat give you clean, trustworthy
  historical data.**

---

## Sprint sequence (dependency-ordered)

The ordering matters because later parts read from earlier ones.

**Sprint 1 — Catalog truth (foundation, highest value).**
ID Doctor (`verify_ids.py`) + provenance sidecar + `msrp`/`image` schema +
re-verify the malformed Prismatic TCIN. → *Parts I, 1c. Unblocks 8a.*
*Done when:* every populated ID is stamped CONFIRMED/NOT_FOUND/BLOCKED with a
timestamp, and a verified-catalog expansion can run safely.

**Sprint 2 — The Source-Confidence spine.**
`confidence.py` unifying health + readiness into one `SourceState` with the Part II
precedence. Pure, additive, no adapter changes. → *Part II. Unblocks III, IV, VIII.*
*Done when:* one function returns the right state for every retailer, with unit tests
for each precedence branch.

**Sprint 3 — Work queue + decision-ready board.**
Derive the ranked queue from confidence + `blockedReason`; pre-fill the Add-ID form;
add board verdict lines; fix the "no route stores" vs "blocked" lie. → *Parts III, IV.*
*Done when:* the dashboard's top action on a fresh default catalog is "Add Costco IDs
for 13 products," one click from doing it.

**Sprint 4 — Costco first-class + Target de-risk.**
"Test Costco Item" 4-step probe; Costco discovery health; Target circuit breaker +
key-rotation flag + coverage-diversification nudge. → *Parts V, VI.*
*Done when:* a blocked Target backs off quietly and the board explains it, and a
Costco item can be diagnosed step-by-step in plain English.

**Sprint 5 — Truthful background op + alert ranking.**
Persisted cross-process heartbeat; `--status`; scheduled-task `-Status` + UI;
per-cycle alert ranking; set-release priority. → *Parts VII, VIII.*
*Done when:* the dashboard truthfully reports a background task it doesn't own, and a
flood of hits arrives newest-grail-nearest-store first.

---

### The through-line

Sprint 1 makes the catalog *trustworthy*. Sprint 2 gives every panel *one truth to
read*. Sprints 3–5 are projections of that truth into the operator's workflow. None
of it touches the adapter internals that are your real risk surface — it wraps them
in honesty and turns the 85%-Target-monoculture into a diversified, self-reporting
system. That's the difference between a scanner that *looks* 85% done and one that
*is*.
