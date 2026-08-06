---
name: poke-tdd
description: Use when implementing any feature or bugfix in this repo, before writing implementation code - red/green/refactor with network-mocked pytest, worked-example money assertions, and provenance tests. Forked from superpowers:test-driven-development.
---

# Poke TDD

Forked from `superpowers:test-driven-development` (v6.2.0, MIT). Read
`.claude/poke-invariants.md` first.

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** If you didn't watch the test fail, you don't know if it tests the right thing.

**Violating the letter of the rules is violating the spirit of the rules.**

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Wrote code before the test? Delete it. Don't keep it as reference, don't adapt it while writing
tests, don't look at it. Implement fresh from the tests.

**Always:** new features, bug fixes, refactors, behavior changes.
**Exceptions (ask the operator):** throwaway prototypes, generated code, config files.

Thinking "skip TDD just this once"? That's rationalization.

## Running tests here

```bash
.claude/scripts/poke-pytest -q                                  # full suite
.claude/scripts/poke-pytest tests/test_margin.py -q -k "fee"    # focused
```

Resolves `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python` (POSIX), else a system
interpreter with pytest. **Exit 3 means the suite did not run** — report that plainly to the
operator rather than claiming green, and do not `pip install` to work around it.

Tests are **network-mocked**. A test that needs live HTTP is a design smell — mock the client, or
the design is wrong.

## Red → Green → Refactor

### RED — write the failing test

One behavior, clear name, real code (no mocks unless unavoidable).

**For money arithmetic, the expected value is computed by hand in a comment.** A test that
asserts whatever the implementation happens to return proves nothing:

```python
def test_tcgplayer_channel_nets_commission_processing_and_fixed():
    fees = margin.FeeModel()
    r = margin.net_margin(cost_incl_tax=30.0, comp=100.0, channel="tcgplayer",
                          est_shipping=8.0, fees=fees)
    # fee = 100*(0.1075+0.025) + 0.30 = 13.55 ; net = 100 - 13.55 - 8 = 78.45
    assert round(r.net_proceeds, 2) == 78.45
    assert r.channel == "tcgplayer"
```

### Verify RED — watch it fail

**MANDATORY. Never skip.** Run the focused test and read the failure. The failure must be the one
you expected — a test failing for the wrong reason (import error, typo, wrong fixture) is not a
red. Fix the test, not the expectation.

### GREEN — minimal implementation

Write the least code that makes the test pass. Then run it and watch it pass, and run the full
suite to confirm nothing regressed.

### REFACTOR — clean up while staying green

Run the suite after each refactor step.

## Repo-specific test classes

Beyond the generic behavior test, this codebase needs these — a change in these areas is not
tested until it has one:

**Provenance tests.** When a value gains a source, assert the source travels with it:

```python
assert quote.source_url.startswith("https://")
assert quote.capture_date == "2026-07-10"
```

**Sentinel-leak tests.** When a "no data" sentinel exists, assert it never reaches an output that
a human reads as a number. This repo has shipped a sentinel leak before; the regression test is
permanent.

**Credit-accounting tests.** Every billable path asserts a bounded `apiCallsConsumed` /
`creditsConsumed`. Assert the `limit=1` argument is actually passed on by-id lookups —
its removal is a money-class defect that no behavior test would catch. Local/read/`refresh=false`
paths assert `0` and `source:"local"`, and assert a billed value is **preserved rather than
dropped**.

**Fail-safe tests.** A PIN-FIRST value's test asserts the **conservative** number (full fee, higher
grading cost), with a comment saying a real-value test is added only after the live source is
pinned and cited. Do not write the optimistic test "ready for later" — it will be uncommented.

**Era tests.** Dated schedules (`fee_model_for`, `grading_fee_for`) get a test per era boundary
plus a malformed-date test asserting the safe branch.

## Test hygiene

- One behavior per test; the name says the behavior.
- Test real code, not mocks. A test that only asserts a mock was called tests nothing.
- **Output must be pristine** — stray warnings or noise in the suite output are findings.
- Never weaken an assertion to make a test pass. If the expected value was wrong, recompute it by
  hand and say so.
- Never delete or `xfail` a failing test to get to green. A failing test is reported with its
  output.

## Commit

Test and implementation land together, conventional style:

```bash
git add scanner/margin.py tests/test_margin.py
git commit -m "feat(poke): channel-aware FeeModel with dated provenance"
```

## Common rationalizations

| Excuse | Reality |
| --- | --- |
| "The suite won't run here, I'll verify later" | Then the work is unverified. Say so; don't claim green. |
| "I'll just pip install pytest" | Dependencies need operator go-ahead. Stop and ask. |
| "The test asserts what the code returns, close enough" | Compute the expected value by hand or the test proves nothing. |
| "It's a one-line fee change, no test needed" | Fee changes are exactly the class that ships fake profit. Test it. |
| "The optimistic test documents the intent" | It documents a number you cannot source. Fail-safe only. |
| "I'll mock the whole thing to avoid network" | Mock the client. Mocking the code under test tests the mock. |
