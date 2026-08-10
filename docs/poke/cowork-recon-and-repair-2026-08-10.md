# Cowork session packet — Recon & Repair, Monday 2026-08-10

Open Cowork on the `Pokemon` repo and say:
*"Read `docs/poke/cowork-recon-and-repair-2026-08-10.md` and execute it."*

Supersedes every earlier Cowork draft.

---

You are running a **recon-and-repair session** across my working environment. The Pokemon resale
engine is the centre of it, but it is not the whole of it.

Read `CLAUDE.md` and `.claude/poke-invariants.md` first. Both are load-bearing and override anything
in this packet that contradicts them. The money and price-accuracy rules are absolute and are
restated at the bottom.

## What I actually want

My stuff is scattered and my systems do not talk to each other. Artifacts are in the wrong places,
the same thing exists in three forms, and pieces that should feed each other do not. I do not have a
tidy list of what is broken — **finding that list is the first half of your job.**

The second half is fixing the things that actually matter, in parallel, without disappearing into
busywork.

**You choose the work. I am not handing you a task list.** That is deliberate: the last version of
this packet picked the tasks up front and would have spent a whole session in the wrong place.

## The anti-busywork contract — read this twice

You have a documented failure mode: when you cannot tell high-value work from low-value work, you do
whatever is in front of you, exhaustively. It feels productive. It is not. This section is the
brake.

### Work that is BANNED unless it is the direct fix to a ranked finding

Do not do any of this on your own initiative. Not as a warm-up, not while you think, not "since I
was in there anyway":

- Formatting, linting, or style sweeps. Import reordering. Whitespace.
- Renaming things for consistency.
- Refactoring code that works and that nothing in your findings blames.
- Writing new documentation *about* documentation. Meta-docs, indexes of indexes, READMEs about the
  README.
- Chasing a test-coverage number. Adding tests to code you are not changing.
- Building an abstraction that has one caller.
- Fixing typos in comments.
- Reorganising a directory because it looks untidy, absent a concrete cost you can name.
- "Improving" prose in files nobody reads.
- Any migration, framework, scheduler, dashboard, or tool that is not the minimum fix to a ranked
  finding.

If you catch yourself doing one of these, stop mid-action and go back to the ranked list.

### The value gate — every unit of work must pass this

Before you spend effort on anything, answer in one line each:

1. **What breaks today because of this?** Name the concrete failure — a wrong number, a lost hour, a
   thing I cannot find, a system that silently does not run. "It is untidy" and "best practice" are
   not answers; if that is the best you have, the item is a LOG, not a FIX.
2. **What does fixing it cost?** In minutes, honestly.
3. **What happens if I never fix it?** If the answer is "nothing much," log it and move on.

**Anything that fails the gate gets one line in the findings doc and zero minutes of work.** Logging
is a complete and respectable outcome. Most findings should end there.

### Effort caps

- **No single item gets more than 45 minutes** without you stopping to re-justify it against the
  ranked list.
- **If an item triples its estimate, abandon it**, log where you got to and why it was harder than it
  looked, and move to the next item. A blown estimate is information, not a reason to keep digging.
- **Two failed approaches on the same item = stop.** Log both, move on. The third approach is almost
  never the one.

---

## Standing authorization — do all of this without asking

- Create `.venv` and install `requirements-dev.txt` if not present. Already-declared deps only.
- Run the suite freely: `.claude/scripts/poke-pytest -q` (network-mocked, ~10s).
- Read anything on disk you can reach. Search broadly.
- Create and edit files in the repo. Commit freely in the repo's conventional style
  (`feat(poke):`, `fix(poke):`, `docs(poke):`, `test(poke):`, `data(poke):`).
- **Move or reorganise files, provided the move is reversible and recorded** — see the Reorg Rules.
- Merge to **local** `main`. Do **not** `git pull` first: local `main` intentionally diverges from
  `origin/main`.
- Create branches, push them to `origin`.
- **Dispatch subagents aggressively and in parallel.** This is how you get volume. A serial session
  will not finish this packet.

---

## Phase 1 — Recon (parallel, read-only, hard-capped)

**Cap: 45 minutes wall-clock for this entire phase.** Fan out; do not go serial.

Dispatch independent read-only subagents, one per territory, all at once. Each returns a structured
finding list — **not prose, not a summary**. Each finding is one row:

```
FINDING | <territory> | <what is wrong, one sentence> | <concrete cost today>
         | <evidence: file:line or path> | <fix estimate in minutes> | <FIX or LOG>
```

### Territories to sweep

1. **This repo's structure.** Five top-level context docs overlap: `CLAUDE.md`, `DOCTRINE.md`,
   `ADVISOR_ROLE.md`, `NEXT_SESSION.md`, `ROADMAP.md`. Which are stale? Which contradict each other?
   Which contradict the code? An agent reading these gets conflicting instructions — find the actual
   conflicts, with line references, not a general impression.
2. **Documentation sprawl.** `docs/` has four homes: `superpowers/specs/`, `superpowers/plans/`,
   `poke/`, `service-plan/`. Which docs are superseded, duplicated, or describe things that no longer
   exist? Which result docs claim outcomes the code contradicts? Rank by *how likely a future
   session is to act on stale information*.
