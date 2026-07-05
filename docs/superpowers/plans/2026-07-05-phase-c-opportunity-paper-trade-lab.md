# Phase C — Opportunity + Paper-Trade Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the private sealed price API (Tracks A+B) into a Money Hypothesis Lab — deterministic opportunity scoring, append-only paper-trade decision recording, outcome marking/replay, and read-only report surfaces — so the program can test whether its own Pokémon deal hypotheses would have made money.

**Architecture:** A new pure scoring engine (`opportunities.py`) consumes the existing owned comp response + momentum summary + optional discovery/deal candidate rows and emits deterministic `Opportunity` records. A separate append-only JSONL ledger (`paper_ledger.py`, mirroring `discovery/ledger.py`) records immutable paper decisions and, as *separate linked rows keyed by `opportunity_id`*, outcomes — "current state" is always a fold, never an edit. An orchestrator + CLI (`lab.py`) builds opportunities from live deps and drives record/outcome/report. New **read-only** GET endpoints in `router.py` expose opportunities, the decision/outcome replay, and a signals report. All of it is structurally PPT-free and network-free on the read path (`refresh` semantics unchanged).

**Tech Stack:** Python 3.11+ stdlib only (dataclasses, hashlib, json, argparse). No new dependencies. `pytest` (network-mocked). Reuses `scanner/margin.py`, `scanner/verdict.py`, `scanner/poke_api/history.py`, `scanner/poke_api/model.py`.

## Global Constraints

- **Price accuracy is STOP-class.** No source → no number. `expected_net`/`expected_roi_pct`/`discount_pct` are `None` (never `0`, never MSRP-as-if-a-price) whenever a *verified entry price* or a *comp* is absent. Every surfaced price carries its source + capture date via the evidence lines. — from `CLAUDE.md`, `docs/poke/private-price-api.md`.
- **No new margin/verdict math.** `expected_net`, `expected_roi_pct`, `verdict_tier` are computed by the *same* functions the alert path uses: `margin.FeeModel(from cfg)` → `margin.cost_basis(entry, cfg.tax_rate)` → `margin.net_margin(cost, comp, "ebay", shipping, fees)` → `verdict.buy_verdict(margin, confidence, verdict.thresholds_from_config(cfg))`. This mirrors `scanner/main.py:verdict_for_alert` exactly; the numbers must match the alert path. — doctrine anchor from the design spec.
- **Config: cite, do not re-declare.** Fees/tax/shipping and the *paper* BUY floor come from the existing `deal_intelligence` config (correct units: fractions not percents; includes the `$0.40` fixed fee). The new `opportunity:` section carries ONLY genuinely-new business policy: the *stricter live floor* and per-trade-type `max_hold_days` / `exit_venue`. Unset business policy surfaces as `TBD_OPERATOR_POLICY`, never invented. — `docs/poke/policy-provenance-audit.md` §Findings P3.
- **No hindsight mutation.** A recorded decision row is immutable. Outcomes are separate append-only rows keyed by `opportunity_id`. Corrections are new lines, never edits. — design-spec doctrine.
- **No live purchase logic, no network on the read path, no PPT call.** The only "live" surface is a `LIVE_PACKET_ELIGIBLE` decision hint for later human action. Every new response continues to report `apiCallsConsumed`-free / 0-credit posture.
- **Never push to any remote. Never install dependencies.** `config.yaml` / `data/state.db` are gitignored. `data/poke/price_history.jsonl` is read-only evidence — never rewritten.
- **Sealed-only now, but keep fields future-compatible** (`asset_class` present; singles/graded are Phase D).
- **Full suite must stay green.** Baseline captured this session: **616 passed**.

## Reconstructed assumptions (mission prompt was truncated mid-config)

The mission text cut off after the `opportunity:` YAML block (pieces 1–2 detailed; pieces 3–5 named in the intro + the 6-question framing but not literally specified). These are reconstructed from: the intro scope ("opportunity scoring, paper-trade decision recording, outcome marking/replay, and API/report surfaces"), the 6-question framing, and the design-spec's ledger/`decide()`/outcome patterns (re-homed into `poke_api`). **Each is called out here so the review checkpoint catches a wrong guess before code depends on it:**

