# Cowork overnight packet — 2026-08-10 → ready for Tuesday

Paste everything below the line into a fresh Cowork session opened on the `Pokemon` repo.
Supersedes `docs/poke/cowork-buy-loop-prompt.md` (that one is buy-loop only; this wraps it in a
prioritized overnight ladder).

---

You are running an overnight autonomous session on `Pokemon-main`. Package `scanner/`, price
subsystem `scanner/poke_api/`, discovery subsystem `scanner/discovery/`. Read `CLAUDE.md` and
`.claude/poke-invariants.md` first — both are load-bearing and override anything here that
contradicts them.

I am asleep. I will read your report Tuesday morning. Work continuously until the ladder is done or
you hit a genuine hard stop.

## Standing authorization — do all of this without asking

- Create `.venv` and install `requirements-dev.txt` if the SessionStart hook has not already. Those
  are dependencies the repo already declares; installing them adds nothing to the footprint.
- Run the suite as often as you like: `.claude/scripts/poke-pytest -q` (or
  `.venv/Scripts/python.exe -m pytest -q` on Windows).
- Read anything. Create and edit files under `scanner/`, `tests/`, `docs/`, `.claude/`.
- Commit freely in the repo's conventional style (`feat(poke):`, `fix(poke):`, `docs(poke):`,
  `test(poke):`, `data(poke):` — scope matches the touched subsystem).
- Merge to **local** `main` as specified in Phase 0. Do not `git pull` first: local `main`
  intentionally diverges from `origin/main`, and pulling would silently reconcile that.
- Create and work on branch `poke-buy-loop`. Push branches to `origin`.
- Dispatch subagents freely — implementers, reviewers, re-reviewers.

## Run the ladder in this order

Order is by value-if-you-run-out-of-time. **Finish whole phases.** A half-finished phase left on a
red suite is worse than one fewer phase — if you are running short, stop cleanly at a phase
boundary with the suite green and say so.

---

### Phase 0 — Land the harness (~10 min, unblocks everything else)

Branch `claude/superpowers-plugin-customize-cvw5s6` has 4 unmerged commits: the project-local
Superpowers fork (`.claude/skills/poke-*`), the doc updates, the SessionStart hook that provisions
`.venv`, and a Cowork prompt.

Merge it to local `main` and verify the suite green on the merged result. The hook in particular
only takes effect for future sessions once it is on the default branch, so this gates everything.

Then run `poke-review` over the merged fork itself — it has never been reviewed. It is
documentation and shell scripts, so scope the reviewer to: shell correctness in
`.claude/hooks/session-start.sh` and `.claude/scripts/poke-pytest`, internal contradictions between
the seven skills, and anything in the guardrail text that is wrong about this repo. Fix Criticals
and Importants; ledger Minors.

---

### Phase 1 — Credit-path audit (money-class; zero live calls)

**Why this is high priority.** `docs/poke/ppt-id-seeding.md` carries an unresolved STOP note from
2026-07-02: **85 credits were already consumed before that session's first call**, and it was never
diagnosed. Until that is understood, every credit budget in this project is built on sand, and the
seeding task cannot safely resume. T5 recently fixed one instance of this class
(`comp_response` was silently dropping `creditsConsumed`) — that fix is evidence the class is real,
not that it is closed.

Do this entirely offline. **Make no live PPT call.**

1. Enumerate every code path that can bill a PPT credit. Start from `scanner/market.py:49` and
   `scanner/poke_api/sources.py`, and follow every caller. Produce a table: entry point → HTTP call
   → `limit` passed → what it reports as consumed → whether that report can be dropped downstream.
2. Flag every path where **the requested `limit` is not explicitly pinned**. The API bills on
   requested `limit`, not results returned; an omitted `limit` defaults to 50 and bills 50. That is
   the single most likely explanation for the 85, and it is exactly the bug T5 half-fixed.
3. Flag every path that can bill and report `0`, or drop the field.
4. Flag anything that could fire **at import time, in a fixture, in a retry, or in a loop** — a
   retry wrapper around a billing call multiplies spend invisibly.
5. Write regression tests for each gap you find, asserting the `limit` argument is actually passed
   and that a billed value survives to the caller. These are the tests no behaviour test catches.
