# `/poke` Pipeline — Phase 0 + Phase 1 (Deterministic Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the two empirical unknowns (Phase 0 spike), then build the deterministic core of the `/poke` discovery pipeline — schema + STOP gate, append-only observation ledger, scorer (4 lenses + fake-markdown + dedup), and HTML renderer + golden test — fully exercised against a hand-authored fixture sweep, sealed-first.

**Architecture:** A new in-repo subpackage `scanner/discovery/` of pure-ish modules that import the existing comp backbone (`scanner.margin`, `scanner.verdict`, `scanner.market`) directly, so the dashboard's Flipper math equals the scanner's BUY/THIN/SKIP verdict by construction. No live web acquisition in this plan — the renderer/scorer/ledger operate on a fixture sweep JSON (the pattern proven by the gun system's `independence-day.json`). Live acquisition, raw/graded comp wiring, and the in-session OPENER/command are a follow-on plan, sequenced by Phase 0's findings.

**Tech Stack:** Python 3 (stdlib + `pyyaml`, both vendored), `pytest` (existing suite), dataclasses, `from __future__ import annotations` style throughout. No new third-party dependency.

## Global Constraints

Every task implicitly includes these. Values copied verbatim from the approved spec `2026-06-27-poke-deal-research-pipeline-design.md` (committed `6c3fcae`).

- **Doctrine (hard, permanent):** no auto-checkout, cart automation, account abuse, login-wall scraping, proxy/distributed polling, auto-listing, unverified IDs, or "AI price prediction." Every number traces to a real comp with a confidence tier. The tool advises; the human transacts.
- **Price-accuracy STOP gate (§6 — halt on any violation):** a `verified` row MUST have `source_url` + `captured_at` and must NOT carry an `EST` badge; an `est` row MUST have `derivation_method` and MUST carry an `EST` badge; no `deal_price` ≤ 0 or non-numeric; `pct_off` MUST be computed from `market_comp`, never MSRP; a graded row MUST carry `grade` + `grader`; a raw row MUST carry `condition`; an `authenticity_risk` row MUST NOT be rendered as a confirmed `STEAL`.
- **Backbone-anchored (§2, §4.3):** the Flipper (FLP) lens computes net margin via `scanner.margin.net_margin` + `scanner.verdict.buy_verdict` using the existing `deal_intelligence` config (`ebay_fvf_pct`, `ebay_fixed_fee`, floors). Never re-hardcode fees. Dashboard == scanner by construction.
- **Two-ledger distinction (§5, §12):** this observation ledger (`data/poke/price_history.jsonl`, market observations) is distinct from the Phase-2 inventory ledger (what you own). Never merge them.
- **Asset-class gate (§3.3):** a row renders as a confirmed deal only with a verified comp for its own class and `deal_price` ≥ ~5% below comp; an EST comp may render badged `EST`, never `STEAL`; no usable comp → not a deal row.
- **Scope fence (this plan):** Phase 0 spike + Phase 1 deterministic core on a fixture, sealed-first. **Do NOT** build live web acquisition, the OPENER/command, raw/graded comp clients, the persona self-test, the prompt-durability sidecar, or the inventory ledger — those are the follow-on plan.
- **Style:** match existing modules — `from __future__ import annotations`, dataclasses, type hints, `SystemExit` for config errors, snake_case, pytest. TDD: failing test first. Frequent commits.
- **Branch:** current branch `phase1-deal-intelligence`; working tree clean except untracked `.playwright-mcp/` (leave it alone). Implement on a dedicated branch `poke-discovery-pipeline`. Full existing suite (172+) must stay green; commit only files each task names.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `scanner/discovery/__init__.py` | Create | Package marker. |
| `scanner/discovery/schema.py` | Create | `DealRow` dataclass + `validate_row` / `assert_sweep` STOP gate (pure). |
| `scanner/discovery/ledger.py` | Create | Append-only observation ledger: `item_key`, `entry_id`, idempotent `append_observation` (small file I/O). |
| `scanner/discovery/score.py` | Create | `pct_off`, badges, fake-markdown flags, lens tags (FLP via backbone), dedup, minimum-discount (pure). |
| `scanner/discovery/render.py` | Create | Sweep dict → HTML via template; nav anchors; section injection; `__main__` CLI. |
| `scanner/discovery/template.html` | Create | Self-contained dark dashboard template (placeholders + inject markers). |
| `scanner/config.py` | Modify | Add `PokeCfg` + `poke` field + parse a `poke:` block. |
| `config.example.yaml` | Modify | Document the `poke:` block. |
| `data/poke/fixtures/sample-sweep.json` | Create | Hand-authored sealed-first fixture sweep (≥10 deal rows; verified + EST + authenticity + catalog-overlap). |
| `docs/poke/PHASE0_FINDINGS.md` | Create | Recorded answers from the two Phase-0 probes (gates the follow-on plan). |
| `tests/test_poke_schema.py` | Create | STOP-gate validation. |
| `tests/test_poke_ledger.py` | Create | Idempotency + kind separation + corrections-append. |
| `tests/test_poke_score.py` | Create | Lens determinism, fake-markdown thresholds, dedup, min-discount, FLP == scanner. |
| `tests/test_poke_render.py` | Create | Required sections present, anchors resolve, every deal row carries source+date. |
| `tests/test_poke_golden.py` | Create | Golden test on the fixture (pass + each hard-fail). |

---

## Task 0: Branch from clean baseline

**Files:** none (git only)

**Interfaces:**
- Produces: a dedicated branch `poke-discovery-pipeline` for isolated review diffs.

- [ ] **Step 1: Confirm clean baseline (ignoring the untracked playwright dir)**

Run: `git status --porcelain | grep -v '.playwright-mcp' | wc -l && git log --oneline -1`
Expected: `0` tracked changes; HEAD at `6c3fcae` (the spec refinement) or later.

- [ ] **Step 2: Confirm the suite is green before changing anything**

Run: `python -m pytest -q 2>&1 | tail -1`
Expected: `172 passed` (or more). This is the regression baseline for every later task.

- [ ] **Step 3: Create the feature branch**

Run: `git switch -c poke-discovery-pipeline`
Expected: "Switched to a new branch 'poke-discovery-pipeline'".

---

## Task 1: Phase 0 spike — comp-verification probe (gates decision #2)

> **This is an investigative spike, not TDD.** Its deliverable is a recorded finding, not code that ships. It answers: *does a sealed product yield a verified-tier comp end-to-end through the existing backbone in the current repo state?* If not, even sealed renders `EST` under the render gate — which the follow-on plan must branch on.

**Files:**
- Create: `scripts/poke_phase0_comp_probe.py`
- Create/append: `docs/poke/PHASE0_FINDINGS.md`

**Interfaces:**
- Consumes: `scanner.config.load` / `from_mapping`, `scanner.market.market_client_from_config`, `scanner.market.comp_from_row`, `scanner.resale` cache (existing).
- Produces: a printed `(comp, confidence_tier)` for a sealed catalog product + a recorded finding.

- [ ] **Step 1: Write the probe script**

```python
# scripts/poke_phase0_comp_probe.py
"""Phase-0 spike: does the comp backbone return a VERIFIED-tier comp for a
sealed product in the current repo state? Prints the comp + confidence tier.
Read-only; no writes to state. Run manually."""
from __future__ import annotations

import sys

from scanner import config as cfg_mod
from scanner import market as market_mod

SEALED_KEY = "prismatic_evolutions_etb"  # a known catalog sealed product


def main() -> int:
    cfg = cfg_mod.load()  # uses the operator's real config.yaml (keys if present)
    product = cfg.products.get(SEALED_KEY)
    if not product:
        print(f"FAIL: {SEALED_KEY} not in catalog")
        return 1
    client = market_mod.market_client_from_config(cfg)
    row = client.estimate(SEALED_KEY, product, 0)
    comp, confidence = market_mod.comp_from_row(row)
    print(f"product={SEALED_KEY}")
    print(f"client={type(client).__name__}")
    print(f"status={row.get('status')!r} source={row.get('source')!r}")
    print(f"comp={comp!r} confidence_tier={confidence!r}")
    print(f"price_confidence={'verified' if confidence in {'high','medium'} else 'est/low'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the probe**

Run: `python scripts/poke_phase0_comp_probe.py`
Expected: prints a comp value + confidence tier. (If it errors on a missing `config.yaml`, the operator must point it at a real config first — the finding then records "blocked: no config/key".)

- [ ] **Step 3: Record the finding**

Create `docs/poke/PHASE0_FINDINGS.md` and write the comp-probe result:

```markdown
# Phase 0 Findings — `/poke` pipeline

## Probe A — sealed comp verification (Task 1)
- Date run: <YYYY-MM-DD>
- Client used: <PokemonPriceTrackerClient | MarketFallbackClient | resale fallback>
- Sealed product: prismatic_evolutions_etb
- Result: comp=<value> confidence_tier=<high|medium|low|none>
- **Verdict:** <YES sealed yields a verified-tier comp today | NO — only low-confidence
  fallback is live; sealed renders EST until a PPT key/quota is in place>
- Implication for follow-on plan: <e.g. "obtain PPT key before live-acquisition phase"
  | "sealed STEALs available now, proceed">
```

- [ ] **Step 4: Commit**

```bash
git add scripts/poke_phase0_comp_probe.py docs/poke/PHASE0_FINDINGS.md
git commit -m "spike(poke): Phase 0 comp-verification probe + finding"
```

---

## Task 2: Phase 0 spike — source-fetchability probe (shapes DISCOVER)

> **Investigative spike.** Answers: *which candidate TCG deal sources are actually fetchable (plain WebFetch vs Playwright-needed vs Cloudflare-blocked)?* If fetchable feeds are thin, the follow-on plan's DISCOVER shifts toward direct eBay/TCGplayer marketplace scanning. This step is done by the implementing agent in-session using WebFetch and the Playwright MCP browser tools; it records evidence, it does not build an adapter.

**Files:**
- Create: `docs/poke/sources.md` (initial tiered list)
- Append: `docs/poke/PHASE0_FINDINGS.md`

**Interfaces:**
- Produces: a tiered, evidence-backed source list + a recorded fetchability finding.

- [ ] **Step 1: Seed the candidate source list**

Create `docs/poke/sources.md`:

```markdown
# `/poke` Sources (tiered by fetchability — evidence-backed, append-only)

Probe each before relying on it. A "Just a moment…" / challenge page is NEVER data;
record it blocked. Removals require a dated entry + reason (sources never silently shrink).

## Candidates to probe (Phase 0)
- r/PKMNTCGDeals (reddit.com/r/PKMNTCGDeals) — deal feed
- TCG deal blogs / curators (record specific URLs as found)
- Target weekly / clearance pages — retailer sale
- Best Buy deals pages — retailer sale
- Costco TCG pages — retailer sale
- Pokémon Center sale pages — retailer sale
- eBay (sold + active listings) — marketplace
- TCGplayer (market + listings) — marketplace

## Tier results (filled by probe)
| Source | Method that worked | Status | Notes |
|---|---|---|---|
| (fill during Step 2) | | | |
```

- [ ] **Step 2: Probe each candidate and record the method that works**

For each candidate: try plain WebFetch first; if it 403s / returns a challenge page, try the Playwright MCP browser (`browser_navigate` + `browser_snapshot`). Record, per source: which method returned real deal content (`webfetch` / `playwright` / `blocked`), and a one-line note. Fill the tier table in `sources.md`. Do **not** fabricate availability — only record what you actually observed.

- [ ] **Step 3: Record the finding**

Append to `docs/poke/PHASE0_FINDINGS.md`:

```markdown
## Probe B — source fetchability (Task 2)
- Date run: <YYYY-MM-DD>
- Fetchable via WebFetch: <list>
- Fetchable only via Playwright: <list>
- Blocked (Cloudflare/challenge): <list>
- **Verdict:** <enough curated/aggregator feeds exist for an aggregator-led DISCOVER
  | feeds are thin — follow-on DISCOVER leans on direct eBay/TCGplayer marketplace scan>
- Implication for follow-on plan: <one line>
```

- [ ] **Step 4: Commit**

```bash
git add docs/poke/sources.md docs/poke/PHASE0_FINDINGS.md
git commit -m "spike(poke): Phase 0 source-fetchability probe + finding"
```

---

## Task 3: Config — `poke` block

**Files:**
- Modify: `scanner/config.py` (add `PokeCfg` after `RetailerCfg` ~line 29; add `poke` field to `Config`; parse in `from_mapping` before the `return Config(`)
- Modify: `config.example.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `PokeCfg(min_rows: int = 10, staleness_days: int = 30, steal_pct: float = 30.0, min_discount_pct: float = 5.0, grading_cost_all_in: float = 97.50)` and `Config.poke: PokeCfg`. Parsed from an optional top-level `poke:` mapping.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py  (add)
from scanner import config as cfg_mod


def test_poke_defaults_when_absent():
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    assert cfg.poke.min_rows == 10
    assert cfg.poke.staleness_days == 30
    assert cfg.poke.steal_pct == 30.0
    assert cfg.poke.min_discount_pct == 5.0
    assert cfg.poke.grading_cost_all_in == 97.50


def test_poke_overrides_parse():
    cfg = cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "poke": {"min_rows": 5, "staleness_days": 14, "steal_pct": 25,
                 "min_discount_pct": 8, "grading_cost_all_in": 80},
    })
    assert cfg.poke.min_rows == 5
    assert cfg.poke.staleness_days == 14
    assert cfg.poke.steal_pct == 25.0
    assert cfg.poke.min_discount_pct == 8.0
    assert cfg.poke.grading_cost_all_in == 80.0


