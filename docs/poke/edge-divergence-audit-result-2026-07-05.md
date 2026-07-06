# E Validation Gate - API vs External Divergence Audit

Date: 2026-07-05
Status: PASS
Commit under test: 718e73b (`feat(poke): build Session E personal edge layer`)

## Scope

This records the first operator-approved Session E external divergence audit.
The audit compared the owned `/api/poke` read-first values against the external
provider through `edge_cli divergence-audit`.

This was an off-hot-path audit only. It did not change read-path behavior, did
not add any auto-buy behavior, and did not tune local values to match the
external provider.

## Command

```text
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli divergence-audit --products journey_together_booster_bundle,prismatic_evolutions_etb --assets umbreon_ex_161_raw_nm,umbreon_ex_161_psa10 --yes --json
```

## Credit Accounting

```text
estimated credits: 5
credits spent: 5
hard_stopped: false
failed: false
```

Breakdown:

- sealed products: 2 credits
- raw asset: 1 credit
- graded asset: 2 credits

## Results

| Subject | Ours | External | Category | Blocking | Note |
|---|---:|---:|---|---|---|
| `journey_together_booster_bundle` | 49.94 | 49.56 | `agree` | false | 0.77% delta, within tolerance |
| `prismatic_evolutions_etb` | 176.17 | 172.06 | `agree` | false | 2.39% delta, within tolerance |
| `umbreon_ex_161_raw_nm` | null | 1528.09 | `source_policy_difference` | false | Local read path has no sold-derived asset comp yet; external has one |
| `umbreon_ex_161_psa10` | null | 6925.5 | `source_policy_difference` | false | Local read path has no sold-derived asset comp yet; external has one |

## Decision

PASS:

- The two sealed comparisons agreed with the external provider inside the
  configured tolerance.
- The two raw/graded differences are explained source-policy differences, not
  unexplained material divergences.
- No row was blocking.
- The command reported the surfaced credit spend and completed without a hard
  stop.

## Follow-On

The next quality gate is not another blind external audit. The raw/graded rows
currently prove policy separation: the external provider can quote the assets,
but the local read-first ledger has no sold-derived asset comp persisted for
them. To compare raw/graded values directly, first populate or refresh the local
asset comp ledger through an approved source path, then rerun the divergence
audit on the same asset keys.
