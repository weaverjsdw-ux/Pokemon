# Live Sealed Deal Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `python -m scanner.discovery.sweep` produce a real, dated sealed-product dashboard from live market comps (PPT v2 by `ppt_id`, eBay/PriceCharting fallback), ranking the catalog by appreciation headroom vs MSRP.

**Architecture:** Extend `scanner/discovery/` in place. One new pure-assembly module (`sweep.py`) + one extracted checker (`golden.py`), consuming the existing schema/scorer/renderer/ledger unchanged. Small additive changes to `market.py` (source URL + credit telemetry on quote rows) and `config.py` (two new `poke` fields). The comp lookup is injected, so all tests run without network.

**Tech Stack:** Python 3.10+ (uses `X | None` unions), pytest, requests, PyYAML. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-28-poke-live-sealed-slice-design.md`

## Global Constraints

- **Never fabricate a row.** A product with no usable comp, no parseable MSRP, or no attribution URL is skipped and counted — it never renders.
- **`price_confidence="verified"` requires an exact-product `sourceUrl`** (PPT `tcgPlayerUrl`) **and** `comp_confidence in {"high", "medium"}`. Everything else is `est` with `derivation_method` set and an EST badge (the STOP gate in `scanner/discovery/schema.py` enforces this).
- **Every rendered row needs a non-empty `source_url` and `captured_at`** — `golden_check` hard-fails otherwise. Est rows carry the fallback quote's search-page `url` as attribution.
- **All derived fields come from the existing backbone:** `score.assign_badges`, `score.lens_tags`, `scanner.main.verdict_for_alert`. No fee/threshold logic is re-implemented in the sweep.
- **Credit governance:** exact-id lookups only (`limit=1` semantics already in the client); `poke.daily_credit_cap` (default 90) guards a run; when exhausted, remaining products degrade to the resale fallback — never an error.
- **A comp failure never errors the run** (spec §8) — exceptions become error rows, which count as `no_comp`.
- **Golden hard-fail halts:** the CLI exits non-zero and does NOT write the dashboard HTML (sweep JSON + manifest + ledger are still persisted — observations are real).
- **Windows-safe console output:** ASCII only in `print()` strings. Files are written with `encoding="utf-8"`.
- **Full existing test suite (251 tests) stays green after every task.** Run `python -m pytest -q` before each commit.

---

### Task 1: `market.py` — sealed quotes carry `sourceUrl` + credit telemetry

The PPT v2 payload includes `tcgPlayerUrl` per sealed product (see `docs/poke/reference/ppt-v2-notes.md`), and every HTTP response carries `X-API-Calls-Consumed` / `X-RateLimit-Daily-Remaining` headers plus `metadata.apiCallsConsumed`. Attach all three to quote rows so the sweep can do provenance mapping and credit guarding.

**Files:**
- Modify: `scanner/market.py`
- Test: `tests/test_market.py`

**Interfaces:**
- Consumes: existing `resale.annotate_quote`, `resale._amount`, `resale._money`.
- Produces: PPT "ok" quote rows gain keys `sourceUrl: str` and `url: str` (both = `tcgPlayerUrl`, possibly `""`). Any PPT row produced from an HTTP response (ok or no-match) gains `creditsConsumed: int` (>= 1) and `dailyRemaining: int | None`. `MarketFallbackClient` carries the primary's telemetry onto a fallback row. Task 5's `LiveCompLookup` reads these keys.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_market.py`. Also extend the existing `_FakeResponse` / `_FakeSession` helpers (at lines 91–109) with an optional `headers` argument — defaulting to `{}` so existing tests are untouched:

```python
class _FakeResponse:
    def __init__(self, payload, headers=None):
        self._payload = payload
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload, headers=None):
        self._payload = payload
        self._headers = headers
        self.last = None

    def get(self, url, params=None, headers=None, timeout=None):
        self.last = {"url": url, "params": params, "headers": headers}
        return _FakeResponse(self._payload, self._headers)
```

New tests at the end of the file:

```python
def test_v2_ok_row_carries_source_url_and_credit_telemetry():
    payload = {
        "data": {"tcgPlayerId": "593355", "name": "Prismatic Evolutions Elite Trainer Box",
                 "tcgPlayerUrl": "https://www.tcgplayer.com/product/593355",
                 "unopenedPrice": 199.14},
        "metadata": {"apiCallsConsumed": {"total": 1}},
    }
    session = _FakeSession(payload, headers={"X-API-Calls-Consumed": "1",
                                             "X-RateLimit-Daily-Remaining": "87"})
    client = PokemonPriceTrackerClient(api_key="k", session=session)
    row = client.estimate("prismatic_evolutions_etb", {"msrp": "$49.99", "ppt_id": "593355"}, 0)
    assert row["status"] == "ok"
    assert row["sourceUrl"] == "https://www.tcgplayer.com/product/593355"
    assert row["url"] == "https://www.tcgplayer.com/product/593355"
    assert row["creditsConsumed"] == 1
    assert row["dailyRemaining"] == 87


def test_v2_credits_fall_back_to_metadata_then_one():
    # no headers at all -> metadata total; no metadata either -> default 1 (a call happened)
    payload = {"data": {"tcgPlayerId": "1", "unopenedPrice": 10.0},
               "metadata": {"apiCallsConsumed": {"total": 3}}}
    client = PokemonPriceTrackerClient(api_key="k", session=_FakeSession(payload))
    row = client.estimate("x", {"ppt_id": "1"}, 0)
    assert row["creditsConsumed"] == 3
    assert row["dailyRemaining"] is None

    bare = {"data": {"tcgPlayerId": "1", "unopenedPrice": 10.0}}
    row = PokemonPriceTrackerClient(api_key="k", session=_FakeSession(bare)).estimate(
        "x", {"ppt_id": "1"}, 0)
    assert row["creditsConsumed"] == 1


def test_v2_no_match_after_http_still_bills_credit():
    session = _FakeSession({"data": None, "metadata": {}},
                           headers={"X-API-Calls-Consumed": "1",
                                    "X-RateLimit-Daily-Remaining": "42"})
    row = PokemonPriceTrackerClient(api_key="k", session=session).estimate(
        "x", {"ppt_id": "999"}, 0)
    assert row["status"] == "no_matches"
    assert row["creditsConsumed"] == 1
    assert row["dailyRemaining"] == 42


def test_fallback_row_carries_primary_telemetry():
    primary = _StubClient(row={"status": "no_matches", "creditsConsumed": 1,
                               "dailyRemaining": 42})
    fallback = _StubClient(row=_ok_row("$50.00"))
    client = MarketFallbackClient(primary, fallback)
    row = client.estimate("k", {"msrp": "$49.99"}, 0)
    assert row["status"] == "ok"
    assert row["creditsConsumed"] == 1
    assert row["dailyRemaining"] == 42


def test_fallback_row_untouched_when_primary_never_called_http():
    primary = _StubClient(row={"status": "no_matches"})  # e.g. no ppt_id, 0 credits
    fallback = _StubClient(row=_ok_row("$50.00"))
    row = MarketFallbackClient(primary, fallback).estimate("k", {"msrp": "$49.99"}, 0)
    assert "creditsConsumed" not in row
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python -m pytest tests/test_market.py -q`
Expected: the 5 new tests FAIL (`KeyError: 'sourceUrl'` / `'creditsConsumed'`); all pre-existing tests PASS.

