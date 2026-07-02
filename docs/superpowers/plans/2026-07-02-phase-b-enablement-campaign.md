# Phase-B Enablement Campaign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear the three Phase-B gates per the approved spec
(`docs/superpowers/specs/2026-07-02-phase-b-enablement-campaign-design.md`): seed the 7
remaining `ppt_id`s (live PPT, ~42 credits authorized), complete the Phase-0 fetchability
sweep to an operator sign-off packet, and hand the operator an eBay keyset setup doc.

**Architecture:** Three independent work packages executed cheapest-risk first (WP1 live data
→ WP2 research sweep → WP3 documentation), plus a read-only integrated verification. No
`scanner/` code changes anywhere. WP1 is the only task that spends PPT credits; WP2 is the
only task that touches the live web (WebFetch/WebSearch/Playwright MCP); WP3 is offline.

**Tech Stack:** PPT v2 REST API (via the seeding doc's `python -c` pattern), WebFetch /
WebSearch / Playwright MCP browser tools, markdown docs, pytest (regression only).

## Global Constraints

Copied from the spec — every task implicitly includes these:

- **Credit ceiling 50 this session** (authorized ~42). `limit=1` on every by-id call —
  omitting `limit` bills 50 credits. Log `X-RateLimit-Daily-Remaining` from every response.
- **Hard-stop WP1 when remaining < 15.** **Circuit-breaker: 2 consecutive API errors abort
  the run.** At most **ONE** alternate-name retry search across the entire run (base spend
  42 + one retry 5 = 47 ≤ 50).
- Never force a guess on an ambiguous match — `NOT_FOUND` with the candidate list is a valid
  terminal state (a wrong id poisons comps silently).
- Price plausibility check on every seeded id (a $5 "ETB" is a wrong variant).
- **No secret values read, printed, or committed** — commands may pass `cfg.market_api_key`
  into a header but must never print it; WP3 documents where eBay secrets GO, never touches
  values.
- Never push. Commits on local `main`, conventional style, each ending with the trailer
  `Co-Authored-By: Claude Fable 5 (1M context) <noreply@anthropic.com>`.
- No `scanner/` code changes; no roadmap/spec edits beyond the two doc files named in WP2.
- WP2 cannot self-certify the Phase-B gate — its packet ENDS with the operator question.
- Test-cycle adaptation: WP1 verifies via by-id lookups + full pytest suite
  (`.venv/Scripts/python.exe -m pytest -q`, expect 276 passed); WP2/WP3 verify via evidence
  rows and symbol checks (no pytest impact).

## File Structure

- Modify: `data/products.yaml` (WP1 — add `ppt_id:` lines only)
- Modify: `docs/poke/ppt-id-seeding.md` (WP1 — checklist resolution)
- Modify: `docs/poke/sources.md` (WP2 — verdict table, stale-claim fix)
- Modify: `docs/poke/PHASE0_FINDINGS.md` (WP2 — append sign-off packet)
- Create: `docs/poke/ebay-keyset-setup.md` (WP3)

---

### Task 1: WP1 — Seed the 7 remaining `ppt_id`s (live PPT, credits authorized)

**Files:**
- Modify: `data/products.yaml`
- Modify: `docs/poke/ppt-id-seeding.md`

**Interfaces:**
- Consumes: `docs/poke/ppt-id-seeding.md` (the canonical procedure — read it first);
  existing seeded entries in `data/products.yaml` (mirror their `ppt_id: "<digits>"`
  placement/quoting style, e.g. `prismatic_evolutions_etb` → `ppt_id: "593355"`).
- Produces: resolved checklist rows Task 4 counts; updated `products.yaml` the suite loads.

- [ ] **Step 1: Read the two files** — `docs/poke/ppt-id-seeding.md` in full;
  `data/products.yaml` enough to see how a seeded product carries `ppt_id` and where the 7
  target keys live.

- [ ] **Step 2: Per product, run the search (5 credits).** Targets and clean search names:

| key | search name |
| --- | --- |
| `destined_rivals_etb` | `Destined Rivals Elite Trainer Box` |
| `surging_sparks_etb` | `Surging Sparks Elite Trainer Box` |
| `surging_sparks_booster_bundle` | `Surging Sparks Booster Bundle` |
| `scarlet_violet_151_etb` | `151 Elite Trainer Box` |
| `scarlet_violet_151_booster_bundle` | `151 Booster Bundle` |
| `paldean_fates_etb` | `Paldean Fates Elite Trainer Box` |
| `crown_zenith_etb` | `Crown Zenith Elite Trainer Box` |

Command (exact; substitute the search name):

```powershell
.venv/Scripts/python.exe -c "
import requests
from scanner import config as cfg_mod
cfg = cfg_mod.load()
r = requests.get('https://www.pokemonpricetracker.com/api/v2/sealed-products',
    params={'search': 'Destined Rivals Elite Trainer Box', 'limit': 5},
    headers={'Authorization': f'Bearer {cfg.market_api_key}'}, timeout=30)
print('HTTP', r.status_code, '| remaining:', r.headers.get('X-RateLimit-Daily-Remaining'))
for d in r.json().get('data', []):
    print(d.get('tcgPlayerId'), '|', repr(d.get('name')), '|', d.get('unopenedPrice'), '|', repr(d.get('setName')))
"
```

Log the `remaining:` value after EVERY call. The first call's value is the session's opening
budget — record it.

- [ ] **Step 3: Select the standalone product in the right set.** Exclusions (from the
  seeding doc + known trap variants): "… and Pokeball", "… Case", "(Sam's Club)",
  "(Dollar General Exclusive)", sticker/tech/poster/binder/Ultra-Premium collections, and
  **"Pokemon Center" exclusive ETB variants** (several sets have both — pick the regular
  standalone ETB). Decision rule: if no candidate clearly satisfies "standalone + right set,"
  record `NOT_FOUND` with the candidate list — do not guess. If the standalone is plausibly
  just outside the top 5, ONE alternate-name retry is allowed for the whole run (e.g.
  `Scarlet & Violet 151 Elite Trainer Box`); after that, `NOT_FOUND`.

- [ ] **Step 4: Add the id to `data/products.yaml`** — surgical Edit, one line per product,
  mirroring the existing style exactly: `ppt_id: "<tcgPlayerId>"` (quoted string) placed the
  same way as in the already-seeded entries.

- [ ] **Step 5: Verify by id (1 credit — `limit=1` is mandatory).**

```powershell
.venv/Scripts/python.exe -c "
import requests
from scanner import config as cfg_mod
cfg = cfg_mod.load()
r = requests.get('https://www.pokemonpricetracker.com/api/v2/sealed-products',
    params={'tcgPlayerId': '625670', 'limit': 1},
    headers={'Authorization': f'Bearer {cfg.market_api_key}'}, timeout=30)
print('HTTP', r.status_code, '| remaining:', r.headers.get('X-RateLimit-Daily-Remaining'))
for d in r.json().get('data', []):
    print(d.get('tcgPlayerId'), '|', repr(d.get('name')), '|', d.get('unopenedPrice'), '|', repr(d.get('setName')))
"
```

(substitute the chosen id). Confirm: name matches the selected standalone product AND
`unopenedPrice` is plausible for the product class (ETBs roughly $40–$250; bundles roughly
$25–$120; a price way outside that band = wrong variant → investigate or `NOT_FOUND`).

- [ ] **Step 6: Stop-rule bookkeeping between products.** If `remaining < 15` → hard-stop the
  run, record which products are left, proceed to Step 7 with partial results. If 2
  consecutive calls returned HTTP ≥ 400 or errored → abort the run the same way. A skipped
  product records WHY (error text / ambiguity list).

- [ ] **Step 7: Update `docs/poke/ppt-id-seeding.md`** — resolve each attempted row in the
  existing line style:
  - seeded: `- [x] <key> — ppt_id: <id> ($<unopenedPrice>; verified 2026-07-02)`
  - not found: `- [x] <key> — NOT_FOUND: <one-line reason> (2026-07-02; stays on resale fallback)`
  - stopped-before-reached (only if hard-stop/abort fired): leave `- [ ]` and add a one-line
    note under the list naming the stop reason and remaining credits.

- [ ] **Step 8: Run the full suite.**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: `276 passed` (products.yaml is load-bearing for config tests; any failure here
means the YAML edit broke loading — fix the YAML, never the tests).

- [ ] **Step 9: Commit** (both files, one commit):

```powershell
git add data/products.yaml docs/poke/ppt-id-seeding.md; git commit -m @'
data(poke): seed remaining Pokemon ppt_ids (<N> verified, <M> not-found)

Co-Authored-By: Claude Fable 5 (1M context) <noreply@anthropic.com>
'@
```

(substitute real counts). Report must include: per-product outcome table, opening/closing
`remaining` values, total credits spent.

---

### Task 2: WP2 — Phase-0 completion sweep (no PPT credits; ends at operator sign-off)

**Files:**
- Modify: `docs/poke/sources.md`
- Modify: `docs/poke/PHASE0_FINDINGS.md` (append only)

**Interfaces:**
- Consumes: the existing verdict-table format in `docs/poke/sources.md` (read it first;
  extend, don't reinvent).
- Produces: zero PENDING rows in `sources.md`; a dated sign-off packet at the end of
  `PHASE0_FINDINGS.md` that Task 4 checks for.

- [ ] **Step 1: Read `docs/poke/sources.md` and the tail of `docs/poke/PHASE0_FINDINGS.md`**
  to match their formats.

- [ ] **Step 2: Probe the fixed set.** Verdict enum (exact strings):
  `fetchable-plain | fetchable-playwright | API-only | dead-for-now`.
  Method per source: (a) WebFetch the URL asking "list any product names and prices visible
  on this page" — meaningful content → `fetchable-plain`; (b) blocked/empty/JS-shell →
  Playwright MCP (`browser_navigate` + `browser_snapshot`) — content → `fetchable-playwright`;
  (c) two timeouts → `dead-for-now`; a policy-layer block or API-requiring wall → `API-only`
  with the API named. If Playwright MCP tools are unavailable in this environment, keep the
  best-supported verdict and note "playwright probe unavailable this session" in the evidence
  cell — honesty over completeness. Every row gets an evidence string (what actually
  returned) + capture date 2026-07-02.

Fixed probe set (starting URLs; follow obvious redirects):

| Source | Start URL |
| --- | --- |
| Target sale/search page | `https://www.target.com/s?searchTerm=pokemon+trading+cards` |
| Best Buy search | `https://www.bestbuy.com/site/searchpage.jsp?st=pokemon+trading+cards` |
| Costco search | `https://www.costco.com/CatalogSearch?dept=All&keyword=pokemon+cards` |
| Pokémon Center new/sale | `https://www.pokemoncenter.com/category/new-releases` (note in evidence: scanner already reads PC product `.js` endpoints for stock) |
| r/PKMNTCGDeals (re-verify) | `https://www.reddit.com/r/PKMNTCGDeals/` |
| eBay search (re-verify) | `https://www.ebay.com/sch/i.html?_nkw=pokemon+elite+trainer+box` |
| TCGplayer search (re-verify) | `https://www.tcgplayer.com/search/pokemon/product?q=elite+trainer+box` |

- [ ] **Step 3: Curators — WebSearch then probe top 3–5.** WebSearch for current Pokémon TCG
  deal roundups/curators (queries like `pokemon tcg deals site` / `pokemon sealed deals
  blog`), pick the top 3–5 distinct candidates by apparent activity, probe each with the
  Step-2 method. Bounded at 5 — this is a fetchability sweep, not a source census.

- [ ] **Step 4: Rewrite the `sources.md` verdict table** — every fixed-set + curator row gets
  verdict/evidence/date; **no PENDING rows may remain**. Replace the stale line 20 claim with
  exactly: `eBay Browse creds NOT configured as of 2026-07-02 (no config.yaml ebay block; env
  vars empty); see docs/poke/ebay-keyset-setup.md` (keep the row's verdict cell accurate:
  `API-only — needs eBay Browse keyset`).

- [ ] **Step 5: Append the sign-off packet** to `docs/poke/PHASE0_FINDINGS.md`:

```markdown
## Phase-0 completion sweep — 2026-07-02

**Method:** WebFetch-first, Playwright-MCP fallback, two-timeout rule, verdicts + evidence
per source (full table in sources.md).

| Source | Verdict | Evidence (2026-07-02) |
| --- | --- | --- |
<one row per source probed, copied from sources.md>

**Changed since June:** <bullets: what re-verification showed vs the June sample, incl. the
corrected eBay-creds claim>

**Recommendation:** <which sources DISCOVER should target first and via what path>

**Operator: does this complete Phase-0 Probe B — signed off? (yes → Phase B unblocked;**
**this packet does not self-certify.)**
```

(The table/bullet contents are the sweep's findings — structure above is binding, findings
come from Steps 2–3 evidence.)

- [ ] **Step 6: Commit:**

```powershell
git add docs/poke/sources.md docs/poke/PHASE0_FINDINGS.md; git commit -m @'
docs(poke): Phase-0 completion sweep - all sources verdicted, sign-off packet appended

Co-Authored-By: Claude Fable 5 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 3: WP3 — eBay keyset setup doc (offline; no secrets touched)

**Files:**
- Create: `docs/poke/ebay-keyset-setup.md`

**Interfaces:**
- Consumes: `scanner/resale.py` symbol ground truth (verified 2026-07-02):
  `credentials_from_config` (:91), `auth_configured(cfg)` (:111),
  `resale_client_from_config(cfg) -> EbayResaleClient | PublicFallbackResaleClient` (:746),
  cred resolution config-first at :94–107, OAuth client-credentials mint at :609.
- Produces: the doc Task 4 existence-checks and the operator action card references.

- [ ] **Step 1: Write the file with exactly this content:**

```markdown
# eBay Browse API — keyset setup (operator task)

The scanner's eBay comp client (`scanner/resale.py` — `EbayResaleClient`) is fully built but
has no credentials, so `resale_client_from_config` silently returns the
PriceCharting/public fallback today (confirmed 2026-07-02). Two values fix it.

## 1. Provision (free, developer.ebay.com)

1. Register at <https://developer.ebay.com> (free account) and sign in.
2. Create an application → request a **Production** keyset (sandbox keys do NOT serve
   production Browse data). Application approval can take from minutes to days.
3. From the keyset page copy two values: **App ID (Client ID)** and **Cert ID (Client
   Secret)**.

## 2. Wire (two lines in the gitignored config.yaml)

Resolution order is config-first, env fallback (`scanner/resale.py:94-107`):

    ebay_client_id: "<App ID>"
    ebay_client_secret: "<Cert ID>"

Env alternative: `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`. Nothing else is needed — the
client mints its own OAuth token via client-credentials (`resale.py:609`);
`ebay_marketplace_id` defaults to `EBAY_US` (leave unset). A pre-minted token via
`ebay_browse_api_token` / `EBAY_BROWSE_API_TOKEN` also works but expires — prefer id+secret.

## 3. Verify (zero API calls, zero secret output)

    .venv/Scripts/python.exe -c "
    from scanner import config as cfg_mod, resale
    cfg = cfg_mod.load()
    print('auth_configured:', resale.auth_configured(cfg))
    print('client:', type(resale.resale_client_from_config(cfg)).__name__)
    "

Before keyset: `auth_configured: False` / `client: PublicFallbackResaleClient`.
After keyset: `auth_configured: True` / `client: EbayResaleClient`.
Optional live check (1 Browse call): run any scanner comp path and confirm the quote's flags
no longer include `public_ebay_search`.

## Security

- These are secrets: never commit, never print, never paste into chat. `config.yaml` is
  already gitignored.
- If a value leaks, rotate the keyset on the eBay developer console (Application Keys page).
```

- [ ] **Step 2: Verify the doc's claims against the code** (guards against drift between
  plan-writing and execution):

Run: `.venv/Scripts/python.exe -c "from scanner import resale; assert hasattr(resale,'auth_configured') and hasattr(resale,'resale_client_from_config') and hasattr(resale,'EbayResaleClient') and hasattr(resale,'PublicFallbackResaleClient'); print('symbols OK')"`
Expected: `symbols OK`

Also run the doc's own Step-3 verify one-liner now — expected (pre-keyset):
`auth_configured: False` / `client: PublicFallbackResaleClient`.

- [ ] **Step 3: Commit:**

```powershell
git add docs/poke/ebay-keyset-setup.md; git commit -m @'
docs(poke): eBay Browse keyset setup instructions (operator task)

Co-Authored-By: Claude Fable 5 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 4: Integrated verification + operator action card (read-only)

**Files:** none created or modified (report only).

**Interfaces:**
- Consumes: Task 1's checklist resolution, Task 2's sign-off packet, Task 3's doc.
- Produces: the campaign verification report + the operator action card.

- [ ] **Step 1: Campaign-done criteria checks** (spec §Verification):

```powershell
Select-String -Path docs/poke/ppt-id-seeding.md -Pattern '^- \[ \]' | Measure-Object | Select-Object -ExpandProperty Count
```
Expected: `0` (all boxes resolved) — unless Task 1 hard-stopped, in which case the count must
equal the recorded stopped-before-reached products and the stop note must exist.

```powershell
Select-String -Path docs/poke/sources.md -Pattern 'PENDING' -Quiet
```
Expected: `False` (zero PENDING rows).

```powershell
Select-String -Path docs/poke/PHASE0_FINDINGS.md -Pattern 'signed off' -Quiet; Test-Path docs/poke/ebay-keyset-setup.md
```
Expected: `True` then `True`.

- [ ] **Step 2: Confirm clean repo state** — `git status --short` shows only the pre-existing
  untracked files (`data/poke/2026-07-01-sealed.*`, `data/poke/price_history.jsonl`,
  `sw-military-le.md`); `git log --oneline -4` shows the Task 1–3 commits. No push occurred.

- [ ] **Step 3: Assemble the operator action card** (in the report):
  1. **Sign off Phase-0** — read the packet at the end of `docs/poke/PHASE0_FINDINGS.md`;
     reply "signed off" (or objections). This is the Phase-B gate.
  2. **Provision the eBay keyset** — follow `docs/poke/ebay-keyset-setup.md` (3 steps,
     ~10 min + eBay approval lag); run its verify one-liner.
  3. Reminder: smoke-test 3 (fresh-session CLAUDE.md recall) self-validates next session.
  Also report: credits spent/remaining (from Task 1), and that the Browse-adapter brainstorm
  is the next move once 1+2 are done.

---

## Self-Review (completed at plan-writing time)

- **Spec coverage:** WP1→Task 1 (targets, procedure, stop rules, done criteria all present);
  WP2→Task 2 (probe set, enum, curator bound 3–5, stale-line fix, packet, operator gate);
  WP3→Task 3 (provisioning, wiring per verified resolution order, zero-cost verify, security);
  cross-cutting guardrails→Global Constraints; campaign-done criteria→Task 4. No gaps.
- **Placeholder scan:** `<N>`/`<M>`/table-content substitutions are run-time findings by
  design (research/data tasks); every command, path, format, and decision rule is exact.
- **Consistency:** verdict enum strings identical in Steps 2/4/5; checklist line formats match
  the existing file; credit math (42 base + max one 5-credit retry = 47 ≤ 50) consistent with
  Global Constraints; resale.py symbols in Task 3 match the grep evidence at :91/:111/:746/:609.