1. **Build in `scanner/poke_api/`, NOT `scanner/discovery/taxonomy.py`+`paper_ledger.py`.** The design spec's discovery-integrated realization is a *different, not-yet-built* alternative; building it too would create a conflicting duplicate. We harvest its doctrine, not its file layout. (A note lands in the docs so a future session doesn't build both.)
2. **Outcome marking/replay is IN Phase C** (the design spec deferred it to "Track F"; the mission pulls it forward). Hence the `paper_ledger` records both decision and outcome row kinds now.
3. **Write path is a CLI + programmatic functions, not new HTTP POST routes.** Recording a paper decision / marking an outcome are operator-gated actions; the HTTP surface stays GET-only reads (consistent with the existing read-first API). Revisit if the operator wants POST endpoints.
4. **`opportunity:` config re-declares fees/tax/paper-floor → intentionally dropped** in favor of citing `deal_intelligence` (see Global Constraints). The `opportunity:` section keeps only the live floor + hold/exit business policy.
5. **"Signals working over time" (Q6) = a fold over recorded decisions+outcomes** (hit-rate + realized net by trade_type / decision), surfaced via `GET /api/poke/signals` and `lab.py report`.

## Doctrine anchors harvested from the design spec (location-independent)

- **Three orthogonal axes, never collapsed:** *trade_type* (which money hypothesis) / *decision_hint* (PAPER_BUY / WATCH / REJECT / LIVE_PACKET_ELIGIBLE) / (future) terminal bucket. Kept distinct on the record.
- **Anchor to the existing evidence spine, not a parallel gate.** `LIVE_PACKET_ELIGIBLE` is reachable only through a verified entry price + attributed comp + sufficient discount + confidence + fresh data + a BUY verdict clearing the *stricter* live floor — the same spine the alert path already requires. No opportunity becomes live-eligible by a path the alert logic wouldn't bless.
- **`decide()` is a total function** (every input maps to a decision; unexpected states fall to `WATCH`, never raise).

---

## File Structure

- **New:** `scanner/poke_api/opportunities.py` — pure `Opportunity` model, `classify_trade`, scoring, `decide`. No I/O, no clock (`as_of` passed in).
- **New:** `scanner/poke_api/paper_ledger.py` — append-only decision+outcome ledger, immutability + idempotent append, `current_by_id` fold, `signals_report`. Mirrors `discovery/ledger.py`.
- **New:** `scanner/poke_api/lab.py` — orchestrator (`build_opportunities` from deps) + CLI (`list` / `record` / `record-all` / `outcome` / `report`). Small I/O boundary.
- **Modify:** `scanner/poke_api/router.py` — read-first comp resolution extracted to a shared helper; new GET endpoints `/opportunities`, `/opportunities/{key}`, `/paper-decisions`, `/signals`; `PokeApiDeps` + `build_deps` extended with `opp_cfg`, `read_decisions`, `candidate_for`.
- **Modify:** `scanner/config.py` — `OpportunityCfg` dataclass + parse under `opportunity:`; add `opportunity` field to `Config`.
- **Modify:** `config.example.yaml` — `opportunity:` section (live floor + hold/exit), TBD-annotated, with a comment that fees/tax/paper-floor are cited from `deal_intelligence`.
- **New tests:** `tests/test_poke_opportunities.py`, `tests/test_poke_paper_ledger.py`, `tests/test_poke_lab.py`; additions to `tests/test_poke_api_router.py` (or the existing poke-router test module) and `tests/test_config.py`.
- **New doc:** `docs/poke/money-hypothesis-lab.md`; update the "Current limitations / C" line in `docs/poke/private-price-api.md`.
- **Untouched:** `margin.py`, `verdict.py`, `history.py`, `model.py` internals, the alert path, `price_history.jsonl`, the golden/schema belts.

---

## Data models

### `Opportunity` (frozen dataclass in `opportunities.py`)