- [ ] **Step 3: Implement**

In `scanner/market.py`:

Replace `_first_unopened_price` (lines 57–65) with a version that also returns the product URL:

```python
def _first_unopened(payload: dict[str, Any]) -> tuple[float | None, str]:
    """(unopenedPrice, tcgPlayerUrl) from the first usable data item."""
    data = payload.get("data")
    items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    for item in items:
        if isinstance(item, dict):
            price = resale._amount(item.get("unopenedPrice"))
            if price is not None:
                return price, str(item.get("tcgPlayerUrl") or "")
    return None, ""


def _int_or(value: Any, default: int | None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _credits_from(payload: dict[str, Any], headers: Any) -> int:
    consumed = _int_or((headers or {}).get("X-API-Calls-Consumed"), None)
    if consumed is None:
        calls = (payload.get("metadata") or {}).get("apiCallsConsumed")
        total = calls.get("total") if isinstance(calls, dict) else calls
        consumed = _int_or(total, 1)  # an HTTP call happened; never claim 0
    return consumed
```

In `PokemonPriceTrackerClient.estimate`, replace the last two lines (`response.raise_for_status()` / `return _quote_from_ppt(...)`) with:

```python
        response.raise_for_status()  # 401/429/5xx -> RequestException -> fallback
        payload = response.json()
        headers = getattr(response, "headers", None) or {}
        row = _quote_from_ppt(product_key, product, payload, checked_at)
        return row | {
            "creditsConsumed": _credits_from(payload, headers),
            "dailyRemaining": _int_or(headers.get("X-RateLimit-Daily-Remaining"), None),
        }
```

In `_quote_from_ppt`, change the first line and the "ok" return to include the URL:

```python
    price, source_url = _first_unopened(payload)
```

```python
    return resale.annotate_quote(product, base | {
        "status": "ok",
        "estimate": money,
        "low": money,
        "high": money,
        "sampleSize": 0,  # single market price, not a sold-comp sample
        "sourceUrl": source_url,
        "url": source_url,
        "detail": "PokemonPriceTracker TCGplayer sealed market price.",
    })
```

In `MarketFallbackClient.estimate`, carry telemetry across the fall-through:

```python
    def estimate(self, product_key: str, product: dict[str, Any], checked_at: int) -> dict[str, Any]:
        consumed = 0
        remaining = None
        try:
            row = self.primary.estimate(product_key, product, checked_at)
            consumed = int(row.get("creditsConsumed") or 0)
            remaining = row.get("dailyRemaining")
            if row.get("status") == "ok":
                return row
        except requests.RequestException:
            pass
        except Exception:
            pass
        row = self.fallback.estimate(product_key, product, checked_at)
        if consumed or remaining is not None:
            row = row | {"creditsConsumed": consumed, "dailyRemaining": remaining}
        return row
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_market.py -q`
Expected: ALL PASS (existing + 5 new).

Run: `python -m pytest -q`
Expected: 256 passed.

- [ ] **Step 5: Commit**

```bash
git add scanner/market.py tests/test_market.py
git commit -m "feat(market): sealed quotes carry sourceUrl + credit telemetry"
```

---

### Task 2: config — `poke.buy_basis` + `poke.daily_credit_cap`

**Files:**
- Modify: `scanner/config.py` (PokeCfg lines 31–38, poke parsing lines 156–170)
- Modify: `config.example.yaml` (poke section, after line 84)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `cfg.poke.buy_basis: str` (only `"msrp"` accepted in this build) and `cfg.poke.daily_credit_cap: int` (default 90). Task 4 reads `buy_basis` for the sweep notes; Task 5's credit guard reads `daily_credit_cap`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_poke_slice_defaults():
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    assert cfg.poke.buy_basis == "msrp"
    assert cfg.poke.daily_credit_cap == 90


def test_poke_slice_overrides_parse():
    cfg = cfg_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "poke": {"buy_basis": "MSRP", "daily_credit_cap": 40},
    })
    assert cfg.poke.buy_basis == "msrp"
    assert cfg.poke.daily_credit_cap == 40


def test_poke_rejects_unknown_buy_basis():
    with pytest.raises(SystemExit):
        cfg_mod.from_mapping({
            "locations": {"home": "A", "work": "B"},
            "poke": {"buy_basis": "observed"},
        })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -q`
Expected: 3 new tests FAIL (`AttributeError: ... no attribute 'buy_basis'` / no `SystemExit`).

- [ ] **Step 3: Implement**

In `scanner/config.py`, add two fields to `PokeCfg`:

```python
@dataclass
class PokeCfg:
    min_rows: int = 10            # golden-test acquisition-failure floor
    staleness_days: int = 30      # comp older than this is flagged stale
    steal_pct: float = 30.0       # verified deal at/above this % off -> STEAL eligible
    min_discount_pct: float = 5.0 # below this % off market -> not a deal row
    grading_cost_all_in: float = 97.50  # live PSA tier all-in (config, value tiers paused 2026-06)
    buy_basis: str = "msrp"       # sealed-board deal-price basis ("observed" is a future hook)
    daily_credit_cap: int = 90    # PPT credits/run guard; past this the sweep uses the resale fallback
