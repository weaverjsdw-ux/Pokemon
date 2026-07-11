# Honest Fee Model + Sealed Credit Accounting Implementation Plan (spec T4 + T5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every margin/EV number net **real, current, versioned** fees (so a real buy is never shown a fake profit) and make every billable sealed path report bounded credit spend or refuse first (no billed call reports 0).

**Architecture:** T4 *extends* the existing pure `FeeModel`/`net_margin` (`scanner/margin.py`) — it is not a rewrite. Fees become **channel-aware** (eBay + TCGplayer), carry **provenance** (`effective_date` + `source_url`), and are selected by date from a small dated **fee schedule** so historical rows keep their era's fees. Grading cost gains the same provenance (PSA value tiers paused; ~$80 floor). T5 mirrors the *already-correct asset credit pattern* (`sources.expected_asset_credits` → `asset_model` `apiCallsConsumed`) onto the sealed refresh route, which today hardcodes `creditsConsumed=0` and then drops the field entirely. Both are Plan 3 of the one-build sequence; the buy loop (T6–T11) is later.

**Tech Stack:** Python 3, `pytest` (network-mocked). No new runtime dependency.

## Global Constraints

- **Package is `scanner/`** (never `target_scanner/`); price subsystem `scanner/poke_api/`.
- **Price/fee accuracy is STOP-class.** Every fee/rate carries a `source_url` + `effective_date`. Estimates are badged; a fee is never fabricated. No source → cite the operator assumption explicitly.
- **Two PIN-FIRST hard gates (operator-mandated, STOP-class).** The eBay ≥$1,000 high-value FVF discount (Task 1) and the PSA grading floor (Task 3) ship **fail-safe** — full FVF / conservative `operator_assumption` grading cost — and are NOT switched to their real values until pinned against the LIVE **eBay Trading Cards category** page and the LIVE **PSA pricing** page respectively, cited with a capture date. An unverified fee/cost always errs toward **higher fees / lower net / higher grading cost — never toward fake profit or a cheaper grade.**
- **Extend, don't rebuild.** `FeeModel` (`margin.py:11-15`), `net_margin` (`margin.py:38-73`), `cost_basis` (`margin.py:27-29`) keep their current call contracts working; new behavior is additive. `MarginResult` (`margin.py:18-24`) already carries `channel`.
- **Fee channel default = eBay** (spec §8.3): when a packet/sale has no chosen sell channel, `net_margin` defaults to `"ebay"` (conservative, higher fees). Explicit channel override allowed. The pre-existing `"local"` channel is unchanged.
- **Versioning is required, not gold-plating.** Fees change often (TCGplayer 2026-02-10; PSA 2026-02 & 2026-06-02). A dated fee schedule selects the era; un-versioned fees silently misprice.
- **Money-class (T5).** `limit=1` mandatory on by-id PPT lookups (`market.py:49`), never removed. Every billable sealed path reports a bounded `apiCallsConsumed` or refuses first; read / `refresh=false` / no-client / unmapped report `0`, `source:"local"`. Surface estimated spend + require operator go-ahead before a billable sealed lookup. Free tier 100 cr/day.
- **The two `_shipping_for` copies are kept identical by contract** (`main.py:347`, `opportunities.py:115`) — any change touches both.
- **TDD, full suite green** at each task boundary: `.venv/Scripts/python.exe -m pytest -q` (network-mocked). Baseline at plan start: **1081 passed**.
- **Local `main`, never pushed.** Work on a feature branch (`poke-honest-fees-credit-accounting`), merge to LOCAL main via finishing-a-development-branch. `config.yaml` unchanged.

## Design decisions (flag at sign-off if any should change)

1. **Provenance granularity — per-model dated snapshot, not per-field.** Each `FeeModel` instance carries one `effective_date` + `source_url`; a dated `FEE_SCHEDULE` list holds one snapshot per fee era, and `fee_model_for(as_of)` picks the latest snapshot with `effective_date <= as_of`. This satisfies the spec's "model selected by date" with far less machinery than per-field temporal tracking. Today there is one current snapshot; the *mechanism* is what prevents silent mispricing when fees next change.
2. **Channel stays a `net_margin` argument** (it already is), not a `FeeModel` field — the same dated `FeeModel` prices any channel; the caller chooses the channel per packet/sale. Default `"ebay"`.
3. **Grading fee** gets a parallel dated `GRADING_SCHEDULE` + `grading_fee_for(as_of, tier="regular")` returning `(fee, effective_date, source_url)`; `grading_ev` consumes the sourced fee instead of a bare `cfg.grading_cost_all_in` constant (which stays as a fallback/override).

