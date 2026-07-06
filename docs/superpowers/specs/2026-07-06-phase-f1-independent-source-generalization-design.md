# Phase F.1 — Independent Source Generalization + PPT Gap Matrix (Design)

**Date:** 2026-07-06
**Status:** Design — ready for the implementation plan.
**Repo:** `Pokemon-main` (package `scanner/`; price-API ladder `scanner/poke_api/`)
**Ladder position:** the follow-on rung to **Phase F** on the private price-API ladder
(A → B → C → D/D.5 → E → F → **F.1**). Not the discovery-slice roadmap. See
[`docs/poke/private-price-api.md`](../../poke/private-price-api.md).
**Follows:** [Phase F design](2026-07-05-phase-f-independent-sold-source-validation-design.md)
and its [result doc](../../poke/phase-f-independent-source-result-2026-07-06.md).

> **This is Phase F.1 — not Phase G, not a redesign.** F built the independent
> PriceCharting adapters and proved them on one card (Umbreon). F.1 **generalizes** that
> layer beyond one card/page shape, adds a **batch** independent-record path + a durable
> **PPT-vs-ours gap matrix**, and hardens the parser — while **preserving** the
> gem-rate/population-ready metadata for G **without building the G engine**.

---

## The system in one line

Prove the Phase-F independent-source layer is **not overfit to Umbreon**: map a small,
verified multi-card/multi-set validation set (exact PriceCharting slugs only), add a
**batch** 0-PPT-credit independent-record CLI, upgrade the local divergence audit into a
**multi-asset gap matrix** with honest new classifications, harden the parser against
multiple page shapes, and publish a durable **PPT-vs-ours capability gap matrix** — all
at **0 PPT credits**, PPT external mode still audit-only, assets still WATCH.

## Source research findings (this session, read-only, 0 PPT credits)

Method: plain `requests.get` with the adapter's browser UA (`independent_sources.UA`) —
the exact fetch path the adapters use — following PriceCharting's search→detail redirect
to discover the canonical slug, then re-fetching the **path-only** slug directly and
running the **real** adapter parser (`pricecharting_card_prices_from_html`) against the
live HTML. No Playwright, no billed API. (WebFetch returns HTTP 403 on PriceCharting;
plain browser-UA `requests` returns 200 — consistent with the Phase F probe.)

### 1. PriceCharting detail pages — exact slugs + cell layout (verified live)

| Card | Set | Canonical slug (verified) | Ungraded | PSA10 (`manual_only_price`) | Grade 9 (`graded_price`) | blocked? |
|---|---|---|---:|---:|---:|:--:|
| Umbreon ex #161 | Prismatic Evolutions | `pokemon-prismatic-evolutions/umbreon-ex-161` | $1,425.00 | $7,013.08 | $1,554.05 | no |
| Charizard ex #199 | Scarlet & Violet 151 | `pokemon-scarlet-&-violet-151/charizard-ex-199` | $399.99 | $1,575.00 | $408.53 | no |
| Pikachu ex #238 | Surging Sparks | `pokemon-surging-sparks/pikachu-ex-238` | $325.50 | $1,062.12 | $330.14 | no |
| Sylveon ex #156 | Prismatic Evolutions | `pokemon-prismatic-evolutions/sylveon-ex-156` | $439.50 | $1,615.00 | $455.00 | no |

**Key result (anti-overfit):** all four pages expose the **same six `#price_data`
cells** with the same ids (`used_price` / `complete_price` / `new_price` / `graded_price`
/ `box_only_price` / `manual_only_price`) — the Phase-F cell map generalizes cleanly
across three different sets. The `pokemon-scarlet-&-violet-151/...` slug contains a
literal `&` and still resolves directly (200). The path-only slug (query string
stripped) resolves without a search step.

