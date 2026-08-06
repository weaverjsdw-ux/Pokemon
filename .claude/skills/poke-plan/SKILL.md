---
name: poke-plan
description: Use when a design spec exists under docs/superpowers/specs/ and implementation is next - writes a TDD, task-by-task implementation plan to docs/superpowers/plans/. Forked from superpowers:writing-plans with this repo's Global Constraints block, commit style, and PIN-FIRST gates prewired.
---

# Poke Plan — spec → executable implementation plan

Forked from `superpowers:writing-plans` (v6.2.0, MIT). Read `.claude/poke-invariants.md` first.

**Announce at start:** "Using poke-plan to write the implementation plan."

Write the plan assuming the implementer is a skilled developer who knows **nothing** about this
codebase, this domain, or good test design — and who will be a fresh subagent that sees only its
own task. Document every file path, every exact value, every command. DRY. YAGNI. TDD.
Frequent commits.

**Save to:** `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md`

## Before writing

1. Read the spec end to end.
2. Read the code the plan will touch — exact line numbers go in the plan.
3. **Record the test baseline.** Run the suite (`.claude/scripts/poke-pytest -q`) and note the
   pass count; the plan states it so every task boundary has something to compare against. If the
   suite cannot run in this environment, say so in the plan instead of inventing a number.
4. **Scope check.** If the spec covers multiple independent subsystems, split into one plan per
   subsystem. Each plan produces working, testable software on its own.

## File Structure

Before defining tasks, map every file created or modified and what each is responsible for, with
exact paths and line ranges. In this codebase: follow established patterns, keep the write set
narrow, and split by responsibility rather than technical layer. Note the twin files that must
change together (`_shipping_for` in `main.py` and `discovery/opportunities.py`).

## Task right-sizing

A task is the smallest unit that carries its own test cycle and is worth a fresh reviewer's gate.
Fold setup, config, and docs into the task whose deliverable needs them. Split only where a
reviewer could meaningfully reject one task while approving its neighbor. Each task ends with an
independently testable deliverable and a green suite.

**Each step is one action (2-5 minutes):** write the failing test → run it and watch it fail →
implement minimally → run it and watch it pass → commit.

## Plan header

Every plan starts with this, filled in:

````markdown
# [Feature Name] Implementation Plan (spec §…)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `poke-sdd` (recommended) or `poke-execute` to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [One sentence — what this builds and why it matters to the money decision]

**Architecture:** [2-3 sentences. Say explicitly whether this extends or rewrites existing code.]

**Tech Stack:** Python 3, `pytest` (network-mocked). [State "No new runtime dependency" when true —
if the plan needs one, that is an operator decision, not a plan decision.]

## Global Constraints

- **Package is `scanner/`** (never `target_scanner/`); price subsystem `scanner/poke_api/`;
  discovery subsystem `scanner/discovery/`.
- **Price/fee accuracy is STOP-class.** Every price/fee/rate carries a `source_url` +
  `effective_date` (or capture date). A number is never fabricated, guessed, or extrapolated.
  No source → cite the operator assumption explicitly and badge it.
- **Exact identity only.** Resolve by exact `tcgPlayerId` / exact id. A miss is honest data,
  never a fuzzy match.
- **Money-class.** `limit=1` mandatory on by-id PPT lookups (`market.py`), never removed. Every
  billable path reports a bounded `apiCallsConsumed` or refuses first; read / `refresh=false` /
  no-client / unmapped report `0`, `source:"local"`. Free tier 100 credits/day; live PPT runs
  need operator go-ahead.
- **Tool advises, human transacts.** No auto-buy / cart / checkout / login automation.
- **PIN-FIRST gates:** [list each unpinned value, its fail-safe default, and the live source that
  must be pinned + cited before the real value switches on. Omit the bullet if there are none.]
- **Extend, don't rebuild.** [Name the existing call contracts that must keep working.]
- **TDD, full suite green** at each task boundary: `.claude/scripts/poke-pytest -q`
  (network-mocked). Baseline at plan start: **N passed**.
