# 07 — Delivery & Knowledge Systems

*GitHub delivery machinery, Notion workspace, the learning loop, ML/Hugging Face feasibility, and public-safe positioning. Everything here is a **paper design** — no GitHub/Notion mutations were made.*

---

## A. GitHub delivery

### Milestones (map to roadmap phases)
- **M0 — Clean Baseline** (Phase 0)
- **M1 — Reliability** (Phase 1)
- **M2 — Catalog & Sources** (Phase 2)
- **M3 — Operator Dashboard** (Phase 3)
- **M4 — Alert Quality** (Phase 4)
- **M5 — Packaging & Packs** (Phase 5)

### Labels
`type:bug` `type:feature` `type:chore` `type:docs` · `area:scanner` `area:web` `area:retailer` `area:state` `area:notify` `area:catalog` `area:sources` · `prio:P0…P3` · `effort:S/M/L` · `doctrine-review` (touches a boundary in [04]) · `blocked` · `good-first-issue`.

### Issue template (`.github/ISSUE_TEMPLATE/task.md`)
```
## Goal (one sentence)
## Why / leverage
## Scope (in)            ## Out of scope
## Files likely touched
## Acceptance criteria (checklist, testable)
## Tests to add
## Doctrine check (any [04] boundary? mark doctrine-review)
## Dependencies (#issue)
```

### First 20 issues (ready to open)

| # | Title | Milestone | Acceptance (short) | Effort | Deps |
|---|---|---|---|---|---|
| 1 | Add `*.bak` to .gitignore; remove scratch/log files | M0 | `git status` clean; no `.bak`/scratch staged | S | — |
| 2 | Commit untracked modules + docs as reviewed baseline | M0 | 170 tests pass on the new commit; CI green | S | 1 |
| 3 | Smoke-verify `--check-config`, `--safe-demo`, web boot | M0 | documented pass of all three | S | 2 |
| 4 | notify: add `raise_for_status` + retry + alert-log | M1 | dead webhook is logged+surfaced, not dropped; test | S | 2 |
| 5 | main: crash-safe outer loop + exponential backoff | M1 | loop survives thrown exception; test | S | 2 |
| 6 | state: heartbeat row + WAL + single-txn writes | M1 | heartbeat advances each cycle; existing state tests green | M | 2 |
| 7 | web: real Liveness indicator (live/stale/down) | M1 | indicator goes stale within one interval of a stalled loop | M | 6 |
| 8 | health: persist on every write; config thresholds | M1 | health survives restart; thresholds configurable; test | M | 6 |
| 9 | resale: persist quote cache to disk | M1 | prices reappear after restart; test | S | 2 |
| 10 | Add `source_mode` setting + enforcement + ack gate | M2 | `durable_only` makes zero personal-use-source calls (test) | M | 2 | 
| 11 | Catalog refresh: Mega Evolution block + Pitch Black | M2 | new SKUs added w/ provenance; Best Buy SKUs API-verified | M | 10 |
| 12 | Catalog: 30th Celebration + First Partner S1–S3 + DR tins | M2 | added; `[needs validation]` MSRPs labeled | M | 11 |
| 13 | Release-watch model (`data/releases.yaml` + loader) | M2 | parse/validate tests; feeds inbox | M | 2 |
| 14 | ID Doctor truthfulness: relabel "URL-resolves only" | M2 | Walmart/Costco/GameStop statuses accurate; test | S | 2 |
| 15 | `POST /api/verify-ids` + ID Doctor UI surface | M3 | verify-from-UI updates provenance; test | M | 14 |
| 16 | Release-watch inbox UI | M3 | release <14d w/ missing IDs surfaces w/ countdown | M | 13 |
| 17 | workqueue: severity-first sort + first `test_workqueue.py` | M3 | deterministic ordering; tests | S | 2 |
| 18 | Source cards: source-durability badge + reasons | M3 | each source shows durability + reason code | S | 10 |
| 19 | Alert ranking by MSRP-protection tier + dedupe | M4 | Tier-1 ETB out-ranks Tier-3 pack; test | M | 4 |
| 20 | Quiet-hours / urgency routing (urgent→ntfy, digest→Discord) | M4 | non-urgent suppressed in quiet hours; cadence ≥60s | M | 19 |