## File Structure

- **Modify** `scanner/margin.py` — extend `FeeModel` (TCGplayer fields + eBay ≥$1,000 FVF-discount fields + `effective_date` + `source_url`); add the `"tcgplayer"` channel + the ≥$1,000 discount to `net_margin`; add `FEE_SCHEDULE` + `fee_model_for(as_of)`.
- **Create** `scanner/grading_fees.py` — dated PSA `GRADING_SCHEDULE` + `grading_fee_for(as_of, tier)` with provenance (value tiers paused 2026-06-02; ~$80 Regular floor + return shipping).
- **Modify** `scanner/poke_api/grading_ev.py` — consume `grading_fee_for(...)` for the sourced grading fee.
- **Modify** the fee consumers to thread the sell `channel` + select the dated model: `scanner/poke_api/edge.py:254` (`_fee_model`), `scanner/poke_api/opportunities.py:115,143` (`_shipping_for` + `compute_margin`), `scanner/discovery/score.py:41,49`, `scanner/main.py:347,361` (`_shipping_for` + `verdict_for_alert`).
- **Modify** `scanner/config.py` — add TCGplayer fee + grading provenance config fields (defaults matching the schedule) under `[deal_intelligence.fees]`.
- **Modify** `scanner/poke_api/model.py` (`comp_response` `:47-76`) — sealed credit accounting (T5): emit + preserve the row's `creditsConsumed` as `apiCallsConsumed` (0/local on the structurally-0-credit CompEngine route; a billing row's value passed through, never dropped), mirroring `asset_model._api_meta` shape. No `router.py`/`engine.py` logic change (CompEngine stays 0-credit; the fix is that `comp_response` stops discarding the field).
- **Tests:** `tests/test_margin.py` (extend), `tests/test_grading_fees.py` (new), and the poke fee/credit test files named per task.

---

### Task 1: Channel-aware, provenance-bearing `FeeModel` + `net_margin`

Extend the pure fee model: add the TCGplayer channel, the eBay ≥$1,000 50%-FVF-discount, and per-model provenance. `resolve()`-style callers unchanged; new fields have defaults so every existing `FeeModel(...)` call still constructs.

**Files:**
- Modify: `scanner/margin.py`
- Test: `tests/test_margin.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `FeeModel` gains (all with defaults): `tcgplayer_commission_pct: float = 0.1075`, `tcgplayer_processing_pct: float = 0.025`, `tcgplayer_fixed_fee: float = 0.30`, `ebay_high_value_threshold: float = 1000.0`, **`ebay_high_value_fvf_pct: float = 0.1325` — FAIL-SAFE default equal to the full FVF (i.e. NO discount applies) until the live eBay Trading Cards category structure is pinned + cited (see PIN-FIRST). An unverified fee model MUST err toward higher fees / lower net, never toward fake profit.**, `effective_date: str = ""`, `source_url: str = ""`.
  - `net_margin(cost_incl_tax, comp, channel, est_shipping, fees)` — unchanged signature; adds a `channel == "tcgplayer"` branch and, in the `"ebay"` branch, applies `ebay_high_value_fvf_pct` when `comp >= ebay_high_value_threshold`.

> **PIN-FIRST — HARD GATE (STOP-class; the load-bearing risk of this plan):** The eBay high-value FVF discount ships **OFF (fail-safe = full FVF)** and stays off until the LIVE **eBay Trading Cards *category* fee page** (not the generic selling-fees rate) is pinned. Extract, with a capture date in `source_url`: the category FVF %, the threshold(s), and whether the reduced rate is **marginal** (applied only to the portion *above* the threshold) or flat. eBay card FVF is almost certainly **marginal tiering** with a category threshold likely **far above $1,000** (historically ~$7,500 for collectible cards) — so a $1,500 card is likely **entirely below** the threshold and pays the **full** FVF. A whole-comp discount here would overstate net by ~$100 on the operator's single biggest card — the exact fake profit this plan exists to kill. Only after the live structure is pinned + cited may the discount switch on (set the real rate/threshold; rewrite the eBay branch to marginal if confirmed) with a matching real-discount test. Until then: **full FVF, no discount.** (Same pin-then-cite for the TCGplayer ~2.5% processing rate — lower stakes, within the spec's stated range.)

- [ ] **Step 1: Write failing tests (worked fee examples — the ≥$1,000 case asserts the FAIL-SAFE full FVF, not a discount, until the PIN-FIRST gate is met)**

```python
# add to tests/test_margin.py
from scanner import margin


