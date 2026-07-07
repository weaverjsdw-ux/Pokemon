# Private Price-API Ladder — Phases G–M Roadmap

**Date:** 2026-07-06
**Status:** Draft for review. A **menu governed by a fixed order**, not seven committed specs — each
phase still earns its own spec → plan → build inside the single G–M build the operator has
scheduled. This document is the **governing contract** for that build: it fixes scope, order,
boundaries, acceptance, and the guardrails every phase inherits.
**Repo:** `Pokemon-main` (package `scanner/`; price-API subsystem `scanner/poke_api/`).
**Ladder position:** the continuation of the **private price-API ladder**
(A → B → C → D/D.5 → E → F → F.1 → **G → H → I → J → K → L → M**). This is **not** the older
`2026-06-28-resale-engine-program-roadmap.md` (that is the *discovery / scanner* A–E program). The
two ladders share a repo and STOP-class doctrine but are different subsystems; when this doc says
"the ladder," it means the `poke_api` price-and-edge layer.

**Companions (load on demand):**
[`private-price-api.md`](../../poke/private-price-api.md) (the A→F.1 ladder narrative),
[`ppt-vs-ours-gap-matrix-2026-07-06.md`](../../poke/ppt-vs-ours-gap-matrix-2026-07-06.md) (the
build/defer/reject source of these phases),
[`phase-g-handoff-notes-2026-07-06.md`](../../poke/phase-g-handoff-notes-2026-07-06.md) (the field
list G consumes — **note: its "pop is login-gated only" premise is superseded below, see §3**),
[`2026-07-06-phase-f1-independent-source-generalization-design.md`](2026-07-06-phase-f1-independent-source-generalization-design.md).

---

## 1. The system in one line

The price-intelligence **spine is built**: an owned, read-first `/api/poke` facade over our own comp
engine + evidence ledger, an **independent** (non-PPT) PriceCharting sold-source validator at 0 PPT
credits, an honest divergence audit, first-class **edge packets**, and STOP-class refusals PPT
itself lacks (ask-only, fake-entry, same-source guards). G–M stops *proving pricing truth* and
starts *turning it into controlled decision usefulness* — without weakening evidence quality. Every
phase adds a decision, a credibility layer, or an operability surface; **none** adds a new source of
truth, a paid read path, an automated buy, or a fuzzy shortcut.

## 2. Approach options (decision reaffirmed)

| # | Roadmap shape | Verdict |
|---|---|---|
| 1 | **Decision-first** — G gem-rate/EV credibility, then verified-entry activation, then breadth. | **Chosen.** Unlocks new *decisions* without weakening evidence quality. Each rung makes a real buy/hold judgment more defensible, not merely more numerous. |
| 2 | **Breadth-first** — ingest many cards/mappings next. | **Not yet.** More rows, not better decisions. Breadth *before* the truth rules (G–K) are stable multiplies un-vetted data. Breadth is **L**, deliberately last-but-one. |
| 3 | **PPT-parity** — chase parse-title, export, population UI, portfolio, polished public API. | **Rejected.** Turns an owned, disciplined edge layer into a PPT clone and adds low-value sprawl. The parts worth having (a *substitute* for parse-title, honest pop) are folded into G/K on our terms; the clone behaviors are Permanent Rejections (§12). |

The gap matrix already encodes this: of its 17 capabilities, the **one** that directly unblocks new
decisions is population/gem-rate (**G**); breadth/mapping/parse-title/export are `defer` (**J–L**);
portfolio/public-API-polish/fuzzy-mapping are `reject` (§12).

## 3. Refreshed public-source assumptions (verified live 2026-07-06)

All four findings below were re-checked this session; two change how G is scoped.

**3.1 PriceCharting *API* — premium, current-values-only, not needed.** The `/api/product` API is a
**paid tool** ("You must have a paid subscription to access the API"), keyed by a unique 40-char
token, CSV limited to one call / 10 min (files regenerated once / 24 h), and returns **current
values only**. Its card fields confirm the exact cells the scraper already reads for free:
`used-price` (Ungraded), `manual-only-price` (**PSA 10**), `graded-price` (Grade 9), `box-only-price`
(Grade 9.5), `new-price` (Grade 8), plus `cib-price` (**CGC 10**) and `bgs-10-price` (**BGS 10**).
**Decision: do not use the API.** It adds a paid dependency for numbers already free on the detail
page. (Note the API *does* expose CGC-10/BGS-10 columns that the free `#price_data` layout does not —
irrelevant to us, since G sources those grades' pop, not their price, and prices stay exact-cell-only
per F.1.) Source: `pricecharting.com/api-documentation`.

**3.2 PSA Public API — login-gated, cert-only, no public pop.** `api.psacard.com/publicapi` uses
OAuth2 password-grant with PSA credentials, 100 calls/day free, and does **one job: certificate
verification** (cert number → the card + grade PSA assigned). There is **no public PSA population
endpoint**; `/pop` HTML is sign-in-gated (403 unauthenticated). **G must not assume a stable public
PSA pop API** — confirmed. Third-party pop scrapers (Apify, Parse.bot) exist but are unofficial,
keyed, and unstable → **rejected** as a G dependency. Sources: `psacard.com/publicapi`,
`psacard.com/publicapi/documentation`, CardGrader PSA-API guide (2026).

