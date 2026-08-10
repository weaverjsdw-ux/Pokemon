# Cowork prompt — Real-Transacting Build, buy loop (T6–T11)

Paste everything below the line into a fresh Cowork session opened on the `Pokemon` repo.

---

Work the **buy loop** of the real-transacting build to completion. Repo is `Pokemon-main`, package
`scanner/`, price subsystem `scanner/poke_api/`. Read `CLAUDE.md` and `.claude/poke-invariants.md`
first — they are load-bearing and override anything in this prompt that contradicts them.

## Standing authorization — do these without asking

You have my go-ahead, for this whole session, for all of the following. Do not stop to confirm any
of them:

- Create `.venv` and `pip install -r requirements-dev.txt`. Those are the dependencies the repo
  already declares; installing them adds nothing to the footprint. Do this **first**, before any
  other work — nothing else is verifiable until the suite runs.
- Run the test suite as often as you like: `.claude/scripts/poke-pytest -q`, or
  `.venv/Scripts/python.exe -m pytest -q` on Windows.
- Read anything in the repo. Create and edit files under `scanner/`, `tests/`, `docs/`, `.claude/`.
- Commit as often as the work warrants, in the repo's conventional style (`feat(poke):`,
  `fix(poke):`, `docs(poke):`, `test(poke):`, scope matching the touched subsystem).
- Create and work on the branch `poke-buy-loop`. Push it to `origin` when a task lands.
- Dispatch subagents freely — implementers, reviewers, re-reviewers.

## The work

The spec is `docs/superpowers/specs/2026-07-06-poke-real-transacting-build-design.md`. T0–T5 are
**done and merged** (roadmap hardening, TCGCSV gate + adapters, the dated channel-aware fee model
with provenance, sealed credit accounting). Your scope is **T6 through T11**, in this order:

| Task | What it is |
| --- | --- |
| **T6** | Data-quality audit — catch a bad slug / missing URL / unsupported grade / stale observation **before** a number prices a real purchase. Today `catalog.validate_asset` (`catalog.py:44`) checks identity *presence* only. |
| **T7** | Source-drift monitor — the buy side now bets real money on one scraped source (PriceCharting). Detect parser-shape drift and **fail safe** rather than silently emitting a wrong or empty number. All parsing is regex over raw HTML in `independent_sources.py`. |
| **T8** | Inventory / cost-basis / P&L ledger — new `scanner/poke_api/inventory_ledger.py` → `data/poke/inventory.jsonl` (gitignored). Template is `gem_rates.py`: separate file, own `entry_id`, own `kind`, own CLI subgroup, append-only, idempotent by sha256, pure writer with `capture_date` passed in. |
| **T9** | Asset verified-entry intake — the load-bearing unblock. The raw/graded buy route is dead code today: `current_asset_entry_candidates` requires a non-empty `asset_key` (`candidates.py:231/241`) but nothing writes one, so `build_asset_packet`'s live route (`edge.py:317`) never fires outside tests. |
| **T10** | Acquisition wiring — `edge_cli acquire`, manual like `outcome`, writing an acquisition row into the T8 ledger from an `EdgePacket` / `opportunity_id` the operator already acted on. |
| **T11** | Outcome / P&L tie-back — extend `signals_report` (`paper_ledger.py:164`) to read **both** ledgers per spec §3: real realized P&L from `inventory_ledger` joined to `edge_packet_id`, and paper outcomes from `paper_ledger`, labelled distinctly and **never blended**. |

## How to run it

Use the project's own skills — they encode the rules below and I want them exercised:

1. **`poke-plan`** — write one implementation plan covering T6–T11 to
   `docs/superpowers/plans/<today>-poke-buy-loop.md`. Record the real test baseline first (run the
   suite and count). Prewire the Global Constraints block. Recompute every worked example by hand
   before you commit the plan.
2. **`poke-sdd`** — execute it. Fresh implementer subagent per task, two-stage review after each,
   ledger every task in `.superpowers/sdd/<plan-basename>/progress.md`, five-round fix-loop cap,
   whole-branch review at the end on your most capable model.
