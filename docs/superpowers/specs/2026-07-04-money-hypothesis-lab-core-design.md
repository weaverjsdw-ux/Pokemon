# Money Hypothesis Lab — Core (Tracks B + C + D) Design

**Date:** 2026-07-04
**Status:** design, pending operator spec-review → writing-plans
**Scope:** Tracks B (trade taxonomy), C (paper ledger), D (decision output). Tracks
A and G are complete (see `docs/poke/slickdeals-track-a-classification-2026-07-04.md`
and `docs/poke/policy-provenance-audit.md`). Tracks E (manual live packet) and F
(outcome tracking) are a **separate follow-on spec** that builds on C's ledger.

## Goal

Make the discovery pipeline record — for **every** candidate that reaches a
decision point, not only alerts — *which money hypothesis it tested, what the
program decided, and why*, in a durable append-only ledger with no hindsight
mutation. A no-alert run must still produce learning: where the funnel broke and
which hypothesis failed. This is paper mode; the only "live" surface is a
`LIVE_PACKET_ELIGIBLE` tag that Track E will later export for **human** action.

## Non-goals (this pass)

- No live network run (Track A is paper-first; a smoke stays operator-gated).
- No new source, no eBay activation, no `comps.engine` flip, no scheduler.
- No new moralizing boundary language (operator instruction; Track G governs).
- No mutation of the existing alert path, evidence belts, or golden gate.
- No invented business policy — unset parameters are `TBD_OPERATOR_POLICY`.

## Doctrine anchors (all load-bearing)

- **Three orthogonal axes, never collapsed:** existing *terminal bucket* (funnel
  disposition, `pipeline.TERMINAL_BUCKETS`) / new *trade-type* (which hypothesis)
  / derived *decision* (PAPER_BUY / WATCH / REJECT / LIVE_PACKET_ELIGIBLE).
- **Anchor to the existing evidence spine, not a parallel gate.** A candidate is
  `LIVE_PACKET_ELIGIBLE` only if it already reached `alerted` (VERIFIED_BUYABLE +
  `assert_alertable` + attributed comp + `pct_off ≥ min_discount` +
  ring-3⇒conf-floor + dedupe) **and** its trade-type is live-eligible **and** it
  clears the live floor. No candidate becomes live-eligible by a path that would
  not have alerted.
- **No hindsight mutation.** A recorded `PaperDecision` is immutable. Track F
  outcomes will be *separate linked rows* keyed by `decision_id`; "current
  outcome" is a fold over them.
- **Price accuracy unchanged (STOP-class).** The Lab reads comp/verify facts the
  pipeline already produced; it never fabricates a price or comp.

---

## Track B — Trade taxonomy: `scanner/discovery/taxonomy.py` (pure, no I/O)

```python
@dataclass(frozen=True)
class TradeType:
    key: str
    hypothesis: str                 # the money claim this type tests
    required_inputs: tuple[str, ...]
    required_evidence: tuple[str, ...]
    comp_source_requirements: str
    confidence_floor: str           # "low"|"medium"|"high" — the type's own floor
    hold_time: str                  # "" => TBD_OPERATOR_POLICY (never invented)
    exit_venue: str                 # "ebay"|"local"|"" (=> TBD)
    fee_assumptions: str            # cites margin.FeeModel; never re-invents rates
    rejection_reasons: tuple[str, ...]
    live_eligible: bool             # may EVER reach LIVE_PACKET_ELIGIBLE
    live_requirements: tuple[str, ...]
```

Seven registered types (constant tuple `TRADE_TYPES`, key → def map `BY_KEY`):

| key | hypothesis (short) | conf_floor | live_eligible | hold/exit |
|---|---|---|---|---|
| `catalog_msrp_restock` | verified retail below sealed comp clears fee-adj margin | medium | **yes** | TBD / ebay default |
| `slickdeals_arbitrage` | community deal, merchant-verified, nets margin | medium | **yes** | TBD / ebay default |
| `ebay_underpriced_bin` | active BIN below comp | medium | **no** (keyset-gated) | TBD / ebay |
| `promo_exclusive_premium` | PC/exclusive promo carries premium | high | **no** | **TBD / TBD** |
| `bundle_partout` | bundle < Σ component value | high | **no** | TBD / TBD |
| `release_window` | new-set timing; comps immature | high | **no** | TBD / TBD |
| `watch_only` | interesting, missing stock/comp/source-confidence | n/a | **no** | — |

