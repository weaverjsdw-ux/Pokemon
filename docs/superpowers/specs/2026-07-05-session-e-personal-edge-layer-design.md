# Session E — Personal Edge Layer (Design Spec)

Date: 2026-07-05
Status: APPROVED for build (operator go-ahead in the Session E prompt; D.5 gates +
one operator-approved live smoke are satisfied — see
[`live-smoke-result-d5-external-card-source.md`](../../poke/live-smoke-result-d5-external-card-source.md)).

## 1. Mission & identity

Session E is the program's **own personal edge layer** built on top of the owned
`/api/poke` evidence spine (Tracks A–D + the Phase C Money-Hypothesis Lab). The
product identity is **our API and our decision layer**. PPT / external-card output
is only an optional adapter or an **off-hot-path audit oracle** — never the program
identity, never on a read path, never a source of truth we tune to blindly.

E is *not* another D.5 adapter pass. It adds a decision/ranking/packet layer that
turns owned evidence (comp + momentum + verified candidates + asset history) into a
first-class **edge packet** with an explainable decision, and adds an
operator-gated divergence audit that compares our answers to the external provider
and classifies any disagreement.

## 2. Hard boundaries (non-negotiable)

- No auto-buy. No cart / checkout / login / bot-wall work.
- No hidden live network calls. No billed PPT/external calls unless the operator
  explicitly approves *during the session* (a `--yes` gate + a configured key).
- No PPT hot path. Read endpoints are structurally 0-credit.
- No fabricated prices, gem rates, comps, fees, confidence, or entry prices. No
  source → no number (STOP-class). Every numeric claim carries a source + date or
  is `null`.
- No live eligibility outside the verified evidence spine.
- No broad unrelated refactors. No push.

## 3. What already exists (the spine E builds on — do NOT rebuild)

- `poke_api/opportunities.py` — deterministic sealed `Opportunity` + scoring +
  `decide()` (LIVE only via `sealed_retail_arbitrage`). Raw/graded assets get
  conservative **WATCH-only** opportunities that are **never** live in D
  (`build_asset_opportunity`, decision hardcoded `WATCH`).
- `poke_api/candidates.py` — the verified-entry wire + STOP-class `entry_evidence_ok`
  gate + append-only `verified_candidates.jsonl` + `candidate_for_provider`.
- `poke_api/lab.py` — orchestrator (`build_opportunities`, `build_asset_opportunities`,
  `resolve_comp_row`, `resolve_asset_comp_row`, `activation_report`) + Phase C CLI.
- `poke_api/paper_ledger.py` — append-only decisions/outcomes keyed on
  `opportunity_id`, bucketed by `trade_type`; `signals_report`, `current_by_id`.
- `poke_api/sources.py` — `ExternalCardPriceClient` (dormant; `limit=1`), raw/graded
  resolvers, `expected_asset_credits` credit bound.
- `poke_api/router.py` — dispatch; `/api/poke/*` served by `web.py` with **no web.py
  change needed** for new `/api/poke/edge-*` routes.
- `margin.py` / `verdict.py` — the exact alert-path money math E reuses (no new math).
- `comps/ppt_validator.py` — the existing sealed PPT spot-check with money-class
  guardrails. **Left untouched**; E's audit is a superset, additive module.

## 4. Architecture — new units (each one clear responsibility)

| Unit | Responsibility | Depends on |
|---|---|---|
| `poke_api/edge.py` | The `EdgePacket` model + builders + edge decision policy + source posture. The core edge layer. | opportunities, candidates, grading_ev, lab, margin, verdict |
| `poke_api/grading_ev.py` | Pure raw→graded grading-EV math. Blocks on any missing input. | margin |
| `poke_api/divergence.py` | Off-hot-path API-vs-external divergence classifier + comparison engine (pure classify + injected clients). | market, sources, resale |
| `poke_api/edge_cli.py` | Aligned CLI: list/show packets, record paper decision/outcome from a packet, run the divergence audit (dry/local vs operator-gated external). | edge, divergence, paper_ledger, router |
| `poke_api/router.py` (edit) | Add 3 read-only 0-credit routes: `/edge-packets`, `/edge-packets/{id}`, `/edge-summary`. | edge |
| `poke_api/candidates.py` (edit) | Additive: asset-keyed verified candidates (`asset_key/condition/grade_key` fields) + disjoint sealed/asset folds. | — |
| `poke_api/catalog.py` (edit) | Additive: surface optional `gem_rate` / `gem_rate_source` on the asset summary. | — |