def test_poke_must_be_mapping():
    import pytest
    with pytest.raises(SystemExit):
        cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}, "poke": []})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -k poke -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'poke'`.

- [ ] **Step 3: Add `PokeCfg` and the `Config.poke` field**

In `scanner/config.py`, after the `RetailerCfg` dataclass (line 26-28) add:

```python
@dataclass
class PokeCfg:
    min_rows: int = 10            # golden-test acquisition-failure floor
    staleness_days: int = 30      # comp older than this is flagged stale
    steal_pct: float = 30.0       # verified deal at/above this % off -> STEAL eligible
    min_discount_pct: float = 5.0 # below this % off market -> not a deal row
    grading_cost_all_in: float = 97.50  # live PSA tier all-in (config, value tiers paused 2026-06)
```

In the `Config` dataclass, after `market_cache_ttl_seconds` (line 64) add:

```python
    poke: PokeCfg = field(default_factory=PokeCfg)
```

(`field` is already imported at `config.py:5`.)

- [ ] **Step 4: Parse the `poke:` block in `from_mapping`**

In `from_mapping`, just before `return Config(` (line 146) add:

```python
    poke_raw = raw.get("poke") or {}
    if not isinstance(poke_raw, dict):
        raise SystemExit("config.yaml: poke must be a mapping.")
    try:
        poke_cfg = PokeCfg(
            min_rows=int(poke_raw.get("min_rows", 10)),
            staleness_days=int(poke_raw.get("staleness_days", 30)),
            steal_pct=_num(poke_raw, "steal_pct", 30.0, "poke.steal_pct"),
            min_discount_pct=_num(poke_raw, "min_discount_pct", 5.0, "poke.min_discount_pct"),
            grading_cost_all_in=_num(poke_raw, "grading_cost_all_in", 97.50, "poke.grading_cost_all_in"),
        )
    except (TypeError, ValueError):
        raise SystemExit("config.yaml: poke.min_rows / poke.staleness_days must be integers.")
```

Then add to the `return Config(...)` keyword arguments:

```python
        poke=poke_cfg,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (new poke tests + all existing config tests stay green).

- [ ] **Step 6: Document the block in `config.example.yaml`**

Add after the `market:` block:

```yaml
# --- /poke AI deal-research pipeline (discovery sweeps) ---
# Discovery is a sibling to the scanner; comps are anchored to the same backbone.
poke:
  min_rows: 10              # golden-test floor; a sweep below this is "likely acquisition failure"
  staleness_days: 30        # a comp older than this is flagged stale, excluded from STEAL
  steal_pct: 30             # a VERIFIED deal at/above this % off market is STEAL-eligible
  min_discount_pct: 5       # below this % off market it is not a deal row
  grading_cost_all_in: 97.50  # live PSA tier all-in (value tiers paused 2026-06; config, not hardcoded)
```

- [ ] **Step 7: Commit**

```bash
git add scanner/config.py config.example.yaml tests/test_config.py
git commit -m "feat(config): add poke discovery config block"
```

---

## Task 4: `schema.py` — `DealRow` + STOP gate

**Files:**
- Create: `scanner/discovery/__init__.py` (empty)
- Create: `scanner/discovery/schema.py`
- Test: `tests/test_poke_schema.py`

**Interfaces:**
- Consumes: nothing (pure).
- Produces:
  - `DealRow` dataclass (fields below).
  - `StopGateError(Exception)`.
  - `validate_row(row: DealRow) -> list[str]` — returns violation messages (empty = clean).
  - `assert_sweep(rows: list[DealRow]) -> None` — raises `StopGateError` if any row violates.
  - `row_from_dict(d: dict) -> DealRow` — build a row from a sweep-JSON dict.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_poke_schema.py
import pytest

from scanner.discovery.schema import (
    DealRow, StopGateError, assert_sweep, row_from_dict, validate_row,
)


def _sealed(**kw):
    base = dict(
        item="Prismatic Evolutions ETB", asset_class="sealed", category="sealed-etb",
        deal_price=39.99, market_comp=60.0, retailer="Target",
        source_url="https://example.com/x", captured_at="2026-06-27",
        price_confidence="verified", comp_confidence="high", pct_off=33,
        badges=["STEAL"],
    )
    base.update(kw)
    return DealRow(**base)


def test_clean_verified_row_has_no_violations():
    assert validate_row(_sealed()) == []


def test_verified_row_needs_source_and_date():
    assert validate_row(_sealed(source_url="")) != []
    assert validate_row(_sealed(captured_at="")) != []


def test_verified_row_must_not_carry_est_badge():
    assert validate_row(_sealed(badges=["STEAL", "EST"])) != []


def test_est_row_needs_method_and_est_badge():
    bad = _sealed(price_confidence="est", derivation_method="", badges=[])
    assert validate_row(bad) != []
    good = _sealed(price_confidence="est", derivation_method="comp_inference",
                   badges=["EST"], comp_confidence="low")
    assert validate_row(good) == []


def test_nonpositive_price_is_a_violation():
    assert validate_row(_sealed(deal_price=0)) != []


def test_pct_off_must_match_market_comp():
    # comp 60, deal 39.99 -> ~33%; claiming 80 is inconsistent
    assert validate_row(_sealed(pct_off=80)) != []


def test_graded_row_needs_grade_and_grader():
    g = _sealed(asset_class="graded", grade="", grader="")
    assert validate_row(g) != []
    ok = _sealed(asset_class="graded", grade="PSA 10", grader="PSA")
    assert validate_row(ok) == []


def test_raw_row_needs_condition():
    r = _sealed(asset_class="raw", condition="")
    assert validate_row(r) != []


def test_authenticity_risk_cannot_be_a_steal():
    a = _sealed(authenticity_risk=True, badges=["STEAL"])
    assert validate_row(a) != []


def test_assert_sweep_raises_on_any_violation():
    with pytest.raises(StopGateError):
        assert_sweep([_sealed(), _sealed(source_url="")])


def test_row_from_dict_roundtrips_known_fields():
    row = row_from_dict({"item": "X", "asset_class": "sealed", "category": "sealed-etb",
                         "deal_price": 10.0, "market_comp": 20.0, "retailer": "R",
                         "source_url": "u", "captured_at": "2026-06-27",
                         "price_confidence": "verified", "comp_confidence": "high",
                         "pct_off": 50, "badges": ["STEAL"]})
    assert row.item == "X" and row.deal_price == 10.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_poke_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.discovery'`.

- [ ] **Step 3: Create the package + implement `schema.py`**

Create empty `scanner/discovery/__init__.py`. Then create `scanner/discovery/schema.py`:

```python
"""Per-deal row schema + the pre-render STOP gate. Pure, no I/O.

Price accuracy beats coverage. The gate halts a sweep rather than ship a row
that overstates confidence or fabricates a basis.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields

ASSET_CLASSES = {"sealed", "raw", "graded"}
PRICE_CONFIDENCE = {"verified", "est"}


class StopGateError(Exception):
    """Raised when any row violates the price-accuracy STOP gate."""


@dataclass
class DealRow:
    item: str
    asset_class: str            # sealed | raw | graded
    category: str               # display section key, e.g. "sealed-etb"
    deal_price: float
    market_comp: float | None
    retailer: str
    source_url: str
    captured_at: str            # ISO date
    price_confidence: str       # verified | est
    comp_confidence: str        # high | medium | low | none
    pct_off: float | None = None
    derivation_method: str = "" # required when price_confidence == "est"
    confidence_detail: str = ""
    capture_method: str = ""
    stale: bool = False
    badges: list[str] = field(default_factory=list)     # STEAL | WARN | EST
    warn_reason: str = ""
    lens_tags: list[str] = field(default_factory=list)  # COL | PLY | INV | FLP
    stock_status: str = "unknown"
    stock_evidence: str = ""
    reprint_risk: bool = False
    finite: bool = False
    grade: str = ""             # graded only, e.g. "PSA 10"
    grader: str = ""            # PSA | CGC | BGS
    cert_number: str = ""
    condition: str = ""         # raw only, e.g. NM | LP
    authenticity_risk: bool = False
    scanner_verdict: str = ""   # attached when item matches a catalog SKU
    note: str = ""
    set: str = ""               # for dedup/ledger identity
    variant: str = ""           # for dedup/ledger identity


def validate_row(row: DealRow) -> list[str]:
    v: list[str] = []
    tag = row.item or "<unnamed>"
    if not isinstance(row.deal_price, (int, float)) or row.deal_price <= 0:
        v.append(f"{tag}: deal_price must be a positive number")
    if row.asset_class not in ASSET_CLASSES:
        v.append(f"{tag}: asset_class must be one of {sorted(ASSET_CLASSES)}")
    if row.price_confidence not in PRICE_CONFIDENCE:
        v.append(f"{tag}: price_confidence must be 'verified' or 'est'")
    if row.price_confidence == "verified":
        if not row.source_url:
            v.append(f"{tag}: verified row needs source_url")
        if not row.captured_at:
            v.append(f"{tag}: verified row needs captured_at")
        if "EST" in row.badges:
            v.append(f"{tag}: verified row must not carry EST badge")
    if row.price_confidence == "est":
        if not row.derivation_method:
            v.append(f"{tag}: est row needs derivation_method")
        if "EST" not in row.badges:
            v.append(f"{tag}: est row must carry EST badge")
    if row.market_comp is not None and row.pct_off is not None and row.market_comp > 0:
        expected = round((row.market_comp - row.deal_price) / row.market_comp * 100)
        if abs(expected - row.pct_off) > 1:
            v.append(f"{tag}: pct_off must be computed from market_comp (got {row.pct_off}, expected ~{expected})")
    if row.asset_class == "graded" and (not row.grade or not row.grader):
        v.append(f"{tag}: graded row needs grade + grader")
    if row.asset_class == "raw" and not row.condition:
        v.append(f"{tag}: raw row needs condition")
    if row.authenticity_risk and "STEAL" in row.badges:
        v.append(f"{tag}: authenticity_risk row must not be a confirmed STEAL")
    return v


def assert_sweep(rows: list[DealRow]) -> None:
    violations = [msg for row in rows for msg in validate_row(row)]
    if violations:
        raise StopGateError("STOP GATE failed:\n" + "\n".join(violations))


_FIELD_NAMES = {f.name for f in fields(DealRow)}


def row_from_dict(d: dict) -> DealRow:
    """Build a DealRow from a sweep-JSON dict, ignoring unknown keys."""
    return DealRow(**{k: v for k, v in d.items() if k in _FIELD_NAMES})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_poke_schema.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add scanner/discovery/__init__.py scanner/discovery/schema.py tests/test_poke_schema.py
git commit -m "feat(poke): DealRow schema + price-accuracy STOP gate"
```

---

## Task 5: `ledger.py` — append-only observation ledger

**Files:**
- Create: `scanner/discovery/ledger.py`
- Test: `tests/test_poke_ledger.py`

**Interfaces:**
- Consumes: nothing (stdlib `hashlib`, `json`).
- Produces:
  - `item_key(obs: dict) -> str` — normalized identity `set|item|variant|grade|condition`, lowercased.
  - `entry_id(kind: str, ikey: str, source_url: str, capture_date: str) -> str` — sha256 hex.
  - `existing_ids(path) -> set[str]` — entry_ids already in the ledger file.
  - `append_observation(path, obs: dict) -> bool` — append if new; return True if appended, False if duplicate. Requires `obs["kind"]` in {"deal","market_comp"}.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_poke_ledger.py
import json

import pytest

from scanner.discovery.ledger import (
    append_observation, entry_id, existing_ids, item_key,
)


def _obs(**kw):
    base = dict(kind="deal", item="Prismatic ETB", set="Prismatic Evolutions",
                variant="", grade="", condition="", price=39.99, currency="USD",
                source_url="https://example.com/x", capture_date="2026-06-27",
                captured="verified", sweep_id="2026-06-27-now", event="now", note="")
    base.update(kw)
    return base


def test_item_key_is_normalized_identity():
    k = item_key(_obs())
    assert k == "prismatic evolutions|prismatic etb||"  + "|"  # set|item|variant|grade|condition
    # exact form pinned in implementation; this asserts lowercase + pipe-joined
    assert k.islower() and k.count("|") == 4


def test_entry_id_is_stable_and_kind_sensitive():
    a = entry_id("deal", "k", "u", "2026-06-27")
    b = entry_id("deal", "k", "u", "2026-06-27")
    c = entry_id("market_comp", "k", "u", "2026-06-27")
    assert a == b and a != c


def test_append_is_idempotent(tmp_path):
    p = tmp_path / "ledger.jsonl"
    assert append_observation(p, _obs()) is True
    assert append_observation(p, _obs()) is False          # duplicate -> no-op
    lines = p.read_text().strip().splitlines()
    assert len(lines) == 1


def test_deal_and_market_comp_are_separate_lines(tmp_path):
    p = tmp_path / "ledger.jsonl"
    append_observation(p, _obs(kind="deal"))
    append_observation(p, _obs(kind="market_comp", price=60.0))
    assert len(p.read_text().strip().splitlines()) == 2


def test_correction_appends_not_mutates(tmp_path):
    p = tmp_path / "ledger.jsonl"
    append_observation(p, _obs(price=39.99))
    append_observation(p, _obs(price=42.99, capture_date="2026-06-28",
                               note="corrects 2026-06-27 entry"))
    lines = p.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["price"] == 39.99  # original is untouched


def test_bad_kind_rejected(tmp_path):
    with pytest.raises(ValueError):
        append_observation(tmp_path / "l.jsonl", _obs(kind="banana"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_poke_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.discovery.ledger'`.

- [ ] **Step 3: Implement `ledger.py`**

```python
"""Append-only observation ledger for /poke sweeps.

One immutable JSON object per line. Idempotent: a re-observed (kind, identity,
source, date) adds nothing. Corrections are appended as new lines, never edits.
This is the MARKET-OBSERVATION ledger; it is NOT the Phase-2 inventory ledger.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

VALID_KINDS = {"deal", "market_comp"}


def item_key(obs: dict) -> str:
    parts = [obs.get("set", ""), obs.get("item", ""), obs.get("variant", ""),
             obs.get("grade", ""), obs.get("condition", "")]
    return "|".join(str(p).strip().lower() for p in parts)


def entry_id(kind: str, ikey: str, source_url: str, capture_date: str) -> str:
    raw = f"{kind}|{ikey}|{source_url}|{capture_date}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def existing_ids(path: Path) -> set[str]:
    path = Path(path)
    if not path.exists():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ids.add(json.loads(line)["entry_id"])
        except (json.JSONDecodeError, KeyError):
            continue
    return ids


def append_observation(path, obs: dict) -> bool:
    kind = obs.get("kind")
    if kind not in VALID_KINDS:
        raise ValueError(f"obs.kind must be one of {sorted(VALID_KINDS)}, got {kind!r}")
    path = Path(path)
    ikey = item_key(obs)
    eid = entry_id(kind, ikey, obs.get("source_url", ""), obs.get("capture_date", ""))
    if eid in existing_ids(path):
        return False
    record = {"entry_id": eid, "item_key": ikey, **obs}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_poke_ledger.py -v`
Expected: PASS. (If `test_item_key_is_normalized_identity` pins an exact string that differs, adjust the assertion to the real `item_key` output — the invariants tested are lowercase + 4 pipes.)

- [ ] **Step 5: Commit**

```bash
git add scanner/discovery/ledger.py tests/test_poke_ledger.py
git commit -m "feat(poke): append-only idempotent observation ledger"
```

---

## Task 6: `score.py` — pct_off, badges, fake-markdown, lenses, dedup

**Files:**
- Create: `scanner/discovery/score.py`
- Test: `tests/test_poke_score.py`

**Interfaces:**
- Consumes: `scanner.margin.FeeModel`, `scanner.margin.cost_basis`, `scanner.margin.net_margin`, `scanner.verdict.VerdictThresholds`, `scanner.verdict.buy_verdict`, `scanner.verdict.thresholds_from_config`; `DealRow` from `scanner.discovery.schema`.
- Produces:
  - `compute_pct_off(deal_price: float, market_comp: float | None) -> float | None`.
  - `fake_markdown_flags(deal_price, market_comp, claimed_was: float | None, has_legit_explanation: bool) -> list[str]` → subset of `{"INFLATED_ORIGINAL","SUSPICIOUSLY_LOW","MISLEADING_PCT"}`.
  - `flipper_is_buy(deal_price: float, market_comp: float, cfg) -> bool` — net margin via backbone clears BUY.
  - `assign_badges(row: DealRow, cfg) -> list[str]` — STEAL / WARN / EST per discipline.
  - `lens_tags(row: DealRow, cfg) -> list[str]` — COL / PLY / INV / FLP per strong-signal cutoffs.
  - `dedup(rows: list[DealRow]) -> list[DealRow]` — keep lowest deal_price per identity.
  - `split_min_discount(rows: list[DealRow], cfg) -> tuple[list[DealRow], list[DealRow]]` → `(deals, below_floor)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_poke_score.py
from scanner import config as cfg_mod
from scanner.discovery.schema import DealRow
from scanner.discovery.score import (
    assign_badges, compute_pct_off, dedup, fake_markdown_flags,
    flipper_is_buy, lens_tags, split_min_discount,
)

CFG = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})


def _row(**kw):
    base = dict(item="ETB", asset_class="sealed", category="sealed-etb",
                deal_price=39.99, market_comp=60.0, retailer="Target",
                source_url="u", captured_at="2026-06-27",
                price_confidence="verified", comp_confidence="high")
    base.update(kw)
    return DealRow(**base)


def test_pct_off_basis_is_market_comp():
    assert compute_pct_off(39.99, 60.0) == 33  # round((60-39.99)/60*100)
    assert compute_pct_off(39.99, None) is None


def test_inflated_original_when_claimed_exceeds_comp_30pct():
    flags = fake_markdown_flags(40, market_comp=60, claimed_was=90, has_legit_explanation=False)
    assert "INFLATED_ORIGINAL" in flags  # claimed 90 > comp 60 by 50% (>30)


def test_suspiciously_low_without_explanation():
    flags = fake_markdown_flags(30, market_comp=60, claimed_was=None, has_legit_explanation=False)
    assert "SUSPICIOUSLY_LOW" in flags  # 30 < 70% of 60 (=42), no explanation


def test_suspiciously_low_suppressed_with_explanation():
    flags = fake_markdown_flags(30, market_comp=60, claimed_was=None, has_legit_explanation=True)
    assert "SUSPICIOUSLY_LOW" not in flags


def test_misleading_pct_when_price_within_normal_range():
    # big claimed discount but sale price ~ comp -> misleading
    flags = fake_markdown_flags(58, market_comp=60, claimed_was=120, has_legit_explanation=False)
    assert "MISLEADING_PCT" in flags


def test_flipper_buy_matches_backbone():
    # deal 40, comp 100 -> healthy net margin -> BUY
    assert flipper_is_buy(40.0, 100.0, CFG) is True
    # deal 58, comp 60 -> thin -> not BUY
    assert flipper_is_buy(58.0, 60.0, CFG) is False


def test_steal_requires_verified_and_threshold():
    steal = assign_badges(_row(deal_price=39.99, market_comp=60.0, pct_off=33), CFG)
    assert "STEAL" in steal                       # verified, 33% >= steal_pct 30
    thin = assign_badges(_row(deal_price=57.0, market_comp=60.0, pct_off=5), CFG)
    assert "STEAL" not in thin


def test_est_row_gets_est_badge_never_steal():
    badges = assign_badges(_row(price_confidence="est", comp_confidence="low",
                                derivation_method="comp_inference",
                                deal_price=39.99, market_comp=60.0, pct_off=33), CFG)
    assert "EST" in badges and "STEAL" not in badges


def test_flp_tag_is_deterministic_and_backbone_aligned():
    tags = lens_tags(_row(deal_price=40.0, market_comp=100.0, pct_off=60), CFG)
    assert "FLP" in tags
    tags2 = lens_tags(_row(deal_price=58.0, market_comp=60.0, pct_off=3), CFG)
    assert "FLP" not in tags2


def test_dedup_keeps_lowest_price_per_identity():
    a = _row(deal_price=45.0, set="Prismatic", variant="", retailer="A")
    b = _row(deal_price=39.99, set="Prismatic", variant="", retailer="B")
    out = dedup([a, b])
    assert len(out) == 1 and out[0].deal_price == 39.99


def test_split_min_discount_drops_thin_rows():
    deal = _row(deal_price=39.99, market_comp=60.0, pct_off=33)
    thin = _row(deal_price=59.0, market_comp=60.0, pct_off=2)
    deals, below = split_min_discount([deal, thin], CFG)
    assert deal in deals and thin in below
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_poke_score.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.discovery.score'`.

- [ ] **Step 3: Implement `score.py`**

```python
"""Deterministic scoring for /poke deals: pct_off, badges, fake-markdown flags,
the four lenses, dedup, and the minimum-discount split.

The Flipper (FLP) lens computes net margin through the existing backbone
(scanner.margin + scanner.verdict) so a dashboard FLP tag equals the scanner's
BUY verdict for the same numbers. No fees are re-hardcoded here.
"""
from __future__ import annotations

from . import schema
from .schema import DealRow
from .. import margin as margin_mod
from .. import verdict as verdict_mod

FAKE_MARKDOWN = {"INFLATED_ORIGINAL", "SUSPICIOUSLY_LOW", "MISLEADING_PCT"}


def compute_pct_off(deal_price: float, market_comp: float | None) -> float | None:
    if not market_comp or market_comp <= 0:
        return None
    return round((market_comp - deal_price) / market_comp * 100)


def fake_markdown_flags(
    deal_price: float,
    market_comp: float | None,
    claimed_was: float | None,
    has_legit_explanation: bool,
) -> list[str]:
    flags: list[str] = []
    if market_comp and market_comp > 0:
        if claimed_was and claimed_was > market_comp * 1.30:
            flags.append("INFLATED_ORIGINAL")
        if deal_price < market_comp * 0.70 and not has_legit_explanation:
            flags.append("SUSPICIOUSLY_LOW")
        # big headline discount but the actual price barely beats market
        if claimed_was and claimed_was > market_comp * 1.20 and deal_price > market_comp * 0.90:
            flags.append("MISLEADING_PCT")
    return flags


def _fees(cfg) -> margin_mod.FeeModel:
    return margin_mod.FeeModel(
        ebay_fvf_pct=cfg.ebay_fvf_pct,
        ebay_fixed_fee=cfg.ebay_fixed_fee,
        local_haircut_pct=cfg.local_haircut_pct,
    )


def flipper_is_buy(deal_price: float, market_comp: float, cfg) -> bool:
    cost = margin_mod.cost_basis(deal_price, cfg.tax_rate)
    result = margin_mod.net_margin(cost, market_comp, "ebay", cfg.ebay_est_shipping, _fees(cfg))
    v = verdict_mod.buy_verdict(result, "high", verdict_mod.thresholds_from_config(cfg))
    return v.tier == "BUY"


def assign_badges(row: DealRow, cfg) -> list[str]:
    badges: list[str] = []
    if row.price_confidence == "est":
        badges.append("EST")
    pct = row.pct_off if row.pct_off is not None else compute_pct_off(row.deal_price, row.market_comp)
    steal_ok = (
        row.price_confidence == "verified"
        and not row.authenticity_risk
        and not row.stale
        and pct is not None
        and pct >= cfg.poke.steal_pct
    )
    if steal_ok:
        badges.append("STEAL")
    if row.warn_reason or row.authenticity_risk:
        badges.append("WARN")
    return badges


def lens_tags(row: DealRow, cfg) -> list[str]:
    tags: list[str] = []
    pct = row.pct_off if row.pct_off is not None else compute_pct_off(row.deal_price, row.market_comp)
    verified = row.price_confidence == "verified" and row.comp_confidence in {"high", "medium"}
    # Collector: verified comp + a collectibility marker
    if verified and (row.finite or row.grade or "alt" in row.variant.lower()):
        tags.append("COL")
    # Player: play-value classes clearing the discount floor
    if row.asset_class in {"raw", "sealed"} and row.category in {"sealed-etb", "singles-meta"} \
            and pct is not None and pct >= cfg.poke.min_discount_pct:
        tags.append("PLY")
    # Investor: verified appreciation basis, comp-backed, not deep-reprint-risk
    if verified and not row.reprint_risk and pct is not None and pct >= cfg.poke.min_discount_pct:
        tags.append("INV")
    # Flipper: net margin clears BUY through the backbone — only on a verified comp
    # (price-accuracy rule: never tag a lens off an EST/low-confidence comp).
    if row.price_confidence == "verified" and row.market_comp \
            and flipper_is_buy(row.deal_price, row.market_comp, cfg):
        tags.append("FLP")
    return tags


def _identity(row: DealRow) -> tuple:
    return (row.item.strip().lower(), row.set.strip().lower(),
            row.variant.strip().lower(), row.grade.strip().lower(),
            row.condition.strip().lower())


def dedup(rows: list[DealRow]) -> list[DealRow]:
    best: dict[tuple, DealRow] = {}
    for row in rows:
        key = _identity(row)
        if key not in best or row.deal_price < best[key].deal_price:
            best[key] = row
    return list(best.values())


def split_min_discount(rows: list[DealRow], cfg) -> tuple[list[DealRow], list[DealRow]]:
    deals: list[DealRow] = []
    below: list[DealRow] = []
    for row in rows:
        pct = row.pct_off if row.pct_off is not None else compute_pct_off(row.deal_price, row.market_comp)
        if pct is not None and pct >= cfg.poke.min_discount_pct:
            deals.append(row)
        else:
            below.append(row)
    return deals, below
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_poke_score.py -v`
Expected: PASS. If `flipper_is_buy` thresholds make a specific assertion flip, adjust the test's deal/comp numbers to ones that clearly clear/miss `buy_floor_net`/`buy_floor_roi` — do not change the backbone call.

- [ ] **Step 5: Commit**

```bash
git add scanner/discovery/score.py tests/test_poke_score.py
git commit -m "feat(poke): scoring — badges, fake-markdown, lenses (FLP via backbone), dedup"
```

---

## Task 7: Fixture sweep JSON (sealed-first)

**Files:**
- Create: `data/poke/fixtures/sample-sweep.json`
- Test: `tests/test_poke_schema.py` (add a fixture-load test)

**Interfaces:**
- Produces: a realistic sweep that passes the STOP gate, with ≥10 deal rows, a mix of verified + EST, one `authenticity_risk` row (in Watch Out, not a STEAL), and one catalog-overlap row carrying a `scanner_verdict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_poke_schema.py  (add)
import json
from pathlib import Path

from scanner.discovery.schema import assert_sweep, row_from_dict


def test_sample_sweep_fixture_passes_stop_gate():
    path = Path("data/poke/fixtures/sample-sweep.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = [row_from_dict(d) for d in data["deals"]]
    assert len(rows) >= 10
    assert_sweep(rows)  # must not raise
    assert any(r.price_confidence == "est" for r in rows)
    assert any(r.authenticity_risk for r in rows)
    assert any(r.scanner_verdict for r in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_poke_schema.py -k sample_sweep -v`
Expected: FAIL — `FileNotFoundError`.

- [ ] **Step 3: Create the fixture**

Create `data/poke/fixtures/sample-sweep.json` (illustrative numbers; every row obeys the STOP gate — verified rows have source+date, the est row has a method + EST badge, the authenticity row is WARN not STEAL):

```json
{
  "event": "now",
  "sweep_id": "2026-06-27-now",
  "captured_window": "2026-06-27",
  "notes": "Hand-authored Phase-1 fixture (sealed-first). Illustrative prices.",
  "deals": [
    {"item": "Prismatic Evolutions Elite Trainer Box", "set": "Prismatic Evolutions", "asset_class": "sealed", "category": "sealed-etb", "deal_price": 39.99, "market_comp": 60.0, "pct_off": 33, "retailer": "Target", "source_url": "https://example.com/pe-etb", "captured_at": "2026-06-27", "price_confidence": "verified", "comp_confidence": "high", "badges": ["STEAL"], "lens_tags": ["INV", "FLP"], "stock_status": "in-stock", "stock_evidence": "page says in stock", "scanner_verdict": "BUY · +$16 net, 38% ROI"},
    {"item": "Surging Sparks Elite Trainer Box", "set": "Surging Sparks", "asset_class": "sealed", "category": "sealed-etb", "deal_price": 41.99, "market_comp": 55.0, "pct_off": 24, "retailer": "Best Buy", "source_url": "https://example.com/ss-etb", "captured_at": "2026-06-27", "price_confidence": "verified", "comp_confidence": "high", "badges": [], "lens_tags": ["INV"], "stock_status": "in-stock"},
    {"item": "Journey Together Booster Bundle", "set": "Journey Together", "asset_class": "sealed", "category": "sealed-bundle", "deal_price": 22.99, "market_comp": 30.0, "pct_off": 23, "retailer": "Costco", "source_url": "https://example.com/jt-bundle", "captured_at": "2026-06-27", "price_confidence": "verified", "comp_confidence": "medium", "badges": [], "lens_tags": ["FLP"], "stock_status": "limited"},
    {"item": "Destined Rivals Elite Trainer Box", "set": "Destined Rivals", "asset_class": "sealed", "category": "sealed-etb", "deal_price": 38.0, "market_comp": 58.0, "pct_off": 34, "retailer": "Pokemon Center", "source_url": "https://example.com/dr-etb", "captured_at": "2026-06-27", "price_confidence": "verified", "comp_confidence": "high", "badges": ["STEAL"], "lens_tags": ["INV", "FLP"], "reprint_risk": false, "stock_status": "in-stock"},
    {"item": "Scarlet & Violet 151 Booster Bundle", "set": "151", "asset_class": "sealed", "category": "sealed-bundle", "deal_price": 24.99, "market_comp": 34.0, "pct_off": 27, "retailer": "Target", "source_url": "https://example.com/151-bundle", "captured_at": "2026-06-27", "price_confidence": "verified", "comp_confidence": "high", "badges": [], "lens_tags": ["FLP"], "stock_status": "in-stock"},
    {"item": "Paldean Fates Elite Trainer Box", "set": "Paldean Fates", "asset_class": "sealed", "category": "sealed-etb", "deal_price": 44.99, "market_comp": 70.0, "pct_off": 36, "retailer": "Best Buy", "source_url": "https://example.com/pf-etb", "captured_at": "2026-06-27", "price_confidence": "verified", "comp_confidence": "high", "badges": ["STEAL"], "lens_tags": ["COL", "INV", "FLP"], "finite": true, "stock_status": "limited"},
    {"item": "Crown Zenith Elite Trainer Box", "set": "Crown Zenith", "asset_class": "sealed", "category": "sealed-etb", "deal_price": 49.99, "market_comp": 75.0, "pct_off": 33, "retailer": "GameStop", "source_url": "https://example.com/cz-etb", "captured_at": "2026-06-27", "price_confidence": "verified", "comp_confidence": "high", "badges": ["STEAL"], "lens_tags": ["COL", "INV", "FLP"], "finite": true, "stock_status": "in-stock"},
    {"item": "Prismatic Evolutions Booster Bundle", "set": "Prismatic Evolutions", "asset_class": "sealed", "category": "sealed-bundle", "deal_price": 23.99, "market_comp": 33.0, "pct_off": 27, "retailer": "Walmart", "source_url": "https://example.com/pe-bundle", "captured_at": "2026-06-27", "price_confidence": "verified", "comp_confidence": "medium", "badges": [], "lens_tags": ["FLP"], "stock_status": "in-stock"},
    {"item": "Surging Sparks Booster Bundle", "set": "Surging Sparks", "asset_class": "sealed", "category": "sealed-bundle", "deal_price": 24.5, "market_comp": 31.0, "pct_off": 21, "retailer": "Target", "source_url": "https://example.com/ss-bundle", "captured_at": "2026-06-27", "price_confidence": "verified", "comp_confidence": "medium", "badges": [], "lens_tags": [], "stock_status": "in-stock"},
    {"item": "151 Elite Trainer Box (est comp)", "set": "151", "asset_class": "sealed", "category": "sealed-etb", "deal_price": 42.0, "market_comp": 64.0, "pct_off": 34, "retailer": "Local LGS", "source_url": "https://example.com/151-etb-est", "captured_at": "2026-06-27", "price_confidence": "est", "comp_confidence": "low", "derivation_method": "comp_inference", "confidence_detail": "inferred from nearby sold range; no direct sealed comp", "badges": ["EST"], "lens_tags": [], "stock_status": "unknown"},
    {"item": "Prismatic Evolutions ETB (too-cheap, possible reseal)", "set": "Prismatic Evolutions", "asset_class": "sealed", "category": "sealed-etb", "deal_price": 24.0, "market_comp": 60.0, "pct_off": 60, "retailer": "Marketplace seller", "source_url": "https://example.com/pe-etb-suspect", "captured_at": "2026-06-27", "price_confidence": "verified", "comp_confidence": "high", "authenticity_risk": true, "warn_reason": "60% under market with no clearance/used explanation — possible reseal; verify factory seal", "badges": ["WARN"], "lens_tags": [], "stock_status": "unknown"}
  ],
  "promo_codes": [
    {"code": "CIRCLE5", "desc": "5% Target Circle bonus on TCG", "retailer": "Target", "window": "Jun 22 - Jul 5", "source_url": "https://example.com/target-circle"}
  ],
  "bundled_offers": [
    {"title": "$15 Target gift card with $50 TCG purchase", "window": "Jun 27 - Jul 3", "retailer": "Target", "source_url": "https://example.com/target-gc"}
  ],
  "watchlist_results": [
    {"item": "Prismatic Evolutions ETB", "target_price": 42.0, "hit": true, "deal_price": 39.99, "retailer": "Target"}
  ],
  "sources": [
    {"name": "Target weekly", "category": "retailer", "tier": "fetchable", "status": "fetched", "note": ""},
    {"name": "Brand X aggregator", "category": "aggregator", "tier": "blocked", "status": "blocked", "note": "Cloudflare challenge — not data"}
  ]
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_poke_schema.py -v`
Expected: PASS (incl. the new fixture test).

- [ ] **Step 5: Commit**

```bash
git add data/poke/fixtures/sample-sweep.json tests/test_poke_schema.py
git commit -m "test(poke): sealed-first fixture sweep passing the STOP gate"
```

---

## Task 8: `render.py` + `template.html` + CLI

**Files:**
- Create: `scanner/discovery/template.html`
- Create: `scanner/discovery/render.py`
- Test: `tests/test_poke_render.py`

**Interfaces:**
- Consumes: `scanner.discovery.schema.row_from_dict`, `assert_sweep`; the template file.
- Produces:
  - `render_sweep(sweep: dict, template: str | None = None) -> str` — returns full HTML. Runs `assert_sweep` on the deal rows first (STOP gate before render).
  - `nav_anchors(html: str) -> list[str]` and `element_ids(html: str) -> list[str]` (helpers reused by the golden test).
  - `main(argv=None) -> int` — CLI: `python -m scanner.discovery.render <sweep.json> [-o out.html]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_poke_render.py
import json
import re
from pathlib import Path

from scanner.discovery.render import nav_anchors, element_ids, render_sweep

SWEEP = json.loads(Path("data/poke/fixtures/sample-sweep.json").read_text(encoding="utf-8"))


def test_required_sections_present():
    html = render_sweep(SWEEP)
    for needle in ("Top Steals", "Watch Out", "Sources"):
        assert needle in html


def test_every_nav_anchor_resolves():
    html = render_sweep(SWEEP)
    ids = set(element_ids(html))
    for anchor in nav_anchors(html):
        assert anchor in ids, f"dangling nav anchor #{anchor}"


def test_every_deal_row_carries_source_and_date():
    html = render_sweep(SWEEP)
    rows = re.findall(r'data-source-url="([^"]*)"\s+data-captured-at="([^"]*)"', html)
    # at least one deal row per fixture deal that is rendered
    assert len(rows) >= 10
    assert all(src and date for src, date in rows)


def test_est_row_renders_est_badge_and_no_steal():
    html = render_sweep(SWEEP)
    assert "EST" in html
    # the authenticity row must be in Watch Out and never a STEAL card
    assert "possible reseal" in html.lower() or "reseal" in html.lower()


def test_stop_gate_blocks_render_on_bad_row():
    import pytest
    from scanner.discovery.schema import StopGateError
    bad = json.loads(json.dumps(SWEEP))
    bad["deals"][0]["source_url"] = ""   # verified row missing source
    with pytest.raises(StopGateError):
        render_sweep(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_poke_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.discovery.render'`.

- [ ] **Step 3: Create `template.html`**

Create `scanner/discovery/template.html` (self-contained, dark, placeholder + inject markers; minimal but real):

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>POKE DEALS — {{EVENT_TITLE}}</title>
<style>
  body { background:#0d1117; color:#e6edf3; font-family:system-ui,Arial,sans-serif; margin:0; }
  header { padding:1rem 1.5rem; border-bottom:1px solid #30363d; }
  nav a { color:#58a6ff; margin-right:1rem; text-decoration:none; }
  main { padding:1.5rem; max-width:1100px; margin:0 auto; }
  section { margin-bottom:2rem; }
  h2 { border-bottom:1px solid #30363d; padding-bottom:.3rem; }
  table { width:100%; border-collapse:collapse; }
  th,td { text-align:left; padding:.4rem .6rem; border-bottom:1px solid #21262d; }
  .deal-price { color:#f0b429; font-weight:700; }
  .orig { color:#8b949e; text-decoration:line-through; }
  .badge { font-size:.75rem; font-weight:700; padding:.1rem .4rem; border-radius:4px; margin-left:.3rem; }
  .badge-steal { background:#196c2e; color:#fff; }
  .badge-warn { background:#9e6a03; color:#fff; }
  .badge-est { background:#30363d; color:#c9d1d9; }
  .lens { font-size:.7rem; border:1px solid #30363d; border-radius:3px; padding:0 .25rem; margin-left:.25rem; }
  .muted { color:#8b949e; font-size:.85rem; }
  footer { padding:1.5rem; color:#8b949e; font-size:.8rem; border-top:1px solid #30363d; }
</style>
</head>
<body>
<header>
  <div><strong>POKE DEALS — {{EVENT_TITLE}}</strong></div>
  <div class="muted">Last updated: {{LAST_UPDATED}} · % off vs verified market, not MSRP · sweep {{SWEEP_ID}}</div>
  <nav><!-- INJECT: NAV --></nav>
</header>
<main>
  <section id="freshness">
    <h2>Freshness</h2>
    <div class="muted">{{FRESHNESS}}</div>
  </section>
  <section id="watchlist">
    <h2>⭐ Watchlist</h2>
    <!-- INJECT: WATCHLIST -->
  </section>
  <section id="top-steals">
    <h2>Top Steals</h2>
    <!-- INJECT: TOP_STEALS -->
  </section>
  <!-- INJECT: CATEGORY_SECTIONS -->
  <section id="promo-codes">
    <h2>Promo Codes</h2>
    <!-- INJECT: PROMO_CODES -->
  </section>
  <section id="bundled-offers">
    <h2>Bundled Offers</h2>
    <!-- INJECT: BUNDLED_OFFERS -->
  </section>
  <section id="watch-out">
    <h2>Watch Out</h2>
    <!-- INJECT: WATCH_OUT -->
  </section>
  <section id="sources">
    <h2>Sources</h2>
    <!-- INJECT: SOURCES -->
  </section>
</main>
<footer>
  ⚠ Decision-support only — verify every price before acting. Prices captured at the dates shown and may have changed.
  Generated by /poke · sweep {{SWEEP_ID}}.
</footer>
</body>
</html>
```

- [ ] **Step 4: Implement `render.py`**

```python
"""Render a /poke sweep dict into the self-contained dashboard HTML.

Runs the STOP gate before producing any HTML — a bad row halts the render
rather than shipping a dashboard that overstates confidence.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import sys
from pathlib import Path

from .schema import assert_sweep, row_from_dict

TEMPLATE_PATH = Path(__file__).with_name("template.html")


def _esc(value) -> str:
    return html_lib.escape(str(value), quote=True)


def _badges_html(badges: list[str]) -> str:
    cls = {"STEAL": "badge-steal", "WARN": "badge-warn", "EST": "badge-est"}
    return "".join(
        f'<span class="badge {cls.get(b, "badge-est")}">{_esc(b)}</span>' for b in badges
    )


def _lens_html(tags: list[str]) -> str:
    return "".join(f'<span class="lens">{_esc(t)}</span>' for t in tags)


def _deal_row_html(d: dict) -> str:
    comp = d.get("market_comp")
    comp_html = f'<span class="orig">${_esc(comp)}</span>' if comp is not None else ""
    pct = d.get("pct_off")
    pct_html = f"{_esc(pct)}%" if pct is not None else ""
    return (
        f'<tr data-source-url="{_esc(d.get("source_url",""))}" '
        f'data-captured-at="{_esc(d.get("captured_at",""))}">'
        f'<td>{_esc(d.get("item",""))}{_lens_html(d.get("lens_tags",[]))}'
        f'{_badges_html(d.get("badges",[]))}</td>'
        f'<td class="deal-price">${_esc(d.get("deal_price",""))}</td>'
        f'<td>{comp_html}</td><td>{pct_html}</td>'
        f'<td><a href="{_esc(d.get("source_url",""))}">{_esc(d.get("retailer",""))}</a> '
        f'<span class="muted">{_esc(d.get("captured_at",""))}</span></td>'
        f'<td>{_esc(d.get("scanner_verdict",""))}</td></tr>'
    )


def _table(rows: list[dict]) -> str:
    if not rows:
        return '<div class="muted">None this sweep.</div>'
    body = "".join(_deal_row_html(d) for d in rows)
    return (
        "<table><thead><tr><th>Item</th><th>Deal</th><th>Market</th>"
        "<th>% Off</th><th>Retailer</th><th>Scanner</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _category_key(d: dict) -> str:
    return str(d.get("category") or d.get("asset_class") or "other")


def render_sweep(sweep: dict, template: str | None = None) -> str:
    deals = sweep.get("deals", [])
    assert_sweep([row_from_dict(d) for d in deals])  # STOP gate before render

    tpl = template if template is not None else TEMPLATE_PATH.read_text(encoding="utf-8")

    steals = [d for d in deals if "STEAL" in d.get("badges", [])]
    watch_out = [d for d in deals if d.get("authenticity_risk") or d.get("warn_reason")]

    # category sections (every section id used in nav must exist)
    cats: dict[str, list[dict]] = {}
    for d in deals:
        cats.setdefault(_category_key(d), []).append(d)
    cat_sections = []
    cat_nav = []
    for key in sorted(cats):
        anchor = "cat-" + re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
        cat_nav.append(anchor)
        cat_sections.append(
            f'<section id="{anchor}"><h2>{_esc(key)}</h2>{_table(cats[key])}</section>'
        )

    nav_ids = ["freshness", "watchlist", "top-steals", *cat_nav,
               "promo-codes", "bundled-offers", "watch-out", "sources"]
    nav_html = "".join(f'<a href="#{a}">{a.replace("-", " ").title()}</a>' for a in nav_ids)

    wl = sweep.get("watchlist_results", [])
    wl_html = "".join(
        f'<div>{_esc(w.get("item",""))} — '
        f'{"TARGET HIT" if w.get("hit") else "tracked"} '
        f'(target ${_esc(w.get("target_price",""))})</div>' for w in wl
    ) or '<div class="muted">No watchlist targets hit this sweep.</div>'

    promos = sweep.get("promo_codes", [])
    promo_html = "".join(
        f'<div><strong>{_esc(p.get("code",""))}</strong> — {_esc(p.get("desc",""))} '
        f'@ {_esc(p.get("retailer",""))} '
        f'(<a href="{_esc(p.get("source_url",""))}">src</a>)</div>' for p in promos
    ) or '<div class="muted">None.</div>'

    bundles = sweep.get("bundled_offers", [])
    bundle_html = "".join(
        f'<div>{_esc(b.get("title",""))} @ {_esc(b.get("retailer",""))} '
        f'(<a href="{_esc(b.get("source_url",""))}">src</a>)</div>' for b in bundles
    ) or '<div class="muted">None.</div>'

    watch_out_html = "".join(
        f'<div><strong>{_esc(d.get("item",""))}</strong> — '
        f'{_esc(d.get("warn_reason","flagged"))} '
        f'(<a href="{_esc(d.get("source_url",""))}">src</a>)</div>' for d in watch_out
    ) or '<div class="muted">Nothing flagged this sweep.</div>'

    sources = sweep.get("sources", [])
    sources_html = "".join(
        f'<div>{_esc(s.get("name",""))} — {_esc(s.get("tier",""))}/'
        f'{_esc(s.get("status",""))} <span class="muted">{_esc(s.get("note",""))}</span></div>'
        for s in sources
    ) or '<div class="muted">No sources recorded.</div>'

    freshness = (
        f'sweep {_esc(sweep.get("sweep_id",""))} · {len(deals)} items · '
        f'{len(steals)} steals · {_esc(sweep.get("notes",""))}'
    )

    out = tpl
    replacements = {
        "{{EVENT_TITLE}}": _esc(sweep.get("event", "")),
        "{{LAST_UPDATED}}": _esc(sweep.get("captured_window", "")),
        "{{SWEEP_ID}}": _esc(sweep.get("sweep_id", "")),
        "{{FRESHNESS}}": freshness,
    }
    for k, v in replacements.items():
        out = out.replace(k, v)
    injects = {
        "<!-- INJECT: NAV -->": nav_html,
        "<!-- INJECT: WATCHLIST -->": wl_html,
        "<!-- INJECT: TOP_STEALS -->": _table(steals),
        "<!-- INJECT: CATEGORY_SECTIONS -->": "".join(cat_sections),
        "<!-- INJECT: PROMO_CODES -->": promo_html,
        "<!-- INJECT: BUNDLED_OFFERS -->": bundle_html,
        "<!-- INJECT: WATCH_OUT -->": watch_out_html,
        "<!-- INJECT: SOURCES -->": sources_html,
    }
    for marker, value in injects.items():
        out = out.replace(marker, value)
    return out


def nav_anchors(html: str) -> list[str]:
    return re.findall(r'href="#([A-Za-z0-9\-_]+)"', html)


def element_ids(html: str) -> list[str]:
    return re.findall(r'id="([A-Za-z0-9\-_]+)"', html)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m scanner.discovery.render <sweep.json> [-o out.html]")
        return 2
    sweep_path = Path(argv[0])
    out_path = None
    if "-o" in argv:
        out_path = Path(argv[argv.index("-o") + 1])
    sweep = json.loads(sweep_path.read_text(encoding="utf-8"))
    html = render_sweep(sweep)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")
        print(f"wrote {out_path}")
    else:
        sys.stdout.write(html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_poke_render.py -v`
Expected: PASS (all).

- [ ] **Step 6: Smoke-render the fixture**

Run: `python -m scanner.discovery.render data/poke/fixtures/sample-sweep.json -o dashboards/2026-06-27-now.html && echo OK`
Expected: `wrote dashboards/...` then `OK`. Open the file to eyeball it (optional).

- [ ] **Step 7: Commit**

```bash
git add scanner/discovery/template.html scanner/discovery/render.py tests/test_poke_render.py
git commit -m "feat(poke): dashboard renderer + template + CLI (STOP gate before render)"
```

---

## Task 9: Golden test

**Files:**
- Create: `tests/test_poke_golden.py`

**Interfaces:**
- Consumes: `render_sweep`, `nav_anchors`, `element_ids`; `scanner.config.from_mapping` (for `poke.min_rows`).
- Produces: the post-render structural gate (hard-fails) that every future sweep must pass.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_poke_golden.py
import json
import re
from pathlib import Path

import pytest

from scanner import config as cfg_mod
from scanner.discovery.render import element_ids, nav_anchors, render_sweep

SWEEP = json.loads(Path("data/poke/fixtures/sample-sweep.json").read_text(encoding="utf-8"))
CFG = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})


def golden_check(html: str, min_rows: int) -> list[str]:
    """Returns a list of HARD-FAIL messages (empty = pass)."""
    fails = []
    ids = set(element_ids(html))
    for anchor in nav_anchors(html):
        if anchor not in ids:
            fails.append(f"dangling nav anchor #{anchor}")
    for needle in ("Top Steals", "Watch Out", "Sources"):
        if needle not in html:
            fails.append(f"missing required section: {needle}")
    rows = re.findall(r'data-source-url="([^"]*)"\s+data-captured-at="([^"]*)"', html)
    if len(rows) < min_rows:
        fails.append(f"deal rows {len(rows)} < floor {min_rows} (likely acquisition failure)")
    for src, date in rows:
        if not src or not date:
            fails.append("a deal row is missing source_url or captured_at")
    return fails


def test_golden_passes_on_fixture():
    html = render_sweep(SWEEP)
    assert golden_check(html, CFG.poke.min_rows) == []


def test_golden_fails_on_missing_section():
    html = render_sweep(SWEEP).replace("Sources", "Srcs")
    fails = golden_check(html, CFG.poke.min_rows)
    assert any("Sources" in f for f in fails)


def test_golden_fails_on_dangling_anchor():
    html = render_sweep(SWEEP) + '<a href="#nope-nope"></a>'
    fails = golden_check(html, CFG.poke.min_rows)
    assert any("nope-nope" in f for f in fails)


def test_golden_fails_below_row_floor():
    html = render_sweep(SWEEP)
    fails = golden_check(html, min_rows=999)
    assert any("acquisition failure" in f for f in fails)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_poke_golden.py -v`
Expected: FAIL — `ModuleNotFoundError` until earlier tasks are in (or, if run last, PASS). If `test_golden_passes_on_fixture` fails because the fixture has <10 rendered rows, add rows to the fixture until ≥ `min_rows`.

- [ ] **Step 3: (No new implementation)** — the golden check lives in the test as a pure function over `render.py` helpers; no module change needed.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_poke_golden.py -v`
Expected: PASS (all four).

- [ ] **Step 5: Commit**

```bash
git add tests/test_poke_golden.py
git commit -m "test(poke): golden structural gate on rendered dashboard"
```

---

## Task 10: Full suite green + docs + scope handoff

**Files:**
- Modify: `README.md` (a short `/poke` discovery subsystem note)
- Append: `docs/poke/PHASE0_FINDINGS.md` (a "next plan" pointer)

**Interfaces:**
- Produces: a green full suite and a recorded handoff to the follow-on (live-acquisition) plan.

- [ ] **Step 1: Run the FULL suite**

Run: `python -m pytest -q 2>&1 | tail -1`
Expected: all tests PASS (172 baseline + the new `test_poke_*` + extended `test_config`).

- [ ] **Step 2: Add a README note**

In `README.md`, add a short subsection (place near the existing scanner overview):

```markdown
### `/poke` discovery subsystem (Phase 1 — deterministic core)

`scanner/discovery/` turns a sweep JSON into a verified deal dashboard:
`schema.py` (STOP gate), `ledger.py` (append-only observation ledger),
`score.py` (badges/fake-markdown/lenses — Flipper via `scanner.margin`),
`render.py` (`python -m scanner.discovery.render <sweep.json> -o out.html`).
Comps are anchored to the same backbone as the scanner, so a Flipper tag equals
the scanner's BUY verdict. Live web acquisition + the in-session `/poke` command
are the follow-on plan; this phase runs on fixtures.
```

- [ ] **Step 3: Record the handoff to the follow-on plan**

Append to `docs/poke/PHASE0_FINDINGS.md`:

```markdown
## Handoff to follow-on plan (live acquisition + raw/graded + regression hardening)
Phase-1 deterministic core is built and green on the fixture. The follow-on plan
(written after these findings) covers, per spec §5/§7:
- DISCOVER adapters (Playwright/WebFetch/WebSearch) per the fetchability verdict above.
- RESEARCH comp routing wired to live `scanner.market`/`resale` (gated by the comp verdict above).
- raw + graded comp paths (PPT graded/singles endpoints — confirm shapes first).
- the in-session OPENER + `/poke` command + mode dispatch.
- regression hardening: watchlist continuity write-path, manifest delta, persona
  self-test, prompt-durability sidecar (`.poke-opener-verified.json`).
```

- [ ] **Step 4: Commit**

```bash
git add README.md docs/poke/PHASE0_FINDINGS.md
git commit -m "docs(poke): Phase-1 core green; README + follow-on handoff"
```

---

## Self-Review (completed by plan author)

**Spec coverage (this plan = Phase 0 + Phase 1 deterministic core):**
- §13.0 Phase-0 comp-verification probe → Task 1; source-fetchability probe → Task 2.
- §3.1 layout (`scanner/discovery/*`, `data/poke/*`, `dashboards/`) → Tasks 4-8.
- §4.1 schema (recast + new `grade`/`grader`/`condition`/`authenticity_risk`/`scanner_verdict`) → `DealRow` Task 4.
- §6 STOP gate (all six rules) → `validate_row` Task 4; enforced before render in Task 8.
- §4.3 four lenses, Flipper via `scanner.margin`/`verdict` → Task 6.
- §5 SCORE (pct_off vs comp, fake-markdown, dedup, min-discount) → Task 6.
- §5 PERSIST observation ledger (kind separation, entry_id idempotency, item_key) → Task 5.
- §7.1 golden test (anchors resolve, required sections, row floor, structural provenance invariant) → Task 9.
- §8 dashboard sections → `template.html` + `render.py` Task 8.
- §9 config (`poke` block) → Task 3.
- Two-ledger distinction → Task 5 docstring + Global Constraints.

**Deliberately deferred to the follow-on plan (NOT in scope here, per the spec's staging + advisor):**
live DISCOVER adapters, RESEARCH live comp routing, raw/graded comp clients, the
OPENER/command, persona self-test, prompt-durability sidecar, manifest delta,
watchlist write-path. Recorded in Task 10 Step 3.

**Placeholder scan:** no TBD/TODO; every code step shows complete code; every command lists expected output. The Phase-0 spike tasks (1, 2) are explicitly investigative with a recorded-finding deliverable, not stubbed code.

**Type consistency:** `DealRow` (Task 4) consumed by `score.py` (Task 6) and `render.py` (Task 8) and the fixture test (Task 7); `row_from_dict`/`assert_sweep`/`StopGateError` names identical across Tasks 4/7/8/9; `cfg.poke.*` fields (Task 3) read in Tasks 6/9; backbone calls use the real committed names `FeeModel`/`cost_basis`/`net_margin` (margin.py) and `buy_verdict`/`thresholds_from_config` (verdict.py).

**Known follow-ups (not Phase-1 blockers):** the exact `item_key` string form is pinned by the implementation and the Task-5 test asserts invariants (lowercase, 4 pipes) rather than a brittle exact string; lens strong-signal cutoffs in `score.py` are first-pass and tunable via config; the fixture's illustrative prices are not live comps (Phase-1 operates on fixtures by design).
