# Cowork session packet — Monday 2026-08-10, morning

Open a Cowork session on the `Pokemon` repo and paste everything below the line — or just say:
*"Read `docs/poke/cowork-monday-2026-08-10.md` and execute it."*

Supersedes the earlier buy-loop and overnight drafts (both deleted).

---

You are running a **bounded morning session** on `Pokemon-main`. Package `scanner/`, price
subsystem `scanner/poke_api/`, discovery subsystem `scanner/discovery/`.

Read `CLAUDE.md` and `.claude/poke-invariants.md` before anything else. Both are load-bearing and
override anything in this packet that contradicts them.

I am around but not watching. Work continuously. I will read your report when you stop.

## The window, and how to manage it

You have **a morning, not a night.** Record the wall-clock time in your first message and treat it
as a budget. This is the single most important instruction in this packet:

> **Finish whole phases. Stop cleanly at a phase or task boundary with the suite green.**
> A half-built task on a red suite is worth less than one fewer task on a green one, because I
> cannot merge it and the next session has to unpick it.

When roughly two-thirds of your window is gone, stop starting new tasks. Spend the remainder
closing out: full suite, final review, ledger, report. Do not attempt "one more task" — that is how
sessions end red.

The ladder below is ordered by **value-if-you-run-out-of-time**, not by dependency alone. Phases 0–2
are the ones I most want; Phase 3 is explicitly open-ended and expected to end partway.

## Standing authorization — do all of this without asking

- Create `.venv` and install `requirements-dev.txt` if the SessionStart hook has not already. Those
  are dependencies the repo already declares; installing them adds nothing to the footprint.
- Run the suite as often as you like: `.claude/scripts/poke-pytest -q` (or
  `.venv/Scripts/python.exe -m pytest -q` on Windows). It is network-mocked and takes ~10s.
- Read anything. Create and edit files under `scanner/`, `tests/`, `docs/`, `.claude/`.
- Commit freely in the repo's conventional style (`feat(poke):`, `fix(poke):`, `docs(poke):`,
  `test(poke):`, `data(poke):` — scope matches the touched subsystem).
- Merge to **local** `main` where the phases below say so. Do **not** `git pull` first: local `main`
  intentionally diverges from `origin/main`, and pulling would silently reconcile that divergence.
- Create and work on branch `poke-buy-loop`. Push branches to `origin`.
- Dispatch subagents freely — implementers, reviewers, re-reviewers.

---

## Phase 0 — Land the harness (~10 minutes; do this first)

Branch `claude/superpowers-plugin-customize-cvw5s6` carries 5 unmerged commits: the project-local
Superpowers fork (`.claude/skills/poke-*`), doc updates, a SessionStart hook that provisions `.venv`
in web sessions, and this packet.

**Why first:** the hook only takes effect for future sessions once it is on the default branch, and
the `poke-*` skills you are about to use all the way through Phases 1–3 live in that branch.

1. Merge it to local `main`. Verify the suite green **on the merged result** — a merge that passes
   on the branch and fails merged is a real failure, and the branch stays put while you investigate.
2. Run `poke-review` over the merged fork. It has never been reviewed. It is documentation and
   shell, so scope the reviewer to:
   - shell correctness and failure modes in `.claude/hooks/session-start.sh` and
     `.claude/scripts/poke-pytest` (especially: does either ever exit 0 while leaving the suite
     unrunnable? that would hand a session a false green)
   - internal contradictions between the seven skills, and between them and `CLAUDE.md`
   - anything in the guardrail text that is factually wrong about this repo
3. Fix Criticals and Importants. Ledger Minors.

**Acceptance:** local `main` contains the harness, suite green on the merged result, review findings
fixed or ledgered.

---

## Phase 1 — Credit-path audit (money-class; entirely offline)

**Why this outranks feature work.** `docs/poke/ppt-id-seeding.md` carries an unresolved STOP note
from 2026-07-02: **85 credits were consumed before that session's first call**, and it was never
diagnosed. Until that is understood, every credit budget in this project is built on sand, seeding
cannot safely resume, and the buy loop would ship on top of an unexplained money leak. T5's recent
`comp_response` fix — a billable path silently dropping `creditsConsumed` — is evidence the bug
*class* is live, not that it is closed.