6. Write the findings to `docs/poke/credit-path-audit-2026-08-10.md` with, for each path, the
   file:line, the billing risk, and whether it is fixed or still open.

If you find a live-fire bug, **fix it** — that is in scope. If the audit cannot explain the 85
credits from evidence in the repo, say so plainly rather than constructing a theory. "Unexplained,
here are the three candidates ranked" is the correct answer if that is the truth.

---

### Phase 2 — The buy loop, T6–T11 (the main event)

Spec: `docs/superpowers/specs/2026-07-06-poke-real-transacting-build-design.md`. T0–T5 are **done
and merged** (roadmap hardening, TCGCSV gate + adapters, dated channel-aware fee model with
provenance, sealed credit accounting). Your scope is T6 through T11:

| Task | What it is |
| --- | --- |
| **T6** | Data-quality audit — catch a bad slug / missing URL / unsupported grade / stale observation **before** a number prices a real purchase. `catalog.validate_asset` (`catalog.py:44`) checks identity *presence* only today. |
| **T7** | Source-drift monitor — the buy side bets real money on one scraped source (PriceCharting). Detect parser-shape drift and **fail safe** rather than silently emit a wrong or empty number. All parsing is regex over raw HTML in `independent_sources.py`. |
| **T8** | Inventory / cost-basis / P&L ledger — new `scanner/poke_api/inventory_ledger.py` → `data/poke/inventory.jsonl` (gitignored). Template is `gem_rates.py`: own file, own `entry_id`, own `kind`, own CLI subgroup, append-only, idempotent by sha256, pure writer with `capture_date` passed in. |
| **T9** | Asset verified-entry intake — the load-bearing unblock. The raw/graded buy route is dead code: `current_asset_entry_candidates` requires a non-empty `asset_key` (`candidates.py:231/241`) but nothing writes one, so `build_asset_packet`'s live route (`edge.py:317`) never fires outside tests. |
| **T10** | Acquisition wiring — `edge_cli acquire`, manual like `outcome`, writing an acquisition row into the T8 ledger from an `EdgePacket` / `opportunity_id` I already acted on. |
| **T11** | Outcome / P&L tie-back — extend `signals_report` (`paper_ledger.py:164`) to read **both** ledgers per spec §3: real realized P&L from `inventory_ledger` joined to `edge_packet_id`, and paper outcomes from `paper_ledger`, labelled distinctly and **never blended**. |

Run it through the project's own skills — I want them exercised:

1. **`poke-plan`** → one plan covering T6–T11 at `docs/superpowers/plans/2026-08-10-poke-buy-loop.md`.
   Record the real baseline first (the suite was 1109 passed / 1 skipped as of 2026-08-10, but
   re-measure — Phase 1 will have added tests). Prewire the Global Constraints block. Recompute
   every worked example by hand before committing the plan.
2. **`poke-sdd`** → execute it. Fresh implementer per task, two-stage review after each, ledger
   every task in `.superpowers/sdd/<plan-basename>/progress.md`, five-round fix-loop cap,
   whole-branch review at the end on your most capable model.
3. **`poke-tdd`** governs every code change inside that: failing test first, watch it fail for the
   right reason, minimal implementation, watch it pass, full suite before commit.

---

### Phase 3 — Close out

- Full suite green, stated with its pass count and the baseline you started from.
- `poke-finish` on `poke-buy-loop`: present the menu and take **option 1, merge to local `main`**.
  You have my authorization for that specific choice tonight. Push the branch to `origin` as well
  so I can read the diff.
- Delete the SDD workspace once the final review is clean — git history is the record.

---

## Do NOT stop for these

These are not check-in moments. Decide and continue:

- "Should I continue to the next task / phase?" — yes. Run the ladder.
- "Here is a progress summary, shall I proceed?" — no summary. Keep going. The ledger is the record.
- A design choice the spec already resolved — the spec governs; implement it.
- A Minor review finding — ledger it as deferred; the final review triages.
- A test failing on its first run — that is the RED half of TDD.
- Naming, file placement, or refactoring inside a task's stated scope — your call.
- Which model to use for a subagent — your call, per `poke-sdd`'s Model Selection table.
- Whether the audit's answer is interesting enough to report — report it either way.

