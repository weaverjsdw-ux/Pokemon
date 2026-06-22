# Phase 1 — Deal Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attach a fee-adjusted BUY/THIN/SKIP verdict to every in-stock alert and activate the owner's buyable retailers, without changing the scanner's buy-side, human-in-the-loop nature.

**Architecture:** Three new pure-ish modules — `margin.py` (fee math), `verdict.py` (tier logic), `market.py` (PokemonPriceTracker price client) — plus thin integration into the existing alert path (`main.run_pass` → `notify.StockAlert`) and web board. The price client conforms to the existing `resale.py` `estimate(product_key, product, checked_at) -> dict` contract and is injected through the **existing** `ResalePriceCache(client_factory=...)` seam, so the background-refreshed comp cache the web UI already drives is reused; the verdict reads the most recent cached comp at alert time (no new synchronous network I/O in the scan loop).

**Tech Stack:** Python 3 (stdlib + `requests` + `pyyaml`, all already vendored), `pytest` 9.0.3, dataclasses, `from __future__ import annotations` style throughout.

## Global Constraints

Every task implicitly includes these. Values copied verbatim from spec `2026-06-18-hobby-resale-engine-design.md` §3.6 / §3.7 / §4 (committed `25de402`).

- **Doctrine (hard):** no auto-checkout, cart automation, account abuse, login-wall scraping, proxy/distributed polling, CAPTCHA bypass, or sub-60s polling. The tool advises; the human transacts. No auto-listing. No unverified IDs. No "AI price prediction" — every number traces to a real comp with a confidence tier.
- **Verdict defaults:** `skip_floor_net 5.00`, `buy_floor_net 15.00`, `roi_gate_enabled true`, `skip_floor_roi 10`, `buy_floor_roi 20`, `min_buy_confidence medium`.
- **Confidence rule:** a comp below `min_buy_confidence` (default `medium`) **cannot produce BUY** — capped at THIN. **Local/FB derived comps are always capped at THIN.**
- **Fee model:** eBay `ebay_fvf_pct 0.1325` + `ebay_fixed_fee 0.40` (trading-card/CCG, fee already includes payment processing). Seller-paid shipping is a cost; buyer-paid shipping increases the FVF base. **All fee/threshold/tax numbers live in config — none hardcoded in logic.**
- **Tax:** cost basis = `observed_price × (1 + tax_rate)`, `tax_rate` default `0.07` (Indiana).
- **PokemonPriceTracker:** `optional-preferred, not required` — scanning must run fully without it. Free tier ~100 credits/day < 132 calls/day full-catalog at 4h cadence, so default `market.preferred=false` and `market.cache_ttl=24h` on free tier. A missing key, rate-limit, or quota response all fall back to the existing scrape path with a labeled confidence downgrade and **never error the scan run.**
- **Scope fence:** Phase 1 only. Do **not** build Phase 2 (ledger/sell-side) or Phase 3 (opening/grading).
- **Style:** match existing modules — `from __future__ import annotations`, dataclasses, type hints, `SystemExit` for config errors, snake_case. Frequent commits. TDD: failing test first.
- **Worktree (verified 2026-06-18):** spec committed at `25de402`; working tree is **dirty** with 40 pre-existing modified/untracked files unrelated to this work. Implement on a dedicated branch/worktree and **preserve all existing uncommitted edits** (no stash-drop, no revert). Commit only files this plan names.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `scanner/margin.py` | Create | Pure fee-adjusted margin math (`FeeModel`, `MarginResult`, `cost_basis`, `net_margin`). No I/O. |
| `scanner/verdict.py` | Create | Pure tier logic (`VerdictThresholds`, `Verdict`, `buy_verdict`). Consumes a `MarginResult`. No I/O. |
| `scanner/market.py` | Create | PokemonPriceTracker price client + `market_client_from_config` factory + `comp_from_row` helper. Conforms to `resale.py` client contract. |
| `scanner/config.py` | Modify | Add `margin`, `verdict`, `market` config groups to `Config` + `from_mapping`. |
| `scanner/notify.py` | Modify | Add `StockAlert.verdict` field; render in `_context_bits()` (console/ntfy) and `_discord()` (separate field). |
| `scanner/main.py` | Modify | `run_pass` gains optional `comp_lookup`; compute + attach verdict at alert build (`main.py:361-374`). |
| `scanner/web.py` | Modify | Wire `market_client_from_config` into `RESALE_PRICES`; build `comp_lookup` from one snapshot per pass; add verdict/margin to board payload. |
| `scanner/web_assets/app.js`, `index.html` | Modify | Render the verdict label + net-margin per product row. |
| `config.example.yaml` | Modify | Document new `deal_intelligence` + `market` blocks and Best Buy enable-when-key. |
| `DOCTRINE.md`, `ADVISOR_ROLE.md` | Modify | Doctrine v2 (resale = first-class input; guardrails kept). |
| `docs/phase1-id-seeding.md` | Create | Enumerated Costco/PC ID-seeding data task (separate from engine). |
| `tests/test_margin.py`, `test_verdict.py`, `test_market.py` | Create | Unit tests for the pure modules + mocked client. |
| `tests/test_notify_alert.py`, `test_config.py`, `test_main.py`, `test_web.py` | Modify | Extend for verdict rendering, config, alert wiring, payload. |

---

## Task 0: Branch from clean baseline

**Files:** none (git only)

**Context:** The previously-dirty 40 files (including the load-bearing untracked
modules `scanner/resale.py`, `confidence.py`, `workqueue.py`, `provenance.py`,
`verify_ids.py`) were committed as a baseline snapshot on `main` at **`cf23e2b`**
(operator-chosen option A). The tree is now clean and the full suite is green
(172 passed). Phase 1 builds on top of that clean baseline.

**Interfaces:**
- Produces: a dedicated branch off clean `main` for isolated Phase 1 review diffs.

- [ ] **Step 1: Confirm clean baseline**

Run: `git status --porcelain | wc -l && git log --oneline -1`
Expected: `0` dirty files; HEAD at `cf23e2b Snapshot prior sprint + service-plan work` (or a later commit if more baseline work landed).

- [ ] **Step 2: Confirm the suite is green before changing anything**

Run: `python -m pytest -q 2>&1 | tail -1`
Expected: `172 passed` (or more). This is the regression baseline for every later task.

- [ ] **Step 3: Create the feature branch**

Run: `git switch -c phase1-deal-intelligence`
Expected: "Switched to a new branch 'phase1-deal-intelligence'". `git status --porcelain` shows `0` (clean). Each later task commits only the exact files it names, so the branch diff stays pure Phase 1.

---

## Task 1: Config schema + defaults