All new read paths are pure: no network, no clock (`as_of`/`today` injected), no
writes. The divergence audit is the only surface that can spend credits, and only
under an explicit `--yes` + configured key.

## 5. Slice A — Edge packet model (`edge.py`)

`EdgePacket` is a frozen dataclass understandable without reading internals. Every
numeric field carries provenance or is `None`.

```
EdgePacket(
  edge_packet_id: str          # sha256(subject_key | trade_type | as_of) — SAME recipe as opportunity_id
  subject_key: str             # product_key (sealed) or asset_key (raw/graded)
  subject_kind: str            # "product" | "asset"
  asset_class: str             # "sealed" | "raw" | "graded"
  name: str
  as_of: str
  thesis: str                  # human hypothesis text (from trade_type)
  trade_type: str              # sealed_* (== underlying opp) OR raw_/graded_verified_arbitrage OR *_grading_ev
  decision_hint: str           # REJECT | WATCH | DATA_NEEDED | PAPER_BUY | LIVE_PACKET_ELIGIBLE
  decision_reason: str
  score: float                 # reuse opportunities.score_opportunity (0..100)
  blockers: list[str]          # named, ordered, most-proximate first
  evidence: list[str]          # STOP-class: every numeric line carries source + date
  risks: list[str]
  source_stack: list[str]      # source slugs behind the comp, in order
  source_posture: list[str]    # deterministic tags (Slice E)
  comp_provenance: dict|None    # {estimate, confidence, basis, primary_source, checked_at, stale}
  entry_provenance: dict|None   # {entry_price, retailer, candidate_id, stock_evidence, stock_checked_at, observed_at, source} or None
  expected_net: float|None
  expected_roi_pct: float|None
  verdict_tier: str            # BUY | THIN | SKIP | n/a
  grading_ev: dict|None         # Slice D block (raw packets only, else None)
  provider_dependency: dict     # {comp_is_external_origin, external_only, requires_external_refresh, used_external_on_read=False}
  status: dict                 # {stale, missing_comp, confidence}
  input_snapshot: dict         # curated candidate provenance for append-only audit (== paper_ledger snapshot)
  # asset identity (None for sealed)
  condition: str|None
  grader: str|None
  grade: str|None
  card_number: str|None
)
```

- `edge_packet_id == opportunities.opportunity_id(subject_key, trade_type, as_of)`
  and the packet dict also carries `opportunity_id` = the same value, so
  `paper_ledger.record_decision(packet_dict)` unifies into the one Phase C ledger
  and `signals_report` buckets by `trade_type` cleanly. New asset trade types
  become new signal buckets; sealed packets keep the underlying opportunity's
  `trade_type` verbatim.
- Serialization: `to_dict()` = `dataclasses.asdict`; ids are deterministic
  (sha256, no clock). Same inputs → identical packet + id (tested).
- `input_snapshot` reuses the candidate provenance curated by
  `opportunities._input_snapshot` so the audit trail runs verified evidence →
  packet → recorded decision, immutably.

## 6. Slice B — Verified-entry expansion for raw/graded (`candidates.py`, additive)

Extend the Phase C wire so raw/graded assets can receive verified entry candidates
**without weakening the gate**. The STOP-class `entry_evidence_ok` gate is unchanged.

1. `VerifiedCandidate` gains three optional fields (default `""`):
   `asset_key`, `condition`, `grade_key`. `candidate_id` does **not** hash them
   (existing ids/rows unchanged; existing tests unaffected). `make_candidate` accepts
   them. For an asset candidate the caller sets `asset_class in {raw,graded}` +
   `asset_key` + the identity discriminator (`condition` for raw, `grade_key` for
   graded).
2. **Disjoint folds** (the critical correctness fix — asset and product key strings
   can be equal, per `test_asset_and_product_routes_do_not_collide_on_a_shared_key`):
   - `current_entry_candidates(rows)` (sealed) now **excludes** any row with
     `asset_class in {raw,graded}` — sealed opportunities never absorb an asset
     candidate. (Behavior unchanged for all existing sealed-only rows, which are
     `asset_class == "sealed"`.)
   - New `current_asset_entry_candidates(rows)` folds entry-verified rows with
     `asset_class in {raw,graded}`, keyed on the explicit **`asset_key`**, latest
     wins by `observed_at`.
   - New `asset_candidate_for_provider(rows)` → `asset_candidate_for(asset_key, asset)`
     returning only an entry-verified asset candidate whose `asset_class` **and**
     identity (`condition`/`grade_key`) match the asset (collision-proof), else None.