```
opportunity_id: str        # sha256(f"{product_key}|{trade_type}|{as_of}")[:24-ish full hex]
product_key: str
name: str
asset_class: str = "sealed"
as_of: str                 # ISO date passed in (evidence as-of; drives id stability + staleness)
hypothesis: str            # from the trade type
trade_type: str            # one of the 5 sealed_* keys
live_eligible: bool        # may this trade type EVER be LIVE_PACKET_ELIGIBLE
entry_price: float | None  # verified retail buy price from candidate; None if unconfirmed
market_comp: float | None  # comp estimate (owned shape); None on no_match/no_comp
unopenedPrice: float | None  # PPT-compatible alias of market_comp
msrp: float | None
discount_pct: float | None # (comp - entry)/comp * 100, both present & comp>0; else None
expected_net: float | None # margin.dollar_margin via reuse; None if entry or comp absent
expected_roi_pct: float | None
verdict_tier: str          # BUY | THIN | SKIP | n/a  (from buy_verdict; n/a when net not computed)
momentum_delta_pct: float | None
momentum_status: str       # no_history | single_observation | ok
latest_confidence: str | None
source_count: int
source_agreement: str      # agree | partial | single | none  (derived from confidence+count)
stale: bool
hold_days: int | str       # cfg.opportunity.max_hold_days[type] or "TBD_OPERATOR_POLICY"
exit_venue: str            # cfg.opportunity.exit_venue[type] or "TBD_OPERATOR_POLICY"
evidence: list[str]        # human-readable, each carries source/date where numeric
risks: list[str]
decision_hint: str         # PAPER_BUY | WATCH | REJECT | LIVE_PACKET_ELIGIBLE
score: float               # deterministic 0..100
score_breakdown: dict[str, float]  # component -> signed contribution
```

`asdict(opportunity)` is the JSON row used by the API, the CLI, and the ledger snapshot.

### Ledger rows (`paper_ledger.py`, one immutable JSON object per line in `data/poke/paper_decisions.jsonl`)

Decision row:
```
{"entry_id": sha256("decision|{opportunity_id}|{decision}|{as_of}"),
 "kind": "decision", "opportunity_id", "product_key", "trade_type", "hypothesis",
 "decision", "decision_reason", "as_of", "recorded_at",
 "entry_price", "market_comp", "msrp", "discount_pct",
 "expected_net", "expected_roi_pct", "verdict_tier", "latest_confidence",
 "momentum_delta_pct", "momentum_status", "stale", "score"}
```

Outcome row (separate, keyed by `opportunity_id`; never edits the decision):
```
{"entry_id": sha256("outcome|{opportunity_id}|{status}|{observed_at}"),
 "kind": "outcome", "opportunity_id", "status",   # SOLD|HELD|PRICE_UP|PRICE_DOWN|EXPIRED|VOID
 "observed_at", "realized_price": float|None, "realized_net": float|None, "note": str}
```

`recorded_at`/`observed_at`/`as_of` are **passed in** (no clock in pure/core code; the CLI supplies today).

---

## Trade taxonomy (5 sealed types) — `classify_trade`, first-match-wins, facts-only

| key | hypothesis (short) | live_eligible |
|---|---|---|
| `sealed_catalog_gap` | product lacks enough comp/history data; improve before acting | no |
| `sealed_stale_comp` | comp exists but is stale; not safe for action, refresh first | no |
| `sealed_retail_arbitrage` | verified retail price materially below current market comp | **yes** |
| `sealed_momentum_watch` | appreciating/strengthening, but no buyable entry confirmed yet | no |
| `sealed_no_edge` | no current actionable edge | no |

`classify_trade(product, comp, momentum, candidate, cfg) -> str`, evaluated in order (first match wins):

1. `market_comp is None` (comp `no_match`/`no_comp`) **or** `momentum_status == "no_history"` → `sealed_catalog_gap`.
2. `stale is True` (comp/momentum staleness) → `sealed_stale_comp`.
3. `entry_price is not None` and `market_comp is not None` and `discount_pct is not None` and `discount_pct >= cfg.poke.min_discount_pct` → `sealed_retail_arbitrage`.
4. `momentum_status == "ok"` and `momentum_delta_pct is not None` and `momentum_delta_pct > 0` → `sealed_momentum_watch`.
5. else → `sealed_no_edge`.

Classification is independent of the eventual decision (an arbitrage that fails the fee-adjusted verdict is still that *hypothesis*; its `decision_hint` records the failure as `REJECT`).

