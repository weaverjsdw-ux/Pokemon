# Poke Invariants — the shared guardrail block

Single source of truth for the constraints every `poke-*` skill inherits. The always-on copy
lives in the repo-root `CLAUDE.md`; `docs/poke/pokebuild-opener.md` restates them for
`/pokebuild`. **All copies are load-bearing** — when one changes, change them all.

Every `poke-*` skill embeds the STOP-class and money-class gates inline (so a session that
never opened this file is still safe) and points here for the full set.

---

## 1. Identity & layout

| Thing | Value |
| --- | --- |
| Package | `scanner/` — **never** `target_scanner/` |
| Discovery subsystem | `scanner/discovery/` |
| Price/edge subsystem | `scanner/poke_api/` |
| PPT v2 client | `scanner/market.py` |
| Specs | `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` |
| Plans | `docs/superpowers/plans/YYYY-MM-DD-<feature>.md` |
| SDD workspace | `.superpowers/sdd/<plan-basename>/` (git-ignored, per-plan) |
| Roadmap | `docs/superpowers/specs/2026-06-28-resale-engine-program-roadmap.md` |

## 2. Price accuracy — STOP-class

Never bend these. A violation is a stop-work defect, not a Minor finding.

- **Never fabricate, guess, or extrapolate a price.** No source → no number.
- **Every price/rate/fee carries its source URL + capture (or effective) date.**
- **Estimates are badged** `EST` / `operator_assumption` and are **never** presented as sold comps.
- **Exact identity only.** No fuzzy match, no guessed slug/id/grade. A miss is honest data.
- **Weak, stale, or fallback-derived sources get a confidence tier**, not fake confidence.
  Low-confidence comps never show BUY.

## 3. PPT / PriceCharting credits — money-class

- The PPT API **bills on requested `limit`, not results returned**. `limit=1` is mandatory on
  by-id lookups (`scanner/market.py`) and **must never be removed**.
- Resolve sealed products by **exact `tcgPlayerId` only** — bare name search returns wrong variants.
- Free tier is **100 credits/day**.
- Every billable path reports a bounded `apiCallsConsumed` / `creditsConsumed` **or refuses
  first**. A billed call that reports `0` is a defect.
- **Surface estimated credit spend and get operator go-ahead before any live PPT-touching run.**

## 4. Doctrine — tool advises, human transacts

- No auto-checkout, cart automation, auto-listing, account abuse, login-wall scraping, or
  proxy/distributed polling. A human reviews and executes every buy and sell.
- Acquisition/sale records are **records of a purchase the human already made** — never an executor.
- No "AI price prediction." Every number traces to a real comp with a confidence tier.
- Prefer first-party or major-retailer MSRP listings over marketplace sellers.

## 5. Fail-safe defaults & PIN-FIRST gates

When a number is not yet pinned to a live, cited source, ship the value that **errs against
the operator's interest** — higher fees, lower net, higher grading cost — never toward fake profit.

A **PIN-FIRST gate** is a spec/plan-level hard gate: the feature ships in its fail-safe state and
the real value is switched on only after the live source is pinned and cited with a capture date.
A plan that flips a PIN-FIRST value without that citation is a spec-compliance failure.

## 6. Tests

Resolve the interpreter before claiming anything about the suite:

| Environment | Command |
| --- | --- |
| Operator's Windows box | `.venv/Scripts/python.exe -m pytest -q` |
| POSIX venv | `.venv/bin/python -m pytest -q` |
| Either, resolved automatically | `.claude/scripts/poke-pytest -q` |

- Tests are **network-mocked**. A test that needs live HTTP is a design smell.
- **If no venv and no `pytest` exist** (typical in a remote/web container), the suite **cannot**
  be run. **STOP and tell the operator.** Do **not** `pip install` — installing dependencies
  requires the operator's go-ahead (§7). Do **not** claim the suite is green; say plainly that
  it was not run and what blocked it.
- Failing tests are reported **with their output**, never smoothed over.

## 7. Git & environment

- **Never push to any remote without explicit operator instruction.** Local `main` may
  intentionally diverge from `origin/main`.
- Never install a dependency without asking. Keep the dependency footprint minimal.
- `config.yaml` (holds the PPT API key) and `data/state.db` are gitignored — never commit or print them.
- No destructive cleanup (`git clean -fdx`, force-push, branch deletion) without an explicit ask.

## 8. Commits

Conventional style, scope matching the touched subsystem:

```
feat(poke):  fix(poke):  docs(poke):  data(poke):  test(poke):
fix(market): fix(scanner): …
```

Atomic commits — one logical change each. Reference the plan task where one exists.

## 9. Scope discipline

The program has a documented over-engineering failure mode (a 16-phase ladder collapsed into one
build). Accordingly:

- Every spec names what it is **explicitly NOT building**, and **names the cost** of each "no."
- Split every "no" into **permanent** vs **deferred** tiers.
- Never broaden a build packet beyond its scope. YAGNI is a review criterion, not a preference.
- Do not build, name, or scaffold the Phase-B runtime `/poke` operator persona from dev harnesses —
  it is a separate roadmap deliverable.

## 10. Load-bearing structures that look like bugs

Do not "reconcile" these — the apparent contradictions are intentional:

- **D-vs-E split.** Comp-alone-never-promotes-off-WATCH is hardcoded in the D layer
  (`discovery/opportunities.py`). Verified entries reach live **only** through the E layer
  (`poke_api/edge.py`). Changes extend the E route; the D functions stay untouched.
- **TCGCSV is not independent of PPT.** It is TCGplayer lineage, so it is a *reference*
  (free substitute), classified external / non-independent, and never counted as
  `cross_source_validated`.
- **The two `_shipping_for` copies** (`main.py`, `discovery/opportunities.py`) are kept identical
  by contract — any change touches both.
- **Three ledgers are never conflated:** observation (`price_history.jsonl`) vs paper decisions
  (`paper_decisions.jsonl`) vs inventory/P&L (`inventory.jsonl`).

Before treating any of these as a defect, re-read the spec that established it.
