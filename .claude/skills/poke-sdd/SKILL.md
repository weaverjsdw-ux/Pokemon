---
name: poke-sdd
description: Use to execute an implementation plan from docs/superpowers/plans/ by dispatching a fresh subagent per task with a two-stage review between tasks - the recommended executor for this repo. Forked from superpowers:subagent-driven-development with the STOP-class/money-class review rubric and this repo's ledger, test command, and commit style.
---

# Poke SDD — subagent-driven execution

Forked from `superpowers:subagent-driven-development` (v6.2.0, MIT). Read
`.claude/poke-invariants.md` first.

Execute a plan by dispatching a fresh implementer subagent per task, a task review (spec
compliance + code quality) after each, and a broad whole-branch review at the end.

**Core principle:** fresh subagent per task + task review + broad final review = high quality,
fast iteration.

**Why subagents:** you construct exactly the context each agent needs — they never inherit your
session's history. That keeps them focused and preserves your context for coordination.

**Narration:** between tool calls, narrate at most one short line. The ledger and the tool results
carry the record.

**Continuous execution:** do not pause to check in between tasks. The only reasons to stop are a
BLOCKED status you cannot resolve, ambiguity that genuinely prevents progress, one of the hard
stops below, or all tasks complete.

## Hard stops — surface to the operator, never decide yourself

- A task would require **fabricating a number**, or shipping a value with no source.
- A task would **remove `limit=1`** from a by-id PPT lookup, or leave a billable path reporting `0`.
- A task would **flip a PIN-FIRST value** to its real value without a live pinned + cited source.
- A task would make the tool **execute a transaction** (auto-buy, cart, checkout, auto-list).
- A task requires **installing a dependency**.
- A task requires a **live network / PPT run** (it spends credits) — get go-ahead, with the
  estimated spend stated, before dispatching.
- A task requires **pushing to a remote**.
- The **test suite cannot run** in this environment.

## Setup

**Branch.** Never start implementation on `main` without the operator's explicit consent. Create
or confirm a feature branch named for the work.

**Ledger.** Conversation memory does not survive compaction. Controllers that lost their place
have re-dispatched entire completed task sequences — the single most expensive failure observed.
Track progress in a file, not only in todos.

- At skill start, run `.claude/skills/poke-sdd/scripts/sdd-workspace PLAN_FILE` — it prints this
  plan's git-ignored directory (`<repo-root>/.superpowers/sdd/<plan-basename>/`), home to every
  artifact for THIS plan: ledger, briefs, reports, review packages. Another plan's directory is
  never yours to read or write.
- Check for this plan's ledger at `<workspace>/progress.md`. If its first line names your plan
  file, tasks with a `Task <N>: complete` line are DONE — do not re-dispatch them; resume at the
  first task without one. A task whose last line is a fix round is mid-loop: resume at the next
  round. A ledger naming a different plan — or a stray one at the old flat path
  `.superpowers/sdd/progress.md` — belongs to another plan: leave it and start your own.
- Create the ledger with its identity as the first line:
  `# SDD ledger — plan: <plan file path>`.
- After compaction, trust the ledger and `git log` over your own recollection.
- `git clean -fdx` destroys the workspace — never run it here.

**Baseline.** Run `.claude/scripts/poke-pytest -q` and compare to the plan's stated baseline. A
mismatch means the tree is not where the plan assumed — surface it before dispatching Task 1. If
the suite cannot run (exit 3), stop: you cannot verify any task's work.

**Read the plan once**, note its context and **Global Constraints**, and create a todo per task.

**Pre-flight scan.** Before dispatching Task 1, read the plan once for:

- tasks that contradict each other or the Global Constraints
- anything the plan mandates that the review rubric treats as a defect (a test asserting nothing,
  verbatim duplication of a logic block)
- **worked examples whose arithmetic does not reconcile** — recompute every one by hand
- **bare numbers with no source**, and **PIN-FIRST values the plan flips on without a citation**

Present everything you find as **one batched question** — each finding beside the plan text that
mandates it, asking which governs — before execution begins, not one interrupt per discovery. If
the scan is clean, proceed without comment.

## Model selection

Use the least powerful model that can do each job, and **always specify the model explicitly** —
an omitted model inherits your session's, usually the most expensive.

| Role | Model |
| --- | --- |
| Implementer, task text contains the complete code (transcription + testing) | cheapest tier |
| Implementer, 1-2 files with a complete spec | cheap |
| Implementer, multi-file integration or judgment | standard |
| Implementer, design judgment or broad codebase understanding | most capable |
| Task reviewer | scaled to the diff's size, complexity, and risk; mid-tier floor |
| Scoped re-review of a small fix diff | cheap-to-mid |
| Fix-loop rounds 4-5 | at least one tier above the implementer that got stuck |
| **Final whole-branch review** | **most capable available** |