---

## Scoring — deterministic, rules-first, 0..100 (no ML)

`score_opportunity` fills `score_breakdown` (signed contributions) then `score = round(clamp(0, 100, sum(breakdown.values())), 1)`. Weights (constants at module top, easily tuned):

| component | rule | range |
|---|---|---|
| `discount` | `min(discount_pct, 50)/50 * 30` when discount_pct not None, else 0 | 0..30 |
| `net` | `clamp(expected_net / (2*buy_floor_net), 0, 1) * 25` when expected_net not None, else 0 | 0..25 |
| `roi` | `clamp(expected_roi_pct / (2*buy_floor_roi), 0, 1) * 15` when not None, else 0 | 0..15 |
| `momentum` | `+10` if delta_pct>0 (ok), `+3` if single_observation, `-8` if delta_pct<0, `0` if no_history | -8..10 |
| `confidence` | high `+15`, medium `+9`, low `+3`, none `0` | 0..15 |
| `sources` | agree `+5`, partial `+3`, single `+1`, none `0` | 0..5 |
| `staleness_penalty` | `-15` if stale else 0 | -15..0 |
| `no_history_penalty` | `-10` if momentum_status == no_history else 0 | -10..0 |
| `risk_penalty` | `-4` per risk in {high_premium_over_msrp, single_source_comp, declining_momentum}, capped at `-12` | -12..0 |

`buy_floor_net`/`buy_floor_roi` are read from cfg (`deal_intelligence.verdict`, cited). Positive components sum to ≤100; penalties pull down. Fully deterministic and explainable via `score_breakdown`.

`source_agreement` derivation: `source_count>=2 and confidence=="high"` → `agree`; `source_count>=2 and confidence=="medium"` → `partial`; `source_count>=1` → `single`; else → `none`.

`risks` derivation (facts only): `stale` → `stale_comp`; `momentum_status in {no_history, single_observation}` → `thin_history`; `confidence in {low, none}` → `low_confidence_comp`; `source_count<=1` → `single_source_comp`; `market_comp and msrp and market_comp/msrp-1 > 0.5` → `high_premium_over_msrp`; `momentum_delta_pct is not None and <0` → `declining_momentum`; `entry_price is None and market_comp is not None` → `no_verified_entry`.

`evidence` derivation (STOP-class, each numeric line carries source/date):
- comp: `f"market comp ${comp} from {source} ({confidence}) as of {checkedAt}"` (source/date from the comp response `sources`/`checkedAt`).
- momentum: `f"momentum {status}: {delta_pct:+}% ({first_seen}→{last_seen})"`.
- entry: `f"verified entry ${entry_price} at {retailer} ({source})"` when candidate present.
- discount: `f"entry {discount_pct}% below comp"` when computed.
- expected: `f"expected net ${expected_net} / {expected_roi_pct}% ROI on eBay (after fees+tax)"` when computed.

---

## `decide()` — decision_hint mapping (total function)

`decide(trade_type, live_eligible, verdict_tier, entry_price, market_comp, stale, discount_pct, live_clear, cfg) -> (decision, reason)`:

| condition (first match) | decision | reason |
|---|---|---|
| `live_eligible` and entry & comp present and not stale and `verdict_tier=="BUY"` and `live_clear` | `LIVE_PACKET_ELIGIBLE` | "verified buyable + clears live floor" |
| trade `sealed_retail_arbitrage` and `verdict_tier=="BUY"` | `PAPER_BUY` | which live requirement is missing (net/roi/conf/stale) |
| trade `sealed_retail_arbitrage` and `verdict_tier=="SKIP"` | `REJECT` | "fee-adjusted margin below skip floor" |
| trade `sealed_retail_arbitrage` and `verdict_tier=="THIN"` | `WATCH` | "thin margin / capped confidence" |
| trade in {`sealed_catalog_gap`,`sealed_stale_comp`,`sealed_momentum_watch`} | `WATCH` | the trade hypothesis (improve data / refresh / no entry yet) |
| else (`sealed_no_edge`) | `WATCH` | "no current actionable edge" |