3. **`poke-finish`** — when the branch is green and reviewed. Present the menu; **merge to local
   `main`** is the expected choice.

`poke-tdd` governs every code change inside that: failing test first, watch it fail for the right
reason, minimal implementation, watch it pass, full suite before commit.

## Do NOT stop for these

You have a documented habit of checking in too often. These are not check-in moments:

- "Should I continue to the next task?" — yes. Run the ladder end to end.
- "Here's a progress summary, shall I proceed?" — no summary. Keep going.
- A design choice the spec already resolved — the spec governs; implement it.
- A Minor review finding — ledger it as deferred and move on. The final review triages them.
- A test that fails on the first run — that is the RED half of TDD. Continue.
- Reformatting, renaming, or file placement inside a task's stated scope — your call.
- Which model to use for a subagent — your call, per `poke-sdd`'s Model Selection table.

## DO stop for these — every one is a hard stop

Surface it to me and wait. Do not decide, do not work around, do not "note it and proceed":

1. **A number with no source.** If a task needs a price, rate, fee, or cost you cannot source, stop.
   Never fabricate, guess, extrapolate, or interpolate one. This is STOP-class.
2. **Removing `limit=1`** from a by-id PPT lookup, or any billable path that would report `0`. The
   API bills on requested `limit`, not results returned. Money-class.
3. **Any live PPT / network call.** They spend credits against a 100/day free tier. Tell me the
   estimated spend and wait. Note there is an **unexplained 85-credit consumption** logged in
   `docs/poke/ppt-id-seeding.md` from 2026-07-02 that was never diagnosed — assume the budget is
   not what it looks like.
4. **Flipping a PIN-FIRST value** off its fail-safe default without a live source pinned and cited
   with a capture date. Unverified always errs toward higher fees / lower net / higher cost.
5. **Anything that executes rather than advises** — auto-buy, cart, checkout, auto-listing, login
   automation. The acquisition record in T10 is a record of a purchase I already made, never an
   executor. If the spec seems to ask otherwise, you have misread it; stop and ask.
6. **A new runtime dependency.** `requirements-dev.txt` is the ceiling. T6–T11 need no new package.
7. **A plan-mandated defect** — the plan's text requiring something the review rubric calls a bug.
   Show me the finding beside the plan text and ask which governs.
8. **The five-round fix-loop cap tripping on a load-bearing finding.**

Everything not on that list: decide it yourself and keep moving.

## Guardrails you must not "fix"

These look like contradictions and are deliberate. Re-read the spec before touching any of them:

- **The D-vs-E split.** Comp-alone-never-promotes-off-WATCH is hardcoded in the D layer
  (`discovery/opportunities.py`: `LIVE_ELIGIBLE = {"sealed_retail_arbitrage"}`,
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

Build T6–T11 and nothing else. This program has a documented over-engineering failure mode — a
16-phase ladder that had to be collapsed into one build. Specifically do **not** build: a dashboard,
a scheduler, a parser framework, export tooling, or the Phase-B runtime `/poke` operator persona.
If you think one is needed, say so at the end; don't build it.

## Definition of done

Stop and report when all of these hold:

- T6–T11 implemented, each with tests written first.
- Full suite green, run by you, output pristine — and you state the pass count and the baseline you
  started from. If the suite will not run, say so plainly; never report a green you did not observe.
- Every number introduced carries a source URL + capture/effective date, or an explicitly badged
  `operator_assumption`.
- Every billable path reports bounded credits or refuses first; `limit=1` intact everywhere.
- Whole-branch review clean, or residual findings parked with written rulings in the ledger.
- Branch `poke-buy-loop` pushed, and `poke-finish` run to the menu.

Then give me: what landed, the test delta, every PIN-FIRST value still fail-safe and what would pin
it, every deferred-minor and parked finding with its ruling, and anything you hit that needs my
decision.

## First message back

Do not ask me what to work on. Set up the venv, run the suite, read the spec, and open with a
one-paragraph readback: baseline pass count, what you found in T6–T11's current state, and anything
in the spec you think is wrong. Then start on the plan without waiting for me.