- **Never pushed.** Work on a feature branch; merge to LOCAL main via `poke-finish`. No remote
  push without explicit operator instruction. `config.yaml` unchanged.
- [Any load-bearing structure this plan must not "reconcile" — see `.claude/poke-invariants.md` §10.]

## Design decisions (flag at sign-off if any should change)

1. …

## File Structure

- **Modify** `path.py:12-40` — …
- **Create** `path.py` — …
- **Tests:** …

---
````

The Global Constraints block is not boilerplate to copy blindly — delete bullets that do not bind
this plan, and add the ones the spec introduces, **with exact values copied verbatim from the
spec**. Every task's requirements implicitly include this section, and it is what gets handed to
each task reviewer as its attention lens.

## Task structure

````markdown
### Task N: [Component Name]

[One paragraph: what this task delivers and why it is a unit.]

**Files:**
- Create: `exact/path.py`
- Modify: `exact/path.py:123-145`
- Test: `tests/test_exact.py`

**Interfaces:**
- Consumes: [exact signatures from earlier tasks]
- Produces: [exact function names, parameter and return types later tasks rely on. The
  implementer sees only this task — this block is how they learn neighboring names.]

> **PIN-FIRST — HARD GATE (STOP-class):** [only when the task carries an unpinned value. State
> the fail-safe default it ships with, the live page that must be pinned, exactly what to extract,
> the capture date requirement, and what the wrong value would cost in dollars.]

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    # worked example with real arithmetic in a comment, so the expected value is checkable
    ...
```

- [ ] **Step 2: Run to verify it fails**

Run: `.claude/scripts/poke-pytest tests/test_exact.py -q -k "specific_behavior"`
Expected: FAIL with [the exact expected failure]

- [ ] **Step 3: Implement**

[Actual code. Name the lines to read first.]

- [ ] **Step 4: Run to verify it passes**

Run: `.claude/scripts/poke-pytest tests/test_exact.py -q`
Expected: PASS (existing tests still green)

- [ ] **Step 5: Commit**

```bash
git add scanner/path.py tests/test_exact.py
git commit -m "feat(poke): <what changed>"
```
````

**Worked examples are mandatory for any money arithmetic.** A fee/margin/EV test asserts a
specific number, and the plan shows the arithmetic that produces it in a comment. A worked example
that does not reconcile is a plan bug that ships as a code bug — it has happened in this repo.

## No placeholders

These are plan failures — never write them:
- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "handle edge cases"
- "Write tests for the above" without the actual test code
- "Similar to Task N" — repeat the code; tasks are read out of order
- A bare number with no source or `operator_assumption` badge
- References to types, functions, or methods not defined in any task

## Self-review

Run this checklist yourself after writing the plan. Fix inline; no subagent dispatch.

1. **Spec coverage** — point to a task for each spec requirement. List gaps; add tasks for them.
2. **Placeholder scan** — every pattern above.
3. **Type consistency** — do names and signatures used in later tasks match what earlier tasks
   defined? (`clearLayers()` in Task 3 vs `clearFullLayers()` in Task 7 is a bug.)
4. **Provenance** — every constant the plan introduces has a source URL + date, or an explicit
   badged assumption.
5. **Credit accounting** — every PPT-touching task states its bounded spend.
6. **PIN-FIRST** — every unpinned value ships fail-safe, and its gate names the live source.
7. **Arithmetic** — recompute every worked example by hand. Do they reconcile?
8. **Commit messages** — conventional style, scope matches the touched subsystem.

## Execution handoff

After saving and committing the plan:

> **"Plan complete and saved to `docs/superpowers/plans/<filename>.md`. Two execution options:**
>
> **1. Subagent-driven (recommended)** — `poke-sdd`: fresh subagent per task, two-stage review
> between tasks, fast iteration.
>
> **2. Inline execution** — `poke-execute`: tasks run in this session with checkpoints.
>
> **Which approach?"**