`live_clear = expected_net is not None and expected_roi_pct is not None and expected_net >= cfg.opportunity.live_min_expected_net and expected_roi_pct >= cfg.opportunity.live_min_roi_pct and confidence_ge(latest_confidence, cfg.opportunity.live_min_confidence)`. Non-live-eligible types can NEVER be `LIVE_PACKET_ELIGIBLE` regardless of numbers. This makes the operator's acceptance tests direct unit tests (no comp ⇒ WATCH; unknown/absent entry ⇒ not live; low confidence ⇒ PAPER_BUY/WATCH; verified high-conf margin + arbitrage ⇒ LIVE_PACKET_ELIGIBLE).

---

## Config — `OpportunityCfg`

```python
@dataclass(frozen=True)
class OpportunityCfg:
    live_min_expected_net: float = 25.0   # stricter than paper buy_floor_net (15) — TBD_OPERATOR_POLICY
    live_min_roi_pct: float = 30.0        # stricter than paper buy_floor_roi (20)   — TBD_OPERATOR_POLICY
    live_min_confidence: str = "medium"   # TBD_OPERATOR_POLICY
    stale_after_days: int = 30            # default mirrors poke.staleness_days
    max_hold_days: dict[str, int] = field(default_factory=dict)   # empty => TBD per type
    exit_venue: dict[str, str] = field(default_factory=dict)      # empty => TBD per type
```

Parsed under `opportunity:` in `from_mapping`, validated (`live_min_confidence` in `VALID_CONFIDENCE`; numbers via `_num`; `max_hold_days` values int, `exit_venue` values str). `config.example.yaml`:

```yaml
opportunity:
  # NOTE: fees, tax, shipping, and the PAPER buy floor are NOT re-declared here —
  # they are cited from deal_intelligence (correct units + the $0.40 fixed fee) so
  # opportunity net/ROI matches exactly what the alert path shows.
  # Only genuinely-new business policy lives here. Unset per-type values below
  # surface as TBD_OPERATOR_POLICY and are never invented.
  live_min_expected_net: 25.00     # TBD_OPERATOR_POLICY (stricter than paper $15 floor)
  live_min_roi_pct: 30.0           # TBD_OPERATOR_POLICY (stricter than paper 20%)
  live_min_confidence: medium      # TBD_OPERATOR_POLICY
  stale_after_days: 30
  max_hold_days:
    sealed_retail_arbitrage: 45
    sealed_momentum_watch: 90
  exit_venue:
    sealed_retail_arbitrage: ebay
    sealed_momentum_watch: ebay
```

---

## `lab.py` — orchestrator + CLI

- `build_opportunities(deps, *, as_of) -> list[dict]`: for each catalog product, resolve read-first comp (shared `router` helper), momentum (`history.momentum`), optional candidate (`deps.candidate_for(product_key)`), then `opportunities.score_opportunity(...)`. Pure given deps; no network.
- `summary(opps) -> {count, by_decision, by_trade_type, by_momentum_status, live_packet_eligible}`.
- CLI `python -m scanner.poke_api.lab <cmd>` (uses real `build_deps`, today from clock at the boundary only):
  - `list [--json]` — scored opportunities + summary.
  - `record --product KEY --decision D [--reason R] [--as-of DATE]` — one paper decision.
  - `record-all [--as-of DATE]` — record each opportunity's `decision_hint` (paper-mode auto-record).
  - `outcome --opportunity ID --status S [--price P] [--net N] [--note ...] [--observed-at DATE]`.
  - `report [--json]` — signals report (hit-rate + realized net by trade_type/decision) + decision/outcome replay.
- Writes go to `data/poke/paper_decisions.jsonl` under the config `ROOT` (tests point it at a temp path). Reads `price_history.jsonl` as evidence, never writes it.

## `router.py` — new GET endpoints (read-only)

