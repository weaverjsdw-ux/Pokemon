# `/pokebuild` Dev Advisor/Coder Harness — Design

**Date:** 2026-07-02
**Status:** Approved design, pending implementation plan
**Owner decision trail:** operator confirmed (a) role = dev **advisor + coder** (not runtime
persona, not advisor-only), (b) delivery = **combo** — lean always-on project `CLAUDE.md` +
on-demand `/pokebuild` slash command reading a rich OPENER contract, (c) name **`/pokebuild`**
(reserving `/poke` for the Phase-B runtime operator persona).

## Problem

Pokemon-main has no session-prep artifact. There is no project `CLAUDE.md`, no Pokemon slash
command, and no Pokemon subagent. The only prep a fresh session gets is auto-memory injection,
which is passive, point-in-time, and explicitly flagged as potentially stale. Consequences:

- Safety-critical invariants (price-accuracy discipline, PPT credit billing trap, don't-push
  policy) live only in memory files and can silently miss or rot.
- Every build session re-derives the same context (what the repo is, how to run tests, where
  the roadmap stands) or trusts stale memory.
- There is no deliberate "enter build mode" affordance with a persona, workflow contract, and
  boundaries — the thing the operator's other programs (`/gun`, `/coder`, `/advisor_builder`)
  all have.

## Goal

A dev-session harness for building in Pokemon-main that (1) makes the safety invariants
**always-on** regardless of what the operator types, and (2) provides a **deliberate, rich
advisor+coder role** entered via one command, prepped from live sources of truth rather than
hardcoded snapshots.

## Non-goals (out of scope)

- The Phase-B **runtime** `/poke` operator persona (scan/watch/check/expert). That is a
  roadmap deliverable (`docs/superpowers/specs/2026-06-28-resale-engine-program-roadmap.md`,
  Phase B) and is intentionally NOT built or named here. `/pokebuild` must not squat on the
  `/poke` name.
- Any change to scanner/discovery code, the roadmap, or the memory files.
- Subagent delegation (`.claude/agents/`) — can be added later if parallel offload is wanted.

## Design principle: point at living state, don't embed it

The harness's session-prep must **read state from sources of truth at session start** (roadmap
spec, `git log`, the SDD progress ledger, referenced runbooks) instead of hardcoding "what's
done." Hardcoded state is exactly how the memory files rotted. The only facts embedded in the
artifacts are (a) stable invariants and (b) stable file locations. Anything volatile is a
pointer plus an instruction to read it fresh.

## Architecture — three artifacts

| # | File | Loading | Carries |
| --- | --- | --- | --- |
| 1 | `Pokemon-main/CLAUDE.md` (repo root, committed) | Always-on, every session in this cwd | Safety invariants + orientation, ~30 lines max |
| 2 | `C:\Users\Weave\.claude\commands\pokebuild.md` (global) | On `/pokebuild [args]` | Thin dispatcher: read the OPENER in full, then dispatch on `$ARGUMENTS` |
| 3 | `Pokemon-main/docs/poke/pokebuild-opener.md` (committed) | Read by the command at invocation | The full session contract: persona, prep protocol, mode dispatch, workflow, guardrails, boundaries |

The split rule: **anything that must hold even when the operator forgets to type `/pokebuild`
goes in CLAUDE.md; everything else goes in the OPENER.** The command file stays thin (mirrors
`/gun`) so the contract is versioned in-repo where it can be reviewed and committed.

## Artifact 1 — `Pokemon-main/CLAUDE.md` (lean, always-on)

Target ≤ ~30 lines of content. Sections and the facts they carry:

1. **What this repo is** (2 lines): route-aware multi-retailer Pokémon TCG sealed restock
   scanner + resale/deal-intelligence engine. Package is `scanner/` (never `target_scanner/`);
   discovery subsystem at `scanner/discovery/`.
2. **Test command** (1 line): `.venv/Scripts/python.exe -m pytest -q` — run the full suite;
   tests are network-mocked, no live HTTP.
3. **Price-accuracy invariants** (STOP-class): never fabricate or guess a price; every price
   carries source URL + capture date; estimates are explicitly badged EST; never present an
   estimate as a comp.
4. **PPT credit guardrails** (money-class): PriceCharting/PPT API bills on requested `limit`,
   not results — `limit=1` is mandatory on by-id lookups and must never be removed; resolve
   sealed products by exact `tcgPlayerId` only (bare name search returns wrong variants); free
   tier is 100 credits/day.
5. **Git & environment policy**: local `main` is intentionally ahead of `origin/main` — never
   push without explicit operator instruction; no dependency installs without asking; runtime
   deps are only `requests` + `PyYAML`; `config.yaml` and `data/state.db` are gitignored
   (config holds the PPT key — never commit or print it).
6. **Workflow pointer** (2 lines): feature work follows the SDD flow (brainstorm → spec in
   `docs/superpowers/specs/` → plan → execute); the program roadmap is
   `docs/superpowers/specs/2026-06-28-resale-engine-program-roadmap.md`. For a full build
   session, run `/pokebuild`.

## Artifact 2 — `~/.claude/commands/pokebuild.md` (thin command)

Frontmatter: `description` (one line: begin a Pokemon-main dev advisor/coder session) and
`argument-hint`: `"[task] | advise <topic>"`.

Body (short, `/gun`-shaped):

