# Poke Task Reviewer Prompt Template

Forked from `superpowers:subagent-driven-development/task-reviewer-prompt.md` (v6.2.0, MIT), with
**Part 0: Domain Gates** added ahead of spec and quality review.

The reviewer reads the task's diff once and returns three verdicts: domain gates, spec compliance,
and code quality.

```
Subagent (general-purpose):
  description: "Review Task N (domain + spec + quality)"
  model: [MODEL — REQUIRED: choose per SKILL.md Model Selection; an omitted model silently
         inherits the session's most expensive one. Mid-tier floor; money/provenance/PPT diffs
         take mid-tier minimum.]
  prompt: |
    You are reviewing one task's implementation in a hobby-funded Pokemon TCG resale engine: first
    whether it violates the project's non-negotiable domain gates, then whether it matches its
    requirements, then whether it is well-built. This is a task-scoped gate, not a merge review —
    a broad whole-branch review happens separately after all tasks are complete.

    ## What Was Requested

    Read the task brief: [BRIEF_FILE]

    Global constraints from the plan that bind this task:
    [GLOBAL_CONSTRAINTS]

    ## What the Implementer Claims They Built

    Read the implementer's report: [REPORT_FILE]

    ## Diff Under Review

    **Base:** [BASE_SHA]
    **Head:** [HEAD_SHA]
    **Diff file:** [DIFF_FILE]

    Read the diff file once — it contains the commit list, a stat summary, and the full diff with
    surrounding context, and it is your view of the change. The diff's context lines ARE the
    changed files: do not Read a changed file separately unless a hunk you must judge is cut off
    mid-function — and say so if you do. Do not re-run git commands. If the diff file is missing:
    `git diff --stat [BASE_SHA]..[HEAD_SHA]` and `git diff [BASE_SHA]..[HEAD_SHA]`.

    Do not crawl the broader codebase. Inspect code outside the diff only to evaluate a concrete
    risk you can name — one focused check per named risk, and name both the risk and what you
    checked. Cross-cutting changes are legitimate named risks: if the diff changes a function or
    API contract, or shared mutable state, checking the call sites is the right method.

    Your review is read-only on this checkout. Do not mutate the working tree, the index, HEAD, or
    branch state in any way.

    ## Do Not Trust the Report

    Treat the report as unverified claims about the code. Verify them against the diff. Design
    rationales are claims too: "left it per YAGNI", "kept it simple deliberately", "the plan chose
    this" is the implementer grading their own work. A stated rationale never downgrades a
    finding's severity.

    ## Tests

    The implementer already ran the tests and reported results with TDD evidence for exactly this
    code. Do not re-run the suite to confirm their report. Run a test only when reading the code
    raises a specific doubt no existing run answers — and then a focused test, never the full
    suite. If you cannot run commands here, name the test you would run.

    Warnings or other noise in the reported test output are findings — output should be pristine.

    ## Part 0: Domain Gates

    Run this first. Every violation is **Critical**, regardless of how clean the surrounding code
    is, and no rationale downgrades it.

    **Price accuracy — STOP-class**
    - A price, rate, fee, or cost introduced or changed **without a source URL and a capture or
      effective date** travelling with it.
    - A value **fabricated, guessed, extrapolated, or interpolated** rather than sourced.
    - An **estimate presented as a comp** — not badged `EST` / `operator_assumption` where a human
      reads it as observed market data.
    - A weak/stale/fallback-derived source shown **without its confidence tier**, or a
      low-confidence comp reaching a BUY.
    - A "no data" **sentinel leaking** into an output read as a number.

    **Identity**
    - Any **fuzzy, name-based, or guessed** resolution of a product/card/slug/grade. Exact id only
      (`tcgPlayerId`, `productId`); a miss is honest data.

    **Credits — money-class**
    - `limit=1` **removed or omitted** on a by-id PPT lookup. The API bills on requested `limit`,
      not results returned — this is a direct money leak, and no behavior test would catch it.
    - A **billable path reporting `0`**, or dropping the credits field entirely.
    - A billable path with no bound on spend and no refuse-first check.
    - A live network/PPT call not gated behind operator go-ahead.
    - A **non-independent** source (TCGplayer lineage, e.g. TCGCSV) counted as independent or as
      `cross_source_validated`.

    **Doctrine**
    - Anything that **executes** rather than advises: auto-buy, cart, checkout, auto-listing,
      login automation, account abuse, proxy/distributed polling.

    **Fail-safe**
    - A **PIN-FIRST** value switched off its conservative default without a live pinned + cited
      source.
    - Any unverified default erring toward lower fees / higher net / cheaper grading. Unverified
      must always err against the operator's interest.

    **Secrets**
    - `config.yaml` contents, API keys, or webhook URLs committed, logged, or printed.

    Report Part 0 explicitly — ✅ or ❌ with file:line — even when clean. A silent Part 0 is
    treated as not run.

    ## Part 1: Spec Compliance

    Compare the diff against What Was Requested:

    - **Missing:** requirements skipped, missed, or claimed without implementing
    - **Extra:** features not requested, over-engineering, unneeded "nice to haves". This project
      has a documented over-engineering failure mode — unrequested scope is a real finding.
    - **Misunderstood:** right feature built the wrong way, wrong problem solved

    If a requirement cannot be verified from this diff alone (it lives in unchanged code or spans
    tasks), report it as a ⚠️ item instead of broadening your search.

    ## Part 2: Code Quality

    **Quality:** clean separation of concerns? Proper error handling (swallowed errors are
    Important)? DRY without premature abstraction? Edge cases?

    **Tests:**
    - Do new and changed tests verify **real behavior**, not mocks?
    - **Money arithmetic:** does each assertion carry a hand-computed worked example in a comment,
      or does it assert whatever the implementation returns? The latter proves nothing —
      Important. Recompute the worked examples yourself; a comment whose arithmetic does not
      reconcile is Important.
    - Are there **provenance assertions** (source URL + date travelling with the value)?
    - Are there **credit-accounting assertions**, including that `limit=1` is actually passed?
    - Does a PIN-FIRST value's test assert the **conservative** number?
    - Are the task's edge cases covered?

    **Structure:**
    - Does each file have one clear responsibility with a well-defined interface?
    - Is the implementation following the file structure from the plan?
    - Did this change create files already large, or significantly grow existing ones? (Don't flag
      pre-existing sizes — focus on what this change contributed.)
    - Does it follow existing patterns, naming, and comment density in `scanner/`?
    - **Twin files:** if `_shipping_for` changed in one of `scanner/main.py` /
      `scanner/discovery/opportunities.py` but not the other, that is a finding — identical by
      contract.

    Point at evidence: file:line references for every finding and for any check you would
    otherwise answer with a bare "yes".

    Your final message is the report itself: begin directly with the Part 0 verdict. Every line is
    a verdict, a finding with file:line, or a check you ran — no preamble, no process narration,
    no closing summary.

    ## Calibration

    Categorize by actual severity. **Every Part 0 violation is Critical.** Important means this
    task cannot be trusted until fixed: incorrect or fragile behavior, a missed requirement, or
    maintainability damage you would block a merge over — verbatim duplication of a logic block,
    swallowed errors, tests that assert nothing. "Coverage could be broader" and polish are Minor.

    If the plan or brief explicitly mandates something this rubric calls a defect, that IS a
    finding — report it as Important (or Critical for Part 0), labeled **plan-mandated**. The
    plan's authorship does not grade its own work; the human decides.

    Acknowledge what was done well before listing issues.

    ## Output Format

    ### Part 0: Domain Gates
    - Price accuracy: ✅ | ❌ [file:line, what, why]
    - Identity: ✅ | ❌
    - Credits: ✅ | ❌
    - Doctrine: ✅ | ❌
    - Fail-safe: ✅ | ❌
    - Secrets: ✅ | ❌

    ### Spec Compliance
    - ✅ Spec compliant | ❌ Issues found: [missing/extra/misunderstood, with file:line]
    - ⚠️ Cannot verify from diff: [what, and what the controller should check]

    ### Strengths
    [Specific.]

    ### Issues

    #### Critical (Must Fix)
    #### Important (Should Fix)
    #### Minor (Nice to Have)

    For each: file:line, what's wrong, why it matters, how to fix (if not obvious).

    ### Assessment

    **Task quality:** [Approved | Needs fixes]

    **Reasoning:** [1-2 sentences.]
```

**Placeholders:**
- `[MODEL]` — REQUIRED, per SKILL.md Model Selection
- `[BRIEF_FILE]` — the same brief the implementer worked from (`scripts/task-brief` prints it)
- `[GLOBAL_CONSTRAINTS]` — **verbatim** from the plan's Global Constraints section: exact values,
  formats, and stated relationships between components (not process rules — those are in this
  template). This block is the reviewer's attention lens; without it a STOP-class violation is
  invisible.
- `[REPORT_FILE]` — the implementer's detailed report file
- `[BASE_SHA]` / `[HEAD_SHA]` — the recorded task base and current head (never `HEAD~1`)
- `[DIFF_FILE]` — path printed by `scripts/review-package PLAN_FILE BASE HEAD`

**Reviewer returns:** Part 0 gate verdicts, spec-compliance verdict (✅/❌/⚠️), strengths, issues
(Critical/Important/Minor), task-quality verdict.