3. A candidate is **buy-shaped** only when it clears the existing gate: positive
   buyable `stock_status` + observed price > 0 + `buy_url` + `stock_evidence` +
   `stock_checked_at` + `observed_at` + `source`/`retailer` + asset identity
   precise enough to avoid raw/graded/condition collisions. Unverified candidates
   stay evidence rows (`entry_price=None`); they can explain WATCH / DATA_NEEDED but
   can never create PAPER_BUY / LIVE_PACKET_ELIGIBLE.

## 7. Slice C — Decision policy (`edge.py`)

One deterministic edge decision across sealed / raw / graded. Allowed hints:
`REJECT | WATCH | DATA_NEEDED | PAPER_BUY | LIVE_PACKET_ELIGIBLE`.

Edge trade taxonomy (superset of the sealed types):

```
LIVE_ELIGIBLE_EDGE = {
  "sealed_retail_arbitrage",     # existing sealed live path (unchanged)
  "raw_verified_arbitrage",      # NEW: raw single, verified entry vs raw comp
  "graded_verified_arbitrage",   # NEW: graded slab, verified entry vs graded comp
}
```

`decide_edge(asset_class, market_comp, stale, entry_price, verdict_tier,
expected_net, expected_roi_pct, latest_confidence, trade_type, cfg)`:

1. `market_comp is None` → **DATA_NEEDED** (+ blocker `"no comp"`). No dollars.
2. else if `trade_type in LIVE_ELIGIBLE_EDGE` and `entry_price is not None` and not
   `stale` and `verdict_tier == "BUY"` and it clears the **stricter live floor**
   (`expected_net ≥ opportunity.live_min_expected_net`,
   `expected_roi_pct ≥ opportunity.live_min_roi_pct`,
   `confidence ≥ opportunity.live_min_confidence`) → **LIVE_PACKET_ELIGIBLE**.
3. else if it is a `*_arbitrage` type with a verified entry:
   `BUY` → **PAPER_BUY**; `SKIP` → **REJECT**; `THIN` → **WATCH**.
4. else → **WATCH** (catalog/momentum/stale evidence — non-live-eligible).

Guarantees:
- `LIVE_PACKET_ELIGIBLE` remains strictly stricter than `PAPER_BUY` and is reachable
  **only** through: verified entry price + attributed comp + fresh data + sufficient
  confidence + fee-adjusted `BUY` verdict + stricter live floor + a live-eligible
  trade type. (Same as Phase C for sealed; the new asset arbitrage types are the
  ONLY way raw/graded becomes buy-shaped.)
- A D-era raw/graded WATCH row **cannot** become live just because it has a comp: an
  asset's edge trade type is `raw_verified_arbitrage`/`graded_verified_arbitrage`
  **only** when `asset_candidate_for` returns an entry-verified candidate; with no
  verified asset entry the asset stays WATCH / DATA_NEEDED (evidence only).
- Money math is the exact alert-path composition via `opportunities.compute_margin`
  (`margin.net_margin` + `verdict.buy_verdict`); no new math. No verified entry or no
  comp → dollar fields `None`.

`opportunities.py` is **not** modified — the D "assets never live" guarantee and its
tests stay intact; E computes the asset buy decision entirely in the edge layer.

## 8. Slice D — Grading EV (`grading_ev.py`)

Pure raw→graded EV. `grading_ev(*, raw_entry, raw_comp, graded_comp, grading_fee,
gem_rate, fees, target_grade, ship_insurance=0.0, downside_comp=None, sources)`:

**Required inputs (missing ANY → blocked, DATA_NEEDED/WATCH + named blocker; never
invent):** `raw_entry` (verified), `raw_comp`, `graded_comp` (for the target grade),
`grading_fee` (config `poke.grading_cost_all_in`, source/date stamped), resale
`fees` (config), and `gem_rate` (asset `gem_rate` field with `gem_rate_source`, or an
operator assumption labeled `operator_assumption`). `ship_insurance` optional.

Model (honest, explainable):
- `cost = cost_basis(raw_entry, tax) + grading_fee + ship_insurance`
- `upside_net = net_margin(graded_comp, ebay) − cost`  (gem hit at target grade)
- `downside_net = net_margin(downside_comp or raw_comp, ebay) − cost`  (non-gem;
  basis labeled explicitly — "downside modeled at raw comp; PSA9 comp not supplied"
  unless a real lower-grade comp is provided)
