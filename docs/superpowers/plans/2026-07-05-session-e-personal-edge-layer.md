# Session E — Personal Edge Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use test-driven-development for every
> task — failing test first, watch it fail, minimal code to pass, commit. Steps use
> checkbox (`- [ ]`) syntax.

**Goal:** Build the personal edge layer on the owned `/api/poke` spine — first-class
edge packets, a raw/graded verified-entry route, a cross-asset decision policy,
grading EV, source posture, read-only 0-credit endpoints, a CLI, and an
operator-gated API-vs-external divergence audit.

**Architecture:** New pure modules `edge.py`, `grading_ev.py`, `divergence.py`,
`edge_cli.py`; additive edits to `candidates.py` (asset-keyed folds), `catalog.py`
(gem_rate passthrough), `router.py` (3 read routes). `opportunities.py`,
`ppt_validator.py`, `web.py` untouched. Reuse `margin`/`verdict`/`opportunities`
math; no new money math.

**Tech Stack:** Python 3, stdlib + existing scanner modules; pytest (network-mocked).

**Test command:** `.venv/Scripts/python.exe -m pytest -q`

---

## File structure

- Create `scanner/poke_api/edge.py` — EdgePacket + builders + `decide_edge` + `source_posture`.
- Create `scanner/poke_api/grading_ev.py` — pure grading EV.
- Create `scanner/poke_api/divergence.py` — classify + compare engine.
- Create `scanner/poke_api/edge_cli.py` — CLI (`python -m scanner.poke_api.edge_cli`).
- Modify `scanner/poke_api/candidates.py` — add `asset_key/condition/grade_key`;
  disjoint sealed fold; `current_asset_entry_candidates` + `asset_candidate_for_provider`.
- Modify `scanner/poke_api/catalog.py` — add `gem_rate`, `gem_rate_source` to `_SUMMARY_FIELDS`.
- Modify `scanner/poke_api/router.py` — add edge routes + wire asset candidate provider into deps.
- New tests: `tests/test_poke_edge.py`, `tests/test_poke_grading_ev.py`,
  `tests/test_poke_edge_api.py`, `tests/test_poke_edge_cli.py`,
  `tests/test_poke_divergence.py`; extend `tests/test_poke_candidates.py`.

---

## Task 1: Asset-keyed verified candidates (Slice B)

**Files:** Modify `scanner/poke_api/candidates.py`; Test `tests/test_poke_candidates.py`.

- [ ] **Step 1: Failing tests** — append to `test_poke_candidates.py`:
  - `test_asset_candidate_carries_identity`: `make_candidate(..., asset_class="graded",
    asset_key="umbreon_psa10", grade_key="psa10", stock_status="verified_buyable", full
    evidence)` → `entry_verified is True`, `asset_key == "umbreon_psa10"`,
    `grade_key == "psa10"`.
  - `test_sealed_fold_excludes_asset_rows`: a verified sealed row (product_key `k`,
    asset_class sealed) and a verified asset row (asset_key `k`, asset_class graded)
    with the SAME key string → `current_entry_candidates(rows)` returns only the
    sealed one; `current_asset_entry_candidates(rows)` returns only the asset one
    keyed by `asset_key`.
  - `test_asset_candidate_for_matches_identity`: `asset_candidate_for_provider(rows)`
    returns the graded candidate for the psa10 asset but `None` for a psa9 asset
    (grade_key mismatch) and `None` for a raw NM asset (asset_class mismatch).
- [ ] **Step 2: Run — verify fail** (`AttributeError`/missing kwargs).
- [ ] **Step 3: Implement**
  - Add `asset_key: str = ""`, `condition: str = ""`, `grade_key: str = ""` to
    `VerifiedCandidate` (after `asset_class`). `candidate_id` unchanged (does not hash
    them). `make_candidate` accepts `asset_key="", condition="", grade_key=""` and
    passes them through.
  - `current_entry_candidates`: skip rows where
    `str(r.get("asset_class") or "sealed") in {"raw","graded"}`.
  - New `current_asset_entry_candidates(rows)`: like the sealed fold but keep only
    `asset_class in {raw,graded}`, key on `r.get("asset_key")` (skip empties), latest
    wins by `observed_at`.
  - New `asset_candidate_for_provider(rows)` → `asset_candidate_for(asset_key, asset)`:
    fold, then return `to_opportunity_candidate(rec)` only if `rec` exists AND
    `rec.asset_class == asset.asset_class` AND identity matches
    (`condition` for raw, `grade_key` for graded), else None. Add `asset_key`,
    `condition`, `grade_key` to `to_opportunity_candidate`'s output.