def test_ebay_high_value_defaults_to_full_fvf_until_pinned():
    # FAIL-SAFE: the >=$1,000 discount is OFF by default -> full 13.25% FVF, never fake profit.
    # A real-discount test is added ONLY after the live eBay Trading Cards category is pinned+cited.
    fees = margin.FeeModel()
    r = margin.net_margin(cost_incl_tax=1000.0, comp=1500.0, channel="ebay",
                          est_shipping=8.0, fees=fees)
    # fee = 1500*0.1325 + 0.40 = 199.15 ; net = 1500 - 199.15 - 8 = 1292.85 (matches reality, not +$100)
    assert round(r.net_proceeds, 2) == 1292.85


def test_ebay_standard_fvf_below_threshold():
    fees = margin.FeeModel()
    r = margin.net_margin(cost_incl_tax=30.0, comp=100.0, channel="ebay",
                          est_shipping=8.0, fees=fees)
    # fee = 100*0.1325 + 0.40 = 13.65 ; net = 100 - 13.65 - 8 = 78.35
    assert round(r.net_proceeds, 2) == 78.35


def test_tcgplayer_channel_nets_commission_processing_and_fixed():
    fees = margin.FeeModel()
    r = margin.net_margin(cost_incl_tax=30.0, comp=100.0, channel="tcgplayer",
                          est_shipping=8.0, fees=fees)
    # fee = 100*(0.1075+0.025) + 0.30 = 13.55 ; net = 100 - 13.55 - 8 = 78.45
    assert round(r.net_proceeds, 2) == 78.45
    assert r.channel == "tcgplayer"


def test_unknown_channel_still_raises():
    import pytest
    with pytest.raises(ValueError):
        margin.net_margin(30.0, 100.0, "carrier-pigeon", 8.0, margin.FeeModel())
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_margin.py -q -k "high_value or tcgplayer or unknown_channel"`
Expected: FAIL (tcgplayer channel raises ValueError today; no high-value discount).

- [ ] **Step 3: Implement — extend `FeeModel` + `net_margin`**

Read the current `FeeModel` (`margin.py:11-15`) and `net_margin` (`margin.py:38-73`) first. Add the new `FeeModel` fields (with the defaults in Interfaces). In `net_margin`, before the eBay fee calc, select the FVF rate:

```python
    if channel == "ebay":
        # FAIL-SAFE: ebay_high_value_fvf_pct defaults to the FULL FVF, so this branch is a
        # no-op discount (full rate at any comp) until the live eBay Trading Cards category
        # is pinned + a real discounted rate/threshold is set (see PIN-FIRST HARD GATE).
        fvf_pct = (fees.ebay_high_value_fvf_pct
                   if comp >= fees.ebay_high_value_threshold else fees.ebay_fvf_pct)
        fee = comp * fvf_pct + fees.ebay_fixed_fee
        net = comp - fee - est_shipping
        # breakeven uses the same fvf_pct (guard denom <= 0 -> inf, as today)
        ...
    elif channel == "tcgplayer":
        fee = comp * (fees.tcgplayer_commission_pct + fees.tcgplayer_processing_pct) \
            + fees.tcgplayer_fixed_fee
        net = comp - fee - est_shipping
        denom = 1.0 - (fees.tcgplayer_commission_pct + fees.tcgplayer_processing_pct)
        breakeven = (cost_incl_tax + fees.tcgplayer_fixed_fee + est_shipping) / denom if denom > 0 else float("inf")
    elif channel == "local":
        ...  # unchanged
    else:
        raise ValueError(f"Unknown sell channel: {channel!r}")
```

(Mirror the existing eBay breakeven formula for the discounted rate. Keep `MarginResult(channel=channel, ...)`.)

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_margin.py -q`
Expected: PASS (existing eBay/local tests still green — defaults preserve them).

- [ ] **Step 5: Commit**

```bash
git add scanner/margin.py tests/test_margin.py
git commit -m "feat(poke): channel-aware FeeModel (TCGplayer + eBay >=\$1000 FVF discount) + provenance fields"
```

