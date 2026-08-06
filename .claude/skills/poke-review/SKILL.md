---
name: poke-review
description: Use after completing a task or feature and before merging in this repo - dispatches a code reviewer subagent with the STOP-class price-accuracy, money-class credit, and doctrine rubric. Forked from superpowers:requesting-code-review.
---

# Poke Review — request a code review

Forked from `superpowers:requesting-code-review` (v6.2.0, MIT). Read
`.claude/poke-invariants.md` first.

Dispatch a reviewer subagent with precisely crafted context — never your session's history. The
diff and the evaluation live in the reviewer's context; only the findings come back to you.

**Core principle:** review early, review often.

## When to request

**Mandatory:**
- After each task in `poke-sdd`
- Before merging to local `main`
- **Any change touching money arithmetic** (fees, margin, EV, grading cost, cost basis)
- **Any change touching provenance** (source URLs, capture dates, confidence tiers, badging)
- **Any change touching PPT call sites** (`scanner/market.py`, `poke_api/sources.py`, routers)

**Optional but valuable:** when stuck, before a refactor, after fixing a complex bug.

## How to request

**1. Get the range.**

```bash
BASE_SHA=$(git rev-parse HEAD~1)   # or the recorded task base, or `git merge-base main HEAD`
HEAD_SHA=$(git rev-parse HEAD)
```

For a multi-commit task use the **recorded base**, never `HEAD~1` — it silently drops every
commit but the last.

**2. Hand the diff over as a file**, so it never enters your context:

```bash
.claude/skills/poke-sdd/scripts/review-package <plan-file> "$BASE_SHA" "$HEAD_SHA"
```

Without a plan file, redirect `git log --oneline`, `git diff --stat`, and `git diff -U10` for the
range into one uniquely named file.

**3. Dispatch a `general-purpose` subagent** using the template at
[code-reviewer.md](code-reviewer.md). Fill in:

- `[DESCRIPTION]` — what you built
- `[PLAN_OR_REQUIREMENTS]` — the plan/task path or the requirements
- `[GLOBAL_CONSTRAINTS]` — **copied verbatim** from the plan's Global Constraints section. This is
  the reviewer's attention lens: exact values, exact formats, stated relationships. Without it the
  reviewer cannot catch a STOP-class violation, because nothing in a diff announces itself as one.
- `[BASE_SHA]`, `[HEAD_SHA]`, `[DIFF_FILE]`

**Do not pre-judge findings.** Never instruct a reviewer to ignore an issue, or write "do not
flag", "don't treat X as a defect", "at most Minor", or "the plan chose". If you think a finding
would be a false positive, let it be raised and adjudicate it. Pre-judging to spare yourself a
review loop is how a real defect gets waved through.

**Do not ask the reviewer to re-run tests the implementer already ran** on the same code — the
implementer's report is the test evidence.

## Acting on feedback

- **Critical** — fix immediately.
- **Important** — fix before proceeding.
- **Minor** — record in the ledger and point the final review at that list. A roll-up nobody
  reads is a silent discard.
- **Push back if the reviewer is wrong** — with technical reasoning and the code or test that
  proves it. Never argue with valid feedback.

**Findings in these classes are never Minor, regardless of how the reviewer graded them:**

- a number with no source
- an estimate presented as a comp
- `limit=1` removed or a billable path reporting `0`
- a fuzzy/guessed identity resolution
- a PIN-FIRST value flipped on without a live citation
- anything that executes a transaction rather than advising

Re-grade them up and fix them.

## Red flags

**Never:** skip review because "it's simple"; ignore Critical issues; proceed with unfixed
Important issues; review the diff inline yourself instead of dispatching (it burns the context
you need to keep driving the work).
