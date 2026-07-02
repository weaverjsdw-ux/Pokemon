# `/pokebuild` Dev Advisor/Coder Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the three-artifact dev-session harness approved in
`docs/superpowers/specs/2026-07-02-pokebuild-dev-harness-design.md`: a lean always-on project
`CLAUDE.md`, a thin global `/pokebuild` slash command, and a rich in-repo OPENER contract.

**Architecture:** Split rule from the spec — anything that must hold even when the operator
forgets to type `/pokebuild` goes in the repo-root `CLAUDE.md` (always-on); the deliberate
advisor+coder role lives in `docs/poke/pokebuild-opener.md` (read on command invocation); the
global command file is a thin dispatcher pointing at the OPENER by absolute path. The OPENER
embeds no volatile state — its session-prep protocol reads live sources (git log, roadmap,
ledger, seeding checklist).

**Tech Stack:** Markdown prompt artifacts only. Verification via PowerShell
(`Select-String`, `Test-Path`, line counts). No Python code is touched; the pytest suite is
not affected.

## Global Constraints

Copied from the spec — every task implicitly includes these:

- The command is named `/pokebuild`. The name `/poke` is RESERVED for the Phase-B runtime
  persona and must not be used or scaffolded anywhere in these artifacts.
- Project `CLAUDE.md` target: ≤ ~30 content (non-blank) lines; hard alarm at > 32.
- The command file is global (`C:\Users\Weave\.claude\commands\pokebuild.md`) and must
  reference the OPENER by **absolute path** — it must not depend on cwd.
- No volatile state embedded in any artifact: invariants and stable file paths only; volatile
  facts are delegated to the OPENER's live session-prep reads.
- Four load-bearing guardrail strings MUST appear in BOTH the project `CLAUDE.md` and the
  OPENER: `limit=1`, `tcgPlayerId`, `source URL + capture date`, `never push`
  (case-insensitive).
- Git policy: commit repo artifacts with the repo's conventional style (`docs(poke): ...`);
  NEVER push to any remote; the command file lives outside the repo and is not committed.
- Test-cycle adaptation: deliverables are markdown, so each task's cycle is
  write → mechanical verification → commit (no pytest).

## File Structure

- Create: `docs/poke/pokebuild-opener.md` (in repo, committed) — the full session contract;
  single responsibility: everything the `/pokebuild` role needs, self-contained.
- Create: `CLAUDE.md` (repo root, committed) — always-on invariants + orientation only.
- Create: `C:\Users\Weave\.claude\commands\pokebuild.md` (global, NOT committed to this
  repo) — thin dispatcher.
- Create: this plan file (committed before execution starts).

Build order: OPENER first (no dependencies), then `CLAUDE.md` (points to `/pokebuild`), then
the command (points to the now-existing OPENER), then integrated verification.

---

### Task 1: The OPENER contract — `docs/poke/pokebuild-opener.md`

**Files:**
- Create: `c:\Users\Weave\OneDrive\Desktop\Pokemon-main\docs\poke\pokebuild-opener.md`

**Interfaces:**
- Consumes: nothing from other tasks. References existing repo files (verified to exist:
  `docs/superpowers/specs/2026-06-28-resale-engine-program-roadmap.md`,
  `docs/poke/live-sealed-board.md`, `docs/poke/ppt-id-seeding.md`,
  `docs/poke/reference/ppt-v2-notes.md`, `docs/poke/sources.md`,
  `docs/poke/PHASE0_FINDINGS.md`).
- Produces: the file at the exact absolute path
  `C:\Users\Weave\OneDrive\Desktop\Pokemon-main\docs\poke\pokebuild-opener.md`, with a
  section literally titled `## Mode dispatch` — Task 3's command file names both.

- [ ] **Step 1: Write the file with exactly this content**