- [ ] **Step 4: Run** the new + all existing `test_poke_candidates.py` — PASS.
- [ ] **Step 5: Commit** `feat(poke): asset-keyed verified candidates (Session E Slice B)`.

## Task 2: Grading EV (Slice D)

**Files:** Create `scanner/poke_api/grading_ev.py`; Test `tests/test_poke_grading_ev.py`.

- [ ] **Step 1: Failing tests**
  - `test_missing_gem_rate_blocks`: all inputs but `gem_rate=None` → `status=="blocked"`,
    `expected_net is None`, blocker names `gem rate`.
  - `test_missing_graded_comp_blocks`: `graded_comp=None` → blocked, blocker names comp.
  - `test_computes_ev_when_all_present`: raw_entry 400, raw_comp 500, graded_comp 1000,
    grading_fee 97.5, gem_rate 0.4, config fees → `expected_net`/`expected_roi_pct`
    computed, `downside_net` present and `< upside`, `assumptions` list non-empty,
    `status=="actionable"` when EV clears the paper BUY floor.
  - `test_downside_basis_labeled`: no `downside_comp` supplied → `gem_rate_basis` /
    an assumption line states downside modeled at raw comp.
- [ ] **Step 2: Run — fail** (module missing).
- [ ] **Step 3: Implement** `grading_ev(*, raw_entry, raw_comp, graded_comp,
  grading_fee, gem_rate, fees: FeeModel, tax_rate, est_shipping, target_grade="",
  ship_insurance=0.0, downside_comp=None, buy_floor_net, gem_rate_basis="",
  grading_fee_basis="")` returning a dict. Block (status `blocked`, dollars None) if
  any of raw_entry/raw_comp/graded_comp/grading_fee/gem_rate is None or ≤0
  (gem_rate in (0,1]); else compute per spec §8 using `margin.cost_basis` +
  `margin.net_margin(..., "ebay", ...)`. `status="actionable"` when
  `expected_net >= buy_floor_net`, else `"watch"`. Every number → an assumptions line.
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `feat(poke): grading EV math (Session E Slice D)`.

## Task 3: Source posture + edge decision (Slice C + E, `edge.py` core)

**Files:** Create `scanner/poke_api/edge.py`; Test `tests/test_poke_edge.py`.

- [ ] **Step 1: Failing tests** (posture + decide, pure):
  - `source_posture`: missing → `["missing_comp"]`; ask-only (`sources=[{"source":"ebay"}]`,
    estimate None) → contains `ask_only_context`; single ppt_cards source →
    `external_only` + `single_source`; two sources tcgplayer+ppt_cards →
    `local_plus_external_audit`; stale flag → includes `stale_comp`.
  - `decide_edge`: no comp → `DATA_NEEDED`; sealed arbitrage BUY clearing live floor →
    `LIVE_PACKET_ELIGIBLE`; sealed arbitrage BUY below live floor → `PAPER_BUY`; SKIP →
    `REJECT`; THIN → `WATCH`; `raw_verified_arbitrage` with entry+BUY+clears floor →
    `LIVE_PACKET_ELIGIBLE`; asset market_watch (comp, no entry) → `WATCH`.
