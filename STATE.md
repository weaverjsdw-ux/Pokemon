# STATE — Pokemon-main (TCG resale engine)

Thin state surface. Observed 2026-08-18 during the cross-portfolio completion session.
Doctrine: `DOCTRINE.md` and `CLAUDE.md` bind; this file only records state, it decides nothing.

## Purpose

Route-aware, multi-retailer Pokémon TCG sealed restock scanner (`scanner/`) plus a
hobby-funded resale / deal-intelligence layer (`scanner/discovery/`, the `/poke` sweep).
Buys are always executed by a human; price accuracy is STOP-class (see `DOCTRINE.md`).

## What works now (verified 2026-08-18)

- Full test suite: **1110 passed in ~17s** (`.venv/Scripts/python.exe -m pytest -q`; network-mocked).
- Scanner CLI + local web UI (`python -m scanner`, `python -m scanner.web`) per README; not
  re-run live today — no live retailer traffic was generated for this check.
- `/poke` discovery Phase 1 (deterministic core: schema STOP gate, ledger, scoring, render)
  is built and covered by the suite.
- Git: local `main` = `origin/main` at `49f32fe` (201 commits, 0 unpushed) before this file.

## Last real activity (evidence)

- Last commit before this file: `49f32fe` 2026-07-11 — "fix(poke): sealed comp_response
  emits/preserves creditsConsumed".
- Untracked working-tree residue from the July sessions (sweep outputs under `data/poke/`,
  two plan docs under `docs/superpowers/plans/`, `sw-military-le.md`) is deliberately left
  in place, uncommitted and unmodified — an adopt-or-discard decision for the operator, not
  for a state pass.

## What remains

- Next planned move (per `NEXT_SESSION.md`): port the GUN DEALS AI deal-research pipeline
  as a fresh brainstorm → spec → plan → build.
- Live-web acquisition + in-session `/poke` command (Phase 1 follow-on).
- Coverage remains the leverage point (`ROADMAP.md` §0): Target-heavy IDs; Costco/GameStop/
  Pokémon Center adapters work but have zero IDs.
- Adjudicate the untracked July files listed above.

## Useful-today action

`python -m scanner --check-config` then `python -m scanner.web` — the dashboard's coverage
and source-health panels are the single best signal of whether the tool is doing anything.
For a dev session: `/pokebuild`.