---

### Task 2: Dated fee schedule — `fee_model_for(as_of)`

The versioning mechanism: a small ordered list of dated `FeeModel` snapshots + a selector, so a row dated in a prior fee era prices with that era's fees. Today there is one current snapshot; the mechanism is the deliverable.

**Files:**
- Modify: `scanner/margin.py`
- Test: `tests/test_margin.py`

**Interfaces:**
- Produces:
  - `FEE_SCHEDULE: tuple[FeeModel, ...]` — one snapshot per era, each with a distinct `effective_date` + `source_url`, ordered oldest→newest. Seed with the current era (`effective_date="2026-02-10"`, TCGplayer 10.75% era + current eBay rates, `source_url` citing eBay/TCGplayer fee pages).
  - `fee_model_for(as_of: str | None = None) -> FeeModel` — the latest snapshot with `effective_date <= as_of`; `as_of=None` → newest. Empty/malformed date → newest (never crash).

- [ ] **Step 1: Write failing tests**

```python
# add to tests/test_margin.py
def test_fee_model_for_returns_newest_by_default():
    m = margin.fee_model_for()
    assert m.effective_date and m.source_url            # provenance present
    assert m is margin.FEE_SCHEDULE[-1]


def test_fee_model_for_selects_by_date():
    # a date before the newest era selects an older snapshot when one exists, else the oldest
    m = margin.fee_model_for("2000-01-01")
    assert m.effective_date <= "2000-01-01" or m is margin.FEE_SCHEDULE[0]
```

- [ ] **Step 2: Run to verify they fail** (`fee_model_for` undefined) — `.venv/Scripts/python.exe -m pytest tests/test_margin.py -q -k fee_model_for`

- [ ] **Step 3: Implement `FEE_SCHEDULE` + `fee_model_for`**

```python
FEE_SCHEDULE: tuple[FeeModel, ...] = (
    FeeModel(effective_date="2026-02-10",
             source_url="https://www.ebay.com/help/selling/fees-credits-invoices/"
                        "selling-fees | https://help.tcgplayer.com/ (TCGplayer 10.75% eff 2026-02-10)"),
)


def fee_model_for(as_of: str | None = None) -> FeeModel:
    if not as_of:
        return FEE_SCHEDULE[-1]
    applicable = [m for m in FEE_SCHEDULE if m.effective_date <= as_of]
    return applicable[-1] if applicable else FEE_SCHEDULE[0]
```

- [ ] **Step 4: Run to verify** (PASS) — `.venv/Scripts/python.exe -m pytest tests/test_margin.py -q`

- [ ] **Step 5: Commit**

```bash
git add scanner/margin.py tests/test_margin.py
git commit -m "feat(poke): dated fee schedule + fee_model_for(as_of) (era-correct fees; versioning mechanism)"
```

---

### Task 3: Grading cost provenance — `grading_fees.py`

Encode PSA grading cost with the live reality (value tiers **paused 2026-06-02**; realistic floor **~$80 Regular** + return shipping), dated + sourced, so `grading_ev`'s break-even reflects today's real cost, not a stale ~$25 assumption.

**Files:**
- Create: `scanner/grading_fees.py`
- Modify: `scanner/poke_api/grading_ev.py`
- Test: `tests/test_grading_fees.py` (new) + the existing grading-EV test file

**Interfaces:**
- Produces: `grading_fee_for(as_of: str | None = None, tier: str = "regular") -> tuple[float, str, str]` returning `(all_in_fee, effective_date, source_url)`. `GRADING_SCHEDULE` holds dated snapshots; the 2026-06-02 snapshot has NO value tier (paused) and a `regular` all-in ≈ $80 grading + ~$15 return shipping. Unknown tier at a date where it doesn't exist → the cheapest *available* tier at that date (never a paused/nonexistent tier), with a note.

> **PIN-FIRST (STOP-class, money-class — grading-EV gates whether the operator grades a raw):** Pin the LIVE PSA pricing page for the Regular-tier all-in + the value-tier **pause date (2026-06-02)**, and cite with a capture date in the snapshot `source_url`. Do NOT lock the ≥$80 figure on memory. FAIL-SAFE direction: for grading-EV a *higher* grading cost is the conservative error (it makes the EV *less* likely to greenlight grading), so until the live page is pinned the schedule value is an explicit **`operator_assumption`** at or above the known real floor, and the tests below assert a **floor** (`>= 80`, cost never understated) — not an exact memory-locked number. Flip the badge from `operator_assumption` to sourced only once the live PSA page is pinned + cited.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_grading_fees.py
from scanner import grading_fees