**Make no live PPT call. This is a static audit of the code.** If you believe the task needs a live
call, you have misread it — stop and ask.

### Method

1. **Enumerate every path that can bill.** Start at `scanner/market.py:49` and
   `scanner/poke_api/sources.py`; follow every caller transitively. Build a table:

   | entry point | HTTP call site | `limit` passed | what it reports consumed | can that report be dropped downstream? |

2. **Flag every call site where `limit` is not explicitly pinned.** The API bills on the *requested*
   `limit`, not results returned; an omitted `limit` on `/sealed-products` defaults to 50 and bills
   50. Your seeding doc confirms this live: one no-`limit` by-id call dropped
   `X-RateLimit-Daily-Remaining` from 95 to 45. **This is the leading candidate for the 85** and is
   exactly the class T5 half-closed.

3. **Flag every path that can bill but report `0`,** or that drops the field before the caller sees
   it. That is the T5 bug's shape.

4. **Flag anything that can fire more than once per logical lookup:** a retry or backoff wrapper
   around a billing call, a loop over products without a between-item budget check, a call at import
   time or in a fixture/conftest, a cache that misses more often than intended. A retry wrapper
   around a 5-credit search is a 15-credit call that nothing accounts for — that fits an 85-credit
   surprise better than anything else.

5. **Check the budget arithmetic itself.** The seeding doc records a genuine ambiguity: the
   `X-RateLimit-Daily-Remaining` header is **post-charge**, so a first observed value of 10 means 15
   pre-charge. If any code reads that header as pre-charge, every budget check in the project is off
   by the size of the call being made. Verify which reading the code uses.

6. **Write regression tests for every gap you find** — asserting the `limit` argument is actually
   passed, and that a billed value survives to the caller. No behaviour test catches either; these
   are the only thing standing between you and a repeat.

7. **Fix the live-fire bugs you find.** That is in scope, TDD as usual.

8. **Write `docs/poke/credit-path-audit-2026-08-10.md`**: every path with its file:line, its billing
   risk, and whether it is now fixed or still open. Follow the shape of the existing result docs in
   `docs/poke/`.

### On the answer

If the audit cannot explain the 85 credits from evidence in the repo, **say so plainly.**
*"Unexplained — here are the three candidates, ranked, and what evidence would settle each"* is the
correct and useful answer. Do not construct a theory to have one. Fabricating a cause here is the
same failure as fabricating a price.

**Acceptance:** the audit doc exists, every billing path is in the table, regression tests are green,
and the 85 credits are either explained or explicitly ranked as unexplained.

---

## Phase 2 — Write the T6–T11 plan (completes even if nothing gets built)

Spec: `docs/superpowers/specs/2026-07-06-poke-real-transacting-build-design.md`. T0–T5 are **done and
merged** (roadmap hardening, TCGCSV gate + adapters, the dated channel-aware fee model with
provenance, sealed credit accounting). Your scope is T6–T11:

| Task | What it is |
| --- | --- |
| **T6** | Data-quality audit — catch a bad slug / missing URL / unsupported grade / stale observation **before** a number prices a real purchase. `catalog.validate_asset` (`catalog.py:44`) checks identity *presence* only today. |
| **T7** | Source-drift monitor — the buy side bets real money on one scraped source (PriceCharting). Detect parser-shape drift and **fail safe** rather than silently emit a wrong or empty number. All parsing is regex over raw HTML in `independent_sources.py`; the date-verified cell ids are at `:30-37` and the pop blob `_POP_RE` at `:98-99`. |
| **T8** | Inventory / cost-basis / P&L ledger — new `scanner/poke_api/inventory_ledger.py` → `data/poke/inventory.jsonl` (gitignored, "runtime ledgers" block), CLI subgroup in `edge_cli.py` (`:681-697`). Template is `gem_rates.py`: own file, own `entry_id`, own `kind`, append-only, idempotent by sha256, pure writer with `capture_date` passed in. |
| **T9** | Asset verified-entry intake — the load-bearing unblock. The raw/graded buy route is dead code: `current_asset_entry_candidates` requires a non-empty `asset_key` (`candidates.py:231/241`) but nothing writes one, so `asset_candidate_for_provider` (`candidates.py:279`) and `build_asset_packet`'s live route (`edge.py:317`) never fire outside tests. |
| **T10** | Acquisition wiring — `edge_cli acquire`, manual like `outcome`, writing an acquisition row into the T8 ledger from an `EdgePacket` / `opportunity_id` I already acted on. |
| **T11** | Outcome / P&L tie-back — extend `signals_report` (`paper_ledger.py:164`) to read **both** ledgers per spec §3: real realized P&L from `inventory_ledger` joined to `edge_packet_id`, and paper outcomes from `paper_ledger`, labelled distinctly and **never blended**. |

