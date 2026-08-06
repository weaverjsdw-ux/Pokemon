---
name: poke-execute
description: Use to execute a written implementation plan from docs/superpowers/plans/ inline in this session with review checkpoints, when subagents are unavailable or the tasks are tightly coupled. Forked from superpowers:executing-plans with this repo's test command, commit style, and STOP-class gates.
---

# Poke Execute — run a plan inline

Forked from `superpowers:executing-plans` (v6.2.0, MIT). Read `.claude/poke-invariants.md` first.

**Announce at start:** "Using poke-execute to implement this plan."

**Prefer `poke-sdd` when subagents are available** — a fresh subagent per task keeps the
controller's context clean and adds a real review gate. Use this skill when subagents are
unavailable, or when the plan's tasks are tightly coupled enough that fresh-context handoffs
would cost more than they save.

## Step 1: Load and review the plan

1. **Branch check.** Never start implementation on `main` without the operator's explicit
   consent. Create or confirm a feature branch named for the work.
2. Read the plan file once. Note its **Global Constraints** — they bind every task.
3. **Verify the test baseline.** Run `.claude/scripts/poke-pytest -q` and compare to the plan's
   stated baseline. A mismatch means the tree is not where the plan assumed — surface it before
   starting. If the suite cannot run at all in this environment, **stop and tell the operator**;
   do not proceed to write code you cannot verify, and do not install dependencies to unblock
   yourself.
4. **Pre-flight conflict scan.** Read the plan once for:
   - tasks that contradict each other or the Global Constraints
   - anything the plan mandates that the review rubric treats as a defect (a test that asserts
     nothing, verbatim duplication of a logic block)
   - **any worked example whose arithmetic does not reconcile** — recompute them
   - **any bare number with no source** — a STOP-class defect in the plan itself
   - **any PIN-FIRST value the plan flips on without a live citation**

   Present everything you find as **one batched question**, each finding beside the plan text that
   mandates it, asking which governs — before execution begins, not one interrupt per discovery.
   If the scan is clean, proceed without comment.
5. Create a todo per task.

## Step 2: Execute tasks

For each task:

1. Mark in_progress.
2. **Read before editing.** Keep the write set narrow — only the files the task names.
3. Follow each step exactly. The plan's steps are bite-sized on purpose.
4. **Run the verification the step specifies.** Watch the test fail before implementing it
   (`poke-tdd`); watch it pass after.
5. Run the focused test while iterating; run the full suite once before committing.
6. Commit in the repo's conventional style — `feat(poke):`, `fix(poke):`, `docs(poke):`,
   `data(poke):`, `test(poke):`, scope matching the touched subsystem.
7. Update the SDD ledger if the work is tracked (`.superpowers/sdd/<plan-basename>/progress.md`).
8. Mark completed.

**Per-task gates — check before marking a task complete:**

- Every number the task introduced carries a source URL + date, or a badged
  `operator_assumption`. No bare numbers.
- Every PPT-touching path reports bounded credits or refuses first; `limit=1` intact.
- Every unpinned value still ships in its fail-safe state.
- Nothing added executes a transaction — the tool advises.
- The suite is green, and you ran it. If it did not run, say so.

## Step 3: Complete

After all tasks are done and verified:

- Announce: "Using poke-finish to complete this work."
- **REQUIRED SUB-SKILL:** `poke-finish`.

Consider `poke-review` on the whole branch first if the change touched money arithmetic,
provenance, or credit accounting — those are the classes of bug this repo cannot absorb.

## Stop and ask when

- A blocker appears: missing dependency, unclear instruction, repeated verification failure.
- The plan has a gap that prevents starting a task.
- A step would require fabricating a number, removing `limit=1`, flipping a PIN-FIRST value
  without a citation, installing a dependency, or pushing to a remote. **These are hard stops,
  not judgment calls** — surface them and wait.
- The test suite cannot run.

**Ask rather than guess.** Don't force through blockers.

## Return to Step 1 when

- The operator updates the plan based on your feedback.
- The fundamental approach needs rethinking.

## Remember

- Review the plan critically first; the pre-flight scan is not optional.
- Follow steps exactly; don't skip verifications.
- Report failing tests **with their output**. Never smooth over a failure.
- Never claim a green suite you did not run.
- Never push to a remote without explicit operator instruction.