def test_regular_tier_reflects_paused_value_tiers_post_2026_06():
    fee, eff, url = grading_fees.grading_fee_for("2026-07-01", "regular")
    assert fee >= 80.0            # value tiers paused -> real floor, not ~$25
    assert eff <= "2026-07-01" and url


def test_value_tier_unavailable_after_pause_falls_back_never_fabricates():
    fee, eff, url = grading_fees.grading_fee_for("2026-07-01", "value")
    assert fee >= 80.0            # no $25 value tier exists post-pause; never invents one
```

- [ ] **Step 2: Run to verify they fail** — `.venv/Scripts/python.exe -m pytest tests/test_grading_fees.py -q`

- [ ] **Step 3: Implement `grading_fees.py`** — a dated `GRADING_SCHEDULE` (each snapshot: `effective_date`, `source_url`, a `tiers: dict[str, float]` all-in map) + `grading_fee_for` selecting the snapshot by date then the tier (fallback to the cheapest available tier when the requested one is absent). Seed the 2026-06-02 snapshot: `tiers={"regular": 80.0 + return_shipping}`, **badged `operator_assumption` in the `source_url`/note until the live PSA page is pinned + cited** (PIN-FIRST; higher-is-safer for grading-EV). Include an earlier snapshot only if a real prior tier is being modeled; otherwise one honest current snapshot.

- [ ] **Step 4: Run to verify** (PASS) — `.venv/Scripts/python.exe -m pytest tests/test_grading_fees.py -q`

- [ ] **Step 5: Wire `grading_ev` to the sourced fee**

Read `grading_ev` (`grading_ev.py:79-136`). It receives `grading_fee` as a param today. Change its default/derivation so the grading fee comes from `grading_fees.grading_fee_for(as_of, tier)` when not explicitly supplied, and record the `(effective_date, source_url)` in the EV result's provenance. Keep `cfg.grading_cost_all_in` honored as an explicit operator override. Add/adjust a test in the existing grading-EV test file asserting the break-even reflects the ≥$80 sourced fee. Run the full suite.

- [ ] **Step 6: Commit**

```bash
git add scanner/grading_fees.py scanner/poke_api/grading_ev.py tests/test_grading_fees.py tests/<grading_ev_test_file>.py
git commit -m "feat(poke): sourced dated PSA grading cost (value tiers paused; ~\$80 floor) feeds grading-EV"
```

---

### Task 4: Thread the sell channel + dated model through the consumers

Make the buy-loop money math channel-aware and era-correct at every consumer, honoring the eBay default (§8.3). Touch **both** `_shipping_for` copies by contract.

**Files:**
- Modify: `scanner/poke_api/opportunities.py` (`_shipping_for:115`, `compute_margin:143-156`)
- Modify: `scanner/main.py` (`_shipping_for:347`, `verdict_for_alert:361-367`)
- Modify: `scanner/poke_api/edge.py` (`_fee_model:254`)
- Modify: `scanner/discovery/score.py` (`_fees:41`, `flipper_is_buy:49`)
- Modify: `scanner/config.py` (add TCGplayer fee fields under `[deal_intelligence.fees]`, defaults matching the schedule)
- Test: the existing consumer test files (opportunities, edge, main/alert, score)

**Interfaces:**
- `compute_margin(entry_price, comp, confidence, product, cfg, *, channel="ebay", as_of=None)` — selects `margin.fee_model_for(as_of)` and passes `channel` into `net_margin`. Default channel `"ebay"` preserves current behavior/tests.
- The other consumers gain the same optional `channel="ebay"` + dated-model selection.

- [ ] **Step 1: Write failing tests** — one per consumer asserting (a) default eBay path is unchanged (regression guard), and (b) passing `channel="tcgplayer"` produces the TCGplayer-fee margin. Example:

```python
# add to the opportunities test file
def test_compute_margin_default_channel_is_ebay_unchanged(...):
    net, roi, tier = opportunities.compute_margin(30.0, 100.0, "high", {}, cfg)
    # matches the pre-change eBay result exactly
    ...