**3.3 NEW — PriceCharting exposes PSA + CGC population as a plain-HTML JSON blob (the G unlock).**
The handoff notes assumed pop was "login-gated + unstable → operator-assumption gem rate only." That
premise is **superseded by a live probe this session.** The card detail page the F.1 adapter already
fetches (`pricecharting.com/game/{slug}`, plain browser-UA `requests` GET, 0 credits) embeds, in the
**initial HTML**, a clean structured blob:

```js
VGPC.pop_data = {"cgc":[0,0,0,1,0,2,16,122,259,366],"psa":[1,2,4,15,43,161,428,2654,9195,5487]};  // Umbreon ex #161
```

Ten-element per-grader arrays along the grade ladder (PSA 10 is the last element), with a
"population census updated monthly" stamp on the page. The chart (`<div id="pop-chart">`) is only the
visualization; the numbers are in the raw HTML — **no Playwright, no login, no paid API, same page and
same fetch path as the price cells.**

**Verified across the whole F.1 validation set, not just Umbreon** (the same anti-overfit bar F.1
itself had to clear). All **four** F.1 cards across three sets carry `VGPC.pop_data` at the same line,
same shape, in initial HTML:

| Card | Set | PSA total | PSA-10 | Sourced PSA-10 gem rate |
|---|---|---:|---:|---:|
| Umbreon ex #161 | Prismatic Evolutions | 17,990 | 5,487 | ≈ 30.5 % |
| Charizard ex #199 | Scarlet & Violet 151 | 97,426 | 27,631 | ≈ 28.4 % |
| Pikachu ex #238 | Surging Sparks | 27,298 | 9,263 | ≈ 33.9 % |
| Sylveon ex #156 | Prismatic Evolutions | 11,401 | 3,320 | ≈ 29.1 % |

A tight 28–34 % band, each carrying a source URL + capture date. This makes G's "sourced gem rate"
branch **real**, not hypothetical — subject to the honesty caveats below and in G (a population
base-rate is a *proxy* for a specific raw card's odds, never a guarantee → still capped PAPER_BUY;
small pops are noisy → sample-size caps). It stays a **record-path** capture (operator-run, stamped,
mapped-assets-only), never a read-path fetch — so it honors G's own "no live pop scraping on read
paths / no broad pop import" boundaries.

**Coverage is broad but not universal** — do not overclaim. The PriceCharting pop feature (Feb 2026)
added pop to "roughly 4× the number of cards," i.e. *more* cards, not *all*. The F.1 set is 4/4, but
G must treat pop as **present-or-absent per asset**: sourced pop is the primary gem-rate path **where
the blob is present and above the sample floor**, and operator-assumption is the honest fallback where
it is absent, sparse, or a grader has no series. Characterizing coverage beyond the F.1 set is a G-spec
task (§15).

**3.4 Reconciliation the doc carries (so pop is stated once, consistently).** G's gem-rate source
options, in honesty order:
1. **Sourced PriceCharting pop → gem rate** — verified 0-credit, on-page, dated (§3.3). **G's
   primary path**, labeled `sourced`, capped PAPER_BUY, gated by sample-size/confidence caps.
2. **Operator-assumption gem rate** — explicit `operator_assumption` label, capped PAPER_BUY. The
   **fallback** for assets PriceCharting has no pop coverage for (or pop below the sample floor).
3. **PSA cert API** — useful for cert *verification*, **not** pop; do not plan a pop feed on it.
4. **Third-party keyed pop scrapers** — rejected (unofficial/unstable).