- "You are now starting a **POKEBUILD** session. The input is: `$ARGUMENTS`."
- **Begin immediately**: read
  `C:\Users\Weave\OneDrive\Desktop\Pokemon-main\docs\poke\pokebuild-opener.md` in full — it is
  the canonical session contract (absolute path: the command file is global and must not
  depend on cwd). If it is missing/unreadable, surface that and stop (do not improvise a
  contract).
- Dispatch on `$ARGUMENTS` per the OPENER's Mode Dispatch rules.
- Load the OPENER's referenced files on demand only (progressive disclosure).

## Artifact 3 — `docs/poke/pokebuild-opener.md` (the session contract)

Sections, in order:

1. **Persona.** Senior Python developer and thinking partner on a hobby-funded Pokémon TCG
   resale engine. Fluent in: the scanner architecture, the discovery/deal-intelligence
   subsystem, sealed-product market mechanics (MSRP vs street, hyped sets, comps), and the
   operator's SDD workflow. Advisor-first: challenge designs, surface trade-offs, say "this is
   the wrong move" when it is — then build. Not a yes-machine, not a scope-broadener.
2. **Session-prep protocol** (live reads, in order, before any advising/building):
   1. `git log --oneline -15` + `git status` — where the repo actually is.
   2. The roadmap spec's phase list — where the program stands (A–E).
   3. `.superpowers/sdd/progress.md` if present (git-ignored ledger of accepted review minors
      and in-flight work).
   4. Then a **one-paragraph state readback** to the operator: current phase, last merged
      work, open follow-ups it can see, and what it thinks the session is for. Operator
      corrects course before any work starts.
3. **Mode dispatch** on `$ARGUMENTS`:
   - First token `advise` → **advisor-only**: read-only session (no Edit/Write to repo code),
     design critique / trade-off analysis / roadmap positioning. Explicit statement that
     advisor mode never edits files.
   - Empty → run session-prep, give the state readback, ask what to work on. Do not
     self-select scope.
   - Anything else → **build packet**: treat `$ARGUMENTS` as the scoped task. If the task is
     genuinely new feature work (not a mechanical fix), run the brainstorming skill first per
     the operator's superpowers flow; small scoped fixes proceed directly with read-before-edit.
4. **Build workflow contract:** read before editing; keep the write set narrow (only files the
   task requires); follow existing code patterns and comment density; every change verified by
   running the affected tests, then the full suite before claiming done; atomic commits with
   the repo's conventional style (`fix(poke):`, `docs(poke):`, `data(poke):`, etc.); update
   `.superpowers/sdd/progress.md` when it exists and the work is SDD-tracked; report outcomes
   faithfully (failing tests reported with output, not smoothed over).
5. **Guardrails** (restated from CLAUDE.md so the contract is self-contained, with the OPENER
   noting CLAUDE.md is the always-on copy): price-accuracy STOP rules; PPT `limit=1` +
   by-`tcgPlayerId`-only + credit budget awareness (surface estimated credit spend before any
   live PPT-touching run); never commit/print the PPT key; no pushes, no installs, no
   destructive cleanup without explicit operator instruction.
6. **Boundaries (do-NOT list):** don't build or name the Phase-B runtime `/poke` persona from
   this harness; don't rewrite the roadmap or specs without the operator asking; don't broaden
   a build packet; don't edit memory files; live-network runs (sweeps, PPT calls) only with
   operator go-ahead since they spend credits; if a task implies any of these, stop and
   surface it.
7. **Referenced files (on demand only):** the roadmap spec; `docs/poke/live-sealed-board.md`
   (sweep runbook); `docs/poke/ppt-id-seeding.md` (open seeding checklist);
   `docs/poke/reference/ppt-v2-notes.md` (PPT v2 API contract); `docs/poke/sources.md`;
   `docs/poke/PHASE0_FINDINGS.md`. Load a file only when the chosen task needs it.

## Error handling

- **OPENER missing/unreadable** → the command surfaces the failure and stops; no improvised
  contract (prevents a silent-degraded session that skips guardrails).
- **Stale embedded facts** → by design there are almost none; the session-prep protocol reads
  live state. If the OPENER's stable pointers break (file moved), the session surfaces the
  broken pointer rather than guessing.
- **Conflict with global CLAUDE.md (Ollama offload policy)** → no exception needed: repo-wide
  reasoning and correctness-critical code are RED (stay on paid) under the existing policy;
  GREEN sub-steps (commit text, docstrings) remain offloadable. The OPENER does not override
  the offload policy.

## Verification

1. **Static:** project CLAUDE.md ≤ ~30 content lines; command file parses (frontmatter +
   body); all file paths referenced by the three artifacts exist on disk.
2. **Smoke test (fresh session):** invoke `/pokebuild` with no args → confirm it reads the
   OPENER, performs the live session-prep reads, and produces a correct state readback without
   editing anything. Invoke `/pokebuild advise <topic>` → confirm read-only behavior.
3. **Guardrail presence check:** grep the built artifacts for the four load-bearing strings
   (`limit=1`, `tcgPlayerId`, source URL + capture date wording, never-push wording) — all
   four must appear in both CLAUDE.md and the OPENER.

## Maintenance

The OPENER's volatile knowledge is delegated to live reads, so routine phase progress requires
no harness edits. The artifacts need touching only when: a stable file path moves, an
invariant genuinely changes (e.g. PPT billing model), or a new mode is wanted. When Phase B
ships the runtime `/poke`, this harness stays as-is — the two commands coexist.