def test_compute_margin_tcgplayer_channel_nets_tcgplayer_fees(...):
    net, roi, tier = opportunities.compute_margin(30.0, 100.0, "high", {}, cfg, channel="tcgplayer")
    ...
```

- [ ] **Step 2: Run to verify they fail** (channel kwarg not accepted).

- [ ] **Step 3: Implement** — thread `channel="ebay"` + `margin.fee_model_for(as_of)` through each consumer, reading each call site from the current source before editing (money-class; guessing risks a wrong margin). Update **both** `_shipping_for` copies identically if their signature changes (they need not change if channel is threaded only through the margin calls). Add the TCGplayer config fields in `config.py` (loader `:386-390` block) with defaults equal to the `FeeModel` defaults.

- [ ] **Step 4: Run the full suite** — `.venv/Scripts/python.exe -m pytest -q` (all green; eBay defaults keep existing tests passing).

- [ ] **Step 5: Commit**

```bash
git add scanner/poke_api/opportunities.py scanner/main.py scanner/poke_api/edge.py scanner/discovery/score.py scanner/config.py tests/
git commit -m "feat(poke): thread sell channel + dated fee model through margin consumers (eBay default, TCGplayer opt-in)"
```

---

### Task 5: Sealed credit accounting — stop dropping the field (spec T5)

**The real gap (verified against the T5 surface map + the Plan-2 final review — NOT the naive reading):** the poke_api sealed refresh route is `router._comp → ReadFirstCompProvider → CompEngine`, and **CompEngine is structurally 0-credit** (tcgplayer/pricecharting/ebay scrapers; it never constructs a PPT client — `comps/engine.py:4` states the invariant). So on this route `creditsConsumed` is *honestly* 0 — there is no billable lookup to put an "upper bound" on. The actual defect is that **`comp_response` drops the credit field entirely** (`model.py:47-76` emits no `apiCallsConsumed`/`creditsConsumed`), so (a) the sealed read API reports *nothing* about credits, and (b) any provider row that *does* bill (a `market.py`-shaped row carrying `creditsConsumed=N` + `dailyRemaining`, if such a provider is ever wired onto this route) would be **silently zeroed/dropped**. The billable sealed surface today is the discovery sweep, which already accounts separately (`sweep.py:216-217`), not through `comp_response`.

**Fix (honest, narrow — preserve-and-emit, do NOT synthesize):** make `comp_response` **preserve and emit** the credit account from the provider row instead of dropping it — reporting `total = 0`, `source:"local"` on the 0-credit CompEngine route (honest, not invented), and **preserving the row's `creditsConsumed`/`dailyRemaining`** when a billing row is passed. Result: the field is always present and truthful, and no billed path can silently report 0 because the value is carried through, never fabricated. Do **not** invent an `expected_sealed_credits` bound for a call that does not happen on this route.

**Pre-flight discriminating check (do this first, confirm in the report):** trace whether any path flowing through `comp_response` can carry a nonzero `creditsConsumed`, and whether `_comp`'s refresh route is ever that path. If confirmed that the only billable sealed surface is the sweep (accounted separately), Task 5 is exactly the preserve-and-emit fix below; if a billing provider *does* reach `comp_response`, the same fix still holds (it preserves that value) — so the fix is correct either way, but the belt test's non-zero case must use a real billing-row fixture, not a fictional `refresh=true`-bounds-CompEngine assertion.

**Files:**
- Modify: `scanner/poke_api/model.py` (`comp_response:47-76` — emit `apiCallsConsumed` from the row's `creditsConsumed`, default `0`/`local`; leave `sealed_facade:151`'s hardcoded `{total:0}` as-is — structurally 0-credit and correct).
- Test: the sealed comp/model test file (the belt).
- (No `router.py`/`engine.py` logic change required — CompEngine keeps `creditsConsumed = 0`; `comp_response` stops discarding it.)

**Interfaces:**
- `comp_response(...)` gains an `apiCallsConsumed` key: `{"total": int(row.get("creditsConsumed") or 0), "source": "external" if total > 0 else "local"}` (mirroring `asset_model._api_meta` shape, `asset_model.py:35-44`), plus a `dailyRemaining` passthrough when the row carries one. `limit=1` stays pinned wherever a sealed PPT client *is* used (`market.py:49`) — unchanged.

- [ ] **Step 1: Write the failing belt test**

```python
# add to the sealed comp/model test file (twin of the asset credit belt)
from scanner.poke_api import model as model_mod