```

In `from_mapping`, inside the existing `poke_cfg = PokeCfg(...)` try-block, add the two kwargs, and validate `buy_basis` just before:

```python
    buy_basis = str(poke_raw.get("buy_basis", "msrp")).strip().lower()
    if buy_basis != "msrp":
        raise SystemExit(
            "config.yaml: poke.buy_basis only supports 'msrp' in this build "
            "('observed' is a future hook, not implemented)."
        )
    try:
        poke_cfg = PokeCfg(
            min_rows=int(poke_raw.get("min_rows", 10)),
            staleness_days=int(poke_raw.get("staleness_days", 30)),
            steal_pct=_num(poke_raw, "steal_pct", 30.0, "poke.steal_pct"),
            min_discount_pct=_num(poke_raw, "min_discount_pct", 5.0, "poke.min_discount_pct"),
            grading_cost_all_in=_num(poke_raw, "grading_cost_all_in", 97.50, "poke.grading_cost_all_in"),
            buy_basis=buy_basis,
            daily_credit_cap=int(poke_raw.get("daily_credit_cap", 90)),
        )
    except (TypeError, ValueError):
        raise SystemExit("config.yaml: poke.min_rows / poke.staleness_days / poke.daily_credit_cap must be integers.")
```

In `config.example.yaml`, add under the `poke:` section (after `grading_cost_all_in`):

```yaml
  buy_basis: msrp           # sealed-board deal-price basis ("observed" last-seen retail is a future hook)
  daily_credit_cap: 90      # PPT credits per sweep run; past this, remaining products use the resale fallback
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -q` then `python -m pytest -q`
Expected: ALL PASS (259 total).

- [ ] **Step 5: Commit**

```bash
git add scanner/config.py config.example.yaml tests/test_config.py
git commit -m "feat(config): poke.buy_basis + poke.daily_credit_cap for the sealed board"
```

---

### Task 3: extract `golden_check` into `scanner/discovery/golden.py`

The checker currently lives inside `tests/test_poke_golden.py` (lines 12–28). The CLI needs it too, so move it to a real module and import it back into the test. Assertions stay byte-identical.

**Files:**
- Create: `scanner/discovery/golden.py`
- Modify: `tests/test_poke_golden.py`

**Interfaces:**
- Produces: `golden_check(html: str, min_rows: int) -> list[str]` — empty list = pass; non-empty = hard-fail messages. Task 5's CLI imports `from . import golden as golden_mod`.

- [ ] **Step 1: Create the module**

Create `scanner/discovery/golden.py`:

```python
"""Golden checks for a rendered /poke dashboard. Shared by the sweep CLI and tests.

Returns HARD-FAIL messages (empty = pass). The caller halts rather than ship
a dashboard that is structurally broken or suspiciously thin (acquisition
failure), or that contains a deal row without provenance.
"""
from __future__ import annotations

import re

from .render import element_ids, nav_anchors


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
```

- [ ] **Step 2: Point the test at it**

In `tests/test_poke_golden.py`: delete the local `golden_check` definition (lines 12–28) and the now-unused `import re`; replace the render import line so only `render_sweep` remains, and import the checker:

```python
from scanner.discovery.golden import golden_check
from scanner.discovery.render import render_sweep
```

The four existing test functions stay untouched.

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_poke_golden.py -q` then `python -m pytest -q`
Expected: ALL PASS (259 — moved, not added).

- [ ] **Step 4: Commit**

```bash
git add scanner/discovery/golden.py tests/test_poke_golden.py
git commit -m "refactor(poke): extract golden_check into discovery.golden for CLI reuse"
```

---

### Task 4: `build_sealed_sweep` — pure assembly

The heart of the slice: catalog + injected comp lookup -> STOP-gated sweep dict. No I/O, no network, no clock reads (everything injected).

**Files:**
- Create: `scanner/discovery/sweep.py` (assembly half; the CLI half lands in Task 5)
- Test: `tests/test_poke_sweep.py`

**Interfaces:**
- Consumes: `config.selected_products(cfg)`; `market.comp_from_row(row) -> (float | None, str)`; `score.compute_pct_off / assign_badges / lens_tags`; `main.verdict_for_alert(cfg, product, price_str, comp_row) -> str`; `schema.DealRow / assert_sweep`; `resale._amount` for MSRP parsing.
- Produces: `build_sealed_sweep(cfg, comp_lookup, *, event: str, sweep_id: str, captured_at: str) -> dict` where `comp_lookup: Callable[[str, dict], dict]` takes `(product_key, product)` and returns a quote-row dict. The returned sweep dict has keys `event, sweep_id, captured_window, notes, deals (list[dict], sorted pct_off desc), promo_codes, bundled_offers, watchlist_results, sources, counts`. `counts = {"scanned", "comped", "no_comp", "no_msrp", "no_source"}`. Task 5 persists and renders this dict.

**Provenance decision (locked here):** the row's `source_url` is `comp_row["sourceUrl"] or comp_row["url"]` — attribution for the human to click. But `verified` status requires the exact-product `sourceUrl` key specifically (only the PPT path sets it) plus high/medium confidence. A comp with no URL at all cannot satisfy the golden per-row provenance rule, so it is skipped + counted as `no_source` (never rendered, never fabricated).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_poke_sweep.py`:

```python
from datetime import date

import pytest

from scanner import config as cfg_mod
from scanner import main as main_mod
from scanner.discovery import score, sweep
from scanner.discovery.schema import row_from_dict

PPT_URL = "https://www.tcgplayer.com/product/593355"
EBAY_URL = "https://www.ebay.com/sch/i.html?_nkw=fake+etb+sealed"

CATALOG = {
    "fake_etb": {"name": "Fake ETB", "set": "FakeSet", "type": "ETB", "msrp": "$49.99"},
    "fake_bundle": {"name": "Fake Bundle", "set": "FakeSet", "type": "Booster Bundle", "msrp": "$26.94"},
    "fake_box": {"name": "Fake Box", "set": "FakeSet", "type": "Surprise Box", "msrp": "$22.99"},
}


def _cfg(catalog=CATALOG, **poke):
    raw = {"locations": {"home": "A", "work": "B"}}
    if poke:
        raw["poke"] = poke
    cfg = cfg_mod.from_mapping(raw)
    cfg.products = dict(catalog)
    cfg.products_filter = None
    return cfg


def _verified_row(estimate="$199.14", confidence="medium"):
    return {"status": "ok", "estimate": estimate, "confidence": confidence,
            "source": "PokemonPriceTracker", "basis": "TCGplayer sealed market",
            "sourceUrl": PPT_URL, "url": PPT_URL}


def _est_row(estimate="$60.00"):
    return {"status": "ok", "estimate": estimate, "confidence": "medium",
            "source": "eBay Browse API", "basis": "active fixed-price asking median",
            "url": EBAY_URL}


def _build(cfg, lookup):
    return sweep.build_sealed_sweep(cfg, lookup, event="sealed",
                                    sweep_id="2026-07-01-sealed",
                                    captured_at="2026-07-01")


def test_verified_comp_maps_to_verified_row():
    swp = _build(_cfg(), lambda k, p: _verified_row())
    assert len(swp["deals"]) == 3
    for d in swp["deals"]:
        assert d["asset_class"] == "sealed"
        assert d["retailer"] == "MSRP"
        assert d["price_confidence"] == "verified"
        assert d["source_url"] == PPT_URL
        assert d["captured_at"] == "2026-07-01"
        assert "EST" not in d["badges"]
    by_item = {d["item"]: d for d in swp["deals"]}
    assert by_item["Fake ETB"]["category"] == "sealed-etb"
    assert by_item["Fake Bundle"]["category"] == "sealed-bundle"
    assert by_item["Fake Box"]["category"] == "sealed-other"
    assert swp["counts"] == {"scanned": 3, "comped": 3, "no_comp": 0,
                             "no_msrp": 0, "no_source": 0}


def test_fallback_comp_maps_to_est_with_attribution():
    swp = _build(_cfg(), lambda k, p: _est_row())
    for d in swp["deals"]:
        assert d["price_confidence"] == "est"
        assert "EST" in d["badges"]
        assert d["source_url"] == EBAY_URL       # search-page attribution
        assert "eBay Browse API" in d["derivation_method"]
        assert "STEAL" not in d["badges"]        # est never a confirmed STEAL


def test_low_confidence_ppt_comp_is_est_even_with_source_url():
    swp = _build(_cfg(), lambda k, p: _verified_row(confidence="low"))
    for d in swp["deals"]:
        assert d["price_confidence"] == "est"
        assert "EST" in d["badges"]


def test_no_comp_product_is_skipped_and_counted():
    def lookup(key, product):
        if key == "fake_etb":
            return {"status": "no_matches"}
        return _verified_row()
    swp = _build(_cfg(), lookup)
    assert len(swp["deals"]) == 2
    assert swp["counts"]["no_comp"] == 1
    assert all(d["item"] != "Fake ETB" for d in swp["deals"])


def test_missing_msrp_is_skipped_and_counted():
    catalog = dict(CATALOG)
    catalog["no_msrp"] = {"name": "No MSRP", "set": "FakeSet", "type": "ETB"}
    swp = _build(_cfg(catalog), lambda k, p: _verified_row())
    assert swp["counts"]["no_msrp"] == 1
    assert len(swp["deals"]) == 3


def test_unattributable_comp_is_skipped_and_counted():
    row = {"status": "ok", "estimate": "$60.00", "confidence": "medium",
           "source": "X", "basis": "y"}  # no sourceUrl, no url
    swp = _build(_cfg(), lambda k, p: row)
    assert len(swp["deals"]) == 0
    assert swp["counts"]["no_source"] == 3


def test_badges_lenses_and_verdict_pin_to_backbone():
    cfg = _cfg()
    comp_rows = {k: _verified_row() for k in CATALOG}
    swp = _build(cfg, lambda k, p: comp_rows[k])
    key_by_item = {p["name"]: k for k, p in CATALOG.items()}
    for d in swp["deals"]:
        row = row_from_dict(d)
        row.badges, row.lens_tags = [], []
        assert score.assign_badges(row, cfg) == d["badges"]
        assert score.lens_tags(row, cfg) == d["lens_tags"]
        key = key_by_item[d["item"]]
        expected = main_mod.verdict_for_alert(
            cfg, CATALOG[key], f"${d['deal_price']:.2f}", comp_rows[key])
        assert d["scanner_verdict"] == expected


def test_deals_sorted_by_pct_off_desc():
    def lookup(key, product):
        return {"fake_etb": _verified_row("$199.14"),      # ~75% off
                "fake_bundle": _verified_row("$30.00"),    # ~10% off
                "fake_box": _verified_row("$100.00")}[key]  # ~77% off
    swp = _build(_cfg(), lookup)
    pcts = [d["pct_off"] for d in swp["deals"]]
    assert pcts == sorted(pcts, reverse=True)


def test_sweep_dict_shape():
    swp = _build(_cfg(), lambda k, p: _verified_row())
    for key in ("event", "sweep_id", "captured_window", "notes", "deals",
                "promo_codes", "bundled_offers", "watchlist_results",
                "sources", "counts"):
        assert key in swp
    assert swp["promo_codes"] == []
    assert swp["bundled_offers"] == []
    assert swp["watchlist_results"] == []
    assert any(s["name"] == "PokemonPriceTracker" for s in swp["sources"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_poke_sweep.py -q`
Expected: FAIL with `ImportError` / `AttributeError` (no `sweep` module yet).

- [ ] **Step 3: Implement**

Create `scanner/discovery/sweep.py` (assembly half):