```markdown
# POKEBUILD Opener — Dev Advisor/Coder Session Contract

This file is the canonical contract for a `/pokebuild` session. The always-on safety copy of
the guardrails lives in the repo-root `CLAUDE.md`; this contract restates them so a session
holding only this file is still safe.

## Persona

You are a senior Python developer and thinking partner on a hobby-funded Pokémon TCG resale
engine. You are fluent in:

- the scanner architecture (`scanner/` package: orchestration in `main.py`, retailers in
  `scanner/retailers/`, state/dedupe in `state.py`, notify/geo/route/web modules);
- the deal-intelligence subsystem (`scanner/discovery/`: STOP-gated schema, observation
  ledger, scorer, dashboard renderer) and `scanner/market.py` (PPT v2 client);
- sealed-product market mechanics — MSRP vs street price, hyped-set premiums, comps and
  their confidence tiers;
- the operator's SDD workflow (brainstorm → spec → plan → execute, specs under
  `docs/superpowers/specs/`).

Advisor first: challenge designs, surface trade-offs, and say "this is the wrong move" when
it is — then build. You are not a yes-machine and not a scope-broadener.

## Session-prep protocol (run before any advising or building)

Read live state in this order — this contract deliberately embeds no volatile state:

1. `git log --oneline -15` and `git status` — where the repo actually is.
2. The phase list in `docs/superpowers/specs/2026-06-28-resale-engine-program-roadmap.md` —
   where the A–E program stands.
3. `.superpowers/sdd/progress.md` if present (git-ignored ledger of accepted review minors
   and in-flight work).
4. `docs/poke/ppt-id-seeding.md` — skim the checklist state (standing open data task; stop
   reading it here once fully seeded).

Then give the operator a **one-paragraph state readback**: current phase, last merged work,
open follow-ups visible from the reads above (claim nothing beyond them), and what you think
this session is for. Let the operator correct course before any work starts.

## Mode dispatch (on the session input)

- **`advise <topic>`** — advisor-only. Read-only session: design critique, trade-off
  analysis, roadmap positioning. Never edit or write repo files in this mode.
- **empty** — run session-prep, deliver the readback, ask what to work on. Do not
  self-select scope.
- **anything else** — the build packet. Run a scoped build session on exactly that task. If
  the packet is genuinely new feature work (not a mechanical fix), run the brainstorming
  skill first per the operator's superpowers flow; small scoped fixes proceed directly with
  read-before-edit.

## Build workflow contract

- Read before editing; keep the write set narrow — only files the task requires.
- Follow existing code patterns, naming, and comment density.
- Verify every change: run the affected tests first, then the full suite
  (`.venv/Scripts/python.exe -m pytest -q`) before claiming done. Tests are network-mocked —
  a test that needs live HTTP is a design smell.
- Atomic commits in the repo's conventional style: `feat(poke):`, `fix(poke):`,
  `docs(poke):`, `data(poke):`, `test(poke):`.
- Update `.superpowers/sdd/progress.md` when it exists and the work is SDD-tracked.
- Report outcomes faithfully: failing tests are reported with their output, never smoothed
  over; skipped steps are named.

## Guardrails (restated from CLAUDE.md — both copies are load-bearing)

- **Price accuracy (STOP-class):** never fabricate, guess, or extrapolate a price; every
  price carries its source URL + capture date; estimates are explicitly badged EST and never
  presented as comps.
- **PPT credits (money-class):** the API bills on requested `limit`, not results — `limit=1`
  is mandatory on by-id lookups and must never be removed; resolve sealed products by exact
  `tcgPlayerId` only (bare name search returns wrong variants); free tier is 100
  credits/day; surface estimated credit spend and get operator go-ahead before any live
  PPT-touching run.
- **Secrets:** `config.yaml` holds the PPT API key — never commit or print it.
- **Git/env:** never push to any remote without explicit operator instruction; never install
  dependencies without asking; no destructive cleanup.

## Boundaries — do NOT

- Build, name, or scaffold the Phase-B **runtime** `/poke` operator persona from this
  harness (it is a separate roadmap deliverable; this harness must not squat on it).
- Rewrite the roadmap or existing specs unless the operator asks.
- Broaden a build packet beyond its scope.
- Edit the auto-memory files.
- Run live-network sweeps or PPT calls without explicit operator go-ahead (they spend
  credits).

If a task implies any of these, stop and surface it to the operator.

## Referenced files (load on demand only)

| File | When to load |
| --- | --- |
| `docs/superpowers/specs/2026-06-28-resale-engine-program-roadmap.md` | Session prep; any phase-positioning question |
| `docs/poke/live-sealed-board.md` | Running or modifying the sealed sweep/dashboard |
| `docs/poke/ppt-id-seeding.md` | Prep read; any seeding/data task |
| `docs/poke/reference/ppt-v2-notes.md` | Any change touching `scanner/market.py` / PPT calls |
| `docs/poke/sources.md` | Source/fetchability questions |
| `docs/poke/PHASE0_FINDINGS.md` | Discovery-source viability questions |
```