- `expected_net = gem_rate·upside_net + (1−gem_rate)·downside_net`
- `expected_roi_pct = expected_net / cost · 100`
- `downside_case = downside_net`

Output block: `{status, expected_net, expected_roi_pct, downside_net, target_grade,
gem_rate, gem_rate_basis, grading_fee, grading_fee_basis, assumptions[], blockers[],
reason}`. `status ∈ {actionable, watch, blocked}`. **Never LIVE**: grading EV rests
on an operator gem-rate assumption (not verified-data confidence), so in Session E a
grading-EV opportunity is capped at **PAPER_BUY**; it lifts a raw packet's top-level
decision to `PAPER_BUY` only when it is `actionable` (all inputs present, verified
raw entry, fee-adjusted EV clears the paper `BUY` floor). Raw→graded pairing is never
guessed: the graded sibling is matched on `tcgplayer_id` + an explicit target
`grade_key`.

## 9. Slice E — Source & comp posture (`edge.py`)

`source_posture(comp)` → a deterministic **list** of tags derived from the comp's own
data provenance (source slugs / status / stale / confidence), **not** from any
live-call state (read paths never call external). Tags (may co-apply):

- `missing_comp` — `estimate is None` and no ok sold/graded source.
- `ask_only_context` — the only source present is an eBay active ask and
  `estimate is None` (ask is context, never sold-comp truth).
- `stale_comp` — `comp.stale`.
- `single_source` — exactly one contributing source.
- `local_only` — has a local-origin source (`tcgplayer`/`pricecharting`/`inhouse`/
  `ledger`) and no external-origin source.
- `external_only` — has an external-origin source (`ppt_cards`) and no local-origin.
- `local_plus_external_audit` — has both.

Read paths default to `used_external_on_read=False` and never mint `estimate` from an
ask. `provider_dependency` on the packet exposes `comp_is_external_origin`,
`external_only`, and `requires_external_refresh` (no local comp; only a billed
refresh would resolve one).

## 10. Slice F — API surfaces (`router.py`, read-only, 0 credits)

- `GET /api/poke/edge-packets` — all edge packets (sealed + raw + graded), score desc.
- `GET /api/poke/edge-packets/{edge_packet_id}` — one packet; clear **404** for an
  unknown id (`ok:false`, `httpStatus:404`).
- `GET /api/poke/edge-summary` — compact roll-up: counts by decision / asset_class /
  trade_type / posture, live-eligible count, top blockers, dormancy note.

Built from `deps` (opportunities + assets + candidates), read-first. Tests assert a
**counting/failing card client is never called** (0 billed calls) on every edge
route — the same belt as `/opportunities`.

## 11. Slice G — CLI surfaces (`edge_cli.py`, `python -m scanner.poke_api.edge_cli`)

- `list [--json] [--asset-class ...] [--decision ...]` — list edge packets.
- `show --id <edge_packet_id> [--json]` — one packet.
- `record --id <edge_packet_id> [--decision D] [--reason R] [--as-of DATE]` — record a
  paper decision **from an edge packet** into `paper_decisions.jsonl` (reuses
  `paper_ledger.record_decision`; ids unify with Phase C).
- `outcome --id <edge_packet_id> --status S [--price P] [--net N] [--note ...]` — mark
  an outcome (reuses `paper_ledger.record_outcome`).
- `divergence-audit [--products ...] [--assets ...] [--local] [--yes] [--json]` — run
  the audit in dry/local mode by default (0 network, 0 credits); external/PPT
  comparison only with explicit `--yes` **and** a configured key.

## 12. Slice H — API vs PPT/external divergence audit (`divergence.py` + CLI)

Off-hot-path comparison between our `/api/poke` outputs and PPT/external outputs.
Never used by any read endpoint.

- **Dry/local mode (default):** classifies our comp vs an **already-recorded external
  observation in the ledger** (source slug `ppt_cards`) at **zero network / zero
  credits**. If there is no recorded external observation for a subject it reports
  `no_external_reference` (not a failure). Fully testable, no key required.
- **External mode (`--yes` + configured key):** money-class guardrails mirror
  `ppt_validator`: refuse without `market.api_key`; print the **estimated spend**
  before any call (sealed 1 credit; raw 1; graded 2 — `limit=1` pinned); **hard-stop**
  before the next subject if the configured remaining-credit floor
  (`HARD_STOP_REMAINING = 15`) would be violated; refuse without `--yes`. Assets use
  `ExternalCardPriceClient`; sealed uses `PokemonPriceTrackerClient` — both injectable
  for hermetic tests.

