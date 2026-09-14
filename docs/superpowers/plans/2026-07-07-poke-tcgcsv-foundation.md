# TCGCSV Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt TCGCSV (free nightly TCGplayer catalog mirror) as an exact-identity source and a de-risked free reference — delivering the roadmap doc-hardening, a shared 0-credit TCGCSV client, the sample-check gate that earns the "TCGplayer == PPT" credit-saving claim, and an exact-`productId` mapping-ingest proposer.

**Architecture:** A new pure-and-fetch module `scanner/poke_api/tcgcsv.py` holds the client (plain `requests` + JSON, honest degrade, 0 credits) and pure parsers (card-number extraction; exact-subtype market-price pick). Two operator CLIs on `edge_cli.py` consume it: `tcgcsv-check` (the gate) and `tcgcsv-ingest` (exact mapping proposals for review — never an auto-write). This plan is the first in the one-build sequence; the TCGCSV **reference adapter** (wiring TCGCSV into the comp engine) is the next plan, gated on this plan's sample-check passing.

**Tech Stack:** Python 3, `requests`, `pytest` (network-mocked). No new runtime dependency.

## Global Constraints

- **Package is `scanner/`** (never `target_scanner/`); price subsystem `scanner/poke_api/`.
- **Exact identity only.** Resolve by exact `tcgplayer_id` / exact `subTypeName`; a miss/ambiguity is honest (`no_match`/`None`/skip), NEVER a fuzzy or guessed value.
- **Price accuracy is STOP-class.** No source → no number. `marketPrice` is nullable → null never becomes a fabricated price. Every recorded number carries its source URL + capture date.
- **TCGCSV is a REFERENCE source, NOT independent.** TCGCSV == TCGplayer market == PPT lineage. A `tcgcsv` number is never counted as independent cross-source validation (enforced in the next plan's adapter; this plan writes no comps).
- **0 credits, no new dependency.** TCGCSV is free/keyless plain `requests`. Live fetch is operator-gated by a **dedicated `poke.tcgcsv`** flag (default false), kept separate from `poke.independent_sources`. No Playwright, no paid client.
- **TCGCSV etiquette:** custom User-Agent required (reuse `independent_sources.UA`); ≤ 10,000 req/24h; ~100ms between requests; check `last-updated.txt` cadence (once/day data).
- **TDD, full suite green** at each task boundary: `.venv/Scripts/python.exe -m pytest -q` (network-mocked; no live HTTP in tests).
- **Local `main`, never pushed** without explicit operator instruction. `config.yaml` ends with `poke.tcgcsv: false`.

---

### Task 0: Roadmap reasoning-hardening (4 doc edits)

Pure documentation. No test. Applies the four edits the spec's T0 names to the G–M roadmap so the "no"s are honest before any code lands.

**Files:**
- Modify: `docs/superpowers/specs/2026-07-06-poke-api-ladder-g-through-m-roadmap.md`

- [ ] **Step 1: Reframe the TCGplayer-independence justification.** Locate §12's bullet on *"TCGplayer live enablement as 'independent' validation"* (and §3.3/§14 where independence is called "structural"). Replace the "structural" framing with: **"conservative default under asymmetric error cost"** — counting TCGCSV/TCGplayer as independent when it mirrors PPT is *false corroboration* (truth-poisoning); treating it non-independent when it might differ merely *forgoes a check* (safe). Add one clause noting this is the one independence claim F.1 could not re-probe (Playwright not installed), so the conservative default is protective, not proven.

- [ ] **Step 2: Relabel G's sourced-pop as transcription-verify + gap-fill.** In the §3.4 / G reconciliation, add a sentence: a sourced PriceCharting pop rate is a *transcription check + coverage gap-fill against the single PSA/CGC census* — NOT independent corroboration (there is one census underneath; GemRate/PSA/PriceCharting all resell it).

- [ ] **Step 3: Split every "no" into permanent-vs-deferred tiers.** Ensure §12 (Permanent Rejections) and the per-phase deferrals are clearly two tiers; move any mis-filed item (e.g. bulk import is a *deferral*, not a permanent reject) to its correct tier.

- [ ] **Step 4: Name the cost of each "no" + retire the portfolio contradiction.** Add a one-line cost to each permanent rejection (e.g. exact-only mapping → slower catalog growth; no-public-API → single-operator). Explicitly reconcile portfolio: the *app* is permanently rejected; the *inventory/cost-basis/P&L ledger* is a real build (the [real-transacting spec](2026-07-06-poke-real-transacting-build-design.md) T8), not a rejection.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-07-06-poke-api-ladder-g-through-m-roadmap.md
git commit -m "docs(poke): harden G-M roadmap reasoning (asymmetric-error framing, pop=transcription-verify, no-tiers, named costs)"
```

---

### Task 1: TCGCSV client + pure parsers

**Files:**
- Create: `scanner/poke_api/tcgcsv.py`
- Test: `tests/poke_api/test_tcgcsv.py`

**Interfaces:**
- Consumes: `scanner.poke_api.independent_sources.UA` (the proven browser User-Agent).
- Produces:
  - `CATEGORY_POKEMON = 3`, `BASE = "https://tcgcsv.com/tcgplayer"`, `LAST_UPDATED_URL`.
  - `fetch_groups() -> list[dict]` · `fetch_products(group_id: int) -> list[dict]` · `fetch_prices(group_id: int) -> list[dict]` — GET the endpoint, return the `results` list; on any HTTP/parse failure return `[]` (honest degrade, never raise into a caller).
  - `card_number_of(product: dict) -> str | None` — pure; reads `extendedData` where `name == "Number"`.
  - `pick_market_price(product_id: int, subtype: str | None, price_rows: list[dict]) -> float | None` — pure; exact `subTypeName` match, returns `marketPrice` only when non-null and > 0; returns `None` when absent, null, ≤ 0, or **ambiguous** (multiple subtype rows and `subtype is None`). Never guesses.

- [ ] **Step 1: Write the failing tests (pure parsers first — no network)**

```python
# tests/poke_api/test_tcgcsv.py
from scanner.poke_api import tcgcsv


def test_card_number_of_reads_extended_data():
    product = {"productId": 1, "name": "Umbreon ex",
               "extendedData": [{"name": "Number", "value": "161/131"},
                                {"name": "Rarity", "value": "SIR"}]}
    assert tcgcsv.card_number_of(product) == "161/131"


def test_card_number_of_missing_returns_none():
    assert tcgcsv.card_number_of({"productId": 1, "extendedData": []}) is None


def test_pick_market_price_exact_subtype():
    rows = [{"productId": 5, "subTypeName": "Holofoil", "marketPrice": 12.5},
            {"productId": 5, "subTypeName": "Reverse Holofoil", "marketPrice": 20.0}]
    assert tcgcsv.pick_market_price(5, "Holofoil", rows) == 12.5


def test_pick_market_price_ambiguous_returns_none():
    rows = [{"productId": 5, "subTypeName": "Holofoil", "marketPrice": 12.5},
            {"productId": 5, "subTypeName": "Reverse Holofoil", "marketPrice": 20.0}]
    assert tcgcsv.pick_market_price(5, None, rows) is None  # never guess which printing


def test_pick_market_price_single_row_no_subtype_ok():
    rows = [{"productId": 9, "subTypeName": "Unopened", "marketPrice": 99.0}]
    assert tcgcsv.pick_market_price(9, None, rows) == 99.0


def test_pick_market_price_null_market_returns_none():
    rows = [{"productId": 5, "subTypeName": "Holofoil", "marketPrice": None}]
    assert tcgcsv.pick_market_price(5, "Holofoil", rows) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/poke_api/test_tcgcsv.py -q`
Expected: FAIL with `ModuleNotFoundError: scanner.poke_api.tcgcsv`

- [ ] **Step 3: Implement the pure parsers + client**

```python
# scanner/poke_api/tcgcsv.py
"""TCGCSV client + pure parsers — free nightly TCGplayer catalog/price mirror.

TCGCSV is a REFERENCE source (TCGplayer lineage == PPT), NOT independent of PPT; it is
used for exact identity (productId) and a free market reference, never as independent
cross-source validation. Plain requests + JSON, 0 credits, keyless. Server-side only
(CORS-blocked in browsers — irrelevant here). Prices are one-to-many with products
(one row per subTypeName); an ambiguous pick is honest None, never a guess.
"""
from __future__ import annotations

import requests

from .independent_sources import UA

CATEGORY_POKEMON = 3
BASE = "https://tcgcsv.com/tcgplayer"
LAST_UPDATED_URL = "https://tcgcsv.com/last-updated.txt"
_TIMEOUT = 20


def _get_json(url: str) -> dict | None:
    """Plain GET → parsed JSON dict, or None on any HTTP/parse failure (honest degrade)."""
    try:
        resp = requests.get(url, headers={"User-Agent": UA, "Accept": "application/json"},
                            timeout=_TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _results(body: dict | None) -> list[dict]:
    if not body:
        return []
    results = body.get("results")
    return [r for r in results if isinstance(r, dict)] if isinstance(results, list) else []


def fetch_groups() -> list[dict]:
    return _results(_get_json(f"{BASE}/{CATEGORY_POKEMON}/groups"))


def fetch_products(group_id: int) -> list[dict]:
    return _results(_get_json(f"{BASE}/{CATEGORY_POKEMON}/{int(group_id)}/products"))


def fetch_prices(group_id: int) -> list[dict]:
    return _results(_get_json(f"{BASE}/{CATEGORY_POKEMON}/{int(group_id)}/prices"))


def card_number_of(product: dict) -> str | None:
    for field in product.get("extendedData", []) or []:
        if isinstance(field, dict) and field.get("name") == "Number":
            value = str(field.get("value") or "").strip()
            return value or None
    return None


def pick_market_price(product_id: int, subtype: str | None,
                      price_rows: list[dict]) -> float | None:
    """Exact-subtype marketPrice for a product, or None (never guess).

    None when: no row, null/≤0 marketPrice, OR ambiguous (multiple subtype rows and no
    subtype supplied). A single row for the product resolves even with subtype=None.
    """
    rows = [r for r in price_rows if r.get("productId") == product_id]
    if not rows:
        return None
    if subtype is not None:
        rows = [r for r in rows if r.get("subTypeName") == subtype]
    elif len(rows) > 1:
        return None  # ambiguous printing — never pick one blindly
    if len(rows) != 1:
        return None
    price = rows[0].get("marketPrice")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return None
    return float(price)
```

- [ ] **Step 4: Run pure-parser tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/poke_api/test_tcgcsv.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Add mocked-fetch tests (no live HTTP)**

```python
# append to tests/poke_api/test_tcgcsv.py
from unittest.mock import patch


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def test_fetch_products_returns_results():
    body = {"success": True, "results": [{"productId": 1, "name": "X"}]}
    with patch("scanner.poke_api.tcgcsv.requests.get", return_value=_Resp(200, body)):
        assert tcgcsv.fetch_products(3170) == [{"productId": 1, "name": "X"}]


def test_fetch_prices_degrades_on_non_200():
    with patch("scanner.poke_api.tcgcsv.requests.get", return_value=_Resp(403, None)):
        assert tcgcsv.fetch_prices(3170) == []


def test_fetch_groups_degrades_on_network_error():
    import requests as _rq
    with patch("scanner.poke_api.tcgcsv.requests.get", side_effect=_rq.RequestException):
        assert tcgcsv.fetch_groups() == []
```

- [ ] **Step 6: Run the full new test file**

Run: `.venv/Scripts/python.exe -m pytest tests/poke_api/test_tcgcsv.py -q`
Expected: PASS (9 passed)

- [ ] **Step 7: Commit**

```bash
git add scanner/poke_api/tcgcsv.py tests/poke_api/test_tcgcsv.py
git commit -m "feat(poke): TCGCSV client + pure parsers (0-credit, exact-subtype, honest degrade)"
```

---

### Task 2: Sample-check gate (spec T1)

**Files:**
- Create: `scanner/poke_api/tcgcsv_check.py`
- Modify: `scanner/poke_api/edge_cli.py` (add `tcgcsv-check` subcommand + dispatch)
- Test: `tests/poke_api/test_tcgcsv_check.py`

**Interfaces:**
- Consumes: `tcgcsv.fetch_prices`, `tcgcsv.pick_market_price`; the held `ppt_cards` `market_comp` rows from `data/poke/price_history.jsonl` (read via `history.read_ledger`); the asset catalog (`catalog`).
- Produces: `sample_check(pairs: list[dict], *, min_n: int = 5, tol_pct: float = 2.0) -> dict` — pure; returns `{"status": "pass"|"fail", "n": int, "max_diff_pct": float|None, "pairs": [...], "reason": str}`. A `pair` is `{"asset_key", "tcgplayer_id", "ppt_price", "tcgcsv_price", "diff_pct"}`.

**Decision (spec §8.2):** the gate is **fixed** — `min_n = 5`, `tol_pct = 2.0`, not per-run tunable.

- [ ] **Step 1: Write the failing test (pure decision logic)**

```python
# tests/poke_api/test_tcgcsv_check.py
from scanner.poke_api import tcgcsv_check


def _pair(diff_pct):
    return {"asset_key": f"a{diff_pct}", "tcgplayer_id": 1, "ppt_price": 100.0,
            "tcgcsv_price": 100.0 * (1 + diff_pct / 100.0), "diff_pct": diff_pct}


def test_pass_when_enough_pairs_all_within_tolerance():
    pairs = [_pair(0.0), _pair(0.5), _pair(1.0), _pair(1.5), _pair(1.9)]
    result = tcgcsv_check.sample_check(pairs)
    assert result["status"] == "pass"
    assert result["n"] == 5


def test_fail_when_any_pair_exceeds_tolerance():
    pairs = [_pair(0.0), _pair(0.5), _pair(1.0), _pair(1.5), _pair(3.0)]
    result = tcgcsv_check.sample_check(pairs)
    assert result["status"] == "fail"
    assert "tolerance" in result["reason"]


def test_fail_when_too_few_pairs():
    pairs = [_pair(0.0), _pair(0.5)]
    result = tcgcsv_check.sample_check(pairs)
    assert result["status"] == "fail"
    assert "n=2" in result["reason"] or "minimum" in result["reason"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/poke_api/test_tcgcsv_check.py -q`
Expected: FAIL with `ModuleNotFoundError: scanner.poke_api.tcgcsv_check`

- [ ] **Step 3: Implement the pure decision**

```python
# scanner/poke_api/tcgcsv_check.py
"""TCGCSV sample-check gate (spec T1). Earns the 'TCGplayer market == PPT' credit-saving
claim at real n BEFORE TCGCSV is trusted as a reference. Pure decision + a thin fetch
orchestrator; 0 PPT credits (reads already-recorded ppt_cards rows).
"""
from __future__ import annotations

MIN_N = 5
TOL_PCT = 2.0


def sample_check(pairs: list[dict], *, min_n: int = MIN_N, tol_pct: float = TOL_PCT) -> dict:
    """PASS only when >= min_n pairs and EVERY pair within tol_pct. Fixed gate (spec 8.2)."""
    n = len(pairs)
    diffs = [abs(float(p["diff_pct"])) for p in pairs]
    max_diff = max(diffs) if diffs else None
    if n < min_n:
        return {"status": "fail", "n": n, "max_diff_pct": max_diff, "pairs": pairs,
                "reason": f"insufficient sample: n={n} below minimum {min_n}"}
    if max_diff is not None and max_diff > tol_pct:
        return {"status": "fail", "n": n, "max_diff_pct": max_diff, "pairs": pairs,
                "reason": f"tolerance exceeded: max diff {max_diff:.2f}% > {tol_pct:g}%"}
    return {"status": "pass", "n": n, "max_diff_pct": max_diff, "pairs": pairs,
            "reason": f"{n} pairs all within {tol_pct:g}%"}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/poke_api/test_tcgcsv_check.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Wire the `tcgcsv-check` CLI (gated, 0-credit, writes a result doc)**

Read the current `edge_cli.py` argparser (around `:86-205`) and dispatch table (`:681-697`) first, then add a subcommand `tcgcsv-check` that: (a) refuses unless `poke.tcgcsv` is true (mirror `independent_sources_enabled`); (b) for each catalog asset holding a `ppt_cards` `market_comp` row, resolves its group + `tcgplayer_id` + expected subtype, fetches TCGCSV prices, builds `pairs` via `tcgcsv.pick_market_price`, runs `sample_check`, prints the verdict, and writes `docs/poke/tcgcsv-sample-check-<capture_date>.md` as the committed result (the ledger is gitignored). Add a test asserting the CLI refuses when the gate flag is off (no network attempted).

```python
# test addition — CLI refuses when the gate is off
def test_cli_refuses_when_gate_off(monkeypatch, capsys):
    from scanner.poke_api import edge_cli
    # build deps/cfg with poke.tcgcsv=False; assert the command returns nonzero and
    # makes no network call (patch tcgcsv.fetch_prices to raise if called).
    ...
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (all green; new tests included)

- [ ] **Step 7: Commit**

```bash
git add scanner/poke_api/tcgcsv_check.py scanner/poke_api/edge_cli.py tests/poke_api/test_tcgcsv_check.py
git commit -m "feat(poke): TCGCSV sample-check gate (fixed >=5 cards / <=2%, gated, 0 credits)"
```

---

### Task 3: Identity ingest — exact mapping proposals (spec T3)

**Files:**
- Create: `scanner/poke_api/tcgcsv_ingest.py`
- Modify: `scanner/poke_api/edge_cli.py` (add `tcgcsv-ingest` subcommand + dispatch)
- Test: `tests/poke_api/test_tcgcsv_ingest.py`

**Interfaces:**
- Consumes: `tcgcsv.fetch_products`, `tcgcsv.card_number_of`; catalog assets (name/set/card_number).
- Produces: `propose_mappings(products: list[dict], assets: list[dict]) -> list[dict]` — pure; for each asset, finds the product whose card number **exactly** matches and whose name matches, emitting `{"asset_key", "tcgplayer_id", "card_number", "product_name", "match": "exact"|"none"}`. Never writes to `assets.yaml`; a non-exact match is `"none"` (surfaced for review, never accepted).

- [ ] **Step 1: Write the failing test**

```python
# tests/poke_api/test_tcgcsv_ingest.py
from scanner.poke_api import tcgcsv_ingest


def test_exact_number_match_proposes_productid():
    products = [{"productId": 111, "name": "Umbreon ex",
                 "extendedData": [{"name": "Number", "value": "161/131"}]}]
    assets = [{"asset_key": "umbreon_ex_161", "name": "Umbreon ex", "card_number": "161/131"}]
    out = tcgcsv_ingest.propose_mappings(products, assets)
    assert out[0]["match"] == "exact"
    assert out[0]["tcgplayer_id"] == 111


def test_no_number_match_is_none_never_guessed():
    products = [{"productId": 111, "name": "Umbreon ex",
                 "extendedData": [{"name": "Number", "value": "160/131"}]}]
    assets = [{"asset_key": "umbreon_ex_161", "name": "Umbreon ex", "card_number": "161/131"}]
    out = tcgcsv_ingest.propose_mappings(products, assets)
    assert out[0]["match"] == "none"
    assert out[0]["tcgplayer_id"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/poke_api/test_tcgcsv_ingest.py -q`
Expected: FAIL with `ModuleNotFoundError: scanner.poke_api.tcgcsv_ingest`

- [ ] **Step 3: Implement the pure proposer**

```python
# scanner/poke_api/tcgcsv_ingest.py
"""TCGCSV identity ingest (spec T3): propose EXACT tcgplayer_id mappings for review.

Replaces a fuzzy mapping assistant with an exact join (card number + name → productId).
Emits PROPOSALS only — never writes assets.yaml; a non-exact candidate is 'none',
surfaced for review, never accepted (STOP-class exact identity).
"""
from __future__ import annotations

from .tcgcsv import card_number_of


def _norm(s) -> str:
    return " ".join(str(s or "").strip().lower().split())


def propose_mappings(products: list[dict], assets: list[dict]) -> list[dict]:
    by_number: dict[str, list[dict]] = {}
    for p in products:
        num = card_number_of(p)
        if num:
            by_number.setdefault(num.strip(), []).append(p)
    out: list[dict] = []
    for asset in assets:
        want_num = str(asset.get("card_number") or "").strip()
        want_name = _norm(asset.get("name"))
        candidates = by_number.get(want_num, [])
        exact = [p for p in candidates if _norm(p.get("name")) == want_name]
        if len(exact) == 1:
            out.append({"asset_key": asset.get("asset_key"),
                        "tcgplayer_id": exact[0].get("productId"),
                        "card_number": want_num,
                        "product_name": exact[0].get("name"), "match": "exact"})
        else:
            out.append({"asset_key": asset.get("asset_key"), "tcgplayer_id": None,
                        "card_number": want_num, "product_name": None, "match": "none"})
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/poke_api/test_tcgcsv_ingest.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Wire the `tcgcsv-ingest --group` CLI (proposals only, gated)**

Add a `tcgcsv-ingest` subcommand: refuses unless `poke.tcgcsv` true; takes `--group <name|id>` (resolve name → groupId via `tcgcsv.fetch_groups`); fetches products; runs `propose_mappings` against unmapped catalog assets in that set; writes proposals to `data/poke/tcgcsv-proposals-<group>.json` (a review artifact — NOT `assets.yaml`); prints an accept/reject summary. Add a test that it writes proposals and never mutates `assets.yaml`.

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (all green)

- [ ] **Step 7: Commit**

```bash
git add scanner/poke_api/tcgcsv_ingest.py scanner/poke_api/edge_cli.py tests/poke_api/test_tcgcsv_ingest.py
git commit -m "feat(poke): TCGCSV exact-id identity ingest (proposals only, never auto-writes catalog)"
```

---

## Self-Review

**Spec coverage (this plan = spec T0, T1, T3 + the shared client the reference adapter (T2) needs):**
- T0 doc-hardening → Task 0 ✓
- T1 sample-check gate (fixed 5/≤2%, fail-fork disables reference not identity) → Task 2 ✓ (the fail-fork is honored structurally: this plan ships identity ingest regardless; the *reference adapter* in the next plan is gated on this gate's `pass`).
- T3 identity ingest (exact, proposals-only) → Task 3 ✓
- Shared TCGCSV client (products + prices + exact-subtype pick) → Task 1 ✓
- **Deferred to the next plan (deliberately):** T2 reference adapter — it touches the comp engine's two-source-agreement confidence and the `_INDEPENDENT_OF_PPT` classification, which need their own careful task (with the mandatory test: a `tcgcsv` comp agreeing with `ppt_cards` is never `cross_source_validated`). Not a gap — a sequencing decision, flagged.

**Placeholder scan:** Task 2 Step 5 and Task 3 Step 5 (the CLI-wiring steps) describe the wiring against exact anchors but do not reproduce the full argparser/dispatch code, because the exact current `edge_cli.py` argparser block must be read at execution time to extend it faithfully (money-class CLI; guessing the surrounding code risks a wrong edit). Each names the exact anchors (`edge_cli.py:86-205`, `:681-697`), the gating rule (`independent_sources_enabled` mirror), the output artifact, and a required test — an executor has an unambiguous, testable target. The pure logic those CLIs call (`sample_check`, `propose_mappings`, `pick_market_price`) is fully coded and tested.

**Type consistency:** `pick_market_price(product_id, subtype, price_rows)`, `sample_check(pairs, *, min_n, tol_pct)`, `propose_mappings(products, assets)`, `card_number_of(product)` — signatures match between their definitions and consumers across tasks. `fetch_prices`/`fetch_products` return `list[dict]` consumed as such. `poke.tcgcsv` gate name is consistent throughout.

---

**Next in the sequence (not this plan):** Plan 2 — TCGCSV reference adapter (T2, gated on this plan's sample-check) + honest fee model (T4) + sealed credit accounting (T5). Then Plan 3 — guards (T6 data-quality, T7 drift). Then Plan 4 — inventory/P&L ledger + buy loop (T8–T11).