`hold_time`, `exit_venue` for types 3–7, and any per-type live-floor overrides
are the empty string ⇒ surfaced as `TBD_OPERATOR_POLICY`. `fee_assumptions` cite
`margin.FeeModel` (eBay FVF 13.25% + $0.40 fixed; local haircut 15%) and the
`margin.cost_basis` tax gross-up — cited, never re-declared.

### Classifier

```python
def classify_trade(candidate, verification, comp_row, product) -> TradeType
```

Pure, deterministic, **first match wins**, in this order (facts only — no
network, no clock):

1. `product` flagged promo/exclusive (e.g. Pokémon Center exclusive marker on the
   catalog product) → `promo_exclusive_premium`.
2. candidate is a bundle (`asset_class == "bundle"` or title bundle markers reused
   from `resale`) → `bundle_partout`.
3. `product` in a release window (catalog `release_date` within
   `taxonomy.RELEASE_WINDOW_DAYS` of `captured_at`, when that metadata exists) →
   `release_window`.
4. `candidate.source == "ebay_browse"` → `ebay_underpriced_bin`.
5. `candidate.source == "slickdeals"` → `slickdeals_arbitrage`.
6. `candidate.matched_product_key` present (Ring 1 catalog) → `catalog_msrp_restock`.
7. else → `watch_only`.

Classification is independent of outcome: a `slickdeals_arbitrage` that fails to
verify is still that *hypothesis*; its *decision* (below) records the failure.

---

## Track C — Paper ledger: `scanner/discovery/paper_ledger.py`