- `GET /api/poke/opportunities` → `{ok, count, summary, opportunities:[...]}` (read-first, no network).
- `GET /api/poke/opportunities/{product_key}` → single opportunity detail or 404.
- `GET /api/poke/paper-decisions` → `{ok, decisions:[...current fold...]}` (decision + current outcome per opportunity_id).
- `GET /api/poke/signals` → `{ok, signals:{...}}` (the `signals_report`).
- Extract `_resolve_comp_row(deps, key, product)` from `_comp` (cached → ledger latest → None) and reuse in `_comp`, `_sealed_products`, and opportunities so behavior stays identical (regression: existing router tests must still pass).
- `PokeApiDeps` gains `opp_cfg: OpportunityCfg`, `read_decisions: Callable[[], list[dict]]`, `candidate_for: Callable[[str, dict], dict | None] = lambda *_: None`. `build_deps` wires `cfg.opportunity`, the decisions ledger reader, and a default no-candidate provider (candidates are a future discovery-wire; the read API works without them).

---

## Tasks

Each task is TDD: write the failing test, run it red, implement minimally, run green, commit. Run the **full suite** (`.venv/Scripts/python.exe -m pytest -q`) at the end of each task; it must stay ≥616.

### Task 0 — `OpportunityCfg` config
**Files:** Modify `scanner/config.py`; Modify `config.example.yaml`; Test `tests/test_config.py`.
**Produces:** `config.OpportunityCfg`; `Config.opportunity: OpportunityCfg`.
- [ ] Test: loading a mapping with an `opportunity:` block yields the typed values; defaults apply when absent; bad `live_min_confidence` → `SystemExit`; `max_hold_days`/`exit_venue` parse to dict.
- [ ] Implement `OpportunityCfg` + parse in `from_mapping`; add field to `Config`; add the `opportunity:` block to `config.example.yaml` with the TBD comments above.
- [ ] Full suite green. Commit `feat(config): opportunity business-policy config (Phase C)`.

### Task 1 — `opportunities.py` (pure engine)
**Files:** Create `scanner/poke_api/opportunities.py`; Test `tests/test_poke_opportunities.py`.
**Consumes:** owned comp response (`model.comp_response` shape), momentum dict (`history.momentum` shape), optional candidate dict (`{source, url, item_name/title, retailer, verified_price, in_stock, matched_product_key}`), `cfg`.
**Produces:** `Opportunity`, `classify_trade`, `score_opportunity`, `decide`, `opportunity_id`, and a `compute_margin(entry, comp, confidence, product, cfg)` helper that reproduces `verdict_for_alert`'s assembly and returns `(expected_net, expected_roi_pct, verdict_tier)` or `(None, None, "n/a")`.
- [ ] Test `compute_margin` matches `main.verdict_for_alert` numbers for a known (entry, comp) and returns `(None,None,"n/a")` when either is None.
- [ ] Test `classify_trade` returns each of the 5 types for fixture inputs (no comp→gap; stale→stale_comp; entry+discount→arbitrage; ok+positive momentum→momentum_watch; else→no_edge).
- [ ] Test `decide` mapping table — one assertion per row (incl. no comp ⇒ WATCH; low-conf arbitrage BUY ⇒ PAPER_BUY; verified high-conf arbitrage clearing live floor ⇒ LIVE_PACKET_ELIGIBLE; non-live-eligible type never LIVE).
- [ ] Test `score_opportunity` is deterministic, `0<=score<=100`, `score_breakdown` sums (pre-clamp) to score, staleness/no-history/risk penalties apply, and STOP-class: no entry ⇒ `expected_net is None`, `discount_pct is None`.
- [ ] Implement to green. Commit `feat(poke): opportunity model + scoring engine (Phase C)`.

### Task 2 — `paper_ledger.py` (append-only decisions + outcomes)
**Files:** Create `scanner/poke_api/paper_ledger.py`; Test `tests/test_poke_paper_ledger.py`.
**Produces:** `decision_entry_id`, `outcome_entry_id`, `build_decision_row`, `append_row`, `record_decision`, `record_outcome`, `read_rows`, `decisions`, `outcomes`, `current_by_id`, `signals_report`.
- [ ] Test append idempotency: re-recording the same (opportunity_id, decision, as_of) is a no-op; a different decision appends a correction line; the first line is never removed (immutability).
- [ ] Test outcome rows are separate, keyed by opportunity_id; `current_by_id` folds to `{opportunity_id: {decision, outcome}}` with latest-wins; a second outcome doesn't erase the decision.
- [ ] Test `signals_report` computes per-trade_type and per-decision counts, and for opportunities with a realized-net outcome, a hit-rate (net>0) and mean realized net.
- [ ] Test missing/ malformed ledger file reads as empty (mirrors `history.read_ledger`).
- [ ] Implement to green (mirror `discovery/ledger.py` immutability). Commit `feat(poke): append-only paper-trade ledger + signals fold (Phase C)`.