**Naming what "sourced" verifies.** A sourced PriceCharting pop rate is a **transcription check +
coverage gap-fill against the single PSA/CGC census** — PriceCharting does not run its own grading
population survey; it transcribes PSA's and CGC's published counts onto its card pages. Treat it as
confirming PriceCharting copied the census correctly (and filling coverage gaps where reaching PSA's
or CGC's own pages directly is harder), **not** as independent corroboration of the population figure:
there is exactly **one census** underneath, and PSA, CGC, GemRate, and PriceCharting all resell the
same numbers. "Sourced" upgrades the rate from an operator guess to a dated, attributable transcription
of the real census — it does not add a second, independent measurement of gem rarity.

The [G-handoff notes](../../poke/phase-g-handoff-notes-2026-07-06.md) remain correct on the PSA-access
research and the field list G consumes; only their "operator-assumption is the safe default because
pop is unreachable" conclusion is updated by §3.3 — a sourced pop path is now reachable and preferred,
with operator-assumption as the honest fallback.

## 4. The phase ladder + the guard

| Phase | One-line purpose | Unlocks |
|---|---|---|
| **G** | Population/GemRate + grading-EV credibility | Raw→graded EV produces a *number* (sourced or assumed), or blocks with named inputs |
| **H** | Verified-entry activation + paper decision loop | WATCH → PAPER_BUY only on real buy evidence; outcome replay |
| **I** | Sealed refresh accounting + source instrumentation cleanup | Every paid path reports bounded spend or refuses first |
| **J** | Verified mapping assistant (not fuzzy) | Faster catalog mapping, exactness preserved |
| **K** | Title / listing normalization + parse-title substitute | Free-text listings become *review candidates*, never trusted comps |
| **L** | Catalog breadth + history depth | More coverage *after* the truth rules are stable |
| **M** | Operator dashboard / report surface | See what to fix/inspect next; changes no decision logic |

**Phase-ladder guard (binding on the G–M build).** The phases are **mutually exclusive** and built
in order. A phase may only build what its own **Build** list names; anything in a *later* phase's
Build list is that phase's job even if convenient now. Each phase's **Do NOT build** list names the
specific temptations that belong to its neighbours (e.g. G must not build verified-entry intake —
that's H; H must not build a mapping assistant — that's J). The **Permanent Rejections** (§12) are
off the table for *every* phase. Two tiers of "do not build" run through this doc:

- **Per-phase deferrals** (transient — *not now, its phase is later*): listed under each phase.
- **Permanent Rejections** (identity-level — *never, unless the product identity changes*): §12.

A per-phase list may also cross-reference a Permanent Rejection inline (tagged **Permanent
Rejection**, §12) as a reminder in context — that reference does not create a third tier; the item
is still filed at §12. Any phase whose Do-NOT-build list carries such a reminder is headed
"(deferrals / rejections)" so the mix is visible at a glance, never silently blurred into "(deferrals)."

---

## G — Population / GemRate + Grading-EV Credibility Layer

**Purpose.** Make raw→graded EV *usable* without inventing gem rates: source a gem rate honestly (or
label it an operator assumption), and expose the break-even gem rate so a grading decision is
explainable. G is a **sourcing + break-even layer, not a new money model** — the raw→graded EV math
(`grading_ev.py`) already exists and is correct; G supplies the one input it blocks on.

**Depends on:** F.1 data spine (asset schema, exact PriceCharting slugs, independent adapters,
ledger identity). The `pricecharting_card_prices_from_html` parser and the `record-asset-comp`
provenance writer are reused; G adds a pop parser beside them.

**Build.**
- **`gem_rate` evidence ledger** — a first-class, append-only, provenance-stamped record (not just
  the `gem_rate` / `gem_rate_source` slots on `assets.yaml`). Each entry carries: `asset_key`,
  grader, the per-grade counts, the derived gem rate, `label` (`sourced` | `operator_assumption`),
  `source_url`, `capture_date`, and `sample_size`. Written on an explicit operator command, never on
  a read path (mirrors the F.1 `record-asset-comp --refresh-independent` pattern; reads serve the
  recorded value).
- **`pop_data` parser** (new, beside `independent_sources.pricecharting_card_prices_from_html`):
  extract `VGPC.pop_data` from the already-fetched detail-page HTML → `{grader: [grade-ladder
  counts]}`. **Pin the index→grade map and the gem-rate definition explicitly** (10 elements; PSA 10
  = last; decide and document gem = `PSA10 / Σ(all PSA)` vs `PSA10 / (PSA9+PSA10)` — the G spec fixes
  one and records why). A page with no `pop_data`, a malformed blob, or a grader absent from the blob
  → honest **no pop** (block), never a guessed rate.
- **`gem-rate record / list / show` CLI** (subcommands on `edge_cli.py`): `record` captures pop for a
  mapped asset (0 credits, gated like the independent path); `list` / `show` read the gem-rate ledger.
  A batch form parallels `record-asset-comps`.
- **`grading-ev` CLI / read endpoint** — surface `grading_ev.grading_ev(...)` with a **break-even gem
  rate** (the gem rate at which fee-adjusted EV = 0) and the actual sourced/assumed rate beside it, so
  the reader sees margin-to-break-even. Read-only, 0 credits.
- **Sourced vs operator-assumption labels** — every gem rate and every grading-EV output states which
  it is; an `operator_assumption` (or a pop below the sample floor) caps the packet at **PAPER_BUY**.
- **Sensitivity table** — grading-EV across gem rates **20 % / 30 % / 40 % / 50 % / custom**, so a
  decision is read against a band, not a point estimate.
- **Sample-size / confidence caps** — a hard minimum total pop below which a sourced rate is treated
  as *insufficient* (→ falls back to operator-assumption or blocks); low pop lowers the confidence
  label. The G spec fixes the floor and documents it.
- **Raw↔graded sibling pairing by exact identity** — pair the raw comp with the graded-target comp
  for the *same* card, matched on `tcgplayer_id` **+** target `grade_key` (as `grading_ev` already
  does) or on `(name, set, card_number)` identity. **First concrete step:** map exact `tcgplayer_id`s
  for the F.1 siblings (Charizard 199, Pikachu 238) so pairing is exact, not name-based.
- **Result docs** for any sourced gem-rate capture (the ledger is gitignored, like `price_history.jsonl`
  — a committed result doc is the durable proof, mirroring the F.1 result-doc pattern).

**Do NOT build (deferrals).**
- Live population scraping on **read** paths (capture is record-path, operator-run only).
- Auto-promotion to LIVE off grading EV (a gem rate — sourced or assumed — is a population proxy for a
  specific card, never verified-data confidence → **capped PAPER_BUY, always**).
- Any **invented** gem rate (missing/insufficient pop → block or operator-assumption, never a guess).
- Broad population import / a pop crawl (mapped assets, on command, only).
- Verified-entry intake or a paper-buy wire (**that is H** — G produces a number and a break-even, not
  a buy).

**Guardrails touched.** STOP-class (no fabricated rate; source URL + capture date on every pop
record). Money-class N/A (0 PPT credits by construction — pop is scraped free, PPT client never
built on the pop path). The PAPER_BUY ceiling on grading EV is preserved exactly.

**Acceptance.** Grading EV produces a **PAPER-only** number with full provenance (which pop source,
what gem rate, what break-even, what sensitivity band) **or** blocks with **named** missing inputs
(no raw comp / no graded comp / no pop and no operator assumption / pop below sample floor). A sourced
pop capture writes a provenance-stamped gem-rate ledger row + result doc; no asset moves off WATCH.

**Code anchors.** `grading_ev.py` (EV + new break-even), `independent_sources.py` (new `pop_data`
parser beside the price parser), `edge_cli.py` (`gem-rate` subcommands + `grading-ev`), `edge.py`
(grading-EV packet still capped PAPER_BUY), `catalog.py` (`gem_rate` / `gem_rate_source` slots,
`tcgplayer_id` mapping), `web.py` (read-only grading-EV endpoint).

---

## H — Verified Entry Activation + Paper Decision Loop

**Purpose.** Move a subject from WATCH to **paper-buy only when there is real buy evidence** — a
verified listing, not a comp. This activates the E verified-entry route for day-to-day use and closes
the paper loop with outcome replay.

**Depends on:** E's verified-entry route (`edge.py` — asset-keyed, `entry_evidence_ok`-gated packets)
and Phase C's append-only paper-trade ledger (`money-hypothesis-lab.md`). H makes the route usable and
records/reports decisions; it does **not** re-architect E.

**Build.**
- **Stronger verified asset-candidate intake** — a safe, validated path to register a real listing as
  a verified entry (extends E's `entry_evidence_ok` gate; no fabricated candidates).
- **Entry-evidence schema** — `price`, `stock/quantity`, listing `URL`, `timestamp`, `seller/source`,
  optional `screenshot/link`. Every field provenance-stamped; missing required fields → the entry is
  not verified (stays WATCH).
- **CLI to add verified entries safely** — operator-run, validated, refuses malformed/ask-only/absent
  evidence (reuses the STOP-class refusals the E writer already enforces).
- **Paper-decision recording from edge packets** — record a PAPER_BUY decision *from* an `EdgePacket`;
  `edge_packet_id` already shares the `opportunity_id` recipe, so a paper decision unifies with the
  Phase C ledger with no new id scheme.
- **Outcome replay / report** — held / sold / expired / price-down, per the paper-trade ledger's
  outcome model, surfaced as a report.
- **Guards proving no comp-only promotion** — a test belt asserting a subject with a comp but **no**
  verified entry stays WATCH / DATA_NEEDED and never reaches PAPER_BUY (defends the E invariant that
  a D-era WATCH-with-comp row is never promoted off a comp alone).

**Do NOT build (deferrals / rejections).**
- Auto-buy, carting, checkout, or login automation (**Permanent Rejection**, §12).
- Fabricated / seeded candidates of any kind.
- Live promotion without a verified entry (a verified entry is the *only* buy wire; unchanged).
- A gem-rate/pop engine (**that is G**), a mapping assistant (**that is J**), or listing parsing
  (**that is K**) — H consumes an operator-supplied listing, it does not *find or parse* one.

**Guardrails touched.** STOP-class (an ask is context, never a comp; no fabricated entry). Doctrine
(human-in-the-loop for every buy; no auto-checkout). The `LIVE_PACKET_ELIGIBLE` floor stays strictly
stricter than PAPER_BUY and reachable only through the full verified spine.

**Acceptance.** A **real operator-supplied listing** produces a PAPER_BUY edge packet with attributed
entry evidence; **no listing → WATCH** (or DATA_NEEDED), never a buy. Outcome replay reports the paper
decision's held/sold/expired/price-down state. The no-comp-only-promotion guard is green.

**Code anchors.** `edge.py` (`decide_edge`, verified-entry fold, `entry_evidence_ok`), the Phase-C
paper-trade ledger + `/paper-decisions` (`money-hypothesis-lab.md`), `edge_cli.py` (verified-entry +
paper-decision subcommands), `opportunities.py` (untouched — its "assets never live in D" guarantee
is a guard target, not an edit target).

---

## I — Sealed Refresh Accounting + Source Instrumentation Cleanup

**Purpose.** Close the one remaining accounting **partial** in the gap matrix (row 3): the legacy
**sealed** `refresh=true` path can make a billable market lookup but does not yet emit
`apiCallsConsumed` (honest silence, documented — not a false `0`). I makes *every* paid path report
bounded spend or refuse before spending.

**Depends on:** the D.5 accounting model (the *asset* comp path already reports
`metadata.apiCallsConsumed.total` with an `estimated` upper bound). I extends that model to the sealed
product path; no new provider behavior.

**Build.**
- **Credit accounting on legacy sealed `refresh=true`** — the `CompEngine.estimate` market fallback
  (when `market.preferred` + a key are configured) emits `apiCallsConsumed`, matching the asset path's
  deterministic upper-bound model (never under-reporting a billable request).
- **Explicit `apiCallsConsumed` on all refresh paths** — sealed and asset, read and refresh; read /
  `refresh=false` / no-client / unmapped all report `0`, `source: "local"`.
- **Refusal / estimate output before money-class calls** — surface estimated credit spend and require
  operator go-ahead before a billable sealed lookup (the same posture the divergence audit's external
  mode already takes).
- **Tests proving no billed call reports `0`** — a counting/failing-client belt on the sealed path,
  the twin of the one already guarding `/opportunities` and every edge route.
- **Docs update for every paid/free path** — `private-price-api.md` D.5 "known gap" note retired;
  each path's credit posture stated.

**Do NOT build (deferrals).**
- New sealed strategy, ranking, or comp logic (accounting only).
- New paid provider behavior or a new billable surface.
- Anything touching the asset/edge accounting (already correct — I is the sealed path only).

**Guardrails touched.** Money-class (PPT bills on requested `limit`, not results → `limit=1` mandatory
on by-id lookups, never removed; resolve sealed by exact `tcgPlayerId` only; free tier 100 cr/day;
surface spend + get go-ahead before any live PPT run). STOP-class unaffected.

**Acceptance.** **Every** possible paid path reports a bounded credit spend or refuses before the
call; **no** billed path reports `apiCallsConsumed.total = 0`. The sealed-refresh test belt is green;
the D.5 "honest silence" gap is closed in code and docs.

**Code anchors.** `scanner/comps/engine.py` (`CompEngine.estimate` market fallback), `market.py` (PPT
v2 client, `limit=1`), `poke_api/model.py` + `router.py` (sealed `products/{key}/comp` shaping +
`apiCallsConsumed`), `config.yaml` (`market.preferred`, key), `private-price-api.md` (D.5 note).

---

## J — Verified Mapping Assistant (Not Fuzzy Mapping)

**Purpose.** Reduce the manual catalog-mapping effort **while preserving exactness** — propose
candidate ids/slugs with evidence for operator review; **never** auto-write catalog truth on a fuzzy
"best match."

**Depends on:** the F.1 exact-slug discipline and the redirect-confirmed slug-resolution method used
to verify the F.1 slugs (search → canonical `/game/{slug}` redirect, then path-only re-fetch). J
turns that manual method into an assistant that *proposes*, gated by the same exactness checks.

**Build.**
- **A helper that proposes** `pricecharting_slug`, `tcgplayer_id`, and optionally image / source
  links for an unmapped asset — a *proposal*, not a write.
- **Redirect-confirmed PriceCharting slug resolver** — only a slug whose canonical `/game/{slug}`
  detail page resolves (200, redirect-confirmed) is proposable; a search that does not redirect to a
  canonical page yields **no proposal** (the F.1 rule: no guessed slugs).
- **Operator review file** — `proposed / accepted / rejected` states; nothing enters `assets.yaml`
  until the operator accepts and the exact checks pass.
- **Evidence per proposal** — card number, set, name, and the source URL; a proposal whose page card
  number disagrees with the asset (the F.1 `pricecharting_page_number_from_html` wrong-slug guard) is
  auto-flagged, never proposed as accepted.
- **No automatic catalog write** unless the exact checks (redirect-confirmed slug, matching card
  number/identity) all pass **and** the operator accepts.

**Do NOT build (deferrals / rejections).**
- Fuzzy auto-write of catalog truth (**Permanent Rejection**, §12).
- "Best match" acceptance, or any acceptance without exact confirmation.
- Bulk uncontrolled import (breadth is **L**, and even L records comps independently per asset).
- Title/free-text parsing (**that is K** — J maps a *known* asset to ids; it does not parse listings).

**Guardrails touched.** STOP-class exact-identity discipline (resolve by exact `tcgPlayerId` /
canonical slug only; no fuzzy; a miss is honest, not a guess). 0 credits (slug resolution is a
plain-page fetch; no PPT client).

**Acceptance.** Mapping work is **faster** — the assistant proposes evidence-backed ids/slugs — but
**catalog truth stays manually- or evidence-confirmed**: no `assets.yaml` write happens without a
redirect-confirmed slug + matching identity + operator acceptance. A non-exact candidate is surfaced
for review, never written.

**Code anchors.** `independent_sources.py` (slug fetch, `pricecharting_page_number_from_html`),
`catalog.py` (asset schema, the write target), a new proposal/review artifact under `data/poke/`,
`edge_cli.py` (a `map-assist` subcommand).

---

## K — Title / Listing Normalization + Parse-Title Substitute

**Purpose.** Understand free-text marketplace listings **without trusting them as comps** — a local
parser that turns a listing title into candidate identity fields with a confidence band, feeding the
J review path, never the comp ledger.

**Depends on:** J's review model (an ambiguous parse becomes a "needs mapping" review item) and the
catalog identity fields (name / set / card number / grade). K is the last of the "truth-rules" phases
before breadth (**L**).

**Build.**
- **Local title parser** — free-text title → candidate identity fields (name, set, number, grade,
  raw/graded), fully offline (no external call, no billed API).
- **Confidence bands** — `exact` / `likely` / `ambiguous` / `reject`; only a parse that resolves to a
  known mapped asset is `exact`.
- **Test corpus** — a fixture set of eBay/TCGplayer-like titles exercising each band.
- **"Needs mapping" output** — ambiguous parses become review candidates (into J's review file), never
  auto-mapped, never comped.
- **Optional PPT `parse-title` audit** — *only* if the operator approves billed calls; an off-hot-path
  comparison of our local parse against PPT's `parse-title`, the same audit-only posture as divergence
  (never a read path, spend surfaced + `--yes` gated).

**Do NOT build (deferrals).**
- Parse-title (ours or PPT's) as a **source of truth** for a comp or an identity write.
- Auto-catalog writes from a parse (a parse feeds J's *review*, not a write).
- Auto-buy decisions from parsed titles (a parsed title is a candidate, not evidence).

**Guardrails touched.** STOP-class (a parsed/free-text listing is a *candidate for review*, never a
trusted asset or comp; an ask is context, never a comp). Money-class on the optional PPT
`parse-title` audit only (spend surfaced, operator `--yes`, off-hot-path).

**Acceptance.** Free-text listings become **candidates for review**, banded by confidence — never
trusted assets, never comps, never buys. An ambiguous title lands in the "needs mapping" review path;
an exact parse resolves to an already-mapped asset. The optional PPT audit runs only under operator
approval and writes nothing to the ledger.

**Code anchors.** a new `poke_api/title_parse.py` (pure, offline, tested), the K test corpus under
`tests/`, J's review file (consumer), `edge_cli.py` (a `parse-title` / `normalize` subcommand),
`divergence.py` (posture pattern for the optional PPT audit).

---

## L — Catalog Breadth + History Depth

**Purpose.** Expand coverage **after** the truth rules (G–K) are stable — grow the catalog in curated
batches with independent comps and scheduled history, while preserving exact mapping and provenance.

**Depends on:** J (verified mapping — every new asset is exactly mapped) and F.1's per-asset
independent-record path (breadth reuses `record-asset-comps`, never a bulk un-vetted import). Breadth
is deliberately **second-to-last**: coverage multiplies whatever discipline precedes it.

**Build.**
- **Curated expansion batches** by set / card class — operator-chosen, each asset exact-mapped (via J).
- **Batch independent comp recording** — reuse `record-asset-comps --refresh-independent` (0 PPT
  credits, per-asset honest degrade); no bulk provider pull.
- **Historical snapshot schedule** for mapped assets — recurring independent-comp captures so
  history/momentum deepen (today "history depth = ledger depth"; L schedules the growth).
- **Exportable coverage report** — `mapped / comped / cross-source / missing` per asset (an honest
  status export, not a PPT-style bulk CSV of prices).
- **Staleness dashboards / reports** — surface stale comps against `poke.staleness_days`.

**Do NOT build (deferrals).**
- A full public card-DB clone (curated batches only; not "every set").
- Approximate / estimated coverage metrics (a coverage report states exact counts, never an estimate).
- Unreviewed mass import (every asset goes through J's exact checks; every comp is independent-recorded).

**Guardrails touched.** STOP-class (exact mapping + provenance on every added asset and comp; no
fabricated coverage number). Money-class (independent recording is 0 PPT credits; any scheduled job
that could touch a billed path inherits I's accounting + refusal).

**Acceptance.** Coverage **grows** — more mapped, comped, cross-source-validated assets, with
scheduled history — while **exact mapping and provenance are preserved**: no approximate coverage
metric, no unreviewed import, every new comp independently sourced and stamped.

**Code anchors.** `edge_cli.py` (`record-asset-comps` batch, a new coverage-report subcommand),
`catalog.py` + `assets.yaml` (the growing catalog), `history.py` (momentum/staleness), a scheduler
hook (cron-style, local), `divergence.py` (`--matrix` for the cross-source column of the report).

---

## M — Operator Dashboard / Report Surface

**Purpose.** Make the useful parts easier to **operate locally** — a read-only surface that shows what
to fix or inspect next, **changing no decision logic**.

**Depends on:** the read APIs already shipped (`/edge-summary`, `/edge-packets`, asset/product
comp/history/momentum) plus G's grading-EV read and L's coverage/staleness reports. M is a *surface*
over existing reads; it computes no new truth.

**Build.**
- **Edge summary card** — the compact roll-up (`/api/poke/edge-summary` already exists) as a local view.
- **WATCH / PAPER_BUY / DATA_NEEDED breakdown** — counts by decision, from the edge summary.
- **Top blockers** — the most common `blockers` across packets (surfaced by the edge summary today).
- **Cross-source status** — the F.1 gap-matrix / `cross_source_validated` view per asset.
- **Gem-rate / EV panel** — G's sourced-vs-assumed gem rate, break-even, and sensitivity band (after G).
- **Recording / audit runbook links** — deep-links to the runbook steps for the actions the dashboard
  surfaces (record a comp, capture pop, run a local audit).

**Do NOT build (deferrals / rejections).**
- Portfolio / wishlist UX (**Permanent Rejection**, §12).
- A public hosted API (local-only by design; **Permanent Rejection**, §12).
- Customer-facing polish.
- **Anything that changes source-of-truth or decision behavior** — M is read-only over existing reads;
  if a "dashboard feature" would compute a new number or alter a decision, it belongs in an earlier
  phase's logic, not M.

**Guardrails touched.** Read-only, 0 credits (M calls only the existing read endpoints, which are
already proven never to hit a billed provider). STOP-class labels (sourced vs EST vs assumption) are
surfaced, never smoothed.

**Acceptance.** The dashboard shows **what to fix or inspect next** — edge breakdown, top blockers,
cross-source status, gem-rate/EV panel — **without changing decision logic**. Every number on it
traces to an existing read endpoint with its existing provenance/label.

**Code anchors.** `web.py` + `poke_api/model.py` (existing read endpoints — the data source),
`scanner/web.py` SPA / an "Edge" card (the E design already names this SPA card as a scoped follow-on),
`edge-layer-runbook.md` (the runbook the links point at). No change to `edge.py` / `grading_ev.py` /
`opportunities.py` decision logic.

---

## 12. Permanent Rejections (identity-level — never, unless the product identity changes)

These are **off the table for every phase G–M** (and beyond). They are not "later" — they are "not
this program." Several are *advantages over PPT*, not gaps (the gap matrix rows 13–17). Each carries
a named cost below — a "no" that costs nothing isn't a real decision.

- **Auto-buy / cart / checkout / login automation.** The human transacts; the tool advises. No
  exceptions across H (verified entry is *operator-supplied evidence*, not automated purchasing).
  **Cost:** every buy stays manual — no speed edge on fast-moving listings, ever.
- **Fuzzy mapping that writes catalog truth.** Exact `tcgPlayerId` / redirect-confirmed slug only; a
  "best match" is never written (J proposes for review; it never auto-writes on similarity).
  **Cost:** exact-only mapping → slower catalog growth, every new asset waits on an exact-match
  confirmation.
- **Portfolio / wishlist app.** Not our identity (M is a read-only operator surface, not a portfolio
  app). **Cost:** no consumer-facing product surface. This rejects the *app*, not the underlying money
  question: the **inventory / cost-basis / P&L ledger** (real acquisitions, real sales, realized P&L)
  is a legitimate, separate build — specified as T8 in the
  [real-transacting spec](2026-07-06-poke-real-transacting-build-design.md) — and is **not** covered
  by this rejection.
- **Public API polish / hosting.** Local-only, read-first, never hosted. **Cost:** no-public-API →
  single-operator; no external consumers, no third-party integration surface.
- **TCGplayer live enablement — or TCGCSV, same lineage — as "independent" validation.** TCGplayer's
  market price == PPT to the cent (PPT resells it), and **TCGCSV is TCGplayer's own bulk export** — the
  same underlying number by a different pipe, not a second source. `_INDEPENDENT_OF_PPT =
  {pricecharting}` is a **conservative default under asymmetric error cost**, not a proven structural
  fact. Counting TCGplayer/TCGCSV as independent when it in fact mirrors PPT would be *false
  corroboration* — truth-poisoning, the dangerous error, since a cross-source check would wrongly
  report agreement. Treating it as non-independent when it might differ merely *forgoes a check* — a
  safe, lost-opportunity error. This is also the one independence claim Phase F.1 could not re-probe
  live (that needs Playwright, which is not installed; F.1 re-confirmed the Phase F conclusion rather
  than re-verifying it) — so the conservative default is **protective, not proven**. Neither a
  tcgplayer comp nor a TCGCSV-sourced price is **ever** counted as independent cross-source validation.
  **Cost:** one fewer cross-source check on the F.1 asset set — a forgone check, not a coverage gap,
  since PriceCharting independence already covers it.
- **PPT-clone behavior.** No re-hosting PPT's product; the `/sealed-products` + `/cards` facades stay
  local compat shims, never external provenance. **Cost:** no drop-in PPT replacement for anyone who
  wants PPT's UI/export surface.
- **Ask-only comps.** An active ask is context, never sold-comp truth (`allow_ask_only=False`).
  **Cost:** thin/illiquid cards with no recent sale stay WATCH/DATA_NEEDED even when an ask is the
  only signal available.
- **Fake / seeded verified entries.** No fabricated candidates; no PAPER_BUY/LIVE off a comp alone.
  **Cost:** no way to bootstrap or demo the buy path without a genuine listing — every walkthrough
  needs a real one.
- **Read-path paid calls.** No read endpoint calls a billed provider; every read reports
  `apiCallsConsumed.total = 0`. Billable surfaces are explicit, operator-gated, and accounted (I).
  **Cost:** reads can go stale between operator-triggered refreshes — no on-demand live re-price on
  every page view.

## 13. Build order & sequencing rationale

**G → H → I → J → K → L → M** (the operator's order; the rationale each edge encodes):

1. **G first** — the single capability the gap matrix says unblocks new *decisions*. Grading-EV is
   already built and blocking; G is the smallest change that turns a block into a defensible number.
2. **H next** — with a credible EV/decision layer, activate the *buy* side (WATCH → PAPER_BUY on real
   evidence) and close the paper loop. G gives H better decisions to record.
3. **I** — a self-contained money-honesty cleanup (the last accounting partial). Order-independent of
   J–M; placed here so the paid-path accounting is closed before breadth (**L**) can schedule jobs
   that touch billed paths.
4. **J** — reduce mapping effort *before* breadth, so L's expansion is fast **and** exact.
5. **K** — title normalization feeds J's review path; both must precede breadth so free-text intake is
   a *review* funnel, never an un-vetted comp source.
6. **L** — breadth *after* G–K, so coverage multiplies discipline, not un-vetted rows (the explicit
   rejection of the breadth-first option, §2).
7. **M** — a read-only surface last, over everything the prior phases produce; it computes no new truth
   so it has nothing to add until the truths exist.

**Mid-build discipline.** Because the operator will execute G–M in one build, the phase-ladder guard
(§4) is the load-bearing control: each phase is a spec → plan → build sub-cycle, its Build list is its
ceiling, its Do-NOT-build list names the neighbour temptations, and the full test suite stays green at
every phase boundary before the next begins.

## 14. Cross-cutting invariants (all phases)

- **Price accuracy is STOP-class.** No source → no number. Every price/rate carries its source URL +
  capture date. Estimates are badged EST / `operator_assumption` and never presented as sold comps.
- **PPT credits are money-class.** Bills on requested `limit`, not results → `limit=1` mandatory on
  by-id lookups, never removed. Resolve sealed by exact `tcgPlayerId` only. Free tier 100 cr/day.
  Surface estimated spend + get operator go-ahead before any live PPT run. 0 PPT credits on every G/J/K
  (independent) path by construction.
- **Exact identity only.** No fuzzy match, no guessed slug/id/grade; a miss is honest data, not a guess.
- **Two ledgers stay distinct.** Observation (market data seen) vs any future inventory ledger — never
  conflated. The gem-rate evidence ledger (G) is a third, provenance-stamped, append-only record.
- **PAPER_BUY vs LIVE ceiling.** `LIVE_PACKET_ELIGIBLE` is strictly stricter than PAPER_BUY and
  reachable only through the verified evidence spine. A gem-rate/EV number (sourced or assumed) caps at
  PAPER_BUY. A comp alone never promotes off WATCH.
- **Independent-of-PPT is a conservative default, not a structural fact.** `_INDEPENDENT_OF_PPT =
  {pricecharting}` — TCGplayer, **including its TCGCSV bulk export (same lineage, not a second
  source)**, is excluded under **asymmetric error cost** (§12): wrongly counting it independent risks
  false corroboration (the dangerous error); wrongly excluding it only forgoes a check (the safe
  error). A material *unexplained* divergence fails the audit; we investigate divergence, we do not
  tune to PPT.
- **Local `main`, never pushed** without explicit operator instruction. No dependency added without
  asking (G/H/I/J/K/L/M add **no** new runtime dependency — no Playwright, no paid API client).
- **Every phase is TDD** with its own tests; the full network-mocked suite
  (`.venv/Scripts/python.exe -m pytest -q`) stays green at each phase boundary.

## 15. Open questions for review (for the advisor/boss pass)

1. **Gem-rate definition (G).** `PSA10 / Σ(all PSA)` (≈30.5 % on Umbreon) vs `PSA10 / (PSA9+PSA10)`
   (≈37.4 %) vs a CGC-inclusive combined rate — which is the canonical break-even input? (Recommend
   `PSA10 / Σ(all PSA)` for the labeled grader, CGC handled as its own series; the G spec fixes it.)
2. **`pop_data` index→grade map.** Confirm the 10-element array is grades 1→10 (no half/Authentic
   offset) before trusting the last element as PSA 10 — a one-page verification task for the G spec.
3. **Sample-size floor (G).** What minimum total pop makes a sourced rate trustworthy vs.
   operator-assumption fallback? (A number to fix in the G spec; e.g. a few-hundred-graded floor.)
4. **Pop coverage beyond the F.1 set (G).** The F.1 four are 4/4, but coverage is "4× more cards," not
   all (§3.3). The G spec should verify `pop_data` presence + shape across the catalog (and any new
   L assets), and characterize the present/absent split so the sourced-vs-assumption fallback is
   driven by real coverage, not the assumption that pop is always there.
5. **Base-rate-as-proxy is stated, not implied (G).** A population gem rate is the rate over *all*
   graded submissions of that card, **not** a hand-picked NM copy in hand; the bias direction is
   unknown (the population includes gambled-on damaged cards, but condition-sensitive cards can also
   grade worse). The G spec should state this assumption in one explicit sentence — it is exactly why
   the PAPER_BUY cap on grading EV is correct and non-negotiable.
6. **H entry-evidence retention.** Are screenshots/links stored locally, or referenced by URL only?
   (Provenance vs. footprint; recommend URL + optional local link, no binary storage.)
7. **I refusal UX.** Should the sealed-refresh money-class refusal mirror the divergence audit's
   `--yes` gate exactly, or is a config-level daily cap sufficient? (Recommend mirror `--yes`.)
8. **M surface host.** Reuse the existing `scanner/web.py` SPA "Edge" card (E's named follow-on), or a
   standalone read-only page? (Recommend the existing SPA card; no new server.)

---

**Bottom line.** The spine is built and generalized; G–M turns it into controlled decision usefulness
along a fixed, mutually-exclusive ladder. The one live-verified change to the prior plan is the
**PriceCharting pop blob (§3.3)**, which upgrades G's gem rate from "operator-assumption only" to
"**sourced, 0-credit, dated — capped PAPER_BUY** with sample-size discipline," fallback
operator-assumption. Every other phase preserves the operator's Build / Do-not-build / Acceptance
intent, enriched with dependencies, code anchors, and the guardrails each phase inherits.
