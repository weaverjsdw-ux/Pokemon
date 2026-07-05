# Live-Smoke Result - D.5 External Card Source

Date: 2026-07-05
Status: PASS on program-side gate

## Scope

This records the operator-approved D.5 smoke for the raw + graded external card
source path. The run validated the two `refresh=true` asset comp routes against a
real upstream `/cards` response shape.

The smoke did not test sealed products, scheduler behavior, auto-buy behavior,
or Session E strategy logic.

## Asset Mapping

The required smoke assets were mapped to the exact TCGplayer product id:

| Asset | Mapping |
|---|---|
| `umbreon_ex_161_raw_nm` | `tcgplayer_id: "610516"` |
| `umbreon_ex_161_psa10` | `tcgplayer_id: "610516"`, `grade_key: psa10` |

Lookup evidence from the pre-smoke mapping pass:

```text
610516 | Umbreon ex - 161/131 | SV: Prismatic Evolutions | 161/131
```

## Smoke Output

The operator ran the local router smoke from the repo root:

```text
refresh_raw:
  ok: true
  estimate: 1528.09
  confidence: low
  source: external
  credits: 1

refresh_graded:
  ok: true
  estimate: 6925.5
  confidence: high
  source: external
  credits: 2

read_path_credits:
  raw: 0
  graded: 0
```

## Decision

PASS:

- Raw external `/cards` JSON parsed without crashing.
- Graded external `/cards?includeEbay=true` JSON parsed without crashing.
- Refresh credit accounting matched the expected program-side bound: raw `1`,
  graded `2`, total `3`.
- Non-refresh read paths remained local and reported `0` credits.

Audit caveat:

- The provider dashboard daily-remaining counter was not independently captured
  before and after the smoke. The local route-reported credit total was exactly
  `3`, which satisfies the program-side smoke gate. If the external dashboard is
  later checked, expected daily counter movement for this smoke is exactly `3`.

## Follow-On

Session E is now unblocked for scoping/build planning, with the additional
acceptance requirement that E must include an off-hot-path comparison between the
homegrown `/api/poke` outputs and PPT/external-provider outputs. Any unexplained
material divergence must be classified and fixed or explicitly documented as an
intentional source-policy difference.