**First PR recommendation:** Issue #1+#2+#3 as a single "Phase 0 baseline" PR — pure housekeeping, no logic, makes everything else reviewable. Then #4 as the first feature PR (smallest, highest-value reliability fix).

**CI recommendation:** keep the Ubuntu+Windows × 3.11/3.12 matrix; add `ruff check` + a coverage floor (e.g., 80%) in M1; gate merges on green. **Block until clean:** no feature PRs until the Phase-0 baseline PR lands.

**Security checklist (PR gate):** no secrets/`.db`/`.bak`; no new live source without [02/H] classification + `doctrine-review`; logs redact coords/query strings; dashboard stays loopback unless token auth added.

---

## B. Notion workspace

> Sync rule of thumb: **repo is source of truth for anything in code/config; Notion is source of truth for research, decisions, and briefings.** Never put secrets in Notion.

| Database | Key properties | Views | Template |
|---|---|---|---|
| **Product Releases** | Set, Game, Release date, Status (announced/preorder/released), Products (relation), English MSRP confidence | Calendar (by date), Board (by status), "Next 30 days" | new-release checklist |
| **Catalog Research** | Product name, Set (rel), Type, MSRP, MSRP-protection tier, Retailer IDs (TCIN/SKU/slug…), Provenance status, Verified date | Table (by tier), "Missing IDs", "Stale (>30d)" | per-product record |
| **Retailers / Sources** | Name, Tier, Durability tier (official/internal/alert-only), Restock pattern, Fair-access system, Last drift check | Table, "Re-check sources" | source profile |
| **Verified ID Queue** | Product+retailer, Status (unchecked/confirmed/url-only/blocked), Action (find/verify/fix), Owner | Board (by status) | verification task |
| **Daily Briefings** | Date, Restocks seen, Alerts fired, Coverage %, Notes | Calendar | daily template (below) |
| **Weekly Service Briefings** | Week, Releases this/next week, Coverage trend, Source-health summary, Decisions, Risks | Gallery | weekly template (below) |
| **Blockers / Risk Register** | Item, Severity, Status, Mitigation, Owner | Board (by severity) | risk entry |
| **Decisions Log** | Decision, Date, Rationale, Doctrine impact, Linked issue | Table (chrono) | decision record |
| **Operator Runbook** | Topic, Steps, Last verified | Table | runbook page |

**Sync from repo → Notion (manual or scripted):** coverage %, source-health snapshot, catalog diffs, new release records. **Stays manual in Notion:** research notes, decisions, briefings, risk register. **Never in Notion:** addresses, webhook, API keys, `config.yaml`, route coordinates, raw `state.db` (store-adjacent data).

---

## C. Learning loop (repeatable research cadence)

**Daily (≤5 min):** scan headlines for new-set/restock news; glance at dashboard liveness + overnight restocks. → write a one-line Daily Briefing. Escalate to a release record if a new product is announced.

**Weekly:** refresh the release calendar; review source health + coverage trend; review alert quality (false/missed). → Weekly Service Briefing + any new GitHub issues.

**Release-window (T-14 → T+7):** confirm all IDs green in ID Doctor; tighten cadence; test both alert channels; prep "go enter the queue" reminders for PC/Best Buy. → release-watch record updated; post-mortem after.

**Templates**

```
DAILY BRIEFING — <date>
News: <bullets w/ links>     New releases to add? <y/n>
Dashboard: liveness <ok/stale> · coverage <%> · overnight restocks <n>
Action: <one thing> → [issue/queue]
```
```
WEEKLY SERVICE BRIEFING — week of <date>
Releases: this week <…> · next 2 weeks <…>
Coverage: <%> (<Δ>) · non-actionable: <list>
Source health: <durability notes; any source drift>
Alert quality: fired <n> · missed <n> · false <n>
Decisions: <…>   Risks: <…>   Issues opened: <#…>
```
```
RELEASE WATCH — <set> (<date>)
Products + IDs needed: <table>   IDs status: <green/url-only/missing>
Retailers expected: <…>   Cadence: <window>   Channels tested: <y/n>
Queue/invite retailers (alert-only): <PC? Best Buy?>
Post-mortem: caught? <…> · misses <…> · fixes <#…>
```
```
PRODUCT RESEARCH RECORD
Name · Set · Type · MSRP · protection tier · resale context (labeled)
IDs: TCIN/SKU/slug/itemId · provenance URL · verified date · status
```
```
RETAILER SOURCE-HEALTH RECORD
Source · durability tier · last success · last status · reason · last drift check
```
**Catalog update checklist:** paste URL → Add-ID extracts → ID Doctor verifies → provenance recorded → coverage rechecked → committed (no secrets).
**Blocker escalation checklist:** reproduce → classify (bug/source-drift) → if doctrine boundary, stop + mark `doctrine-review` → log in Risk Register → open issue → note in weekly.