**Turn count beats token price.** The cheapest models routinely take 2-3× the turns on multi-step
work — costing more overall. Mid-tier is the floor for reviewers and for implementers working
from prose rather than complete code.

**One exception to "cheapest that fits": any task touching money arithmetic, provenance, or PPT
call sites takes a standard model minimum, and its reviewer takes mid-tier minimum.** A cheap
model that quietly drops a `source_url` costs more than the tokens it saved.

## The task loop

Everything you paste into a dispatch prompt — and everything a subagent prints back — stays
resident in your context for the rest of the session. **Hand artifacts over as files.**

### 1. Dispatch the implementer

Record BASE (`git rev-parse HEAD`) before dispatching — the review package and fix-round diffs
need it.

- **Task brief:** run `.claude/skills/poke-sdd/scripts/task-brief PLAN_FILE N` — it extracts the
  task's full text to a uniquely named file and prints the path. Your dispatch contains: (1) one
  line on where this task fits; (2) the brief path, introduced as "read this first — it is your
  requirements, with the exact values to use verbatim"; (3) interfaces and decisions from earlier
  tasks the brief cannot know; (4) your resolution of any ambiguity you noticed in the brief;
  (5) the report-file path and report contract. Exact values appear **only** in the brief. Never
  make a subagent read the whole plan file.
- **Report file:** name it after the brief (`task-N-brief.md` → `task-N-report.md`) and put the
  path in the dispatch.
- A dispatch describes **one task**, not the session's history. Never paste accumulated prior-task
  summaries into later dispatches.
- If an earlier task parked a finding in the area this task touches, carry a pointer to that
  ledger entry.
- Record the implementer's agent identity — fix rounds 1-3 resume it.
- **Never dispatch implementation subagents in parallel** (conflicts).

Template: [implementer-prompt.md](implementer-prompt.md)

### 2. Handle the report

**DONE:** generate the review package
(`.claude/skills/poke-sdd/scripts/review-package PLAN_FILE BASE HEAD` — it prints the path it
wrote; BASE is the commit you recorded, **never `HEAD~1`**, which silently drops all but the last
commit of a multi-commit task), then dispatch the task reviewer with that path.

**DONE_WITH_CONCERNS:** read the concerns first. Correctness or scope concerns get addressed
before review; observations get noted and proceed.

**NEEDS_CONTEXT:** provide the missing context and re-dispatch.

**BLOCKED:** assess. Context problem → more context, same model. Needs more reasoning →
more capable model. Too large → break it up. Plan is wrong → escalate to the operator. **Never**
force the same model to retry without changing something.

If the implementer asks questions — before starting or mid-task — answer clearly and completely.
Don't rush it into implementation.

### 3. Review the task

Never skip the task review, and never accept a report missing either verdict — spec compliance
AND task quality are both required. Implementer self-review never replaces it.

- Hand the reviewer its diff as a **file** (the review package). The output never enters your
  context. Never dispatch a task reviewer without a diff file.
- **Reviewer inputs:** the brief file, the report file, the review package — plus the
  **Global Constraints copied verbatim** from the plan. That constraints block is the reviewer's
  attention lens; without it, a STOP-class violation is invisible, because nothing in a diff
  announces itself as one.
- Do not add open-ended directives ("check all uses") without a concrete, task-specific reason.
- Do not ask a reviewer to re-run tests the implementer already ran on the same code.
- **Do not pre-judge findings.** Never write "do not flag", "don't treat X as a defect", "at most
  Minor", or "the plan chose". If you think a finding would be a false positive, let it be raised
  and adjudicate it in the loop.

A ⚠️ "cannot verify from diff" item does not block the review, but you must resolve each one
yourself before marking the task complete — you hold the cross-task context the reviewer lacks. A
confirmed gap is a failed spec review and enters the fix loop.

Template: [task-reviewer-prompt.md](task-reviewer-prompt.md)

### 4. The fix loop

Triggers on spec ❌, any Critical or Important finding, or a ⚠️ item you confirmed as a real gap.

Two routes leave the loop immediately:

- **Minor findings** go to the ledger as you go
  (`Task <N>: minor (deferred): <one-liner>`), and the final review is pointed at that list. They
  never enter the loop. A roll-up nobody reads is a silent discard.
- **Plan-mandated findings** — anything conflicting with what the plan's text requires — are the
  operator's decision: present the finding and the plan text, ask which governs. Do not dismiss
  the finding because the plan mandates it, and do not dispatch a fix that contradicts the plan
  without asking.

Everything else enters the loop. A round is one fix dispatch plus one scoped re-review. **Five
rounds maximum per task.**