## DO stop for these — surface and wait

Every one is a hard stop. Do not decide, do not work around, do not "note it and proceed":

1. **A number with no source.** Never fabricate, guess, extrapolate, or interpolate a price, rate,
   fee, or cost. STOP-class.
2. **Removing `limit=1`** from a by-id PPT lookup, or any billable path that would report `0`.
   Money-class.
3. **Any live PPT or network call.** They spend credits against a 100/day free tier, and the budget
   is provably not what it looks like (see Phase 1). Phase 1 is an offline audit — if you think it
   needs a live call, you have misread it; stop and ask.
4. **Flipping a PIN-FIRST value** off its fail-safe default without a live source pinned and cited
   with a capture date. Unverified always errs toward higher fees / lower net / higher cost.
5. **Anything that executes rather than advises** — auto-buy, cart, checkout, auto-listing, login
   automation. T10's acquisition record is a record of a purchase I already made, never an executor.
6. **A new runtime dependency.** `requirements-dev.txt` is the ceiling. Nothing here needs a new one.
7. **A plan-mandated defect** — the plan requiring something the review rubric calls a bug. Show me
   the finding beside the plan text and ask which governs.
8. **The five-round fix-loop cap tripping on a load-bearing finding.**
9. **A merge conflict on Phase 0**, or a red suite on a merged result. Leave it, do not force it.

Everything not on that list: decide it yourself and keep moving.

## Guardrails you must not "fix"

Deliberate contradictions. Re-read the spec before touching any of them:

- **The D-vs-E split.** Comp-alone-never-promotes-off-WATCH is hardcoded in the D layer
  (`discovery/opportunities.py`: `LIVE_ELIGIBLE = {"sealed_retail_arbitrage"}`,
  `build_asset_opportunity` hardcodes `decision_hint="WATCH"`). Verified entries reach live **only**
  through the E layer (`poke_api/edge.py:40`). **This build extends the E route only and must not
  touch the D functions.**
- **TCGCSV is not independent of PPT.** TCGplayer lineage; TCGplayer market == PPT. It is a free
  *reference*, classified external / non-independent, **never** counted as `cross_source_validated`.
- **`PAPER_BUY < LIVE` ceiling.** `LIVE_PACKET_ELIGIBLE` stays strictly stricter than `PAPER_BUY`.
- **Three ledgers never conflate.** Observation (`price_history.jsonl`) vs paper decisions
  (`paper_decisions.jsonl`) vs the new inventory/P&L (`inventory.jsonl`).
- **The two `_shipping_for` copies** (`main.py:347`, `discovery/opportunities.py:115`) are identical
  by contract. Change one, change both.

## Scope ceiling

Phases 0–3 and nothing else. This program has a documented over-engineering failure mode — a
16-phase ladder that had to be collapsed into one build. Do **not** build: a dashboard, a scheduler,
a parser framework, export tooling, or the Phase-B runtime `/poke` operator persona. If you think
one is needed, say so in the report; do not build it.

## The report I read Tuesday morning

Lead with the answer, not the process. I want:

1. **Phase completion** — which phases finished, which did not, and where you stopped.
2. **The credit answer.** What explains the 85 credits, or the ranked candidates if it is still
   unexplained. This is the thing I most want to know.
3. **Test delta** — baseline pass count → final, and confirmation you ran it yourself. If the suite
   did not run at any point, say so; never report a green you did not observe.
4. **What landed** — per task, one line.
5. **Every PIN-FIRST value still fail-safe**, and what would pin each one.
6. **Deferred minors and parked findings**, each with its ruling.
7. **Anything needing my decision**, with enough context to answer without scrolling.
8. **Credit spend: 0.** Confirm no live PPT call was made. If one was, that is the first line of the
   report, not the last.

## First message

Do not ask me what to work on. Verify the venv, run the suite, read the spec, and open with a
one-paragraph readback: baseline pass count, what you found in the current state of Phase 0's branch
and T6–T11, and anything in the spec you think is wrong. Then start Phase 0 without waiting.