**Sold-listing presence:** each detail page carries a completed/recent-sales section
(`id="completed"`, a `chart_data` price-history blob) but does **not** expose a clean
numeric sample-size in the initial HTML. F.1 therefore records only the **displayed
per-grade market summary** (the `#price_data` cells) and treats sample size as a **G
placeholder**, not a parsed field.

**Blocked/challenge behavior:** none observed on any of the four (HTTP 200, no
`Just a moment` / `cf-browser-verification`). A challenge or 403/429 still degrades to a
`blocked` quote (never evaded) per the Phase-F degrade matrix — unchanged.

### 2. PriceCharting API — documented as NOT appropriate for F.1

The PriceCharting **API** (`/api/product`) is **subscription-gated** (a paid plan issues
a 40-char token passed as `t`), **1 call/sec** (CSV once/10 min), and returns
current-values only. It would add a **paid dependency** for numbers already free on the
public detail page the adapters scrape. **F.1 does not use the API.** (Sources:
pricecharting.com/api-documentation.) Keeping the plain-page scrape is the money-honest,
0-credit choice.

### 3. TCGplayer — Phase F finding preserved (not independent of PPT)

Re-confirmed the Phase F conclusion (no new live probe — that needs Playwright, which is
**not** installed): TCGplayer's rendered **market price equals the PPT (`ppt_cards`)
number to the cent** ($1,528.09 for the tracked Umbreon printing), because PPT resells
the TCGplayer market number. TCGplayer is therefore **not an independent validator** for
market price. F.1 encodes this **structurally**: only `pricecharting` counts as
independent-of-PPT for cross-source validation (`_INDEPENDENT_OF_PPT = {"pricecharting"}`),
so a (hypothetical) tcgplayer comp agreeing with `ppt_cards` is **never** flagged
`cross_source_validated`. `TcgPlayerRenderedSource` stays the dormant `blocked` shell;
no Playwright dependency is added.

### 4. PSA population / gem-rate access — G research, not an F.1 blocker

PSA has **no public population-report API**. The PSA Public API (psacard.com/publicapi)
is **login-gated** (OAuth2 password grant, 100 calls/day free) and centered on **cert
verification** (cert number → what PSA graded), not pop counts. Pop data is browsable
HTML (psacard.com/Pop) or third-party scrapers only. **Conclusion:** population/gem-rate
sourcing is **login-gated + unstable → deferred to Phase G research**, documented in the
G handoff. F.1 **preserves** the gem-rate/pop metadata slots (`gem_rate`,
`gem_rate_source` already on the asset schema) but **builds no pop/gem-rate engine**.

## Chosen assets and why

Small but meaningful validation set (six new rows + the four existing Umbreon controls),
chosen to exercise every honest code path across **three sets** and **four cards**:

| asset_key (new) | class | identity | slug | proves |
|---|---|---|---|---|
| `charizard_ex_199_151_raw_nm` | raw NM | Charizard ex #199 (SV 151) | `pokemon-scarlet-&-violet-151/charizard-ex-199` | raw single, **different set**, `&`-slug |
| `charizard_ex_199_151_psa10` | graded | PSA 10 | same | **PSA-exact** `manual_only_price` on a 2nd card |
| `pikachu_ex_238_ss_raw_nm` | raw NM | Pikachu ex #238 (Surging Sparks) | `pokemon-surging-sparks/pikachu-ex-238` | raw single, **3rd set** |
| `pikachu_ex_238_ss_psa9` | graded | PSA 9 | same | **grader-agnostic Grade-9 proxy** on a 2nd card |
| `charizard_ex_199_151_cgc10` | graded | **CGC 10** | same | **unsupported grade → honest `no_match`** |
| `sylveon_ex_156_raw_lp` | raw **LP** | Sylveon ex #156 (Prismatic) | `pokemon-prismatic-evolutions/sylveon-ex-156` | **non-NM raw** condition caveat (not auto-recorded) |