Append-only JSONL at `data/poke/paper_decisions.jsonl`, reusing `ledger.py`'s
immutability contract (one immutable JSON object per line; sha256 identity;
corrections appended as new lines, never edits). **Separate file** from
`price_history.jsonl` (that ledger's docstring scopes it to market observations).

```python
@dataclass(frozen=True)
class PaperDecision:
    decision_id: str        # sha256(f"{source}|{listing_id}|{sweep_id}") — stable, replay-safe
    sweep_id: str
    captured_at: str        # passed in; no clock in pure code
    source: str
    listing_url: str
    title: str
    ring: str               # "ring1:<catalog_key>" | "ring2:<set>" | "ring3"
    trade_type: str         # TradeType.key
    hypothesis: str         # TradeType.hypothesis (what was tested)
    verified_price: float | None
    shipping_tax_assumption: str   # cites FeeModel + tax gross-up, or "n/a"
    comp_value: float | None
    comp_basis: str
    confidence: str
    expected_net: float | None     # see "margin/verdict derivation" below
    expected_roi_pct: float | None
    verdict_tier: str       # BUY|THIN|SKIP, or "n/a" — see derivation below
    decision: str           # PAPER_BUY|WATCH|REJECT|LIVE_PACKET_ELIGIBLE
    decision_reason: str
    diagnostic: str         # ""|SOURCE_BLOCKED|PARSER_SUSPECT|PRICE_MISMATCH|NO_COMP|below_*|out_of_stock
    terminal_bucket: str    # the existing pipeline bucket (audit link)
```

**Margin/verdict derivation.** `expected_net`, `expected_roi_pct`, and
`verdict_tier` are computed by the **same pure functions the alert path already
uses** — `margin.net_margin(cost_incl_tax, comp, channel, est_shipping, fees)`
and `verdict.buy_verdict(margin_result, comp_confidence, thresholds)` — fed the
`verified_price` (grossed up by `margin.cost_basis` with the config tax rate) and
the resolved `comp`. When comp or price is absent they are `None`/`"n/a"` (never
0-as-real). The exact reuse (extract the components from the existing
`main.verdict_for_alert` call vs. call `margin`/`verdict` directly in the
post-step) is a planning detail; either way no new margin math is introduced and
the numbers match what the alert path would show.

Functions:
- `build_decision(...) -> PaperDecision` — pure; assembles the row from facts the
  pipeline already holds.
- `append_decision(path, decision) -> bool` — idempotent by `decision_id`
  (re-recording the same candidate in the same sweep is a no-op), mirroring
  `ledger.append_observation`.
- `read_decisions(path) -> list[dict]` / `current_by_id(path) -> dict[str, dict]`
  — the fold Track F will extend (latest row per `decision_id`). This pass only
  writes decision rows; F adds outcome rows.

### Decision mapping — pure `decide()`

`decide(terminal_bucket, verify_state, trade_type, verdict_tier, comp_confidence,
live_floor) -> (decision, decision_reason, diagnostic)`:

| terminal_bucket (+ state) | decision | diagnostic |
|---|---|---|
| `alerted` + `trade.live_eligible` + verdict `BUY` + conf ≥ `live_floor` | `LIVE_PACKET_ELIGIBLE` | "" |
| `alerted` / `suppressed_dupe` (else) | `PAPER_BUY` | reason = which live requirement is missing |
| `below_min_discount` | `REJECT` | `below_min_discount` |
| `below_confidence` | `WATCH` | `below_confidence` |
| `no_comp` | `WATCH` | `NO_COMP` |
| `unverifiable` (state `SOURCE_BLOCKED`) | `WATCH` | `SOURCE_BLOCKED` |
| `unverifiable` (state `PARSER_SUSPECT`) | `WATCH` | `PARSER_SUSPECT` |
| `unverifiable` (other) | `WATCH` | `unverifiable` |
| `out_of_stock` | `REJECT` | `out_of_stock` |
| `price_mismatch` | `REJECT` | `PRICE_MISMATCH` |

`live_floor` is a config value `discovery.live_packet_floor` **defaulting to the
paper BUY floor** (`verdict.VerdictThresholds`: net ≥ $15, ROI ≥ 20%, conf ≥
medium), documented as `TBD_OPERATOR_POLICY` so the operator can tighten it later
with no code change. `watch_only` trade type has `live_eligible=False`, so it can
never be `LIVE_PACKET_ELIGIBLE` regardless of bucket.

This table makes the operator's acceptance tests direct unit tests:
no comp ⇒ WATCH · unknown stock ⇒ WATCH · low confidence ⇒ WATCH/PAPER_BUY ·
verified high-conf margin + live-eligible trade ⇒ LIVE_PACKET_ELIGIBLE.

---

## Track D — Decision output

**Manifest.** `run_once` adds two keys:
- `manifest["decisions"]` — list of `asdict(PaperDecision)` (one per candidate).
- `manifest["decision_summary"]` — `{by_decision: {...}, by_trade_type: {...},
  by_diagnostic: {...}, live_packet_eligible: N}`.

Both are also attached to `manifest["board"]` so the renderer can read them.
**Invariant (asserted):** `len(decisions) == len(candidates) == len(outcomes)` —
every candidate produces exactly one decision, no silent drops (mirrors the
existing counts-reconcile assert).

**Dashboard (light).** A new `#hypothesis-lab` section (new template placeholder
`{{HYPOTHESIS_LAB}}`) renders the `decision_summary` counts and a compact table
grouped by decision (LIVE_PACKET_ELIGIBLE → PAPER_BUY → WATCH → REJECT), each row
showing title, trade-type, verified/comp/net/ROI/confidence, and diagnostic. Buy
URLs pass through the existing `_safe_href` allowlist. **The Buyable-now golden
belt and STOP gate are untouched** — the Lab section is additive and never claims
buyability the belts don't already permit.

---

## Wiring & data flow

In `pipeline.run_once`'s per-candidate loop, after `_classify` returns
`(bucket, reason)` (unchanged), add a pure post-step:

```python
trade = taxonomy.classify_trade(c, v, comp_row, product)
decision = paper_ledger.build_decision(c, v, comp_row, comp, comp_conf,
                                       verdict_tier, bucket, reason, trade,
                                       sweep_id, captured_at, live_floor)
manifest_decisions.append(asdict(decision))
if not dry_run and ledger_path is not None:
    paper_ledger.append_decision(decisions_path, decision)
```

- `_classify` already computes `comp_row`, `comp`, `comp_conf`, and builds the
  row/verdict; to avoid recomputation the post-step is fed those facts. Minimal
  refactor: `_classify` returns a small `ClassifyResult` (bucket, reason,
  comp_row, comp, comp_conf, verdict_tier, product) instead of a bare tuple, OR
  the loop re-derives the few facts it needs. **Chosen:** extend `_classify`'s
  return to a lightweight dataclass; the bucket/reason semantics are identical,
  so the manifest counts and every existing test still pass.
- **Dry-run writes nothing** (matches the existing listing-ledger gate:
  `ledger_path is not None and not dry_run`); the in-memory `manifest["decisions"]`
  is still produced so `--dry-run` reporting shows the funnel.
- Live-run path writes `data/poke/paper_decisions.jsonl` next to
  `price_history.jsonl` under the `--out` root (isolated smoke → temp root, never
  repo `data/poke`).

## Error handling

- Taxonomy and decide() are total functions (every input maps to a type/decision);
  an unexpected bucket falls to `WATCH`/`unverifiable` diagnostic, never raises.
- `append_decision` failure must never abort a run (same posture as the notifier
  belt): catch, print a one-line stderr notice, continue — the board and every
  other candidate's disposition still complete.
- No comp / no price ⇒ `expected_net`/`expected_roi_pct` are `None`, never 0-as-real.

## Testing (maps 1:1 to the operator's acceptance list)

New `tests/test_disc_taxonomy.py`, `tests/test_disc_paper_ledger.py`, and
additions to `tests/test_poke_pipeline.py`:

1. `classify_trade` returns the right type for each of the 7 (fixture candidates).
2. `decide()` mapping table — one assertion per row above.
3. **paper ledger records candidates without network** (dry-run in-memory
   decisions produced; live write only when `ledger_path` set + not dry-run).
4. **no comp → no live packet** (`no_comp` ⇒ WATCH).
5. **unknown stock → no live packet** (`unverifiable` ⇒ WATCH).
6. **low confidence → PAPER_BUY or WATCH, not live** (`below_confidence` ⇒ WATCH;
   live-eligible trade with sub-live-floor conf ⇒ PAPER_BUY).
7. **verified high-confidence margin → LIVE_PACKET_ELIGIBLE** (end-to-end with an
   injected verifier + comp, `catalog_msrp_restock`).
8. **outcome update does not rewrite original decision** — deferred to Track F,
   but the ledger's immutability + `current_by_id` fold is unit-tested now
   (appending a second row with the same `decision_id` doesn't remove the first).
9. **ledger immutability / stable id / idempotent re-append**.
10. **manifest invariant**: `len(decisions) == candidates == outcomes`.
11. **policy audit completeness** (`tests/test_policy_audit.py`): each of the 8
    boundary categories has ≥1 catalogued occurrence at a known file:line, so a
    deleted boundary or renamed doc fails loudly.
12. Full suite stays green (currently 577).

## Files

- **New:** `scanner/discovery/taxonomy.py`, `scanner/discovery/paper_ledger.py`,
  `tests/test_disc_taxonomy.py`, `tests/test_disc_paper_ledger.py`,
  `tests/test_policy_audit.py`.
- **Changed:** `scanner/discovery/pipeline.py` (per-candidate post-step +
  `_classify` return shape + manifest keys + decisions write),
  `scanner/discovery/render.py` + its template (new `#hypothesis-lab` section),
  `config.example.yaml` (`discovery.live_packet_floor`, TBD-annotated),
  `docs/poke/buyable-pipeline-runbook.md` (document the ledger + decision output).
- **Untouched:** verify/resolve/comps/margin/verdict logic, golden/schema belts,
  the alert path.

## Rollback

Additive and reversible: the two new modules and the JSONL are inert if unused;
reverting the pipeline post-step and the render placeholder restores prior
behavior with no migration (`paper_decisions.jsonl` is disposable append-only
history, like `price_history.jsonl`).