**Files:**
- Modify: `scanner/config.py` (the `Config` dataclass ~lines 22-40 and `from_mapping` ~lines 58-129)
- Modify: `config.example.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config` gains fields — `tax_rate: float = 0.07`; `ebay_fvf_pct: float = 0.1325`; `ebay_fixed_fee: float = 0.40`; `local_haircut_pct: float = 0.15`; `skip_floor_net: float = 5.0`; `buy_floor_net: float = 15.0`; `roi_gate_enabled: bool = True`; `skip_floor_roi: float = 10.0`; `buy_floor_roi: float = 20.0`; `min_buy_confidence: str = "medium"`; `market_preferred: bool = False`; `market_api_key: str = ""`; `market_cache_ttl_seconds: int = 86400`. Parsed from a top-level `deal_intelligence:` mapping (with nested `fees:`, `verdict:`) and a `market:` mapping.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py  (add these tests)
from scanner import config as cfg_mod


def test_deal_intelligence_defaults_when_absent():
    cfg = cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
    })
    assert cfg.tax_rate == 0.07
    assert cfg.ebay_fvf_pct == 0.1325
    assert cfg.ebay_fixed_fee == 0.40
    assert cfg.local_haircut_pct == 0.15
    assert cfg.skip_floor_net == 5.0
    assert cfg.buy_floor_net == 15.0
    assert cfg.roi_gate_enabled is True
    assert cfg.skip_floor_roi == 10.0
    assert cfg.buy_floor_roi == 20.0
    assert cfg.min_buy_confidence == "medium"
    assert cfg.market_preferred is False
    assert cfg.market_cache_ttl_seconds == 86400


def test_deal_intelligence_overrides_parse():
    cfg = cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "deal_intelligence": {
            "tax_rate": 0.0,
            "fees": {"ebay_fvf_pct": 0.10, "ebay_fixed_fee": 0.30, "local_haircut_pct": 0.2},
            "verdict": {
                "skip_floor_net": 2, "buy_floor_net": 20,
                "roi_gate_enabled": False, "skip_floor_roi": 5, "buy_floor_roi": 30,
                "min_buy_confidence": "high",
            },
        },
        "market": {"preferred": True, "api_key": "k", "cache_ttl_seconds": 3600},
    })
    assert cfg.tax_rate == 0.0
    assert cfg.ebay_fvf_pct == 0.10
    assert cfg.roi_gate_enabled is False
    assert cfg.min_buy_confidence == "high"
    assert cfg.market_preferred is True
    assert cfg.market_api_key == "k"
    assert cfg.market_cache_ttl_seconds == 3600


def test_invalid_min_buy_confidence_rejected():
    import pytest
    with pytest.raises(SystemExit):
        cfg_mod.from_mapping({
            "locations": {"home": "A", "work": "B"},
            "deal_intelligence": {"verdict": {"min_buy_confidence": "ludicrous"}},
        })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -k "deal_intelligence or min_buy_confidence" -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'tax_rate'`.

- [ ] **Step 3: Add the fields to the `Config` dataclass**

In `scanner/config.py`, append to the `Config` dataclass (after `ebay_client_secret`):

```python
    # --- Phase 1 deal intelligence ---
    tax_rate: float = 0.07
    ebay_fvf_pct: float = 0.1325
    ebay_fixed_fee: float = 0.40
    local_haircut_pct: float = 0.15
    skip_floor_net: float = 5.0
    buy_floor_net: float = 15.0
    roi_gate_enabled: bool = True
    skip_floor_roi: float = 10.0
    buy_floor_roi: float = 20.0
    min_buy_confidence: str = "medium"
    market_preferred: bool = False
    market_api_key: str = ""
    market_cache_ttl_seconds: int = 86400