```python
"""Live sealed deal board: build a /poke sweep from live comps (MSRP buy basis).

    python -m scanner.discovery.sweep [--out DIR] [--event NAME]

Pure assembly (build_sealed_sweep) is separated from I/O (main): the comp
lookup is injected, so tests never touch the network. Doctrine: never
fabricate a row; a product with no usable comp / MSRP / attribution URL is
skipped and counted. STOP gate before render; a golden hard-fail halts the
run (exit 1) instead of shipping a bad dashboard.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from .. import config as cfg_mod
from .. import main as main_mod
from .. import market as market_mod
from .. import resale
from . import schema, score

CompLookup = Callable[[str, dict], dict]


def _msrp(product: dict) -> float | None:
    return resale._amount(product.get("msrp"))


def _category(product: dict) -> str:
    ptype = str(product.get("type") or "").strip().lower()
    if ptype == "etb":
        return "sealed-etb"
    if ptype == "booster bundle":
        return "sealed-bundle"
    return "sealed-other"


def _provenance(comp_row: dict, comp_confidence: str) -> tuple[str, str, str, str]:
    """(price_confidence, source_url, derivation_method, confidence_detail).

    Only an exact-product sourceUrl (PPT tcgPlayerUrl) at high/medium
    confidence earns "verified". Fallback comps keep their search-page url
    as attribution but stay "est" - the STOP gate then requires the EST
    badge + derivation_method, so an est comp can never render as a
    confirmed STEAL.
    """
    exact_url = str(comp_row.get("sourceUrl") or "")
    source_url = exact_url or str(comp_row.get("url") or "")
    if exact_url and comp_confidence in {"high", "medium"}:
        return "verified", source_url, "", ""
    method = " / ".join(
        part for part in (str(comp_row.get("source") or ""), str(comp_row.get("basis") or ""))
        if part
    ) or "market comp"
    detail = str(comp_row.get("confidenceReason") or "")
    return "est", source_url, method, detail


def build_sealed_sweep(
    cfg: Any,
    comp_lookup: CompLookup,
    *,
    event: str,
    sweep_id: str,
    captured_at: str,
) -> dict:
    products = cfg_mod.selected_products(cfg)
    rows: list[schema.DealRow] = []
    counts = {"scanned": 0, "comped": 0, "no_comp": 0, "no_msrp": 0, "no_source": 0}
    comp_sources: dict[str, int] = {}

    for key, product in products.items():
        counts["scanned"] += 1
        deal_price = _msrp(product)
        if deal_price is None or deal_price <= 0:
            counts["no_msrp"] += 1
            continue
        comp_row = comp_lookup(key, product) or {}
        comp, comp_confidence = market_mod.comp_from_row(comp_row)
        if comp is None:
            counts["no_comp"] += 1
            continue
        price_confidence, source_url, derivation, detail = _provenance(comp_row, comp_confidence)
        if not source_url:
            counts["no_source"] += 1  # unattributable comp: never render without provenance
            continue
        row = schema.DealRow(
            item=str(product.get("name") or key),
            asset_class="sealed",
            category=_category(product),
            deal_price=deal_price,
            market_comp=comp,
            retailer="MSRP",
            source_url=source_url,
            captured_at=captured_at,
            price_confidence=price_confidence,
            comp_confidence=comp_confidence,
            pct_off=score.compute_pct_off(deal_price, comp),
            derivation_method=derivation,
            confidence_detail=detail,
            capture_method="live-comp",
            set=str(product.get("set") or ""),
        )
        row.badges = score.assign_badges(row, cfg)
        row.lens_tags = score.lens_tags(row, cfg)
        row.scanner_verdict = main_mod.verdict_for_alert(
            cfg, product, f"${deal_price:.2f}", comp_row)
        rows.append(row)
        counts["comped"] += 1
        label = str(comp_row.get("source") or "unknown")
        comp_sources[label] = comp_sources.get(label, 0) + 1

    schema.assert_sweep(rows)  # STOP gate before the dict leaves this function
    rows.sort(key=lambda r: (r.pct_off is None, -(r.pct_off or 0)))

    sources = [
        {"name": name, "category": "comp", "tier": "api", "status": "used",
         "note": f"{n} comps"}
        for name, n in sorted(comp_sources.items())
    ]
    sources.append({"name": "no_comp", "category": "comp", "tier": "n/a",
                    "status": "skipped",
                    "note": f"{counts['no_comp']} products had no usable comp"})

    return {
        "event": event,
        "sweep_id": sweep_id,
        "captured_window": captured_at,
        "notes": (f"Live sealed board - buy basis {cfg.poke.buy_basis.upper()} - "
                  f"{counts['comped']}/{counts['scanned']} comped"),
        "deals": [asdict(r) for r in rows],
        "promo_codes": [],
        "bundled_offers": [],
        "watchlist_results": [],
        "sources": sources,
        "counts": counts,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_poke_sweep.py -q` then `python -m pytest -q`
Expected: ALL PASS (268 total).

- [ ] **Step 5: Commit**

```bash
git add scanner/discovery/sweep.py tests/test_poke_sweep.py
git commit -m "feat(poke): build_sealed_sweep - live-comp sealed board assembly behind the STOP gate"
```

---

### Task 5: CLI — live lookup, credit guard, persist, ledger, render, golden gate

**Files:**
- Modify: `scanner/discovery/sweep.py` (append the I/O half)
- Test: `tests/test_poke_sweep.py` (append CLI + credit-guard tests)

**Interfaces:**
- Consumes: Task 4's `build_sealed_sweep`; Task 3's `golden.golden_check`; Task 1's telemetry keys; `render.render_sweep`; `ledger.append_observation(path, obs) -> bool` (obs needs `kind` in `{"deal","market_comp"}`, identity fields `set/item/variant/grade/condition`, `source_url`, `capture_date`); `config.load()`, `config.ROOT`.
- Produces: `main(argv=None, comp_lookup=None, cfg=None) -> int` (0 ok, 1 golden fail, 2 usage) and `LiveCompLookup(cfg, market_client=None, resale_client=None)` — callable `(product_key, product) -> dict` with attributes `credits_used: int`, `exhausted: bool`.

**Output layout** (`--out DIR` swaps the root; default is the repo root `config.ROOT`):
- `<root>/data/poke/<sweep_id>.json` — sweep dict
- `<root>/data/poke/<sweep_id>.manifest.json` — counts, badge breakdown, sources, credits, golden failures
- `<root>/data/poke/price_history.jsonl` — observation ledger (append-only, idempotent)
- `<root>/dashboards/<date>-sealed.html` — written ONLY when golden passes

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_poke_sweep.py`:

```python
# ---------------------------------------------------------------- CLI + guard


