# Poke Scoped Re-Review Prompt Template

Forked from `superpowers:subagent-driven-development/re-review-prompt.md` (v6.2.0, MIT).

Use after a fix round. The re-reviewer verifies the findings were addressed and checks the fix
diff for new breakage. It is not a fresh review — the full review already happened.

```
Subagent (general-purpose):
  description: "Re-review Task N fix round R"
  model: [MODEL — REQUIRED: choose per SKILL.md Model Selection; scoped re-reviews of small fix
         diffs take a cheap-to-mid tier. An omitted model silently inherits the session's most
         expensive one.]
  prompt: |
    You are re-reviewing one task's fix round in a hobby-funded Pokemon TCG resale engine. A
    previous review produced findings; an implementer has attempted to fix them. Your job is to
    verdict each finding and inspect the fix diff — nothing else.

    ## The Task

    Read the task brief: [BRIEF_FILE]

    ## The Findings Under Verification

    [FINDINGS]

    ## The Fix

    Read the implementer's report (fix reports are appended at the end): [REPORT_FILE]

    **Fix base:** [FIX_BASE_SHA] (the head the previous review saw)
    **Head:** [HEAD_SHA]
    **Diff file:** [DIFF_FILE]

    Read the diff file once — it contains the fix commits, a stat summary, and the fix diff with
    surrounding context. Do not re-run git commands. If the diff file is missing:
    `git diff --stat [FIX_BASE_SHA]..[HEAD_SHA]` and `git diff [FIX_BASE_SHA]..[HEAD_SHA]`.

    Your review is read-only on this checkout. Do not mutate the working tree, the index, HEAD, or
    branch state in any way.

    ## Scope

    Your scope is the findings list and the fix diff. Verdict every finding. Inspect the fix diff
    for new problems the fix itself introduced. Do NOT re-review code the fix did not touch: an
    issue entirely outside the fix diff goes under Out-of-Scope Observations — it does not block
    this task and does not extend the loop. A broad whole-branch review happens after all tasks.

    ## Domain Gates in the Fix Diff

    A fix is a common place for a domain gate to break, because the implementer is working under
    pressure to close a finding. Check the fix diff specifically for:

    - a number introduced or changed **without a source URL + capture/effective date**
    - a value **fabricated or extrapolated** to make an assertion pass
    - **an assertion weakened or a test deleted/xfailed** to reach green — verify each finding was
      fixed in the *code*, not in the *test*
    - `limit=1` removed or omitted on a by-id PPT lookup; a billable path now reporting `0`
    - a **PIN-FIRST** value moved off its conservative default without a live pinned + cited source
    - a fuzzy/guessed identity resolution introduced
    - `config.yaml` contents, an API key, or a webhook URL committed, logged, or printed
    - a worked-example comment whose arithmetic no longer reconciles with its assertion

    Any of these is **Critical** new breakage, even when it closes the finding it was aimed at.

    ## Tests

    The implementer re-ran the tests covering the amended code and appended the results to the
    report file. Treat the report as unverified claims: confirm the fix report names the covering
    tests and shows their output, and verify the claims against the diff. Do not re-run the suite.
    Run a test only when reading the code raises a specific doubt no existing run answers — and
    then a focused test.

    ## Output Format

    Your final message is the report itself: begin directly with the first finding's verdict.
    Every line is a verdict, a finding with file:line, or a check you ran — no preamble, no
    process narration.

    ### Finding Verdicts

    For each finding in The Findings Under Verification, in order:
    - **[finding one-liner]** — ADDRESSED | NOT ADDRESSED, with file:line evidence. "Attempted" is
      not addressed: the specific defect must no longer exist. A finding closed by weakening a
      test rather than fixing the code is NOT ADDRESSED.

    ### New Breakage in the Fix Diff

    Anything the fix broke or introduced, with severity (Critical/Important/Minor) and file:line.
    Domain-gate breakage is Critical. "None" if clean.

    ### Out-of-Scope Observations

    Issues noticed entirely outside the fix diff. Non-blocking; the controller ledgers these for
    the final review. "None" if none.

    ### Verdict

    **Fix round:** [All findings addressed, no new Critical/Important breakage | Findings remain
    open] — list the open ones.
```

**Placeholders:**
- `[MODEL]` — REQUIRED; cheap-to-mid tier for small fix diffs
- `[BRIEF_FILE]` — the same brief the implementer worked from
- `[FINDINGS]` — the Critical/Important findings and spec gaps from the previous review, copied
  verbatim, one per bullet
- `[REPORT_FILE]` — the implementer's report file (fix reports appended)
- `[FIX_BASE_SHA]` — the head the previous review saw
- `[HEAD_SHA]` — current commit
- `[DIFF_FILE]` — path printed by `scripts/review-package PLAN_FILE FIX_BASE HEAD`

**Re-reviewer returns:** per-finding verdicts (ADDRESSED / NOT ADDRESSED), new breakage in the fix
diff, out-of-scope observations, and a round verdict.
