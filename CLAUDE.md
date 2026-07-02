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