- [ ] **Step 2: Run — fail.**
- [ ] **Step 3: Implement** in `edge.py`:
  - `LIVE_ELIGIBLE_EDGE`, `EDGE_TRADE_TYPES` (sealed types re-exported from
    `opportunities.TRADE_TYPES` + `raw_verified_arbitrage`, `graded_verified_arbitrage`,
    `raw_market_watch`/`graded_market_watch`/`*_catalog_gap` + `*_grading_ev`).
  - `_EXTERNAL_SLUGS = {"ppt_cards"}`; `_LOCAL_SLUGS = {"tcgplayer","pricecharting",
    "inhouse","ledger","ledger latest"}`.
  - `source_posture(comp) -> list[str]` per spec §9 (deterministic).
  - `decide_edge(...) -> (hint, reason, blockers)` per spec §7, reusing
    `opportunities._confidence_ge` + `cfg.opportunity` floors.
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `feat(poke): edge decision policy + source posture (Session E Slice C/E)`.

## Task 4: EdgePacket model + builders (Slice A, wiring C/D/E)

**Files:** Modify `scanner/poke_api/edge.py`; Test `tests/test_poke_edge.py`.

- [ ] **Step 1: Failing tests**
  - `test_edge_packet_id_deterministic`: two builds, same inputs → identical
    `edge_packet_id` == `opportunities.opportunity_id(subject_key, trade_type, as_of)`,
    and packet dict carries `opportunity_id` equal to it.
  - `test_sealed_packet_from_opportunity`: build from a sealed arbitrage opp (verified
    candidate) → `decision_hint`, `expected_net`, `entry_provenance` populated,
    `asset_class=="sealed"`, `grading_ev is None`.
  - `test_raw_packet_no_comp_is_data_needed_no_dollars`: raw asset, no comp →
    `DATA_NEEDED`, `expected_net is None`, `comp_provenance is None`, blocker "no comp".
  - `test_raw_packet_ask_only_is_context_only`: raw asset, ask-only comp (estimate
    None) → posture has `ask_only_context`, no dollars, WATCH/DATA_NEEDED.
  - `test_verified_raw_entry_makes_buy_shaped`: raw asset + entry-verified asset
    candidate + confident raw comp clearing floors → `LIVE_PACKET_ELIGIBLE` (or
    `PAPER_BUY` below live floor); `entry_provenance` carries candidate_id + stock evidence.
  - `test_unverified_raw_candidate_not_buy_shaped`: an evidence-only asset candidate
    (entry_verified False) → packet is WATCH, `entry_provenance is None`,
    `decision_hint != PAPER_BUY and != LIVE_PACKET_ELIGIBLE`.
  - `test_grading_ev_block_attached_for_raw`: raw asset with graded sibling comp +
    gem_rate on the asset → `grading_ev` block present with numbers; without gem_rate
    → `grading_ev.status=="blocked"` and a blocker surfaced on the packet.
- [ ] **Step 2: Run — fail.**
- [ ] **Step 3: Implement**
  - `EdgePacket` frozen dataclass (spec §5) + `to_dict` (asdict) + `opportunity_id`
    mirror field.
  - `build_sealed_packet(product_key, product, comp, momentum, candidate, cfg, *, as_of)`:
    reuse `opportunities.build_opportunity` for the base facts (trade_type, score,
    risks, evidence, money math, input_snapshot), then apply `decide_edge` (remaps
    no-comp→DATA_NEEDED; else matches the opp decision), attach posture / provenance.
  - `build_asset_packet(asset_key, asset, comp, momentum, asset_candidate, graded_sibling_comp,
    cfg, *, as_of)`: compute entry_price from `asset_candidate`; classify edge trade
    type (`*_verified_arbitrage` when entry present + comp, else the D
    `*_market_watch`/`*_catalog_gap`); compute margin via `opportunities.compute_margin`;
    `decide_edge`; attach `grading_ev` for raw when a target graded comp + gem_rate
    exist (lift to PAPER_BUY when actionable); posture / provenance / identity fields.
  - `comp_provenance(comp)` / `entry_provenance(candidate)` helpers.
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `feat(poke): EdgePacket model + sealed/asset builders (Session E Slice A)`.

## Task 5: Lab-level edge orchestration + endpoints (Slice F)

**Files:** Modify `scanner/poke_api/edge.py` (orchestrators), `router.py`; Test
`tests/test_poke_edge_api.py`.