class _StubEstimator:
    def __init__(self, row):
        self.row = row
        self.calls = 0

    def estimate(self, key, product, checked_at):
        self.calls += 1
        return dict(self.row)


def test_live_lookup_degrades_to_fallback_when_cap_hit():
    cfg = _cfg(daily_credit_cap=2)
    market = _StubEstimator(_verified_row() | {"creditsConsumed": 1, "dailyRemaining": 50})
    fallback = _StubEstimator(_est_row())
    lookup = sweep.LiveCompLookup(cfg, market_client=market, resale_client=fallback)
    for key, product in CATALOG.items():
        lookup(key, product)
    assert market.calls == 2          # cap=2 -> third product skips the market path
    assert fallback.calls == 1
    assert lookup.credits_used == 2


def test_live_lookup_stops_market_calls_when_daily_remaining_zero():
    cfg = _cfg()
    market = _StubEstimator(_verified_row() | {"creditsConsumed": 1, "dailyRemaining": 0})
    fallback = _StubEstimator(_est_row())
    lookup = sweep.LiveCompLookup(cfg, market_client=market, resale_client=fallback)
    for key, product in CATALOG.items():
        lookup(key, product)
    assert market.calls == 1
    assert lookup.exhausted is True
    assert fallback.calls == 2


def test_live_lookup_turns_exceptions_into_error_rows():
    cfg = _cfg()

    class _Boom:
        def estimate(self, key, product, checked_at):
            raise ValueError("boom")

    lookup = sweep.LiveCompLookup(cfg, market_client=_Boom(), resale_client=_Boom())
    row = lookup("fake_etb", CATALOG["fake_etb"])
    assert row["status"] == "error"   # comp_from_row -> (None, "none") -> counted no_comp


def test_cli_writes_sweep_manifest_dashboard_and_ledger(tmp_path):
    cfg = _cfg(min_rows=3)
    rc = sweep.main(["--out", str(tmp_path)],
                    comp_lookup=lambda k, p: _verified_row(), cfg=cfg)
    assert rc == 0
    today = date.today().isoformat()
    poke_dir = tmp_path / "data" / "poke"
    assert (poke_dir / f"{today}-sealed.json").exists()
    assert (poke_dir / f"{today}-sealed.manifest.json").exists()
    dash = tmp_path / "dashboards" / f"{today}-sealed.html"
    assert dash.exists()

    from scanner.discovery.golden import golden_check
    assert golden_check(dash.read_text(encoding="utf-8"), 3) == []

    ledger_path = poke_dir / "price_history.jsonl"
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 6            # market_comp + deal line per comped product

    # idempotent re-run: same day, same comps -> nothing new appended
    rc2 = sweep.main(["--out", str(tmp_path)],
                     comp_lookup=lambda k, p: _verified_row(), cfg=cfg)
    assert rc2 == 0
    assert len(ledger_path.read_text(encoding="utf-8").splitlines()) == 6


def test_cli_halts_without_dashboard_on_golden_failure(tmp_path, capsys):
    cfg = _cfg(min_rows=99)          # impossible floor -> acquisition-failure canary
    rc = sweep.main(["--out", str(tmp_path)],
                    comp_lookup=lambda k, p: _verified_row(), cfg=cfg)
    assert rc == 1
    today = date.today().isoformat()
    assert not (tmp_path / "dashboards" / f"{today}-sealed.html").exists()
    # evidence still persisted for diagnosis
    assert (tmp_path / "data" / "poke" / f"{today}-sealed.json").exists()
    assert (tmp_path / "data" / "poke" / f"{today}-sealed.manifest.json").exists()
    out = capsys.readouterr().out
    assert "GOLDEN FAIL" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_poke_sweep.py -q`
Expected: new tests FAIL (`AttributeError: ... 'LiveCompLookup'` / `'main'`); Task-4 tests still PASS.

- [ ] **Step 3: Implement**

Append to `scanner/discovery/sweep.py` (and extend the module imports at the top with `argparse`, `json`, `sys`, `time`, `from datetime import date`, `from pathlib import Path`, plus `from . import golden as golden_mod`, `from . import ledger as ledger_mod`, `from . import render as render_mod`):

```python
class LiveCompLookup:
    """One live comp call per product, credit-guarded.

    Uses PPT (behind MarketFallbackClient) while the run's credit budget and
    the account's daily balance hold; afterwards short-circuits straight to
    the resale fallback. Any exception becomes an error row - a comp failure
    never errors the run (it just skips + counts that product).
    """

    def __init__(self, cfg: Any, market_client: Any = None, resale_client: Any = None) -> None:
        self.cfg = cfg
        self.resale_client = resale_client or resale.resale_client_from_config(cfg)
        if market_client is not None:
            self.market_client = market_client
        elif getattr(cfg, "market_preferred", False) and getattr(cfg, "market_api_key", ""):
            self.market_client = market_mod.MarketFallbackClient(
                market_mod.PokemonPriceTrackerClient.from_config(cfg), self.resale_client)
        else:
            self.market_client = None
        self.credits_used = 0
        self.exhausted = False

    def __call__(self, product_key: str, product: dict) -> dict:
        checked_at = int(time.time())
        try:
            if (self.market_client is not None and not self.exhausted
                    and self.credits_used < self.cfg.poke.daily_credit_cap):
                row = self.market_client.estimate(product_key, product, checked_at)
                self.credits_used += int(row.get("creditsConsumed") or 0)
                remaining = row.get("dailyRemaining")
                if isinstance(remaining, int) and remaining <= 0:
                    self.exhausted = True
                return row
            return self.resale_client.estimate(product_key, product, checked_at)
        except Exception as exc:  # never error the run over one comp
            return {"status": "error", "detail": str(exc)[:200]}


def _badge_breakdown(deals: list[dict]) -> dict[str, int]:
    breakdown: dict[str, int] = {}
    for d in deals:
        for badge in d.get("badges", []):
            breakdown[badge] = breakdown.get(badge, 0) + 1
    return breakdown