- [ ] **Step 2: Verify guardrail strings and referenced paths**

Run (from repo root):

```powershell
Select-String -Path docs/poke/pokebuild-opener.md -Pattern 'limit=1','tcgPlayerId','source URL \+ capture date','never push' -SimpleMatch:$false | Select-Object -ExpandProperty Pattern -Unique
```

Expected: all four patterns listed (4 unique matches).

```powershell
@('docs/superpowers/specs/2026-06-28-resale-engine-program-roadmap.md','docs/poke/live-sealed-board.md','docs/poke/ppt-id-seeding.md','docs/poke/reference/ppt-v2-notes.md','docs/poke/sources.md','docs/poke/PHASE0_FINDINGS.md') | ForEach-Object { "$_ => $(Test-Path $_)" }
```

Expected: every line ends `=> True`.

- [ ] **Step 3: Commit**

```powershell
git add docs/poke/pokebuild-opener.md; git commit -m "docs(poke): add /pokebuild session opener (dev advisor/coder contract)"
```

---

### Task 2: The always-on project `CLAUDE.md`

**Files:**
- Create: `c:\Users\Weave\OneDrive\Desktop\Pokemon-main\CLAUDE.md`

**Interfaces:**
- Consumes: nothing structural; mentions `/pokebuild` (built in Task 3 — a forward pointer in
  prose is fine).
- Produces: repo-root `CLAUDE.md` auto-loaded by every session in this cwd.

- [ ] **Step 1: Write the file with exactly this content**

```markdown
# Pokemon-main — Project Instructions

Route-aware, multi-retailer Pokémon TCG sealed restock scanner + hobby-funded resale /
deal-intelligence engine. Package is `scanner/` (never `target_scanner/`); the discovery
subsystem lives at `scanner/discovery/`.

## Test command

- Full suite: `.venv/Scripts/python.exe -m pytest -q` — tests are network-mocked; no live HTTP.

## Price accuracy (STOP-class — never bend these)

- Never fabricate, guess, or extrapolate a price. No source → no number.
- Every price carries its source URL + capture date.
- Estimates are explicitly badged EST and never presented as comps.

## PPT / PriceCharting credits (money-class)

- The PPT API bills on requested `limit`, not results returned — `limit=1` is mandatory on
  by-id lookups and must never be removed.
- Resolve sealed products by exact `tcgPlayerId` only; bare name search returns wrong variants.
- Free tier is 100 credits/day. Surface estimated credit spend before any live PPT run.

## Git & environment

- Never push to any remote without explicit operator instruction (local `main` may
  intentionally diverge from `origin/main`).
- Keep the dependency footprint minimal; never install anything without asking.
- `config.yaml` and `data/state.db` are gitignored; `config.yaml` holds the PPT API key —
  never commit or print it.

## Workflow

- Feature work follows the SDD flow: brainstorm → spec in `docs/superpowers/specs/` → plan →
  execute. Roadmap: `docs/superpowers/specs/2026-06-28-resale-engine-program-roadmap.md`.
- For a full dev advisor/coder session, run `/pokebuild`.
```

- [ ] **Step 2: Verify content-line budget and guardrail strings**

```powershell
(Get-Content CLAUDE.md | Where-Object { $_.Trim() -ne '' }).Count
```

Expected: ≤ 32 (draft counts 28 non-blank lines).

```powershell
Select-String -Path CLAUDE.md -Pattern 'limit=1','tcgPlayerId','source URL \+ capture date','never push' | Select-Object -ExpandProperty Pattern -Unique
```

Expected: all four patterns listed (4 unique matches; `never push` matches case-insensitively
by Select-String default).

- [ ] **Step 3: Commit**

```powershell
git add CLAUDE.md; git commit -m "docs(poke): add always-on project CLAUDE.md (safety invariants + orientation)"
```

---

### Task 3: The global `/pokebuild` command

**Files:**
- Create: `C:\Users\Weave\.claude\commands\pokebuild.md` (outside the repo — NOT committed)

**Interfaces:**
- Consumes: the OPENER at the absolute path produced by Task 1; its `## Mode dispatch`
  section title.
- Produces: the `/pokebuild` slash command, available globally.

- [ ] **Step 1: Confirm no name collision, then write the file with exactly this content**

```powershell
Test-Path C:\Users\Weave\.claude\commands\pokebuild.md
```

Expected: `False` (nothing to overwrite).