- [ ] **Step 1: Failing tests** (router dispatch, injected fakes; mirror
  `test_poke_asset_api.py` patterns):
  - `/api/poke/edge-packets` lists sealed + asset packets, score desc; a
    `_CountingCardClient` (raises on any lookup) is never called → 0 credits.
  - `/api/poke/edge-packets/{id}` returns the matching packet; unknown id → 404,
    `ok:false`.
  - `/api/poke/edge-summary` returns counts by decision/asset_class + live count +
    top blockers; counting card client never called.
  - `test_edge_endpoints_spend_no_credits`: FakeProvider `estimate_calls == 0` across
    all three routes.
  - Regression: `test_opportunities_still_no_billed_calls` unaffected (existing suite).
- [ ] **Step 2: Run — fail** (404 unknown route).
- [ ] **Step 3: Implement**
  - `edge.build_edge_packets(deps, *, as_of) -> list[dict]` = sealed packets for
    `deps.products` (via `resolve_comp_row` + `candidate_for`) + asset packets for
    `deps.assets` (via `resolve_asset_comp_row` + `asset_candidate_for` +
    graded-sibling comp resolution by `tcgplayer_id`+`grade_key`), sorted by score desc.
  - `edge.edge_summary(packets) -> dict`.
  - `router`: `_edge_packets`, `_edge_packet`, `_edge_summary`; dispatch
    `["edge-packets"]`, `["edge-packets", id]`, `["edge-summary"]`.
  - `router.build_deps`: also fold an `asset_candidate_for` from the candidate ledger
    (default) and store on deps as `asset_candidate_for` (default `lambda k,a: None`);
    add the field to `PokeApiDeps`.
- [ ] **Step 4: Run — PASS** (new + `test_poke_asset_api.py` + `test_poke_api_lab_endpoints.py`).
- [ ] **Step 5: Commit** `feat(poke): read-only 0-credit edge endpoints (Session E Slice F)`.

## Task 6: Divergence audit (Slice H)

**Files:** Create `scanner/poke_api/divergence.py`; Test `tests/test_poke_divergence.py`.

- [ ] **Step 1: Failing tests** (pure classify + engine w/ injected clients):
  - `classify_divergence`: within tolerance → `agree`; our estimate present, no
    external ref → `no_external_reference`; ask-only ours vs sold theirs →
    `ask_vs_sold_difference`; large gap, no explanatory category →
    `unexplained_material_divergence` (`material is True`); stale-local flag →
    `stale_local`.
  - `audit_local`: compares our comp vs a ledger `ppt_cards` observation at 0 network;
    returns rows + a `material` count; no client used.
  - `run_audit(..., yes=False)` external mode → refuses (returns/exits with the
    "pass --yes" message), no client call.
  - `run_audit(..., yes=True, remaining below floor)` → HARD STOP before next subject.
  - `run_audit` with a material unexplained divergence → overall `failed True`.
- [ ] **Step 2: Run — fail.**
- [ ] **Step 3: Implement** `divergence.py`:
  - `HARD_STOP_REMAINING = ppt_validator.HARD_STOP_REMAINING` (reuse the constant).
  - `classify_divergence(ours: dict, theirs: dict|None, *, tolerance_pct) -> dict`
    returning `{category, material, delta_pct, defensible, note}` per spec §12.
  - `audit_local(subjects, observations, *, tolerance_pct)` — build our comp via the
    read-first resolvers; external ref = latest ledger obs with source `ppt_cards`.
  - `estimate_spend(subjects)` + `run_audit(deps, subjects, *, yes, local, client_sealed,
    client_asset, tolerance_pct)` with the money-class guardrails (refuse w/o key,
    print spend, `--yes` gate, hard-stop) — injectable clients for tests.
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `feat(poke): API-vs-external divergence audit (Session E Slice H)`.

## Task 7: Edge CLI (Slice G)

**Files:** Create `scanner/poke_api/edge_cli.py`; Test `tests/test_poke_edge_cli.py`.