Use **`poke-plan`**. Write one plan to `docs/superpowers/plans/2026-08-10-poke-buy-loop.md`:

- **Re-measure the baseline first.** The suite was 1109 passed / 1 skipped on 2026-08-10 before this
  session; Phase 1 will have added tests. State the number you actually observe.
- Prewire the Global Constraints block from the spec's cross-cutting invariants, with exact values
  copied verbatim.
- Mark every unpinned value as a **PIN-FIRST** gate with its fail-safe default.
- **Recompute every worked example by hand before committing the plan.** A worked example that does
  not reconcile ships as a code bug — it has happened in this repo (`docs(poke)` commit `d81a401`
  fixed a plan whose tcgplayer example dropped the $0.30 fixed fee).
- Run the plan self-review checklist before you commit it.

**Why this phase completes even in a short window:** a finished plan is a durable deliverable. If
the clock beats you in Phase 3, the remaining tasks are fully specified and the next session — or a
subagent fleet — executes them cold.

**Acceptance:** the plan exists, is committed, passes its own self-review, and every task has exact
file paths, real code, and reconciling arithmetic.

---

## Phase 3 — Execute as much of the plan as the window allows

Use **`poke-sdd`**: fresh implementer subagent per task, two-stage review after each, ledger every
task in `.superpowers/sdd/2026-08-10-poke-buy-loop/progress.md`, five-round fix-loop cap,
whole-branch review at the end on your most capable model. `poke-tdd` governs every code change
inside it: failing test first, watch it fail for the right reason, minimal implementation, watch it
pass, full suite before commit.

Work the tasks in plan order. **T6 and T7 first regardless** — they are the guards that make the
later tasks' numbers trustworthy, and they are the two most likely to fit the window.

**This phase is expected to end partway. That is fine and planned for.** When you stop:

- stop at a **task boundary**, suite green, everything committed
- the ledger's last line says exactly which task is next and why you stopped
- the branch is pushed so I can read the diff

**Acceptance:** every task you started is finished, reviewed, and green — or was never started.
Nothing half-built.

---

## Phase 4 — Close out (reserve time for this)

- Full suite, green, run by you. State the pass count and the baseline you started from.
- Whole-branch `poke-review` on the work that landed, on your most capable model.
- `poke-finish` on `poke-buy-loop`. Present the menu and take **option 1, merge to local `main`** —
  you have my authorization for that choice today. Push the branch to `origin` as well.
- Delete the SDD workspace only if the plan is fully executed. If Phase 3 ended partway, **leave the
  workspace in place** — its ledger is how the next session resumes without re-dispatching completed
  tasks.

---

## Do NOT stop for these

Not check-in moments. Decide and continue:

- "Should I continue to the next task / phase?" — yes. Run the ladder.
- "Here is a progress summary, shall I proceed?" — no summary. Keep going. The ledger is the record.
- A design choice the spec already resolved — the spec governs; implement it.
- A Minor review finding — ledger it as deferred; the final review triages.
- A test failing on its first run — that is the RED half of TDD.
- Naming, file placement, or refactoring inside a task's stated scope — your call.
- Which model to use for a subagent — your call, per `poke-sdd`'s Model Selection table.
- Whether the audit's answer is interesting enough to report — report it either way.
- Whether you have time for one more task — apply the two-thirds rule and decide yourself.

## DO stop for these — surface and wait

Every one is a hard stop. Do not decide, do not work around, do not "note it and proceed":