`classify_divergence(ours, theirs, *, tolerance_pct, ...)` → one of:
`mapping_error`, `stale_local`, `stale_external`, `source_policy_difference`,
`ask_vs_sold_difference`, `fee_assumption_difference`, `confidence_method_difference`,
`provider_payload_issue`, `unexplained_material_divergence`, plus `agree` (within
tolerance) and `no_external_reference`. Classification is explained (why our answer or
theirs is more defensible — we do **not** tune blindly to PPT). A
**material unexplained divergence fails the audit command (exit 1)** and is documented
as blocking. Materiality = magnitude beyond `comps.agreement_tolerance_pct` with no
explanatory category.

## 13. Slice I — UI / report surface

The web dashboard is a large JS SPA served as static assets + `/api/status`. A full
dashboard card is out of scope for a clean, bounded change. Instead E ships:
- `GET /api/poke/edge-summary` (JSON report endpoint), and
- `edge_cli.py list` / `show` (compact human-readable board),

which are the documented report surface. A dashboard "Edge" card is recorded as a
scoped follow-on in the runbook (do **not** omit the API/CLI core to chase UI).

## 14. Slice J — Documentation

Update `docs/poke/private-price-api.md` (E section: personal edge layer, endpoints,
posture, live gate), `docs/poke/money-hypothesis-lab.md` (edge packets + asset
verified-entry route + grading EV + divergence audit), a short E follow-through
pointer in `docs/poke/live-smoke-result-d5-external-card-source.md`, and a new
`docs/poke/edge-layer-runbook.md` (packet/audit usage + the credit/`--yes` gate + the
dashboard-card follow-on). Docs must state: E is our edge layer not PPT cloning;
PPT/external comparison is audit-only; read paths are 0 credits; live/billed calls
need explicit operator approval; divergences are investigated, not auto-treated as our
bug.

## 15. Fee / grading / gem-rate assumption posture (STOP-class)

- **eBay fees:** reuse the config `deal_intelligence` fee model
  (`ebay_fvf_pct 0.1325`, `ebay_fixed_fee 0.40`, tax, shipping, `local_haircut_pct`)
  — the **same** model the alert path uses, so packet net/ROI matches the alert path
  exactly. This is a **labeled config assumption**, not a claim of the current
  collectibles FVF (~13.6–15%) or the ≥$1,000-card 50% FVF discount. Any such
  difference is exactly what the divergence `fee_assumption_difference` category
  exists to surface — we label the assumption, we do not silently claim it is
  conservative.
- **Grading fee:** `poke.grading_cost_all_in` (default `97.50`), stamped
  `"PSA Regular $79.99 all-in; value tiers paused 2026-06 (psacard.com/info/submission-updates)"`.
  Turnaround (40–50 business days as of 2026-06) is volatile → documented, never used
  in the EV math.
- **Gem rate:** no config/source exists → it is **never invented**. It must come from
  the asset's `gem_rate` field (+ `gem_rate_source`) or an operator assumption labeled
  `operator_assumption`; absent → grading EV blocks with a named blocker.

## 16. Testing (TDD — failing test first per slice)

Model: deterministic packet + id serialization; sealed packet from an opportunity;
raw/graded packet from an asset. Decision: no comp → DATA_NEEDED (no dollars);
ask-only → context only, no comp truth; verified raw/graded entry can create a
buy-shaped packet; unverified raw/graded candidate cannot; LIVE only through the
evidence spine; a D-era WATCH-with-comp asset never goes live without an E verified
entry. Grading EV: missing gem rate blocks; missing any required input blocks;
computes net/ROI only when all assumptions exist. API: edge endpoints read-only +
0-credit (counting/failing card client), unknown id → clear 404. CLI: list/show
paths. Divergence: dry/local classifies at 0 credits; refuses external without
`--yes`; classifies material unexplained divergence as a failure. Regressions: D.5
asset comp refresh accounting unchanged; existing `/opportunities` no billed calls;
disjoint candidate folds don't cross sealed/asset.

## 17. Out of scope / follow-ons (explicit)

- Dashboard "Edge" card (report endpoint + CLI ship now; the SPA card is a follow-on).
- Grading-EV-driven LIVE eligibility (capped at PAPER_BUY this session — gem rate is
  an operator assumption, not verified-data confidence).
- eBay Browse live keyed stock/price check (still keyset-gated; Browse stays
  ask/candidate context — active FIXED_PRICE listings, never sold comp).
- Provider actual-credit-header accounting on the asset refresh path (still the
  documented deterministic upper bound).