- [ ] **Step 1: Failing tests** (call `edge_cli.main(argv, deps=...)`, capsys):
  - `list` prints packets; `list --json` emits valid JSON with `edge_packets`.
  - `show --id <id>` prints one; unknown id → non-zero + message.
  - `record --id <id>` appends a decision to a tmp `paper_decisions.jsonl` (idempotent
    on re-run).
  - `outcome --id <id> --status SOLD --net 20` appends an outcome.
  - `divergence-audit --local` runs at 0 credits; `divergence-audit` (external) without
    `--yes` refuses.
- [ ] **Step 2: Run — fail.**
- [ ] **Step 3: Implement** `edge_cli.py` argparse subcommands (`list/show/record/
  outcome/divergence-audit`), reusing `edge.build_edge_packets`,
  `paper_ledger.record_decision/record_outcome`, `divergence.run_audit`. `main(argv,
  *, deps=None)` builds deps lazily like `lab.main`.
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `feat(poke): edge CLI (Session E Slice G)`.

## Task 8: catalog gem_rate passthrough (support D)

**Files:** Modify `scanner/poke_api/catalog.py`; Test `tests/test_poke_catalog.py` (extend).

- [ ] **Step 1: Failing test** — `test_asset_summary_surfaces_gem_rate`: an asset with
  `gem_rate: 0.4` + `gem_rate_source: "operator_assumption 2026-07-05"` →
  `asset_summary` includes both fields.
- [ ] **Step 2: Run — fail.**
- [ ] **Step 3: Implement** — add `"gem_rate"`, `"gem_rate_source"` to `_SUMMARY_FIELDS`.
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `feat(poke): surface gem_rate on asset summary (Session E)`.

## Task 9: Docs (Slice J)

**Files:** Modify `docs/poke/private-price-api.md`, `docs/poke/money-hypothesis-lab.md`,
`docs/poke/live-smoke-result-d5-external-card-source.md`; Create
`docs/poke/edge-layer-runbook.md`.

- [ ] Update the E section of `private-price-api.md` (personal edge layer, endpoints,
  posture, live gate, audit-only external). Flip the "E — Blocked" bullet to BUILT.
- [ ] Add an edge section to `money-hypothesis-lab.md` (packets, asset verified-entry
  route, grading EV assumptions, divergence audit).
- [ ] Add an E follow-through pointer to the D.5 smoke doc.
- [ ] Write `edge-layer-runbook.md` (packet + audit usage, credit/`--yes` gate,
  0-credit read paths, dashboard-card follow-on).
- [ ] Commit `docs(poke): document Session E personal edge layer`.

## Task 10: Full verification + self-review + final commit

- [ ] Run focused: `pytest tests/test_poke_edge*.py tests/test_poke_grading_ev.py
  tests/test_poke_asset*.py tests/test_poke_candidate*.py tests/test_poke_opportunities.py
  tests/test_poke_lab.py tests/test_poke_api_lab_endpoints.py tests/test_poke_divergence.py
  tests/test_poke_catalog.py tests/test_comps_validator.py` — all PASS.
- [ ] Run the full suite `pytest -q` — no regressions.
- [ ] Self-review the diff: no hidden live calls, no scope leak, no fabricated numbers,
  disjoint folds hold, ids unify.
- [ ] Stage only intentional Session E files (leave the 6 unrelated untracked files).
- [ ] Commit `feat(poke): build Session E personal edge layer`. **No push.**

## Self-review (plan vs spec)

- Spec §5 (packet) → Task 4. §6 (candidates) → Task 1. §7 (decide) → Task 3. §8
  (grading EV) → Task 2. §9 (posture) → Task 3. §10 (API) → Task 5. §11 (CLI) → Task 7.
  §12 (divergence) → Task 6. §13 (report) → `edge-summary` (Task 5) + CLI (Task 7).
  §14 (docs) → Task 9. §15 (assumptions) → Tasks 2/8/9. §16 (tests) → every task.
- Type consistency: `edge_packet_id`/`opportunity_id` recipe fixed in Tasks 3–4;
  `decide_edge` signature identical across Tasks 3–5; `asset_candidate_for` name used
  in Tasks 1 + 5. Grading EV block key `grading_ev` used in Tasks 2/4/9.
- No placeholders: each task names files, test cases, and the exact functions/edits.