---

## D. ML / Hugging Face feasibility

**Verdict: rules first. No training for v1.** The pipeline is structured IDs + JSON/API responses; deterministic logic already does the job. ML earns its place only at fuzzy text/image edges, and even there a small local model is optional, not required.

| Candidate use | Rules enough? | If ML: tool | Local? | Sensitive data? | Hallucination risk | Test that proves value | Verdict |
|---|---|---|---|---|---|---|---|
| Product-title normalization across retailers | **Mostly** (token match already in `resale.py`) | sentence-transformer embeddings for fuzzy match | yes | no | low | match accuracy vs current `_title_allowed` on a labeled set | defer; revisit if mismatches appear |
| First-party vs marketplace/inflated listing detection | **Yes** (seller field + price-vs-MSRP heuristic) | small classifier | yes | no | med | precision/recall vs heuristic on eBay fixtures | rules first |
| Image match when titles drift | No (genuinely hard) | CLIP image embeddings | yes | no (public images) | med | top-1 match on a product-image set | **only if** title matching demonstrably fails |
| OCR on screenshots | Rarely needed | Tesseract / TrOCR | yes | maybe (screenshots) | med | field-extraction accuracy | defer; avoid unless a real need |
| Retailer/page → structured research record | Partly (regex/JSON) | small summarizer LLM | borderline | maybe | **high** | human-review agreement rate | keep human-in-loop; no autonomous writes |
| Cluster products by set/type/chase priority | **Yes** (catalog metadata) | embeddings + clustering | yes | no | low | matches manual tiers | rules first |
| Rank research-queue items | **Yes** (the workqueue formula) | learned ranker | yes | no | low | ordering vs operator preference | rules first |

**Use-rules-first list:** title matching, marketplace detection, clustering, queue ranking, MSRP-protection tiering — all deterministic today.
**HF model families to evaluate later (only if a real gap appears):** sentence-transformers (fuzzy title match), CLIP (image match), a small instruct LLM for *human-reviewed* page→record drafting, TrOCR/Tesseract (OCR). All can run locally; none should make autonomous catalog writes.
**No-training v1 recommendation:** ship Phases 0–4 with zero ML. Re-open the question only when (a) title/image mismatches measurably hurt coverage, with a labeled test set to prove improvement, and (b) the model runs locally with no sensitive data and no autonomous writes.

---

## E. Positioning (public-safe) — *only the operational service is the product; this is the wrapper*

**Naming directions (3):**
1. **"MSRP Watch"** — plain, honest, says exactly what it does. Anti-scalper by tone.
2. **"Shelf Price Sentinel"** / "Sentinel" — guardian framing; protection, not acquisition.
3. **"PackKeeper"** — hobby/opener framing ("keep packs at pack price"); friendly, community.

**Positioning routes (3):**
1. **The honest-collector tool** — "Built by someone who opens packs, to buy at the price on the box." Leads with doctrine.
2. **The reliability tool** — "Truthful liveness, fast alerts, no fake confidence." Leads with the engineering quality + source honesty.
3. **The local-first/privacy tool** — "Your addresses, your webhook, your machine. Nothing leaves home." Leads with the privacy model.

**Taglines:** "Buy it at the price on the box." · "Restock alerts for openers, not scalpers." · "MSRP protection, locally run." · "It tells you the truth about whether it's even working."

**Public-safe demo concept:** record/screenshot **only** `--safe-demo` (synthetic stores, synthetic OUT/IN rows). Show the four dashboard zones, the coverage bar, source badges, and a sample alert — all synthetic.

**Must NOT appear in any public material:** real home/work addresses, store IDs/coordinates/route lines, the Discord webhook or any URL with it, API keys, `config.yaml` contents, real `state.db` data, or any framing that implies flipping/resale profit, auto-checkout, or beating other buyers via automation. Keep a **private operator README** (full detail) separate from a **public sanitized README** (doctrine-forward, demo-mode screenshots, durable-source setup).