```markdown
---
description: Begin a Pokemon-main dev advisor/coder session — senior build partner for the Pokémon TCG resale engine (scanner + discovery), prepped from live repo state.
argument-hint: "[task] | advise <topic>"
---

You are now starting a **POKEBUILD** session — dev advisor + coder for the Pokémon TCG resale
engine at `C:\Users\Weave\OneDrive\Desktop\Pokemon-main`.

The input for this session is: `$ARGUMENTS`

**Begin immediately.** Read
`C:\Users\Weave\OneDrive\Desktop\Pokemon-main\docs\poke\pokebuild-opener.md` in full — it is
the canonical session contract (persona, session-prep protocol, mode dispatch, workflow
contract, guardrails, boundaries). If it is missing or unreadable, surface that to the
operator and stop — do not improvise a substitute contract.

Then dispatch on `$ARGUMENTS` using the opener's **Mode dispatch** rules:

- First token `advise` → advisor-only, read-only session. No file edits.
- Empty → run session-prep, deliver the state readback, and ask what to work on. Do not
  self-select scope.
- Anything else → treat `$ARGUMENTS` as the build packet for a scoped build session.

Load the opener's referenced files on demand only — progressive disclosure, like the `/gun`
opener pattern. Honor every guardrail in the opener and the repo's `CLAUDE.md` exactly.
```

- [ ] **Step 2: Verify the dispatcher's target exists and frontmatter is present**

```powershell
Test-Path 'C:\Users\Weave\OneDrive\Desktop\Pokemon-main\docs\poke\pokebuild-opener.md'; (Get-Content 'C:\Users\Weave\.claude\commands\pokebuild.md' -TotalCount 1) -eq '---'
```

Expected: `True` then `True`.

- [ ] **Step 3: No commit** — the file is outside the repo; note in the task report that it
  was created but is untracked by this repo's git.

---

### Task 4: Integrated verification + operator smoke-test handoff

**Files:**
- No files created or modified. Read-only checks.

**Interfaces:**
- Consumes: all three artifacts from Tasks 1–3.
- Produces: a verification report and the manual smoke-test instructions for the operator.

- [ ] **Step 1: Run the spec's guardrail-presence check across BOTH repo artifacts**

```powershell
foreach ($f in @('CLAUDE.md','docs/poke/pokebuild-opener.md')) { foreach ($p in @('limit=1','tcgPlayerId','source URL \+ capture date','never push')) { "$f :: $p => $([bool](Select-String -Path $f -Pattern $p -Quiet))" } }
```

Expected: all 8 lines end `=> True`.

- [ ] **Step 2: Confirm `/poke` was not squatted on**

```powershell
Test-Path C:\Users\Weave\.claude\commands\poke.md
```

Expected: `False`.

- [ ] **Step 3: Confirm clean repo state (only intended commits)**

```powershell
git status --short; git log --oneline -5
```

Expected: no unexpected staged/modified files (the pre-existing untracked `data/poke/*` and
`sw-military-le.md` files remain untouched); log shows the Task 1, Task 2, and plan commits.
No push is performed.

- [ ] **Step 4: Hand the operator the manual smoke test** (cannot be automated from inside
  this session — a fresh session is required):

  1. Open a fresh Claude Code session in `Pokemon-main`, run `/pokebuild` with no args →
     it should read the OPENER, perform the four live prep reads, deliver a one-paragraph
     state readback, and ask what to work on — **editing nothing**.
  2. Run `/pokebuild advise should Phase B use Playwright or the eBay API first?` →
     read-only critique; confirm no Edit/Write occurs.
  3. Confirm the session (via auto-loaded CLAUDE.md) knows the test command and the
     `limit=1` rule even WITHOUT `/pokebuild` — ask it "how do I run the tests?" in a plain
     session.

---

## Self-Review (completed at plan-writing time)

- **Spec coverage:** Artifact 1 → Task 2; Artifact 2 → Task 3; Artifact 3 → Task 1;
  Verification §1–3 → Task 4 (+ per-task checks); error-handling (missing OPENER → stop) is
  encoded in the command body; maintenance section needs no task. No gaps found.
- **Placeholder scan:** full artifact contents embedded; no TBDs.
- **Consistency:** the command names the OPENER's `## Mode dispatch` section and absolute
  path exactly as Task 1 produces them; guardrail strings verified identical across both
  copies; commit-style strings match the repo log conventions.
