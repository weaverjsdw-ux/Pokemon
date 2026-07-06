# E Asset Gate — Persisted Raw/Graded API-vs-External Divergence Audit

Date: 2026-07-05
Status: PASS
Follows: [edge-divergence-audit-result-2026-07-05.md](edge-divergence-audit-result-2026-07-05.md)
(the first Session E audit, where the raw/graded rows returned `ours: null`).

## Scope

This records the second, asset-focused operator-approved external divergence
audit — the follow-on the first audit named. Between the two audits the local
read-first ledger was populated with sold-derived raw/graded comps (see
*Local comp gap fixed* below), so the raw/graded rows now compare **numeric ours
vs numeric external** instead of `null` vs a number.

Off-hot-path, audit-only. It did not change read-path behavior, add any auto-buy
behavior, or tune local values to match the external provider.

## Local comp gap fixed (why the first audit showed `ours: null`)

The D.5 `refresh=true` path (`router._asset_comp` → `sources.resolve_*_comp`)
**computed** a raw/graded comp row and returned it in the HTTP response but never
**persisted** it. Nothing appended an asset `market_comp` to
`data/poke/price_history.jsonl`, so read-first (`lab.resolve_asset_comp_row` →
`history.latest`) — and therefore the external audit's `ours`
(`divergence._our_served`) — found nothing and returned `null`
(`source_policy_difference`).

Fix (smallest durable, repo-native): a provenance-honest `market_comp` writer
(`sources.build_asset_comp_observation` / `record_asset_comp`, identity built from
the shared `history.asset_identity` so the persisted `item_key` byte-matches
read-first) plus a `record-asset-comp` edge CLI command (0-credit from-value
default; operator-gated billed `--refresh`). The two documented D.5 smoke values
were recorded at **0 credits** (already-captured evidence, not a new call):

| Asset | comp | confidence | source | capture_date |
|---|---:|---|---|---|
| `umbreon_ex_161_raw_nm` | 1528.09 | low | `ppt_cards` | 2026-07-05 |
| `umbreon_ex_161_psa10` | 6925.50 | high | `ppt_cards` | 2026-07-05 |

Read endpoints now serve these at **0 credits** (`source: local`), and the edge
packets carry `comp_provenance` (WATCH + comp) instead of `DATA_NEEDED` /
`missing_comp`.

## Command

```text
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli divergence-audit --assets umbreon_ex_161_raw_nm,umbreon_ex_161_psa10 --yes --json
```

## Credit Accounting

```text
estimated credits: 3
credits spent: 3
hard_stopped: false
failed: false
```

Breakdown: raw asset 1 credit + graded asset 2 credits (`limit=1` pinned).

Audit caveat (consistent with the D.5 smoke): the asset external path does not
surface the provider's daily-remaining counter, so no independent dashboard
before/after delta was captured. The route-reported deterministic spend is exactly
`3`. Expected external dashboard daily-counter movement for this audit is `3`.

## Results

| Subject | Ours | External | Category | Blocking | Delta | Note |
|---|---:|---:|---|---|---:|---|
| `umbreon_ex_161_raw_nm` | 1528.09 | 1528.09 | `agree` | false | 0.0% | within agreement tolerance |
| `umbreon_ex_161_psa10` | 6925.50 | 6925.50 | `agree` | false | 0.0% | within agreement tolerance |

## Decision

PASS:

- Both raw/graded rows now compare **numeric ours vs numeric external** (the first
  audit's `ours: null` / `source_policy_difference` is resolved).
- Both agreed within the configured tolerance (0.0% delta).
- No row was blocking; the command reported the surfaced credit spend (3) and
  completed without a hard stop.

## Honest framing (what this PASS does and does not prove)

- **What it proves:** the read-first ledger now serves a real number for these
  assets, and the persisted value round-trips against a fresh same-day provider
  fetch (a persisted-vs-fresh **consistency** check — no staleness, no corruption).
- **What it does NOT prove:** independent-source validation. `ours` was *derived
  from* the same provider (`ppt_cards`) on 2026-07-05; `theirs` is a fresh
  `ppt_cards` call today. This is same-provider consistency, **not** a second
  independent source confirming the price.
- The **local** audit (`divergence-audit --local`) still honestly reports
  `source_policy_difference` for these assets (0 credits): `_local_ours` requires a
  **non-`ppt_cards`** local-origin comp, and we have none. That is correct behavior,
  not a failed fix.
- **Follow-on (independent local source):** map + configure an independent
  sold-derived adapter (TCGplayer / PriceCharting) for these singles. Once a
  non-`ppt_cards` comp is persisted, the **local** audit will compare two
  independent sources numerically and the external PASS becomes a true
  cross-source validation.

## Edge activation status — DORMANT BY DESIGN

E is **built and validated but intentionally dormant** for these assets. Operator
confirmed (2026-07-05) there is **no real operator-verified entry evidence** (no
genuine buyable listing with observed price + stock evidence + buy URL + check
timestamp) for either Umbreon single. Per STOP-class rules no candidate was
fabricated.

Current edge packets (read-first, 0 credits):

| Asset | decision_hint | comp_provenance | blockers |
|---|---|---:|---|
| `umbreon_ex_161_raw_nm` | WATCH | 1528.09 (`ppt_cards`, low) | no verified entry price; grading EV: no raw entry / no gem rate |
| `umbreon_ex_161_psa10` | WATCH | 6925.50 (`ppt_cards`, high) | no verified entry price |

A raw/graded single becomes buy-shaped **only** through the E verified-entry route
(an `asset_key`-keyed, `entry_evidence_ok`-gated verified candidate). With a comp
present but no verified entry, both sit at WATCH with the blocker
`no verified entry price`. Supplying real entry evidence via
`lab candidate-add` / the candidate wire (preserving `asset_key` + `condition` /
`grade_key`) is the single next step to activate; a comp alone never promotes to
PAPER_BUY / LIVE.

## Remaining next step

Independent local sold source for these singles (TCGplayer / PriceCharting
adapter) so the **local** audit becomes a true cross-source check, and — only when
real operator-verified entry evidence exists — a verified asset candidate to move
an asset off WATCH.