### Task 3 — `lab.py` (orchestrator + CLI)
**Files:** Create `scanner/poke_api/lab.py`; Test `tests/test_poke_lab.py`.
**Consumes:** `router.PokeApiDeps` (extended in Task 4 — build Task 4's deps shape here first if needed, or use a local deps struct and reconcile). **Produces:** `build_opportunities`, `summary`, `main(argv)`.
- [ ] Test `build_opportunities` over injected deps (fake products + comp_provider + ledger observations + candidate_for) yields one opportunity per product with correct decision_hint; no network.
- [ ] Test CLI `record` then `outcome` then `report` round-trips through a temp ledger path and the report reflects the outcome; `list --json` emits valid JSON; `record-all` records every hint.
- [ ] Implement to green. Commit `feat(poke): money-hypothesis lab orchestrator + CLI (Phase C)`.

### Task 4 — `router.py` endpoints + deps wiring
**Files:** Modify `scanner/poke_api/router.py`; Test the poke-router test module.
**Produces:** `_resolve_comp_row` shared helper; `_opportunities`, `_opportunity`, `_paper_decisions`, `_signals`; extended `PokeApiDeps` + `build_deps`.
- [ ] Test existing comp/history/momentum/sealed-products responses are byte-for-byte unchanged after the `_resolve_comp_row` extraction (regression).
- [ ] Test `/api/poke/opportunities` returns scored opportunities + summary with injected deps; `/opportunities/{key}` 404s an unknown key; `/paper-decisions` and `/signals` return the fold/report; all report 0-credit / no-network.
- [ ] Implement to green. Commit `feat(api): expose opportunities, paper-decisions, signals endpoints (Phase C)`.

### Task 5 — docs
**Files:** Create `docs/poke/money-hypothesis-lab.md`; Modify `docs/poke/private-price-api.md` (flip the "C — not built" limitation line).
- [ ] Document the 5 trade types, `decide()` table, scoring, the ledger/immutability + replay, the CLI, the new endpoints, the config (with the TBD business-policy note + the "not building `discovery/taxonomy.py`" reconciliation note).
- [ ] Full suite green. Commit `docs(poke): document Money Hypothesis Lab (Phase C)`.

---

## Testing (maps to the mission's 6 questions + acceptance intuitions)

1. Opportunity answers Q1–Q4: `trade_type`+`hypothesis` (what/why), `evidence`+`risks` (support/weaken), `decision_hint` (buy/watch/reject/live).
2. Ledger answers Q5: record → outcome → `current_by_id` replay (immutability proven).
3. `signals_report` answers Q6: hit-rate + realized net by signal.
4. STOP-class: no comp / no entry ⇒ `None` numbers, never fabricated; every numeric evidence line carries source/date.
5. `LIVE_PACKET_ELIGIBLE` only via the verified evidence spine + stricter live floor; non-eligible types never reach it.
6. Determinism: same inputs ⇒ same `opportunity_id`, `score`, `decision_hint`.
7. No-network / 0-credit on every new read surface.
8. Full suite stays green (≥616).

## Rollback

Additive and reversible: three new modules + one JSONL are inert if unused; reverting the router endpoints + config field restores prior behavior with no migration (`paper_decisions.jsonl` is disposable append-only history, like `price_history.jsonl`).

## Self-review (run after drafting, before executing)

- **Spec coverage:** pieces 1 (opportunities+scoring), 2 (config), 3 (recording), 4 (outcome/replay), 5 (report/API) each map to a task. ✔
- **Placeholder scan:** every task has concrete test intent + interfaces; scoring/decide/ledger-identity are fully specified above. ✔
- **Type consistency:** `expected_net`/`expected_roi_pct`/`verdict_tier` names match `margin.MarginResult.dollar_margin`/`roi_pct` and `verdict.Verdict.tier`; `opportunity_id` identical in `Opportunity`, ledger rows, and folds. ✔