Controls (unchanged, already mapped): `umbreon_ex_161_raw_nm`, `umbreon_ex_161_raw_lp`,
`umbreon_ex_161_psa10`, `umbreon_ex_161_psa9`. Umbreon keeps its recorded `ppt_cards`
references (raw $1,528.09, PSA10 $6,925.50) so the gap matrix has **live cross-source
teeth** on it; the new cards have **no** PPT reference (that would be a billed call) and
so honestly classify `no_external_reference`.

Why these and not others: only slugs whose canonical `/game/...` detail page was
**verified live this session** are mapped. Candidates whose search did **not** redirect
to a canonical detail page (e.g. `charizard ex 223`, `mimikyu ex 253`, `iono 237`,
`moonbreon vmax 215`) are **left out** — no guessed slugs (STOP-class).

## Exact PriceCharting slug policy

- **Exact `pricecharting_slug` only** — the canonical `/game/{slug}` path, stored on the
  asset. No fuzzy name search, no "nearest" match, never a guessed variant. A
  missing/unmatched slug is honest `skipped`/`no_match`, never a fabricated number.
  (Mirrors the money-class "resolve by exact `tcgPlayerId` only" rule.)
- Slugs may contain literal `&` (SV 151) — stored verbatim; the adapter builds
  `https://www.pricecharting.com/game/{slug}` and it resolves.