def _append_ledger(path: Path, sweep: dict, capture_date: str) -> int:
    """market_comp + deal observation per rendered row. Idempotent; returns appended count."""
    appended = 0
    for d in sweep["deals"]:
        base = {
            "set": d.get("set", ""), "item": d.get("item", ""),
            "variant": d.get("variant", ""), "grade": "", "condition": "",
            "source_url": d.get("source_url", ""), "capture_date": capture_date,
        }
        appended += ledger_mod.append_observation(path, base | {
            "kind": "market_comp",
            "comp": d.get("market_comp"),
            "comp_confidence": d.get("comp_confidence", ""),
        })
        appended += ledger_mod.append_observation(path, base | {
            "kind": "deal",
            "deal_price": d.get("deal_price"),
            "market_comp": d.get("market_comp"),
            "pct_off": d.get("pct_off"),
            "price_confidence": d.get("price_confidence", ""),
            "badges": d.get("badges", []),
        })
    return appended


def main(argv: list[str] | None = None,
         comp_lookup: CompLookup | None = None,
         cfg: Any = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scanner.discovery.sweep",
        description="Render the live sealed deal board from the tracked catalog.")
    parser.add_argument("--out", default=None,
                        help="output root (default: repo root; writes data/poke/ + dashboards/)")
    parser.add_argument("--event", default="sealed", help="event label for the sweep id")
    args = parser.parse_args(argv)

    cfg = cfg or cfg_mod.load()
    root = Path(args.out) if args.out else cfg_mod.ROOT
    today = date.today().isoformat()
    sweep_id = f"{today}-{args.event}"
    lookup = comp_lookup if comp_lookup is not None else LiveCompLookup(cfg)

    sweep = build_sealed_sweep(cfg, lookup,
                               event=args.event, sweep_id=sweep_id, captured_at=today)

    poke_dir = root / "data" / "poke"
    poke_dir.mkdir(parents=True, exist_ok=True)
    sweep_path = poke_dir / f"{sweep_id}.json"
    sweep_path.write_text(json.dumps(sweep, indent=2, ensure_ascii=False), encoding="utf-8")

    html = render_mod.render_sweep(sweep)  # STOP gate runs again inside
    fails = golden_mod.golden_check(html, cfg.poke.min_rows)
    credits = getattr(lookup, "credits_used", 0)

    manifest = {
        "sweep_id": sweep_id,
        "captured_at": today,
        "counts": sweep["counts"],
        "badges": _badge_breakdown(sweep["deals"]),
        "sources": sweep["sources"],
        "credits_consumed": credits,
        "golden_failures": fails,
    }
    (poke_dir / f"{sweep_id}.manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    appended = _append_ledger(poke_dir / "price_history.jsonl", sweep, today)

    if fails:
        for message in fails:
            print(f"GOLDEN FAIL: {message}")
        print(f"HALTED: dashboard not written ({len(fails)} golden failures). "
              f"Evidence kept at {sweep_path}")
        return 1

    dash_dir = root / "dashboards"
    dash_dir.mkdir(parents=True, exist_ok=True)
    dash_path = dash_dir / f"{today}-sealed.html"
    dash_path.write_text(html, encoding="utf-8")

    c = sweep["counts"]
    steals = sum(1 for d in sweep["deals"] if "STEAL" in d.get("badges", []))
    print(f"scanned={c['scanned']} comped={c['comped']} no_comp={c['no_comp']} "
          f"no_msrp={c['no_msrp']} no_source={c['no_source']} steals={steals} "
          f"credits={credits} ledger+={appended}")
    print(f"dashboard: {dash_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_poke_sweep.py -q` then `python -m pytest -q`
Expected: ALL PASS (273 total).

- [ ] **Step 5: Commit**

```bash
git add scanner/discovery/sweep.py tests/test_poke_sweep.py
git commit -m "feat(poke): sweep CLI - credit-guarded live comps, persist + ledger + golden-gated dashboard"
```

---

### Task 6: seed `ppt_id` for the Pokemon sealed catalog (data task, live API)

Follow `docs/poke/ppt-id-seeding.md` exactly. 12 products remain (checkboxes in that doc). This task needs the operator's PPT key (`config.yaml` `market.api_key` or `PPT_API_KEY`) and network access. **If the key is missing, stop and ask the operator — do not guess ids.**

**Files:**
- Modify: `data/products.yaml` (add `ppt_id:` lines, mirroring the `prismatic_evolutions_etb` entry at line 24)
- Modify: `docs/poke/ppt-id-seeding.md` (check off each product or record NOT_FOUND)

**Budget note:** each search bills its `limit` (use `limit=5`), each by-id verify is 1 credit ⇒ ~72 credits for all 12 on the Free tier's 100/day. Watch `X-RateLimit-Daily-Remaining`; if it drops below ~20, finish the remainder the next day. Do Task 7's live run on a different day OR confirm ≥ 20 credits remain.

- [ ] **Step 1: For each unchecked product in `docs/poke/ppt-id-seeding.md`, search PPT**

Run (substituting the clean product name, e.g. `Prismatic Evolutions Booster Bundle`):

```
python -c "import requests; from scanner import config as cfg_mod; cfg = cfg_mod.load(); r = requests.get('https://www.pokemonpricetracker.com/api/v2/sealed-products', params={'search': 'PRODUCT NAME HERE', 'limit': 5}, headers={'Authorization': f'Bearer {cfg.market_api_key}'}, timeout=30); [print(d.get('tcgPlayerId'), repr(d.get('name')), d.get('unopenedPrice'), repr(d.get('setName'))) for d in (r.json().get('data') or [])]; print('remaining:', r.headers.get('X-RateLimit-Daily-Remaining'))"
```

Pick the row whose `name` is the **standalone product in the right set**. Exclude: `... and Pokeball`, `... Case`, `(Sam's Club)`, `(Dollar General Exclusive)`, sticker/tech collections. If no standalone match exists, record `NOT_FOUND` in the seeding doc and move on — that product stays on the resale fallback.

- [ ] **Step 2: Verify each candidate id by exact lookup (1 credit)**

```
python -c "import requests; from scanner import config as cfg_mod; cfg = cfg_mod.load(); r = requests.get('https://www.pokemonpricetracker.com/api/v2/sealed-products', params={'tcgPlayerId': 'CANDIDATE_ID'}, headers={'Authorization': f'Bearer {cfg.market_api_key}'}, timeout=30); d = r.json().get('data') or {}; print(d.get('tcgPlayerId'), repr(d.get('name')), d.get('unopenedPrice'))"
```

Accept only if the returned `name` matches the standalone product and `unopenedPrice` is plausible (a 2–4x MSRP multiple is legitimate for hyped sets — do NOT reject it as junk).

- [ ] **Step 3: Record results**

For each verified id, add to the product's entry in `data/products.yaml` (same format as line 24):

```yaml
  ppt_id: "<tcgPlayerId>"   # PokemonPriceTracker tcgPlayerId (standalone <type>; verified <today>)
```

Check the product off in `docs/poke/ppt-id-seeding.md` with the id, price seen, and date — or record `NOT_FOUND (<date>)`. Leave all MTG products without `ppt_id` (PPT is Pokemon-only).

- [ ] **Step 4: Sanity-check the catalog still parses**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS (products.yaml is loaded by config tests).

- [ ] **Step 5: Commit**

```bash
git add data/products.yaml docs/poke/ppt-id-seeding.md
git commit -m "data(poke): seed verified ppt_ids for the Pokemon sealed catalog"
```

---

### Task 7: runbook + manual live spot-check

The spec requires the live spot-check to be documented, not in CI (§9). Write the runbook, run the board live once, verify against reality, and confirm the whole suite is green.

**Files:**
- Create: `docs/poke/live-sealed-board.md`
- No code changes.

- [ ] **Step 1: Write the runbook**

Create `docs/poke/live-sealed-board.md`:

```markdown
# Live Sealed Deal Board — runbook

The board answers: **"which sealed products are most worth grabbing at retail (MSRP) right now?"**
It ranks the tracked catalog by appreciation headroom = live market comp vs MSRP.

## Prerequisites
- `config.yaml` with `market.preferred: true` and `market.api_key` set (or `PPT_API_KEY`).
  Without a key the board still runs — every comp comes from the eBay/PriceCharting
  fallback and renders EST (lower confidence), never a confirmed STEAL.
- Pokemon products should have verified `ppt_id`s (see `ppt-id-seeding.md`).
  MTG products always use the fallback (PPT is Pokemon-only).

## Run
    python -m scanner.discovery.sweep            # writes dashboards/<date>-sealed.html
    python -m scanner.discovery.sweep --out DIR  # everything under DIR instead (testing)

Outputs per run: `data/poke/<date>-sealed.json` (sweep), `.manifest.json` (counts,
badges, sources, credits, golden results), `data/poke/price_history.jsonl`
(append-only observation ledger — idempotent, safe to re-run), and the dashboard.
A golden hard-fail (structure broken, rows below `poke.min_rows`, or a row without
provenance) exits 1 and does NOT write the dashboard.

## Credits
One comp call per product per run (~13 PPT credits with a fully seeded catalog;
Free tier = 100/day). `poke.daily_credit_cap` (default 90) short-circuits the rest
of a run to the fallback if a run would blow the budget. The manifest and run
summary print credits consumed.

## Reading the board
- **STEAL** — verified comp, >= `poke.steal_pct` off. **EST** — estimated comp
  (fallback source or weak confidence); trust it less, click the source link.
- **Rank** — rows sort by % off (appreciation headroom vs MSRP).
- **Scanner column** — the same fee-adjusted BUY/THIN/SKIP verdict the scanner
  alerts with (identical math, pinned by test).
- The tool advises; the human transacts. Verify price + seal before buying.

## Spot-check after a live run (manual, ~2 min)
1. Prismatic Evolutions ETB shows a comp near its live market (~$199 as of 2026-06)
   with confidence `medium`+, badge STEAL, and a sane scanner verdict.
2. Row source links open the right product/search pages.
3. No secrets or addresses in the HTML: search it for your street/city and API key.
4. Manifest `counts` reconcile: scanned = comped + no_comp + no_msrp + no_source.
```

- [ ] **Step 2: Run the board live once**

Run: `python -m scanner.discovery.sweep`
Expected: exit 0; summary line prints scanned/comped/credits; dashboard written to `dashboards/<today>-sealed.html`.

If it golden-fails on `min_rows` (acquisition failure — e.g., public fallbacks blocked AND few seeded ids): that is the canary working. Diagnose via the manifest's `counts` + `sources`, fix (usually: finish Task 6 seeding), and re-run. Do not lower `min_rows` to force a pass.

- [ ] **Step 3: Execute the runbook's spot-check checklist**

Open the dashboard, verify all four checklist items. Record the outcome (pass/fail + the Prismatic comp seen) in the PR/commit message.

- [ ] **Step 4: Full suite green**

Run: `python -m pytest -q`
Expected: 273 passed.

- [ ] **Step 5: Commit**

```bash
git add docs/poke/live-sealed-board.md
git commit -m "docs(poke): live sealed board runbook + recorded spot-check"
```

---

## Spec deviations (deliberate, small)

1. **`no_source` skip-counter (not in spec):** an "ok" comp with neither `sourceUrl` nor `url` cannot satisfy the golden per-row provenance rule, so it is skipped + counted rather than rendered with an empty link or dropped silently. Same doctrine as `no_comp` (never fabricate, demote-never-hide is satisfied by the manifest count).
2. **Est rows carry the fallback's search-page `url` as `source_url`:** the spec's provenance step only names PPT's `sourceUrl`; without this, every fallback row would golden-fail on empty `data-source-url` and the CLI could never ship a board with fallback comps. `verified` still keys strictly off the exact-product `sourceUrl`.
3. **`main()` accepts `cfg=` injection** in addition to the spec's monkeypatched-client idea — same no-network guarantee, less brittle than patching module internals.

## Execution notes

- Tasks 1–5 are pure TDD, no network, no operator input.
- Task 6 requires the operator's PPT API key + live network, and consumes ~72 Free-tier credits; it can run any time after Task 1 (it is data-only) but MUST precede Task 7's live run for a sharp board.
- Task 7's live run consumes ~13-21 credits; keep it on a separate day from Task 6 (or confirm remaining balance ≥ 20).