1. **A number with no source.** Never fabricate, guess, extrapolate, or interpolate a price, rate,
   fee, or cost. STOP-class.
2. **Removing `limit=1`** from a by-id PPT lookup, or any billable path that would report `0`.
   Money-class.
3. **Any live PPT or network call.** They spend credits against a 100/day free tier, and the budget
   is provably not what it looks like — that is what Phase 1 exists to find out.
4. **Flipping a PIN-FIRST value** off its fail-safe default without a live source pinned and cited
   with a capture date. Unverified always errs toward higher fees / lower net / higher cost.
5. **Anything that executes rather than advises** — auto-buy, cart, checkout, auto-listing, login
   automation. T10's acquisition record is a record of a purchase I already made, never an executor.
   If the spec seems to ask otherwise, you have misread it.
6. **A new runtime dependency.** `requirements-dev.txt` is the ceiling. Nothing here needs one.
7. **A plan-mandated defect** — the plan requiring something the review rubric calls a bug. Show me
   the finding beside the plan text and ask which governs.
8. **The five-round fix-loop cap tripping on a load-bearing finding.**
9. **A merge conflict in Phase 0, or a red suite on a merged result.** Leave it; do not force it.

Everything not on that list: decide it yourself and keep moving.

## Guardrails you must not "fix"

Deliberate contradictions. Re-read the spec that established each before touching it:

- **The D-vs-E split.** Comp-alone-never-promotes-off-WATCH is hardcoded in the D layer
  (`discovery/opportunities.py`: `LIVE_ELIGIBLE = {"sealed_retail_arbitrage"}`;
  `build_asset_opportunity` hardcodes `decision_hint="WATCH"`). Verified entries reach live **only**
  through the E layer (`poke_api/edge.py:40`). **This build extends the E route only and must not
  touch the D functions.**
- **TCGCSV is not independent of PPT.** TCGplayer lineage; TCGplayer market == PPT. It is a free
  *reference*, classified external / non-independent, and is **never** counted as
  `cross_source_validated`.
- **`PAPER_BUY < LIVE` ceiling.** `LIVE_PACKET_ELIGIBLE` stays strictly stricter than `PAPER_BUY`,
  reachable only through the full verified-evidence spine.
- **Three ledgers never conflate.** Observation (`price_history.jsonl`) vs paper decisions
  (`paper_decisions.jsonl`) vs the new inventory/P&L (`inventory.jsonl`). Distinct files, distinct
  `kind`, append-only, idempotent by sha256 `entry_id`, pure writers.
- **The two `_shipping_for` copies** (`main.py:347`, `discovery/opportunities.py:115`) are identical
  by contract. Change one, change both.

## Scope ceiling

Phases 0–4 and nothing else. This program has a documented over-engineering failure mode — a
16-phase ladder that had to be collapsed into a single build. Do **not** build: a dashboard, a
scheduler, a parser framework, export tooling, or the Phase-B runtime `/poke` operator persona. If
you think one is needed, say so in the report; do not build it.

## The report

Lead with the answer, not the process. Give me, in this order:

1. **Where you stopped and why** — which phases finished, which task is next, and how much of the
   window you used.
2. **The credit answer.** What explains the 85 credits, or the ranked candidates with the evidence
   that would settle each. This is the thing I most want to know.
3. **Test delta** — baseline pass count → final, and confirmation you ran it yourself. If the suite
   did not run at any point, say so; never report a green you did not observe.
4. **What landed** — one line per task.
5. **Every PIN-FIRST value still fail-safe**, and what would pin each one.
6. **Deferred minors and parked findings**, each with its ruling.
7. **Anything needing my decision**, with enough context to answer without scrolling back.
8. **Credit spend: 0.** Confirm no live PPT call was made. If one was, that is the *first* line of
   the report, not the last.
9. **How to resume** — the exact next task, and whether the SDD workspace is still on disk.

## First message

Do not ask me what to work on. Note the wall-clock time, verify the venv, run the suite, read the
spec, and open with a one-paragraph readback: baseline pass count, the state of Phase 0's branch and
of T6–T11, and anything in the spec you think is wrong. Then start Phase 0 without waiting.