**Rounds 1-3 — resume the original implementer.** Send it the open findings verbatim; its context
is intact. If your harness cannot message a live subagent, dispatch a fresh one carrying the brief
path, the report-file path, and the findings — the report file is the persistent memory either way.

**Rounds 4-5 — fresh implementer on a more capable model**, with the brief path, report-file path,
open findings, and this framing: "A prior implementer attempted this task [N] times; you own it
now. Read the report file for what was tried."

**Every round:** the implementer fixes, re-runs the tests covering the amended code, appends its
fix report to the same report file, and returns the short contract. Before re-dispatching the
reviewer, confirm the fix report contains the covering tests, the command run, and the output.
Name the covering test files in the fix message — a one-line fix does not need the whole suite.

**The re-review is scoped.** Run `review-package PLAN_FILE FIX_BASE HEAD` (FIX_BASE = the head the
previous review saw) and dispatch [re-review-prompt.md](re-review-prompt.md) with the findings
list, brief, report file, and diff path. New Critical/Important breakage in the fix diff joins the
open findings. Out-of-scope observations go to the ledger as deferred minors — they never extend
the loop.

**After each round,** append:
`Task <N>: fix round <R>/5 (<X> addressed, <Y> open — <one-liners>; commits <a7>..<b7>)`

**Never fix findings yourself in the controller session** — controller fixes pollute your context
and skip review.

**The breaker.** When round 5's re-review still leaves findings open, stop dispatching and
adjudicate each one yourself:

- **Reviewer is wrong, or contestable:** park it —
  `Task <N>: parked — <finding> — ruling: <why the code stands>`.
- **Real, but nothing downstream builds on it:** park it with a ruling saying it's real and deferred.
- **Real and load-bearing** — a later task builds on it, or it reveals a plan defect: **STOP.**
  Append `Task <N>: BLOCKED — <reason>` and report to the operator with the finding, the plan text
  it collides with, and the fix history.
- **A Part 0 domain-gate finding is never parked.** A fabricated number, a removed `limit=1`, a
  leaked sentinel, a flipped PIN-FIRST value, or an executing (rather than advising) code path is
  load-bearing by definition — it goes to the operator, always.

Adjudicate only at the cap. Every adjudication is a ledger entry; silent discards are forbidden.

### 5. Complete the task

When the review is clean — or every open finding is parked with a ruling at the cap — append:

- `Task <N>: complete (commits <base7>..<head7>, review clean)`
- `Task <N>: complete (commits <base7>..<head7>, <K> parked)` after a tripped breaker

Mark the todo complete and move on. Never move to the next task while Critical/Important issues
are neither fixed nor parked-with-ruling at the cap.

## Final review

Run `review-package PLAN_FILE MERGE_BASE HEAD` (MERGE_BASE = `git merge-base main HEAD`) and
dispatch [../poke-review/code-reviewer.md](../poke-review/code-reviewer.md) on the **most capable
available model**. Point it at the ledger's deferred-minor and parked lines so it can triage which
must be fixed before merge, and hand it the plan's Global Constraints verbatim.

If it returns findings, dispatch **ONE** fix subagent with the complete findings list — not one
fixer per finding (per-finding fixers each rebuild context and re-run suites; a real session's
final-review fix wave cost more than all its tasks combined). Then run exactly one scoped
re-review of the fix wave. Adjudicate residuals as in the task breaker. There is no second fix
wave — residual load-bearing findings surface to the operator at `poke-finish`.

## Finish

When the final review is clean and its fixes are merged, delete this plan's workspace
(`rm -rf <workspace>`) — git history is the record now. Sibling directories belong to other plans.

Then use `poke-finish`.

## Common rationalizations

| Excuse | Reality |
| --- | --- |
| "Close enough on spec compliance" | Reviewer found spec gaps = not done. Fix, or hit the cap and adjudicate. |
| "I'll fix it myself, dispatching is overhead" | Controller fixes pollute your context and skip review. Resume the implementer. |
| "One more round will converge" | Past the cap, rounds don't converge — the failure is structural. |
| "This finding is obviously wrong, I'll drop it" | You adjudicate only at the cap, and every ruling is a ledger entry. |
| "The fix was small, skip the re-review" | Unreviewed fixes are how regressions land. |
| "Ledger bookkeeping is overhead" | The ledger is what survives compaction. |
| "The missing source_url is a Minor" | It is STOP-class. There is no Minor tier for fabricated data. |
| "The plan says to remove `limit=1`, so it's fine" | Plan-mandated money-class defects go to the operator, never through. |
| "A live run would settle this question" | Live runs spend credits. State the estimated spend and get go-ahead. |
| "I'll park the sentinel leak and note it" | Part 0 findings are never parked. Escalate. |