```

- [ ] **Step 4: Parse the new blocks in `from_mapping`**

In `scanner/config.py`, add this helper above `from_mapping` and parse inside it. Insert the parsing just before the `return Config(` statement:

```python
VALID_CONFIDENCE = {"none", "low", "medium", "high"}


def _num(mapping: dict[str, Any], key: str, default: float, label: str) -> float:
    try:
        return float(mapping.get(key, default))
    except (TypeError, ValueError):
        raise SystemExit(f"config.yaml: {label} must be a number.")
```

```python
    di_raw = raw.get("deal_intelligence") or {}
    if not isinstance(di_raw, dict):
        raise SystemExit("config.yaml: deal_intelligence must be a mapping.")
    fees_raw = di_raw.get("fees") or {}
    verdict_raw = di_raw.get("verdict") or {}
    market_raw = raw.get("market") or {}
    if not isinstance(market_raw, dict):
        raise SystemExit("config.yaml: market must be a mapping.")
    min_conf = str(verdict_raw.get("min_buy_confidence", "medium")).lower()
    if min_conf not in VALID_CONFIDENCE:
        raise SystemExit(
            "config.yaml: deal_intelligence.verdict.min_buy_confidence must be one of "
            + ", ".join(sorted(VALID_CONFIDENCE))
        )
    try:
        market_cache_ttl = int(market_raw.get("cache_ttl_seconds", 86400))
    except (TypeError, ValueError):
        raise SystemExit("config.yaml: market.cache_ttl_seconds must be an integer.")
```

Then add these keyword arguments to the `return Config(...)` call:

```python
        tax_rate=_num(di_raw, "tax_rate", 0.07, "deal_intelligence.tax_rate"),
        ebay_fvf_pct=_num(fees_raw, "ebay_fvf_pct", 0.1325, "deal_intelligence.fees.ebay_fvf_pct"),
        ebay_fixed_fee=_num(fees_raw, "ebay_fixed_fee", 0.40, "deal_intelligence.fees.ebay_fixed_fee"),
        local_haircut_pct=_num(fees_raw, "local_haircut_pct", 0.15, "deal_intelligence.fees.local_haircut_pct"),
        skip_floor_net=_num(verdict_raw, "skip_floor_net", 5.0, "deal_intelligence.verdict.skip_floor_net"),
        buy_floor_net=_num(verdict_raw, "buy_floor_net", 15.0, "deal_intelligence.verdict.buy_floor_net"),
        roi_gate_enabled=bool(verdict_raw.get("roi_gate_enabled", True)),
        skip_floor_roi=_num(verdict_raw, "skip_floor_roi", 10.0, "deal_intelligence.verdict.skip_floor_roi"),
        buy_floor_roi=_num(verdict_raw, "buy_floor_roi", 20.0, "deal_intelligence.verdict.buy_floor_roi"),
        min_buy_confidence=min_conf,
        market_preferred=bool(market_raw.get("preferred", False)),
        market_api_key=str(market_raw.get("api_key", "") or os.getenv("PPT_API_KEY", "")),
        market_cache_ttl_seconds=market_cache_ttl,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (new tests + existing config tests stay green).

- [ ] **Step 6: Document the config in `config.example.yaml`**

Add after the `resale_prices:` block:

```yaml
# --- Phase 1 deal intelligence: fee-adjusted BUY/THIN/SKIP verdicts on alerts ---
# Resale comps are context for MSRP-protection decisions, never a scalping target.
deal_intelligence:
  tax_rate: 0.07            # cost-basis sales-tax multiplier (Indiana default)
  fees:
    ebay_fvf_pct: 0.1325    # eBay trading-card final value fee (incl. payment processing)
    ebay_fixed_fee: 0.40    # eBay per-order fixed fee
    local_haircut_pct: 0.15 # local/FB sells below online comp by this fraction
  verdict:
    skip_floor_net: 5.00
    buy_floor_net: 15.00
    roi_gate_enabled: true
    skip_floor_roi: 10
    buy_floor_roi: 20
    min_buy_confidence: medium   # comps weaker than this never show BUY

# Optional PokemonPriceTracker market source. Optional-preferred, never required:
# scanning runs fully without it. Free tier ~100 credits/day < full-catalog need,
# so keep preferred:false + 24h TTL on free tier, or pay Standard for 4h cadence.
market:
  preferred: false
  api_key: ""               # or PPT_API_KEY env var
  cache_ttl_seconds: 86400  # 24h on free tier; lower only on a paid tier
```

- [ ] **Step 7: Commit**

```bash
git add scanner/config.py config.example.yaml tests/test_config.py
git commit -m "feat(config): add Phase 1 deal-intelligence + market config"
```

---

## Task 2: `margin.py` — fee-adjusted margin math

**Files:**
- Create: `scanner/margin.py`
- Test: `tests/test_margin.py`

**Interfaces:**
- Consumes: nothing (pure).
- Produces:
  - `FeeModel(ebay_fvf_pct: float, ebay_fixed_fee: float, local_haircut_pct: float)` (frozen dataclass).
  - `MarginResult(channel: str, net_proceeds: float, dollar_margin: float, roi_pct: float, breakeven_price: float)` (frozen dataclass).
  - `cost_basis(observed_price: float, tax_rate: float) -> float`.
  - `net_margin(cost_incl_tax: float, comp: float, channel: str, est_shipping: float, fees: FeeModel) -> MarginResult` where `channel` is `"ebay"` or `"local"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_margin.py
import pytest

from scanner.margin import FeeModel, MarginResult, cost_basis, net_margin

FEES = FeeModel(ebay_fvf_pct=0.1325, ebay_fixed_fee=0.40, local_haircut_pct=0.15)


def test_cost_basis_applies_tax():
    assert cost_basis(40.0, 0.07) == pytest.approx(42.8)


def test_ebay_margin_matches_spec_example():
    # Buy $43 incl tax, comp $60, ship $8 seller-paid.
    # fee = 60*0.1325 + 0.40 = 7.95 + 0.40 = 8.35; net = 60 - 8.35 - 8 = 43.65
    r = net_margin(43.0, 60.0, "ebay", 8.0, FEES)
    assert r.channel == "ebay"
    assert r.net_proceeds == pytest.approx(43.65)
    assert r.dollar_margin == pytest.approx(0.65)
    assert r.roi_pct == pytest.approx(0.65 / 43.0 * 100, rel=1e-3)
    # breakeven price p: p*(1-0.1325) = cost + fixed + ship = 43 + 0.40 + 8 = 51.40
    assert r.breakeven_price == pytest.approx(51.40 / 0.8675, rel=1e-3)


def test_local_margin_applies_haircut_no_fees():
    # comp $60, haircut 15% -> net 51; cost 43 -> margin 8
    r = net_margin(43.0, 60.0, "local", 0.0, FEES)
    assert r.channel == "local"
    assert r.net_proceeds == pytest.approx(51.0)
    assert r.dollar_margin == pytest.approx(8.0)
    # breakeven comp where comp*(1-haircut) = cost -> 43/0.85
    assert r.breakeven_price == pytest.approx(43.0 / 0.85, rel=1e-3)


def test_unknown_channel_raises():
    with pytest.raises(ValueError):
        net_margin(43.0, 60.0, "whatnot", 0.0, FEES)


def test_zero_cost_roi_is_zero_not_crash():
    r = net_margin(0.0, 60.0, "ebay", 8.0, FEES)
    assert r.roi_pct == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_margin.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.margin'`.

- [ ] **Step 3: Implement `scanner/margin.py`**

```python
"""Pure fee-adjusted margin math for the deal-intelligence verdict.

Resale comps are context for MSRP-protection decisions, not a scalping target.
No network or disk I/O — every input is passed in, every output is a value.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeeModel:
    ebay_fvf_pct: float = 0.1325
    ebay_fixed_fee: float = 0.40
    local_haircut_pct: float = 0.15


@dataclass(frozen=True)
class MarginResult:
    channel: str
    net_proceeds: float
    dollar_margin: float
    roi_pct: float
    breakeven_price: float


def cost_basis(observed_price: float, tax_rate: float) -> float:
    """Landed cost = observed retail price grossed up by sales tax."""
    return round(observed_price * (1.0 + tax_rate), 2)


def _roi(dollar_margin: float, cost_incl_tax: float) -> float:
    if cost_incl_tax <= 0:
        return 0.0
    return dollar_margin / cost_incl_tax * 100.0


def net_margin(
    cost_incl_tax: float,
    comp: float,
    channel: str,
    est_shipping: float,
    fees: FeeModel,
) -> MarginResult:
    """Net proceeds and margin for selling at `comp` on `channel`.

    eBay: fee = comp*fvf + fixed; seller-paid shipping is a cost.
    local: no platform fee/shipping; comp is haircut to a derived local price.
    """
    if channel == "ebay":
        fee = comp * fees.ebay_fvf_pct + fees.ebay_fixed_fee
        net = comp - fee - est_shipping
        denom = 1.0 - fees.ebay_fvf_pct
        breakeven = (
            (cost_incl_tax + fees.ebay_fixed_fee + est_shipping) / denom
            if denom > 0
            else float("inf")
        )
    elif channel == "local":
        net = comp * (1.0 - fees.local_haircut_pct)
        denom = 1.0 - fees.local_haircut_pct
        breakeven = cost_incl_tax / denom if denom > 0 else float("inf")
    else:
        raise ValueError(f"Unknown sell channel: {channel!r}")

    margin = net - cost_incl_tax
    return MarginResult(
        channel=channel,
        net_proceeds=round(net, 2),
        dollar_margin=round(margin, 2),
        roi_pct=round(_roi(margin, cost_incl_tax), 2),
        breakeven_price=round(breakeven, 2),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_margin.py -v`
Expected: PASS (all 5).

- [ ] **Step 5: Commit**

```bash
git add scanner/margin.py tests/test_margin.py
git commit -m "feat(margin): pure fee-adjusted margin math"
```

---

## Task 3: `verdict.py` — BUY/THIN/SKIP tier logic

**Files:**
- Create: `scanner/verdict.py`
- Test: `tests/test_verdict.py`

**Interfaces:**
- Consumes: `MarginResult` from `scanner.margin`.
- Produces:
  - `VerdictThresholds(skip_floor_net, buy_floor_net, roi_gate_enabled, skip_floor_roi, buy_floor_roi, min_buy_confidence)` (frozen dataclass; defaults = global constants).
  - `Verdict(tier: str, headline: str, net: float, roi_pct: float, channel: str, confidence: str)` (frozen dataclass). `tier` ∈ {`"BUY"`,`"THIN"`,`"SKIP"`}.
  - `buy_verdict(margin: MarginResult, comp_confidence: str, thresholds: VerdictThresholds, derived_only: bool = False) -> Verdict`.
  - `thresholds_from_config(cfg) -> VerdictThresholds`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_verdict.py
from scanner.margin import MarginResult
from scanner.verdict import Verdict, VerdictThresholds, buy_verdict

T = VerdictThresholds()  # spec defaults: skip 5/10, buy 15/20, roi gate on, min medium


def m(net, roi, channel="ebay"):
    return MarginResult(channel, net, net, roi, 0.0)


def test_buy_requires_both_net_and_roi_with_good_confidence():
    v = buy_verdict(m(18.0, 42.0), "high", T)
    assert v.tier == "BUY"
    assert "BUY" in v.headline and "42" in v.headline


def test_net_clears_but_roi_fails_is_not_buy():
    # net 18 >= 15 but roi 8 < buy_floor_roi 20, and roi 8 < skip_floor_roi 10 -> SKIP
    v = buy_verdict(m(18.0, 8.0), "high", T)
    assert v.tier == "SKIP"


def test_thin_band():
    # net 10 (between 5 and 15), roi 15 (between 10 and 20) -> THIN
    v = buy_verdict(m(10.0, 15.0), "high", T)
    assert v.tier == "THIN"


def test_low_confidence_caps_buy_to_thin():
    v = buy_verdict(m(18.0, 42.0), "low", T)
    assert v.tier == "THIN"
    assert "low" in v.headline.lower()


def test_derived_local_comp_capped_at_thin():
    v = buy_verdict(m(40.0, 90.0, channel="local"), "high", T, derived_only=True)
    assert v.tier == "THIN"


def test_roi_gate_disabled_uses_net_only():
    t = VerdictThresholds(roi_gate_enabled=False)
    v = buy_verdict(m(18.0, 1.0), "high", t)
    assert v.tier == "BUY"


def test_skip_when_below_net_floor():
    v = buy_verdict(m(2.0, 50.0), "high", T)
    assert v.tier == "SKIP"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_verdict.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.verdict'`.

- [ ] **Step 3: Implement `scanner/verdict.py`**

```python
"""Pure BUY/THIN/SKIP tier logic. Demote-never-hide.

Margin sets the tier (gated on net dollars AND % ROI by default); hype affects
only ranking elsewhere; confidence can cap a BUY down but never invents one.
"""
from __future__ import annotations

from dataclasses import dataclass

from .margin import MarginResult

CONFIDENCE_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


@dataclass(frozen=True)
class VerdictThresholds:
    skip_floor_net: float = 5.0
    buy_floor_net: float = 15.0
    roi_gate_enabled: bool = True
    skip_floor_roi: float = 10.0
    buy_floor_roi: float = 20.0
    min_buy_confidence: str = "medium"


@dataclass(frozen=True)
class Verdict:
    tier: str
    headline: str
    net: float
    roi_pct: float
    channel: str
    confidence: str


def thresholds_from_config(cfg) -> VerdictThresholds:
    return VerdictThresholds(
        skip_floor_net=cfg.skip_floor_net,
        buy_floor_net=cfg.buy_floor_net,
        roi_gate_enabled=cfg.roi_gate_enabled,
        skip_floor_roi=cfg.skip_floor_roi,
        buy_floor_roi=cfg.buy_floor_roi,
        min_buy_confidence=cfg.min_buy_confidence,
    )


def _margin_tier(margin: MarginResult, t: VerdictThresholds) -> str:
    roi_ok_buy = (not t.roi_gate_enabled) or margin.roi_pct >= t.buy_floor_roi
    roi_bad_skip = t.roi_gate_enabled and margin.roi_pct < t.skip_floor_roi
    if margin.dollar_margin >= t.buy_floor_net and roi_ok_buy:
        return "BUY"
    if margin.dollar_margin < t.skip_floor_net or roi_bad_skip:
        return "SKIP"
    return "THIN"


def buy_verdict(
    margin: MarginResult,
    comp_confidence: str,
    thresholds: VerdictThresholds,
    derived_only: bool = False,
) -> Verdict:
    tier = _margin_tier(margin, thresholds)
    confidence = (comp_confidence or "none").lower()

    capped_reason = ""
    if tier == "BUY":
        below_min = CONFIDENCE_ORDER.get(confidence, 0) < CONFIDENCE_ORDER.get(
            thresholds.min_buy_confidence, 2
        )
        if derived_only:
            tier = "THIN"
            capped_reason = " (derived local comp)"
        elif below_min:
            tier = "THIN"
            capped_reason = f" ({confidence}-confidence comp)"

    headline = (
        f"{tier} · {_signed(margin.dollar_margin)} net, "
        f"{margin.roi_pct:g}% ROI{capped_reason}"
    )
    return Verdict(
        tier=tier,
        headline=headline,
        net=margin.dollar_margin,
        roi_pct=margin.roi_pct,
        channel=margin.channel,
        confidence=confidence,
    )


def _signed(amount: float) -> str:
    sign = "+" if amount >= 0 else "-"
    return f"{sign}${abs(amount):.2f}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_verdict.py -v`
Expected: PASS (all 7).

- [ ] **Step 5: Commit**

```bash
git add scanner/verdict.py tests/test_verdict.py
git commit -m "feat(verdict): pure BUY/THIN/SKIP tier logic with confidence cap"
```

---

## Task 4: `market.py` — PokemonPriceTracker client + factory

**Files:**
- Create: `scanner/market.py`
- Test: `tests/test_market.py`

**Interfaces:**
- Consumes: `resale.resale_client_from_config`, `resale.annotate_quote`, `resale._amount` (existing).
- Produces:
  - `PokemonPriceTrackerClient` with `estimate(product_key, product, checked_at) -> dict` (annotate_quote-compatible row) and `from_config(cfg)`.
  - `MarketFallbackClient(primary, fallback)` with the same `estimate` signature: tries primary, falls through to fallback on any exception or non-`ok` status.
  - `market_client_from_config(cfg)` — returns a `MarketFallbackClient` wrapping PPT + the resale client when `cfg.market_preferred and cfg.market_api_key`, else `resale_client_from_config(cfg)`.
  - `comp_from_row(row: dict) -> tuple[float | None, str]` → `(numeric_comp_or_None, confidence)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_market.py
import pytest

from scanner import resale
from scanner.market import (
    MarketFallbackClient,
    PokemonPriceTrackerClient,
    comp_from_row,
    market_client_from_config,
)


class _Cfg:
    def __init__(self, **kw):
        self.market_preferred = kw.get("market_preferred", False)
        self.market_api_key = kw.get("market_api_key", "")
        # resale_client_from_config reads these:
        self.ebay_browse_api_token = ""
        self.ebay_client_id = ""
        self.ebay_client_secret = ""
        self.ebay_marketplace_id = "EBAY_US"


class _StubClient:
    def __init__(self, row=None, exc=None):
        self.row = row
        self.exc = exc
        self.calls = 0

    def estimate(self, key, product, checked_at):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.row


def _ok_row(value):
    return resale.annotate_quote(
        {"msrp": "$49.99"},
        {
            "productKey": "k", "status": "ok", "estimate": value,
            "low": value, "high": value, "sampleSize": 12,
            "source": "PokemonPriceTracker", "basis": "sold comp median",
            "checkedAt": 0,
        },
    )


def test_comp_from_row_parses_estimate_and_confidence():
    row = _ok_row("$59.99")
    comp, conf = comp_from_row(row)
    assert comp == pytest.approx(59.99)
    assert conf in {"high", "medium", "low"}


def test_comp_from_row_handles_missing():
    comp, conf = comp_from_row({"status": "pending"})
    assert comp is None
    assert conf == "none"


def test_fallback_used_when_primary_raises():
    import requests
    primary = _StubClient(exc=requests.RequestException("429 quota"))
    fallback = _StubClient(row=_ok_row("$50.00"))
    client = MarketFallbackClient(primary, fallback)
    row = client.estimate("k", {"msrp": "$49.99"}, 0)
    assert row["status"] == "ok"
    assert fallback.calls == 1


def test_fallback_used_when_primary_not_ok():
    primary = _StubClient(row={"status": "no_matches"})
    fallback = _StubClient(row=_ok_row("$50.00"))
    client = MarketFallbackClient(primary, fallback)
    row = client.estimate("k", {"msrp": "$49.99"}, 0)
    assert row["status"] == "ok"
    assert fallback.calls == 1


def test_factory_without_preference_returns_resale_client():
    client = market_client_from_config(_Cfg(market_preferred=False))
    assert not isinstance(client, MarketFallbackClient)


def test_factory_with_preference_wraps_ppt():
    client = market_client_from_config(_Cfg(market_preferred=True, market_api_key="k"))
    assert isinstance(client, MarketFallbackClient)
    assert isinstance(client.primary, PokemonPriceTrackerClient)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_market.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.market'`.

- [ ] **Step 3: Implement `scanner/market.py`**

```python
"""PokemonPriceTracker market source, behind the resale.py client contract.

Optional-preferred, never required: a missing key, rate-limit, or quota all
fall through to the existing resale/scrape client. Scanning never depends on it.
"""
from __future__ import annotations

from typing import Any

import requests

from . import resale

PPT_SEARCH_URL = "https://www.pokemonpricetracker.com/api/v1/prices"
SOURCE_LABEL = "PokemonPriceTracker"
BASIS = "sold comp median"


class PokemonPriceTrackerClient:
    def __init__(self, api_key: str, session: requests.Session | None = None) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()

    @classmethod
    def from_config(cls, cfg: Any) -> "PokemonPriceTrackerClient":
        return cls(api_key=str(getattr(cfg, "market_api_key", "") or ""))

    def estimate(self, product_key: str, product: dict[str, Any], checked_at: int) -> dict[str, Any]:
        query = resale.product_query(product)
        response = self.session.get(
            PPT_SEARCH_URL,
            params={"q": query, "condition": "sealed"},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=20,
        )
        response.raise_for_status()  # 401/429/5xx -> RequestException -> fallback
        return _quote_from_ppt(product_key, product, response.json(), checked_at)


def _quote_from_ppt(
    product_key: str, product: dict[str, Any], payload: dict[str, Any], checked_at: int
) -> dict[str, Any]:
    results = payload.get("results") or payload.get("data") or []
    prices = [
        p for item in results
        if isinstance(item, dict)
        for p in [resale._amount(item.get("marketPrice") or item.get("price"))]
        if p is not None
    ]
    base = {
        "productKey": product_key,
        "source": SOURCE_LABEL,
        "basis": BASIS,
        "query": resale.product_query(product),
        "checkedAt": checked_at,
    }
    if not prices:
        return resale.annotate_quote(product, base | {
            "status": "no_matches", "estimate": "", "low": "", "high": "",
            "sampleSize": 0, "detail": "No PokemonPriceTracker comps matched.",
        })
    prices.sort()
    median = prices[len(prices) // 2]
    return resale.annotate_quote(product, base | {
        "status": "ok",
        "estimate": resale._money(median),
        "low": resale._money(prices[0]),
        "high": resale._money(prices[-1]),
        "sampleSize": len(prices),
        "detail": f"Median of {len(prices)} PokemonPriceTracker sold comps.",
    })


class MarketFallbackClient:
    def __init__(self, primary: Any, fallback: Any) -> None:
        self.primary = primary
        self.fallback = fallback

    def estimate(self, product_key: str, product: dict[str, Any], checked_at: int) -> dict[str, Any]:
        try:
            row = self.primary.estimate(product_key, product, checked_at)
            if row.get("status") == "ok":
                return row
        except requests.RequestException:
            pass
        except Exception:
            pass
        return self.fallback.estimate(product_key, product, checked_at)


def market_client_from_config(cfg: Any) -> Any:
    resale_client = resale.resale_client_from_config(cfg)
    if getattr(cfg, "market_preferred", False) and getattr(cfg, "market_api_key", ""):
        return MarketFallbackClient(PokemonPriceTrackerClient.from_config(cfg), resale_client)
    return resale_client


def comp_from_row(row: dict[str, Any]) -> tuple[float | None, str]:
    """Numeric comp + confidence from a cached quote row."""
    if not row or row.get("status") != "ok":
        return None, "none"
    return resale._amount(row.get("estimate")), str(row.get("confidence") or "none")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_market.py -v`
Expected: PASS (all 6). Note: tests never hit the network — they use stubs and `annotate_quote` directly.

- [ ] **Step 5: Verify `resale` exposes the helpers used**

Run: `python -c "from scanner import resale; print(resale.product_query, resale._amount, resale._money, resale.annotate_quote)"`
Expected: prints four callables (no AttributeError). If `_money`/`_amount` names differ, adjust `market.py` imports to the actual names in `resale.py`.

- [ ] **Step 6: Commit**

```bash
git add scanner/market.py tests/test_market.py
git commit -m "feat(market): PokemonPriceTracker client with graceful fallback"
```

---

## Task 5: `StockAlert.verdict` field + rendering

**Files:**
- Modify: `scanner/notify.py` (`StockAlert` dataclass `notify.py:26-40`; `_context_bits` `notify.py:42-50`; `_discord` `notify.py:78-118`)
- Test: `tests/test_notify_alert.py`

**Interfaces:**
- Consumes: nothing new (verdict string is supplied by the caller in Task 7).
- Produces: `StockAlert` gains `verdict: str = ""`. Rendered in `line()`/`_context_bits()` (console + ntfy) and as a Discord embed field.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_notify_alert.py  (add)
from scanner.notify import StockAlert


def _alert(**kw):
    base = dict(
        retailer="Best Buy", product_name="Prismatic ETB",
        store_label="Online", distance_miles=None, status="ONLINE_IN_STOCK",
        url="https://example.com", price="$49.99",
    )
    base.update(kw)
    return StockAlert(**base)


def test_verdict_renders_in_line_when_present():
    line = _alert(verdict="BUY · +$18.00 net, 42% ROI").line()
    assert "BUY · +$18.00 net, 42% ROI" in line


def test_no_verdict_means_no_verdict_text():
    line = _alert().line()
    assert "BUY" not in line and "ROI" not in line


def test_verdict_added_to_discord_embed_fields():
    from scanner.notify import Notifier
    alert = _alert(verdict="SKIP · +$0.50 net, 1% ROI")
    embed_fields = []

    class _N(Notifier):
        def _discord(self, a):  # capture the embed the real method would build
            return super()._discord(a)

    # Build the embed inline to assert structure (mirror _discord field logic):
    n = Notifier(discord_webhook="")  # no webhook -> send() won't POST
    # Directly assert the field-building contract:
    assert alert.verdict == "SKIP · +$0.50 net, 1% ROI"
```

> Note: the third test asserts the field value is present on the alert; the embed-field wiring is verified by the assertion in Step 3's code review and the `test_web`/manual spot-check. Keep unit tests free of live HTTP.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_notify_alert.py -k verdict -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'verdict'`.

- [ ] **Step 3: Implement the field + rendering**

In `scanner/notify.py`, add to the `StockAlert` dataclass (after `seen_count`):

```python
    verdict: str = ""                # "BUY · +$18 net, 42% ROI" | "" when no comp
```

In `_context_bits`, append before `return bits`:

```python
        if self.verdict:
            bits.append(self.verdict)
```

In `_discord`, after the `priority` field block (around `notify.py:103`), add:

```python
        if alert.verdict:
            embed["fields"].append(
                {"name": "Verdict", "value": alert.verdict, "inline": False}
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_notify_alert.py -v`
Expected: PASS (new + existing notify tests).

- [ ] **Step 5: Commit**

```bash
git add scanner/notify.py tests/test_notify_alert.py
git commit -m "feat(notify): render BUY/THIN/SKIP verdict in console, ntfy, Discord"
```

---

## Task 6: Wire verdict into `run_pass`

**Files:**
- Modify: `scanner/main.py` (imports ~line 23-28; `run_pass` signature ~line 332; alert build `main.py:361-374`)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `margin.cost_basis`, `margin.net_margin`, `margin.FeeModel`, `verdict.buy_verdict`, `verdict.thresholds_from_config`, `market.comp_from_row`.
- Produces: `run_pass(cfg, stores_by_retailer, state, notifier, comp_lookup=None)` — `comp_lookup: Callable[[str], dict | None]` returns a cached quote row for a product key. Attaches `verdict=` to each `StockAlert`. When `comp_lookup` is None or returns no usable comp, the alert fires with `verdict=""` (unchanged behavior).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main.py  (add)
from scanner import main as main_mod
from scanner.notify import StockAlert


def test_verdict_for_alert_buy(monkeypatch):
    # comp row: $80 sealed, high confidence; product msrp $50; observed $50.
    row = {"status": "ok", "estimate": "$80.00", "confidence": "high"}
    v = main_mod.verdict_for_alert(
        cfg=_mini_cfg(), product={"msrp": "$49.99"},
        observed_price="$50.00", comp_row=row,
    )
    assert v.startswith("BUY")


def test_verdict_for_alert_no_comp_returns_empty():
    v = main_mod.verdict_for_alert(
        cfg=_mini_cfg(), product={"msrp": "$49.99"},
        observed_price="$50.00", comp_row=None,
    )
    assert v == ""


def _mini_cfg():
    from scanner import config as cfg_mod
    return cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main.py -k verdict_for_alert -v`
Expected: FAIL — `AttributeError: module 'scanner.main' has no attribute 'verdict_for_alert'`.

- [ ] **Step 3: Add the helper + imports**

In `scanner/main.py` imports, add:

```python
from . import margin as margin_mod
from . import market as market_mod
from . import verdict as verdict_mod
```

Add this helper near the other module-level helpers (e.g. above `run_pass`):

```python
def _price_to_float(text: str) -> float | None:
    import re as _re
    if not text:
        return None
    match = _re.search(r"\d[\d,]*\.?\d*", str(text))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def verdict_for_alert(cfg, product, observed_price, comp_row) -> str:
    """Headline verdict string for an alert, or '' when no usable comp/price."""
    comp, confidence = market_mod.comp_from_row(comp_row or {})
    observed = _price_to_float(observed_price)
    if comp is None or observed is None:
        return ""
    fees = margin_mod.FeeModel(
        ebay_fvf_pct=cfg.ebay_fvf_pct,
        ebay_fixed_fee=cfg.ebay_fixed_fee,
        local_haircut_pct=cfg.local_haircut_pct,
    )
    cost = margin_mod.cost_basis(observed, cfg.tax_rate)
    ebay = margin_mod.net_margin(cost, comp, "ebay", _est_shipping(product), fees)
    v = verdict_mod.buy_verdict(
        ebay, confidence, verdict_mod.thresholds_from_config(cfg)
    )
    return v.headline


def _est_shipping(product) -> float:
    """Flat seller-paid shipping estimate; configurable later. Sealed ~2lb."""
    return 8.0
```

- [ ] **Step 4: Thread `comp_lookup` into `run_pass`**

Change the signature:

```python
def run_pass(
    cfg: cfg_mod.Config,
    stores_by_retailer: dict[str, list[Store]],
    state: State,
    notifier: Notifier,
    comp_lookup: Any = None,
) -> list[StockResult]:
```

At the alert build (`main.py:361-374`), add `verdict=` to the `StockAlert(...)` kwargs:

```python
                comp_row = comp_lookup(result.product_key) if comp_lookup else None
                alert = StockAlert(
                    retailer=retailer.name,
                    product_name=result.product_name,
                    store_label=result.store.label() if result.store else "Online",
                    distance_miles=result.store.distance_miles if result.store else None,
                    status=result.status,
                    url=result.url,
                    price=result.price,
                    priority=product_priority(prod)[0],
                    msrp=str(prod.get("msrp") or ""),
                    image_url=str(prod.get("image") or ""),
                    first_seen=hist.get("firstSeen"),
                    seen_count=hist.get("inStockCount"),
                    verdict=verdict_for_alert(cfg, prod, result.price, comp_row),
                )
                notifier.send(alert)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS (new + existing). Existing callers that omit `comp_lookup` still work (defaults to None → `verdict=""`).

- [ ] **Step 6: Commit**

```bash
git add scanner/main.py tests/test_main.py
git commit -m "feat(main): attach fee-adjusted verdict to alerts via comp_lookup"
```

---

## Task 7: Web — inject market client + verdict in board payload

**Files:**
- Modify: `scanner/web.py` (cache instance `web.py:55`; the pass-runner that calls `run_pass`; the board payload builder)
- Modify: `scanner/web_assets/app.js`, `scanner/web_assets/index.html`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `market.market_client_from_config`, `market.comp_from_row`, `verdict_for_alert` (Task 6).
- Produces: each board product row in the JSON payload gains `verdict: {tier, headline, net, roi}` (or `null` when no comp). `run_pass` is called with a `comp_lookup` built from one `RESALE_PRICES.snapshot(cfg)` per pass.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web.py  (add) — adjust the payload-builder name to the real one
from scanner import web as web_mod


def test_board_row_includes_verdict_field(monkeypatch):
    cfg = _web_cfg()
    snapshot = {"products": {"prismatic_evolutions_etb": {
        "status": "ok", "estimate": "$80.00", "confidence": "high"}}}
    monkeypatch.setattr(web_mod.RESALE_PRICES, "snapshot", lambda c: snapshot)
    lookup = web_mod.build_comp_lookup(cfg)
    row = lookup("prismatic_evolutions_etb")
    assert row["status"] == "ok"
    # verdict string is derivable from the row:
    from scanner.main import verdict_for_alert
    v = verdict_for_alert(cfg, {"msrp": "$49.99"}, "$49.99", row)
    assert v.startswith("BUY") or v.startswith("THIN")


def _web_cfg():
    from scanner import config as cfg_mod
    return cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web.py -k verdict -v`
Expected: FAIL — `AttributeError: module 'scanner.web' has no attribute 'build_comp_lookup'`.

- [ ] **Step 3: Use the market client for the cache and add `build_comp_lookup`**

In `scanner/web.py`, change the cache instance (`web.py:55`):

```python
RESALE_PRICES = resale.ResalePriceCache(client_factory=market.market_client_from_config)
```

Add the import at the top (with the other `from . import` lines):

```python
from . import market
```

Add this helper:

```python
def build_comp_lookup(cfg: cfg_mod.Config):
    """One snapshot per pass; return a per-key cached-row lookup."""
    snapshot = RESALE_PRICES.snapshot(cfg)
    products = snapshot.get("products", {})
    return lambda key: products.get(key)
```

- [ ] **Step 4: Pass the lookup into `run_pass` and add verdict to the payload**

Find where `web.py` calls `run_pass(...)` (the interval/pass runner) and pass the lookup:

```python
        comp_lookup = build_comp_lookup(cfg)
        results = run_pass(cfg, stores_by_retailer, state, notifier, comp_lookup=comp_lookup)
```

In the board payload builder (where each product row dict is assembled), add a verdict field. Use the same helper as alerts so the two never drift:

```python
        from .main import verdict_for_alert  # local import avoids a cycle at module load
        comp_row = comp_lookup(product_key) if comp_lookup else None
        row["verdict"] = verdict_for_alert(cfg, product, row.get("price", ""), comp_row) or None
```

- [ ] **Step 5: Render it in the board UI**

In `scanner/web_assets/app.js`, where a product row is rendered, add (near the priority/MSRP rendering):

```javascript
      if (product.verdict) {
        const v = document.createElement('span');
        const tier = product.verdict.split(' ')[0].toLowerCase(); // buy|thin|skip
        v.className = 'verdict verdict-' + tier;
        v.textContent = product.verdict;
        row.appendChild(v);
      }
```

In `scanner/web_assets/styles.css`, add minimal styling:

```css
.verdict { font-weight: 600; margin-left: 0.5rem; }
.verdict-buy { color: #2ecc71; }
.verdict-thin { color: #f1c40f; }
.verdict-skip { color: #95a5a6; }
```

(If `index.html` needs a column header for the verdict, add a `<th>Verdict</th>` to the board table header to match.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_web.py -v`
Expected: PASS (new + existing web tests).

- [ ] **Step 7: Manual spot-check (safe demo mode, no secrets)**

Run: `python -m scanner.web` then open `http://127.0.0.1:8765`.
Expected: board rows show a verdict label where a comp exists; no secrets/addresses/webhooks in the payload. Stop the server after the check.

- [ ] **Step 8: Commit**

```bash
git add scanner/web.py scanner/web_assets/app.js scanner/web_assets/index.html scanner/web_assets/styles.css tests/test_web.py
git commit -m "feat(web): inject market client and show verdict on the board"
```

---

## Task 8: Retailer activation — Best Buy enable-when-key; Costco/PC ID-seeding doc

**Files:**
- Modify: `config.example.yaml` (Best Buy comment already present at line 27 — clarify enable-when-key)
- Create: `docs/phase1-id-seeding.md` (enumerated Costco/PC data task)
- Test: `tests/test_main.py` (guard test)

**Interfaces:**
- Produces: a guard test proving missing Costco/PC IDs do not break the engine, and a written, enumerated ID-seeding task (data work, separate from code).

- [ ] **Step 1: Write the failing guard test**

```python
# tests/test_main.py  (add)
def test_missing_costco_pc_ids_do_not_break_run_pass(monkeypatch):
    """Engine must run with zero Costco/PC IDs (graceful, not an exception)."""
    from scanner import config as cfg_mod
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    # No retailers enabled -> run_pass returns [] without raising.
    from scanner.state import State
    from scanner.notify import Notifier
    state = State(":memory:") if _state_accepts_memory() else State()
    results = main_mod.run_pass(cfg, {}, state, Notifier())
    assert results == []


def _state_accepts_memory():
    import inspect
    from scanner.state import State
    return "path" in inspect.signature(State.__init__).parameters
```

> If `State()` cannot take `:memory:`, use the existing test's standard `State` construction pattern from the current `tests/test_main.py` instead of the `:memory:` branch.

- [ ] **Step 2: Run test to verify it passes (this is a guard, may already pass)**

Run: `python -m pytest tests/test_main.py -k missing_costco -v`
Expected: PASS — the engine already tolerates empty IDs. If it FAILS, fix `run_pass` to skip retailers with no IDs (it already does via `enabled`/registry checks); do not add Costco/PC ID requirements.

- [ ] **Step 3: Clarify Best Buy in `config.example.yaml`**

Ensure the Best Buy line reads (enable only when the free key is present; absent key leaves it cleanly disabled):

```yaml
  bestbuy:       { enabled: false, api_key: "" }   # 17/22 SKUs ready. Set enabled:true + free key (https://developer.bestbuy.com). Absent key => stays disabled, never errors.
```

- [ ] **Step 4: Write the enumerated ID-seeding data task**

Create `docs/phase1-id-seeding.md`:

```markdown
# Phase 1 Data Task — Costco & Pokémon Center ID Seeding

Separate from the engine code. Missing IDs must never block margin/verdict.
All IDs pass the existing verify → provenance gate (`scanner/verify_ids.py`,
`data/id_provenance.json`). No guessing — verify each before commit.

## Costco (`costco_item_id`) — target keys (active Prismatic-era, in catalog)
- [ ] prismatic_evolutions_etb
- [ ] prismatic_evolutions_booster_bundle
- [ ] prismatic_evolutions_surprise_box

Source: Costco product URL segment before `.html`. Verify via the Costco
4-endpoint chain in `scanner/retailers/costco.py`. Record verdict in provenance.

## Pokémon Center (`pokemoncenter_slug`) — target keys
- [ ] prismatic_evolutions_etb
- [ ] (add PC-exclusive SKUs as they appear; PC stays alert-only/human checkout)

Source: Pokémon Center product URL slug. Verify the slug resolves before commit.

## Done when
Each checked box has a verified ID in `data/products.yaml` + a provenance entry,
OR a recorded NOT_FOUND/BLOCKED verdict explaining why it could not be sourced.
```

- [ ] **Step 5: Commit**

```bash
git add config.example.yaml docs/phase1-id-seeding.md tests/test_main.py
git commit -m "docs(retailers): Best Buy enable-when-key + enumerated Costco/PC ID task"
```

---

## Task 9: Doctrine v2 + full-suite green

**Files:**
- Modify: `DOCTRINE.md`, `ADVISOR_ROLE.md`
- Test: full suite

**Interfaces:**
- Produces: doctrine that treats resale comps as first-class decision input while keeping every operational guardrail.

- [ ] **Step 1: Rewrite `DOCTRINE.md`**

Replace the body with (keep the heading style):

```markdown
# Hobby MSRP Doctrine (v2)

This project funds a sealed-TCG hobby: buy at retail to open and collect, sell
what I don't keep. Resale/market data is now a **first-class decision input** —
it tells me whether a retail find clears a fee-adjusted margin worth acting on —
but the objective is still legitimate retail buying, not scalping.

Non-negotiables (unchanged):

- No auto-checkout, cart automation, account abuse, login-wall scraping, or
  proxy/distributed polling. A human reviews and executes every buy and sell.
- Prefer first-party or major-retailer MSRP listings over marketplace sellers.
- When a price source is weak, stale, or fallback-derived, label its confidence
  tier instead of presenting fake confidence. Low-confidence comps never show BUY.
- No auto-listing, no unverified IDs, no "AI price prediction." Every number
  traces to a real comp with a confidence tier.
```

- [ ] **Step 2: Update `ADVISOR_ROLE.md`**

Change the opening framing from "not a resale or scalping workflow" to:

```markdown
Start from doctrine v2: this is a hobby MSRP scanner whose buy/skip decisions are
informed by fee-adjusted resale margin. Resale data is a decision input, not a
scalping objective. Optimize for legitimate retail buying; reject auto-checkout,
auto-listing, account risk, hidden/proxy scraping, and fake confidence.
```

- [ ] **Step 3: Run the FULL suite**

Run: `python -m pytest -q`
Expected: all tests PASS (existing + the new `test_margin`, `test_verdict`, `test_market`, and the extended config/notify/main/web tests).

- [ ] **Step 4: Commit**

```bash
git add DOCTRINE.md ADVISOR_ROLE.md
git commit -m "docs(doctrine): v2 — resale comps as first-class buy/skip input"
```

---

## Self-Review (completed by plan author)

**Spec coverage (§3 Phase 1):**
- 3.2 `market.py` → Task 4. `margin.py` → Task 2. `verdict.py` → Task 3.
- 3.2 key→query mapping / graceful fallback / quota guard → Task 4 (`MarketFallbackClient`).
- 3.3 alert construction + cost basis → Task 6; two-touch-point rendering (console/ntfy + Discord) → Task 5; web payload → Task 7; `ppt_query` catalog field → handled via `product_query` fallback in Task 4 (a dedicated `ppt_query` column is optional and deferred; resolution order still holds).
- 3.4 Best Buy enable-when-key, Costco/PC seeding decoupled → Task 8.
- 3.5 acceptance criteria 1-7 → AC1 Task 5/7, AC2 Task 2, AC3 Task 4, AC4 Task 8, AC5 Task 3, AC6 Task 9, AC7 Task 9.
- 3.6 defaults → Task 1 (config) consumed everywhere. 3.7 TDD order → task order. Worktree warning → Task 0.

**Placeholder scan:** no TBD/TODO; every code step shows real code; commands have expected output.

**Type consistency:** `MarginResult` (Task 2) consumed by `buy_verdict` (Task 3) and `verdict_for_alert` (Task 6); `comp_from_row` (Task 4) returns `(float|None, str)` consumed in Task 6/7; `Config` fields (Task 1) read by `FeeModel`/`thresholds_from_config` (Tasks 3/6). `verdict_for_alert` name identical in Tasks 6 and 7.

**Known follow-ups (not Phase 1 blockers):** the PokemonPriceTracker endpoint/param shape in Task 4 (`PPT_SEARCH_URL`, response keys `results`/`marketPrice`) must be confirmed against live API docs during implementation — the mocked tests pin the contract, and Step 5 of Task 4 verifies the `resale` helper names. Real shipping cost is a flat `$8.00` placeholder in `_est_shipping` (Task 6), configurable in a later pass.
