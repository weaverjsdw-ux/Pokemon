# NEXT SESSION — Pokémon discovery: resume the built pipeline

Reconciled against the working tree on 2026-09-05. The former instruction to port
a discovery pipeline from scratch is superseded by the implementation already
in `scanner/discovery/`. This card describes code inspected locally; it does not
claim a new live retailer run or authorize spend, alerts, or activation.

## Read the existing path first

- `scanner/discovery/pipeline.py`: one-shot discovery → verification → comparison
  and verdict → deduplication → board/manifest → alert decision. Stages accept
  injected dependencies for offline tests.
- `scanner/discovery/adapters/`: source adapters and their registered slugs.
- `scanner/discovery/candidates.py`: catalog, watched-set, and wildcard candidates
  share one normalized record and the existing title matcher.
- `scanner/discovery/verify.py`: same-listing stock and price evidence.
- `tests/test_poke_pipeline.py`: the existing behavioral proof for the full path.

The pipeline accounts for every candidate in a terminal bucket, including
`unverifiable` and `no_comp`. Missing comparison evidence must remain visible;
it does not establish bad value. A verified purchase alert is a stricter outcome
than retaining a discovery candidate.

## The next implementation question is narrower

`pipeline.default_verifier()` currently routes Slickdeals through its merchant
resolution/verification path. Other sources explicitly return unverifiable
until a same-listing check is supplied. Inspect that exact remaining seam and
current source readiness before proposing an additional adapter or a new engine.
Existing code alone does not prove that a source is accessible today.

Use `/pokebuild` for scoped development. Start by preserving the current dirty
work, reading `CLAUDE.md` and the program roadmap it names, and running the
existing offline pipeline tests:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_poke_pipeline.py
```

An attended live-source test, paid lookup, notification, or scheduled activation
needs the operator's specific authorization. Price provenance, exact identity,
and the existing credit limits remain governed by `CLAUDE.md` and `DOCTRINE.md`.