- **Wrong-slug detection (new in F.1, at the record boundary):** a parser helper
  `pricecharting_page_number_from_html` extracts the page's card number (`#NNN`). On the
  **recording path only** (never a read/serve path — asset reads are ledger-only), when
  an asset carries a `card_number` **and** the page number is confidently extracted
  **and** they differ, the adapter returns `no_match` ("page card #X ≠ asset
  card_number Y — wrong slug?"). This records **nothing** (the safe STOP-class outcome)
  and prints an honest reason — it never suppresses a number on a read path and never
  fabricates. The divergence audit's `mapping_error` (>100% delta) remains the runtime
  safety net for a wrong slug that happens to point at a similarly-numbered card.

## Grade mapping policy (unchanged from F; re-affirmed + generalized)

Exact-only, per the verified cell map:

| grade_key | cell | semantics |
|---|---|---|
| `psa10` | `manual_only_price` | **PSA-exact** (only `psa10` may use this cell) |
| `*9.5` | `box_only_price` | grader-agnostic Grade 9.5 |
| `*9` (`psa9`, `cgc9`, `bgs9`) | `graded_price` | **grader-agnostic** Grade 9 proxy |
| `*8` | `new_price` | grader-agnostic Grade 8 |
| `*7` | `complete_price` | grader-agnostic Grade 7 |
| `cgc10`, `bgs10`, `*6`, unparseable | — | **honest `no_match`** (no exact cell) |

- **Unsupported grades degrade honestly:** `cgc10`/`bgs10` have no generic Grade-10 cell
  (only PSA 10 has a graded column) → `no_match`, never a nearest-cell guess.
- **Confidence stays locked `low`** for every graded PriceCharting comp (PSA-exact
  included) — a single independent sold source is `low`. Cross-source validation is
  supplied by the audit agreeing, not by the confidence field (Phase F rule, unchanged).
- The PSA-exact vs grader-agnostic distinction rides in the quote **basis/detail note**
  (provenance), and the F.1 matrix uses the asset's `grade_key` to classify a
  grader-agnostic-vs-grader-specific gap as `grade_mapping_difference`.

## Raw condition caveat

PriceCharting "Ungraded" (`used_price`) is a **single loose price that does not
distinguish raw condition** (NM vs LP/MP/HP). F.1 makes the Phase-F hand-decision a
**programmatic guard** (a batch must enforce what F did by hand):

- **Only NM-proxy raw is auto-recordable off Ungraded.** The recording path treats
  `condition ∈ {NM, "" (blank), MINT, NM-MT}` as an NM-ish loose proxy that **may** be
  recorded off `used_price`.
- **Non-NM raw (LP/MP/HP/DMG/PLAYED) is never auto-recorded** off Ungraded — that would
  over-value the card. The batch/single independent-record path **skips** it (0 network)
  with an explicit caveat: *"PriceCharting Ungraded is not condition-exact for
  condition=LP; not auto-recorded — map a condition-specific source or use the audited
  from-value path."* The slug stays mapped (so it can resolve later); the honest deferral
  is explicit, not silent. `sylveon_ex_156_raw_lp` is the test-of-record for this.

## PPT comparison policy

- **PPT stays audit-only, 0 billed calls in F.1.** No new PPT/billable surface. The gap
  matrix compares our recorded **independent** (`pricecharting`) comp against an
  **already-recorded** `ppt_cards` observation in the (gitignored) ledger — 0 network, 0
  credits. New PPT references are **not** minted (that is a billed call requiring operator
  go-ahead).
- **We investigate divergence; we do not tune to PPT.** A **material unexplained
  divergence fails the audit** (blocking). Every material row states whether ours or
  theirs is more defensible. Do **not** blindly tune our comp to match PPT.
- **TCGplayer is not counted as independent** of PPT (`_INDEPENDENT_OF_PPT` = just
  `pricecharting`).

## Batch recording design

New CLI subcommand (sibling to the existing single `record-asset-comp`):

```
python -m scanner.poke_api.edge_cli record-asset-comps --refresh-independent --assets a,b,c --dry-run
python -m scanner.poke_api.edge_cli record-asset-comps --refresh-independent --assets a,b,c --yes
```

- **Gated by `poke.independent_sources: true`** (default off) — the same 0-credit "live
  network allowed here" switch as the single path.
- **`--refresh-independent` is required** (the only mode the batch supports). It runs the
  **independent** resolver (`resolve_independent_asset_row`), which **never constructs or
  accepts a PPT client** → **0 PPT credits by construction**, even in principle.
- **Write semantics:** `write = args.yes and not args.dry_run`.
  - `--dry-run` → live-fetch **preview**, **no writes** (shows what would be recorded, or
    the honest skip reason). `--dry-run` always wins (no write even if `--yes` also given).
  - `--yes` (no `--dry-run`) → **persist**.
  - neither → treated as preview (no write); prints a hint to pass `--yes` to persist.
- **Per-asset outcome (records nothing on any of):** unmapped asset_key; no slug
  (`skipped`); no matching cell (`no_match`); challenge/403 (`blocked`); wrong-slug number
  mismatch (`no_match`); non-NM raw condition (caveat skip, 0 network); an `ebay`/ask-only
  or `ppt_cards` slug (refused — the independent path has no `ppt_cards` fallback).
- **Each persisted row carries** (via the existing provenance-honest
  `record_asset_comp` writer, unchanged): `item_key` (byte-matches read-first),
  `source` (the real slug, e.g. `pricecharting`), `source_url`, `basis`, `comp`,
  `comp_confidence`, `capture_date`, and asset identity (`asset_key`, `asset_class`).
- **Output:** a per-asset table (+ `--json`) summarizing status/source/comp/confidence/
  reason and a roll-up (recorded / previewed / skipped counts). Because
  `price_history.jsonl` is gitignored, the live run's rows are captured in the F.1
  **result doc** (below).
- **Refactor:** the single `record-asset-comp --refresh-independent` and the batch share
  one per-asset helper (`_resolve_independent_for_asset` + `_persist_independent_result`);
  the single path's behavior/return codes are preserved.

## Local audit matrix design

Upgrade the local (dry) audit into a **multi-asset gap matrix** — a new
`divergence.audit_matrix(...)` plus a `--matrix` flag on `divergence-audit --local`
(additive; the existing `divergence-audit` behavior is untouched). Still **0 network / 0
credits** — it only reads the ledger.

**Row fields (required):** `asset_key`, `asset_class`, `condition_or_grade_key`, `ours`,
`ours_source`, `ours_capture_date`, `ppt_reference`, `ppt_capture_date`, `delta_pct`,
`classification`, `cross_source_validated`, `defensibility`, `notes`.

**Classification vocabulary (required set):** `agree`, `no_external_reference`,
`no_independent_reference`, `source_policy_difference`, `mapping_error`,
`grade_mapping_difference`, `raw_condition_difference`, `stale_local`, `stale_external`,
`confidence_method_difference`, `unexplained_material_divergence`.

Classification logic (enrichment on top of the existing `classify_divergence`):

1. **theirs (`ppt_cards`) missing →** `no_external_reference` (defensible: ours; the new
   cards land here — honest, no PPT ref).
2. **ours missing, or ours_source is `ppt_cards` (not independent) →**
   `no_independent_reference` (we have no independent number to cross-check).
3. **both present, ours_source independent:** run the base classifier; then refine a
   *material* gap:
   - raw asset + non-NM condition → `raw_condition_difference` (explained, non-blocking).
   - graded asset + grade maps to a **grader-agnostic** proxy cell (not `psa10`) →
     `grade_mapping_difference` (explained, non-blocking).
   - a huge gap (≥100%) stays `mapping_error`; an otherwise-unexplained material gap stays
     `unexplained_material_divergence` (**blocking — fails the audit**).
4. `cross_source_validated` is set **only** when `ours_source ∈ _INDEPENDENT_OF_PPT`
   (`pricecharting`) **and** the row is `agree`.

**Honesty note (labeled in the result doc):** with the live F.1 ledger,
`raw_condition_difference` and `grade_mapping_difference` are **demonstrated via
constructed observations in tests**, not observed on live data — raw LP is guarded from
recording, and the new cards lack PPT references. The matrix must be *able* to produce
them (vocabulary + logic + tests); it is honest that they did not fire live.

**A material unexplained divergence fails the audit.** F.1 does not tune to PPT.

## Result-doc strategy for gitignored ledger rows

`data/poke/price_history.jsonl` is **gitignored** (untracked) — the recorded rows never
enter git. So F.1 writes a **committed** result doc
`docs/poke/phase-f1-independent-source-result-2026-07-06.md` (mirroring the Phase F
result doc) capturing, for the live 0-credit batch run: each written row (asset_key,
comp, confidence, source, source_url, capture_date, basis, ledger item_key), the
resulting **gap-matrix** classifications, and a plain statement of the live ledger state
(which cards have a PPT reference and which honestly classify `no_external_reference`).
That doc is the durable, reviewable proof the ledger writes happened.

## Explicit G handoff notes (do NOT build G in F.1)

F.1 **preserves** the metadata G needs and documents the handoff in
`docs/poke/phase-g-handoff-notes-2026-07-06.md`; it builds **no** pop/gem-rate engine.
G should consume, per asset/comp: `asset_key`, `grade_key`, `grader`, `grade`,
`condition`, comp `source`, `source_url`, `capture_date`, the raw↔graded **sibling**
relationship (matched on `tcgplayer_id` + target `grade_key`, as `grading_ev` already
does), `sample_size` (a **placeholder** — PriceCharting does not expose a clean count;
PSA pop is login-gated/no-API), a **population/gem-rate source placeholder** (`gem_rate` +
`gem_rate_source` slots already exist and are never invented), and the break-even/gem-rate
inputs `grading_ev` already blocks on. See the handoff doc for the full field list and the
PSA-access research. **Out of scope for F.1:** any pop/gem-rate fetch, any break-even
engine, any move off WATCH.

## Guardrails (STOP-class + doctrine, restated)

- **0 PPT credits** on every F.1 path (independent adapters never call PPT; the matrix is
  ledger-only). PPT external mode stays audit-only; no new billable surface.
- **No fake verified entry candidates; no PAPER_BUY/LIVE promotion from a comp alone.**
  `opportunities.py` / `edge.py` / the verified-entry route are **untouched**; assets stay
  WATCH regardless of the numbers.
- **No fuzzy matching, no guessed grades/slugs.** Exact slug/id only. Unsupported grades
  and non-NM raw degrade honestly (no_match / caveat skip).
- **No Playwright install** (TCGplayer stays the dormant shell; not necessary — proven).
- **No broad catalog import, no portfolio/wishlist UI, no public API polish.**
- Every persisted price carries source URL + capture date + basis; no source → no number;
  an active ask is context, never a comp.
- **config.yaml ends at `poke.independent_sources: false`** (flipped true only for the
  live batch run, then reset).

## Out of scope (explicit)

Population/gem-rate engine; break-even engine; any move off WATCH; verified-entry/candidate
creation; broad card-DB/set ingestion or bulk import; parse-title matching; automated
slug/id mapping; title/listing normalization; CardMarket/JP; portfolio/wishlist UX; public
API polish; the PriceCharting subscription API; TCGplayer live render / Playwright; new
PPT/billed calls.

## Acceptance criteria

1. `assets.yaml` carries the six new mapped rows (exact verified slugs) spanning three
   sets; unsupported grade (`cgc10`) and non-NM raw (`sylveon…raw_lp`) present.
2. Parser hardened + tested against multiple shapes: Ungraded / PSA10 / Grade 9 parse;
   comma prices parse; blank/dash/missing price → `no_match`; unsupported grade →
   `no_match`; wrong-slug number mismatch detected → `no_match`; non-200 → `blocked`;
   challenge/interstitial → `blocked`; raw condition caveat preserved; a tcgplayer comp
   equal to PPT is **not** counted independent.
3. `record-asset-comps` batch: gated on `poke.independent_sources`; `--dry-run` writes
   nothing; live uses only independent sources; **never** constructs a PPT client; 0 PPT
   credits (asserted); no-source/no-match/blocked/ask-only/raw-caveat records nothing;
   each persisted row carries the full provenance set.
4. `divergence audit_matrix` (`--matrix`) produces the required fields + the full
   classification vocabulary; a material unexplained divergence **fails**; the new
   explained categories are demonstrated (labeled test-demonstrated).
5. Committed **gap matrix** doc (`docs/poke/ppt-vs-ours-gap-matrix-2026-07-06.md`) with
   the required capability rows + decisions; committed **result doc** for the gitignored
   ledger rows; committed **G handoff** doc.
6. Full suite green (`.venv/Scripts/python.exe -m pytest -q`); docs updated (Track F.1 in
   `private-price-api.md`, runbook batch command, `sources.md` new verified rows); **no
   Playwright dependency added**; **0 PPT credits**; `config.yaml` ends `independent_sources: false`.

## Build task outline (for the plan)

1. Assets: add the six rows to `assets.yaml`; assert they load (catalog test).
2. Parser hardening (TDD): `pricecharting_page_number_from_html` + multi-shape fixtures +
   tests (comma / dash / missing / unsupported-grade / wrong-number).
3. Adapter wrong-slug guard (record-boundary `no_match`) + tests.
4. Raw-condition recordability guard (helper) + tests.
5. Batch `record-asset-comps` CLI (shared per-asset helper) + `--dry-run`/`--yes` + tests.
6. `divergence.audit_matrix` + new categories + `--matrix` flag + `_INDEPENDENT_OF_PPT`
   tightening + tests (incl. tcgplayer-not-independent, constructed grade/condition rows).
7. Live 0-credit batch run (gate on → run → gate off); capture the result doc + gap matrix.
8. Docs: Track F.1, runbook, sources.md, gap matrix, result doc, G handoff. Full suite +
   review. Reset config. Stage F.1 files by path only; commit locally (no push).
