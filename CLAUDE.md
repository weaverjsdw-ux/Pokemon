# Pokemon-main — Project Instructions

Route-aware, multi-retailer Pokémon TCG sealed restock scanner + hobby-funded resale /
deal-intelligence engine. Package is `scanner/` (never `target_scanner/`); the discovery
subsystem lives at `scanner/discovery/`.

## Test command

- Full suite: `.venv/Scripts/python.exe -m pytest -q` — tests are network-mocked; no live HTTP.
- Portable equivalent: `.claude/scripts/poke-pytest -q` — resolves the Windows venv, a POSIX venv,
  or a system interpreter. **Exit 3 means the suite did not run** (typical in a remote/web
  container, which has no venv): say so plainly, never claim green, and never `pip install` to
  work around it.

## Price accuracy (STOP-class — never bend these)

- Never fabricate, guess, or extrapolate a price. No source → no number.
- Every price carries its source URL + capture date.
- Estimates are explicitly badged EST and never presented as comps.

## PPT / PriceCharting credits (money-class)

- The PPT API bills on requested `limit`, not results returned — `limit=1` is mandatory on
  by-id lookups and must never be removed.
- Resolve sealed products by exact `tcgPlayerId` only; bare name search returns wrong variants.
- Free tier is 100 credits/day. Surface estimated credit spend and get operator go-ahead before any live PPT run.

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
- The flow is implemented by the project-local Superpowers fork in `.claude/skills/` — these load
  in every environment, including Claude Code on the web where marketplace plugins are absent:
  `poke-brainstorm` → `poke-plan` → `poke-sdd` (or `poke-execute`) → `poke-finish`, with
  `poke-tdd` and `poke-review` running inside execution. Shared guardrails:
  `.claude/poke-invariants.md`; rationale and upstream re-sync notes: `.claude/README.md`.