def test_sealed_comp_response_reports_zero_local_on_free_route():
    # a CompEngine-style row (structurally 0-credit) -> field PRESENT, 0/local, never dropped
    row = {"status": "ok", "estimate": "$50.00", "creditsConsumed": 0, "sources": []}
    resp = model_mod.comp_response("pe_etb", {"name": "X", "set": "S"}, row)
    assert resp["apiCallsConsumed"]["total"] == 0
    assert resp["apiCallsConsumed"]["source"] == "local"


def test_sealed_comp_response_preserves_a_billing_rows_credits_never_zeroes_it():
    # a billing provider row (market.py-shaped) must NOT be silently dropped/zeroed
    row = {"status": "ok", "estimate": "$50.00", "creditsConsumed": 1,
           "dailyRemaining": 87, "sources": []}
    resp = model_mod.comp_response("pe_etb", {"name": "X", "set": "S"}, row)
    assert resp["apiCallsConsumed"]["total"] == 1        # preserved, not 0
    assert resp["apiCallsConsumed"]["source"] == "external"
    assert resp.get("dailyRemaining") == 87
```

- [ ] **Step 2: Run to verify they fail** (`comp_response` emits no `apiCallsConsumed` key today).

- [ ] **Step 3: Implement** — read `comp_response` (`model.py:47-76`) first. Add the `apiCallsConsumed` block (read from `row.get("creditsConsumed")`, default 0/local) + a `dailyRemaining` passthrough when present. Do NOT synthesize a non-zero bound and do NOT add an `expected_sealed_credits`. Confirm no existing sealed-response test asserted the *absence* of the field (adjust if so — the field is now always present).

- [ ] **Step 4: Run the full suite** — `.venv/Scripts/python.exe -m pytest -q` (all green).

- [ ] **Step 5: Commit**

```bash
git add scanner/poke_api/model.py tests/
git commit -m "fix(poke): sealed comp_response emits/preserves creditsConsumed (0/local on free route; never silently drops a billed value)"
```

---

## Self-Review

**Spec coverage:**
- T4 channels (eBay + TCGplayer, ≥$1,000 eBay FVF discount) → Task 1 ✓
- T4 versioning (effective_date + source_url, model selected by date) → Tasks 1 (fields) + 2 (schedule) ✓
- T4 grading cost provenance (PSA value tiers paused, ~$80 floor) → Task 3 ✓
- T4 propagation to all consumers + both `_shipping_for` copies + eBay default (§8.3) → Task 4 ✓
- T4 `fee_assumption_difference` divergence audit hook (`divergence.py:42-45`) — the slot already exists and is reserved; wiring a fee-comparison mode is **deferred** (spec calls it "surfaced when a caller compares fee-adjusted values"; no consumer needs it yet) → noted, not built (log the deferral).
- T5 sealed credit accounting → Task 5 ✓ — reframed to the *honest* gap (verified vs the T5 map + Plan-2 final review): the CompEngine sealed route is structurally 0-credit, so the fix is `comp_response` preserving/emitting the row's `creditsConsumed` (0/local here; a billing row's value passed through), NOT synthesizing a non-zero bound for a call that never fires. "No billed path reports 0" holds because the value is carried through, never fabricated; `limit=1` unchanged where a sealed PPT client is used.

**Placeholder scan:** Tasks 1–3 carry full core code + tests. Tasks 4–5 give exact anchors + required tests for the money-class consumer/router wiring (read-at-execution, per Plan-1/Plan-2 convention) because the exact call sites must be read to extend faithfully; the pure logic they depend on (channel `net_margin`, `fee_model_for`, `grading_fee_for`, the asset credit pattern) is fully specified. No `TBD`/"add error handling".

**Type consistency:** `net_margin(cost_incl_tax, comp, channel, est_shipping, fees)` unchanged across Tasks 1/4. `fee_model_for(as_of)` and `grading_fee_for(as_of, tier)` consistent between definition (Tasks 2/3) and consumers (Tasks 3/4). `FeeModel` new fields defaulted so every existing constructor call still compiles. Sealed `apiCallsConsumed` mirrors `asset_model._api_meta`'s shape exactly.

**Open item for sign-off:** the three "Design decisions" above (per-model provenance; channel-as-arg; grading schedule) — confirm before execution.