3. **The ledgers and data surface.** `data/poke/` holds `price_history.jsonl`,
   `paper_decisions.jsonl`, `verified_candidates.jsonl`, `gem_rates.jsonl`, plus `data/products.yaml`
   and `data/poke/assets.yaml`. Do they join? Can you trace one product from catalog → observation →
   decision → outcome? **Where does that chain break?** That is the "systems not talking" complaint
   in its most concrete form — find the actual break.
4. **The code's dead ends.** Find code that cannot fire in production. The spec already names one
   (`candidates.py:231/241` gates the asset route behind an `asset_key` nothing writes, so
   `edge.py:317` never runs outside tests). **Find the others.** Dead paths that look alive are worse
   than missing features, because they make the system look more capable than it is.
5. **Config and secrets surface.** `config.yaml` (gitignored, holds the PPT key) vs
   `config.example.yaml`. Has the example drifted from what the code reads? Is any key, webhook, or
   address committed anywhere in history? Is any config field read by nothing, or read by code but
   absent from the example?
6. **The sibling program.** `NEXT_SESSION.md` says the GUN DEALS program at
   `OneDrive\Desktop\GUN DEALS\` is the proven reference implementation, and that the Pokemon engine
   should lift its spine (discover → research → score → verify → persist → render). **If you can
   reach that directory, read it.** What does it do that this repo reimplemented worse, or has not
   implemented? What is genuinely duplicated? If you cannot reach it, say so in one line and move on
   — do not hunt.
7. **The wider machine, time-boxed to 10 minutes.** Look for artifacts belonging to this project that
   live outside the repo: exports, spreadsheets, screenshots, downloaded CSVs, scratch notes, old
   copies of the repo. You have connectors for Google Drive, Notion, Airtable, and Gmail — check
   whether project data is stranded in one of them, or duplicated between one of them and the repo.
   **Report locations only. Move nothing outside the repo in this phase.**

### Recon rules

- **Read-only. Change nothing in Phase 1.**
- Every finding needs evidence — a path, a `file:line`, a command output. A finding without evidence
  is a guess and gets dropped.
- Cost must be concrete. "Confusing" is not a cost; "a session following this doc will remove
  `limit=1` and burn 50 credits" is.
- Do not fix anything you find, however small and tempting. Note it and keep sweeping. **Fixing
  during recon is the single most common way this phase overruns.**

---

## Phase 2 — Triage (the gate; ~20 minutes, and I read this)

Consolidate every subagent's findings into **one ranked table** and write it to
`docs/poke/recon-2026-08-10.md`. Deduplicate — the same root cause found by three agents is one row.

```markdown
| # | Finding | Cost today | Fix est. | Verdict |
|---|---------|-----------|----------|---------|
| 1 | ...     | ...       | 20m      | FIX     |
```

Then split explicitly:

- **FIX NOW** — passes the value gate, fits the window, and something concrete breaks without it.
  Aim for **5–12 items**, not three and not forty.
- **LOG ONLY** — real but low-impact. One line each. Zero minutes. **This section should be the
  longest one.** If it is not, you are not being honest about what matters.
- **NEEDS MY DECISION** — real, significant, and not yours to call. Anything that deletes data,
  changes doctrine, spends credits, or picks between two defensible architectures.

Then, in one short paragraph: **what is the single biggest thing wrong with my setup?** Your honest
opinion, not a hedge. If the answer is "nothing structural, it is mostly fine," say that — I would
rather hear it than have you manufacture a crisis to justify the session.

**Do not wait for my approval on the FIX NOW list.** Commit the triage doc and start executing.

---

## Phase 3 — Repair (parallel, the bulk of the session)

Work the FIX NOW list. **Fan out subagents across independent items** — this is where volume comes
from. Group items that touch the same files into one agent to avoid conflicts; everything else runs
concurrently. Use worktree isolation if agents would otherwise collide.

Rules:

- **Smallest fix that resolves the finding.** Not the best possible version. Not a general solution.
  The finding is the spec, and the finding's scope is the ceiling.
- **Code changes are TDD** (`poke-tdd`): failing test first, watch it fail for the right reason,
  minimal implementation, watch it pass, full suite before commit.
- **Doc and structure changes need no test**, but must be committed separately from code changes.
- **One commit per finding**, message referencing the triage row. That makes the whole session
  reviewable and any single fix revertible.
- **Suite green at every commit.** If a fix goes red and is not green within its estimate, revert it,
  log it, move on.
- Re-run the suite before you move to the next item. Not at the end. At each item.

### Reorg rules — for anything that moves files

Your instinct will be to tidy. Tidying is banned as an end in itself, but a move that fixes a ranked
finding is legitimate. When you move something:

- Use `git mv` inside the repo so history follows.
- **Update every reference** — grep for the old path across `.md`, `.py`, `.yaml`, `.json` and fix
  each hit. A move that leaves dangling references is worse than no move.
- Write every move to `docs/poke/recon-2026-08-10.md` as a manifest row: `from → to → why`.
- **Never move or delete anything outside this repo.** If something belongs elsewhere on my machine,
  say so in NEEDS MY DECISION. That is my call, not yours.
- **Never delete a file that is not in git.** Untracked means unrecoverable.

### Integration work gets priority

My core complaint is that things do not talk to each other. Within the FIX NOW list, **prefer the
items that connect two things over the items that build a new thing.** A join that lets me trace one
product from catalog through observation to decision to outcome is worth more than any new feature,
because it makes everything already built legible.

---

## Phase 4 — Verify and close (reserve 30 minutes; do not skip)

1. **Full suite**, green, run by you. State the pass count and the baseline you started from. The
   suite was 1109 passed / 1 skipped on 2026-08-10 — re-measure, do not quote me.
2. **`poke-review`** over the whole session's diff, on your most capable model, with the invariants
   from `.claude/poke-invariants.md` handed to it verbatim as its attention lens. Fix Criticals and
   Importants; ledger Minors.
3. **Dangling-reference check.** Grep for every path you moved and confirm zero stale references.
4. **`poke-finish`.** Present the menu, take **option 1 — merge to local `main`**. You have my
   authorization for that today. Push the branch to `origin` too.

---

## Do NOT stop for these

Decide and continue:

- "Should I continue to the next item / phase?" — yes.
- "Here is a progress summary, shall I proceed?" — no summary. Keep going.
- Whether a finding is worth fixing — that is what the value gate is for. Apply it and decide.
- Whether to fan out or go serial — fan out.
- Which model a subagent gets — your call, per `poke-sdd`'s Model Selection table.
- A test failing on first run — that is the RED half of TDD.
- A Minor review finding — ledger it.
- Naming, file placement, or approach *inside* a ranked item's scope — your call.
- Whether your honest opinion in Phase 2 will annoy me — it will not. Say it.

## DO stop for these — hard stops, every one

1. **A number with no source.** Never fabricate, guess, extrapolate, or interpolate a price, rate,
   fee, or cost. STOP-class.
2. **Removing `limit=1`** from a by-id PPT lookup, or any billable path reporting `0`. The API bills
   on requested `limit`, not results returned. Money-class.
3. **Any live PPT or network call that spends credits.** 100/day free tier, and the budget is
   provably not what it looks like — `docs/poke/ppt-id-seeding.md` records 85 credits consumed before
   a session's first call, never diagnosed. State estimated spend and wait.
4. **Flipping a PIN-FIRST value** off its fail-safe default without a live source pinned and cited
   with a capture date. Unverified errs toward higher fees / lower net / higher cost.
5. **Anything that executes rather than advises** — auto-buy, cart, checkout, auto-listing, login
   automation.
6. **Deleting anything**, or moving anything outside this repo.
7. **A new runtime dependency.** `requirements-dev.txt` is the ceiling.
8. **Rewriting doctrine.** `DOCTRINE.md` and `CLAUDE.md`'s guardrails are mine. You may report that
   they contradict something; you may not resolve it yourself.
9. **A finding that turns out to need a spec** — if a fix is really a feature, stop and put it in
   NEEDS MY DECISION. Do not brainstorm it, do not build it.

## Guardrails you must not "fix"

Deliberate contradictions. Re-read the spec that established each before touching it:

- **The D-vs-E split.** Comp-alone-never-promotes-off-WATCH is hardcoded in the D layer
  (`discovery/opportunities.py`). Verified entries reach live **only** through E (`poke_api/edge.py`).
  Extending E is fine; touching the D functions is not.
- **TCGCSV is not independent of PPT.** TCGplayer lineage; it is a free *reference*, classified
  external / non-independent, and is **never** `cross_source_validated`.
- **`PAPER_BUY < LIVE` ceiling.** `LIVE_PACKET_ELIGIBLE` stays strictly stricter than `PAPER_BUY`.
- **Three ledgers never conflate.** Observation vs paper decisions vs inventory/P&L. Making them
  *joinable* is the goal; merging them is not.
- **The two `_shipping_for` copies** (`main.py:347`, `discovery/opportunities.py:115`) are identical
  by contract. Change one, change both.

---

## The report

Lead with the answer. In this order:

1. **The single biggest thing wrong with my setup**, and whether you fixed it.
2. **The triage table** — how many findings, how many fixed, how many logged, how many need me.
3. **What you fixed** — one line each, with the commit.
4. **What you deliberately did not fix**, and why. I want to see the judgment, not just the output.
5. **Anything needing my decision**, with enough context to answer without scrolling back.
6. **Test delta** — baseline → final, confirmed you ran it. Never report a green you did not observe.
7. **Credit spend: 0.** Confirm no live PPT call. If one happened, that is the *first* line, not the
   sixth.
8. **The move manifest** — every file that moved, and confirmation that references were updated.
9. **Where the next session should start.**

## First message

Do not ask me what to work on — choosing is your job in this packet. Note the wall-clock time, verify
the venv, run the suite for a baseline, and dispatch the Phase 1 recon fan-out immediately. Your
first message to me should be one paragraph: the baseline, the territories you dispatched, and your
time budget. Then keep going without waiting.
