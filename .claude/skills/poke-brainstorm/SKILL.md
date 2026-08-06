---
name: poke-brainstorm
description: Use before any feature work, behavior change, or new subsystem in this Pokemon resale engine - turns a rough idea into a reviewed design spec under docs/superpowers/specs/. Forked from superpowers:brainstorming with this repo's price-accuracy, credit, and scope gates.
---

# Poke Brainstorm — idea → reviewed design spec

Forked from `superpowers:brainstorming` (v6.2.0, MIT) and tuned for this repo. Read
`.claude/poke-invariants.md` before the first question — the gates below are the short form.

**Announce at start:** "Using poke-brainstorm to turn this into a design spec."

<HARD-GATE>
Do NOT write code, scaffold, edit `scanner/`, or invoke an implementation skill until you have
presented a design and the operator has approved it. Every project goes through this — a config
change and a new subsystem alike. The design can be three sentences; it still gets presented.
</HARD-GATE>

<STOP-CLASS>
A design that lets a number exist without a source is rejected before it reaches the operator.
No fabricated, guessed, or extrapolated prices. Every price/rate/fee carries a source URL +
capture date. Estimates are badged `EST` and never presented as sold comps. Exact identity only.
</STOP-CLASS>

<MONEY-CLASS>
Any design that touches PPT/PriceCharting must state its credit cost. `limit=1` on by-id lookups
is mandatory and never removed. Free tier is 100 credits/day. Live runs need operator go-ahead.
</MONEY-CLASS>

## Checklist

Create a task for each item and complete them in order:

1. **Read live repo state** — `git log --oneline -15`, `git status`, the phase list in
   `docs/superpowers/specs/2026-06-28-resale-engine-program-roadmap.md`
2. **Ask clarifying questions** — one at a time
3. **Run the Poke Design Interrogation** (below) — the repo-specific questions that generic
   brainstorming does not know to ask
4. **Propose 2-3 approaches** with trade-offs and your recommendation
5. **Present the design in sections**, get approval after each
6. **Write the spec** to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` and commit
7. **Self-review the spec** against the checklist below, fix inline
8. **Operator reviews the written spec** — wait for approval
9. **Hand off to `poke-plan`** — the only skill you invoke next

## Process

**Understanding the idea.** Read the repo state first. If the request spans multiple independent
subsystems, say so immediately and help decompose before spending questions on details — each
sub-project gets its own spec → plan → build cycle. One question per message; prefer multiple
choice; focus on purpose, constraints, success criteria.

**Advisor first.** Challenge the design. Say "this is the wrong move" when it is, before building
it. You are not a yes-machine and not a scope-broadener.

**Exploring approaches.** Lead with your recommendation and why. YAGNI ruthlessly — strip
unnecessary features from every approach.

**Presenting the design.** Scale each section to its complexity. Cover architecture, components,
data flow, provenance, error handling, testing. Ask after each section whether it looks right.

## The Poke Design Interrogation

Every design in this repo answers these before it is written up. A design that cannot answer one
of them is not ready.

**Provenance**
- For every number the design introduces: what is the source URL, and what dates it?
- Which numbers are estimates? How are they badged so they can never be read as comps?
- What is the confidence tier when the source is weak, stale, or fallback-derived?
- How does an identity resolve — exact `tcgPlayerId` / exact slug? What happens on a miss?
  (Answer must be "an honest miss", never a fuzzy match.)

**Credits & money**
- Does any path touch PPT? What is the per-run credit cost, and where is it surfaced?
- Is every billable path either reporting bounded spend or refusing first?
- Is there a free-tier alternative (e.g. TCGCSV) — and is it correctly classified
  **non-independent** so it never counts as cross-source validation?

**Doctrine**
- Does anything here execute rather than advise? (Auto-buy, auto-list, cart, checkout, login
  automation → the design is rejected, not negotiated.)
- Does any output present uncertainty as confidence?

**Fail-safe**
- Which values are not yet pinned to a live cited source? Each one becomes a **PIN-FIRST gate**:
  it ships in the state that errs toward higher fees / lower net / higher cost, and switches on
  only after the source is pinned and cited.

**Scope (this program's known failure mode)**
- What is this design **explicitly NOT building**? List it.
- For each "no": is it **permanent** or **deferred**, and what does the "no" **cost**?
- Does this collapse into one build, or does it need to be a phase ladder? Prefer one build.

**Load-bearing structures**
- Does this touch the D-vs-E split, the `_shipping_for` twins, the three ledgers, or the
  PPT-independence classification? If so, re-read the spec that established it before proposing
  a change — those contradictions are intentional (`.claude/poke-invariants.md` §10).

## Writing the spec

Save to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`. Follow the shape the existing
specs use — read a recent one first (e.g. `2026-07-06-poke-real-transacting-build-design.md`):

- Title, **Date**, **Status**, **Repo**, ladder/phase position
- The system in one line
- **Cross-cutting invariants** every task inherits (the STOP-class / money-class / doctrine /
  fail-safe gates, stated with this design's specifics)
- The design decisions resolved, with rationale
- The ordered task list
- **"Do NOT build"** — permanent vs deferred, each with its cost

Commit with `docs(poke): <topic> design spec`.

## Spec self-review

Fresh eyes on the written spec. Fix inline; no re-review loop.

1. **Placeholders** — any TBD/TODO, vague requirement, or unspecified value? Fix.
2. **Provenance** — does every number in the spec carry a source, or an explicit
   `operator_assumption` badge? Any bare number is a STOP-class defect.
3. **Credit accounting** — is every PPT-touching path's cost stated?
4. **Fail-safe** — is every unpinned value marked PIN-FIRST with its conservative default?
5. **Internal consistency** — do sections contradict each other? Does the architecture match the
   task list?
6. **Scope** — is the "Do NOT build" section present, tiered, and costed?
7. **Ambiguity** — could a requirement be read two ways? Pick one and make it explicit.

## Operator review gate

> "Spec written and committed to `<path>`. Please review it before I write the implementation plan."

Wait. If changes are requested, make them and re-run the self-review. Only proceed on approval.

## Handoff

Invoke `poke-plan`. That is the only skill you invoke after this one.
