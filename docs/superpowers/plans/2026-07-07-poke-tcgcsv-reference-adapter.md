# TCGCSV Reference Adapter Implementation Plan (spec T2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the free TCGCSV TCGplayer-market mirror into the comp engine as a de-risked, **non-independent** reference — lifting sealed comp confidence, providing a free raw reference, retiring set-name matching with an exact `tcgcsv_group_id` field — and attempt to turn the still-false T1 sample-check gate green at n≥5.

**Architecture:** A new adapter module `scanner/poke_api/tcgcsv_source.py` wraps the Plan-1 TCGCSV client (`tcgcsv.py`) as a `CompSourceQuote`-producing source. It fills the dead sealed `tcg` slot in `CompEngine` (confidence lifts: `tcg + pricecharting agree → high`, `resolve()` unchanged) when `poke.tcgcsv` is enabled, and supplies a raw-asset **reference** quote that is recorded external-footing (`source="tcgcsv"`, `low`) but never slotted into the raw independent resolver — so it never lifts raw confidence. `tcgcsv` is registered non-independent everywhere and excluded from both sides of the divergence audit, enforced by two tests. This is Plan 2 of the one-build sequence; the fee model (T4) and credit accounting (T5) are Plan 3.

**Tech Stack:** Python 3, `requests`, `pytest` (network-mocked). No new runtime dependency.

## Global Constraints

- **Package is `scanner/`** (never `target_scanner/`); price subsystem `scanner/poke_api/`.
- **Exact identity only.** Resolve by exact `tcgplayer_id` / exact `tcgcsv_group_id` / exact `subTypeName`; a miss/ambiguity is honest (`no_match`/`None`/`skipped`), NEVER a fuzzy or guessed value.
- **Price accuracy is STOP-class.** No source → no number. `marketPrice` is nullable → null never becomes a fabricated price. Every recorded number carries its source URL + capture date.
- **TCGCSV is a REFERENCE source, NOT independent of PPT** (TCGCSV == TCGplayer market == PPT lineage). Register `tcgcsv` in `_EXTERNAL_SLUGS` (`edge.py` + `divergence.py`); **never** in `_INDEPENDENT_OF_PPT`. A `tcgcsv` comp is **never** `cross_source_validated`, and a recorded `tcgcsv` observation is **never** the independent/"ours" side of the divergence audit (spec §9.4 — two required tests).
- **Sealed confidence = `high` on agreement** (spec §9.2): tcgcsv fills the dead sealed `tcg` slot; `comps/model.py:resolve()` is **unchanged**. Raw/graded = **reference-only** (spec §9.3): tcgcsv never fills the raw independent `tcg` slot, never lifts raw confidence.
- **0 credits, no new dependency.** TCGCSV is free/keyless plain `requests`. Live fetch is operator-gated by the **dedicated `poke.tcgcsv`** flag (default false; `config.yaml` stays false), which gates the whole adapter — fetch AND confidence contribution (soft gate coupling, spec §9.6). No Playwright, no paid client. Every new read path spends **0 PPT credits**.
- **Money-class (Task 6 only).** Recording fresh `ppt_cards` comps for the gate sample bills PPT (`limit=1` mandatory, `market.py`); surface the estimated spend and get operator go-ahead first. Free tier 100 credits/day.
- **TCGCSV etiquette:** custom User-Agent (reuse `independent_sources.UA`, already used by `tcgcsv.py`); ~100ms between requests; once/day data.
- **TDD, full suite green** at each task boundary: `.venv/Scripts/python.exe -m pytest -q` (network-mocked; no live HTTP in tests). Baseline at plan start: **1055 passed**.
- **Local `main`, never pushed** without explicit operator instruction. Work on branch `poke-tcgcsv-reference-adapter`; merge to LOCAL main via finishing-a-development-branch.

## File Structure

- **Create** `scanner/poke_api/tcgcsv_source.py` — `TcgCsvSource` (sealed comp source, `.fetch(product_key, product, checked_at)`) + `raw_reference_quote(asset, checked_at, *, fetch_prices=None)` (raw-asset reference). Both emit `CompSourceQuote(source="tcgcsv")`. Wraps `tcgcsv.py`; honest degrade; 0 credits.
- **Modify** `scanner/comps/engine.py` — `CompEngine.from_config` selects `TcgCsvSource` when `poke.tcgcsv`, else the dead `TcgPlayerSource` (unchanged `__init__` default).
- **Modify** `scanner/comps/model.py` — `_exact_source_url` accepts `source == "tcgcsv"` for STOP-class attribution.
- **Modify** `scanner/poke_api/edge.py` — add `tcgcsv` to `_EXTERNAL_SLUGS` (`:55`).
- **Modify** `scanner/poke_api/divergence.py` — add `tcgcsv` to `_EXTERNAL_SLUGS` (`:36`), introduce `_PPT_SLUGS` for the "theirs" side, split `_latest_market_comp` selection so tcgcsv is excluded from both sides; never add to `_INDEPENDENT_OF_PPT`.
- **Modify** `scanner/poke_api/tcgcsv_check.py` — `build_pairs` resolves the group via the exact `tcgcsv_group_id` catalog field (retires set-name matching there); `resolve_group_id` stays only for the ingest `--group <name>` path.
- **Modify** `scanner/poke_api/tcgcsv_ingest.py` — proposals carry `tcgcsv_group_id`.
- **Modify** `scanner/poke_api/edge_cli.py` — a `tcgcsv-ref` subcommand (record a free raw reference comp), gated on `poke.tcgcsv`.
- **Modify** `data/poke/assets.yaml` — Task 6 operator mapping (exact `tcgplayer_id` + `tcgcsv_group_id`); never auto-written.
- **Tests:** `tests/poke_api/test_tcgcsv_source.py` (new); additions to `tests/poke_api/test_tcgcsv_check.py`, `tests/poke_api/test_tcgcsv_ingest.py`, `tests/test_comps_model.py`, `tests/test_comps_engine.py`, `tests/test_poke_divergence.py`, `tests/test_poke_edge.py`, and `tests/test_poke_asset_comp_record.py`. (Note the split layout: Plan-1 tcgcsv tests live under `tests/poke_api/`; the older poke_api/comps tests are flat under `tests/`.)

---

### Task 1: `TcgCsvSource` adapter + `raw_reference_quote`

The new source that turns a TCGCSV price into a `CompSourceQuote`. Pure-ish: it calls the Plan-1 client and never raises into a caller. `source="tcgcsv"` always. Resolves by exact `tcgplayer_id` (the productId) + exact `tcgcsv_group_id` (the group) + optional exact `subTypeName`; any miss is an honest status, never a guess.

**Files:**
- Create: `scanner/poke_api/tcgcsv_source.py`
- Test: `tests/poke_api/test_tcgcsv_source.py`

**Interfaces:**
- Consumes: `scanner.poke_api.tcgcsv.fetch_prices(group_id)`, `tcgcsv.pick_market_price(product_id, subtype, price_rows)`; `scanner.comps.model.CompSourceQuote` (`source, kind, status, price, url, fetched_at, sample_size=None, detail="", raw_excerpt=""`), `model.SOLD_DERIVED`.
- Produces:
  - `class TcgCsvSource` with `__init__(self, cfg=None, *, fetch_prices=None)` and `fetch(self, product_key: str, product: dict, checked_at: int) -> CompSourceQuote` — sealed signature identical to `comps.tcgplayer.TcgPlayerSource.fetch`. Reads `product["ppt_id"]` (productId) + `product["tcgcsv_group_id"]` (group) + optional `product["tcgcsv_subtype"]`.
  - `raw_reference_quote(asset: dict, checked_at: int, *, fetch_prices=None) -> CompSourceQuote` — asset flavor. Reads `asset["tcgplayer_id"]` + `asset["tcgcsv_group_id"]` + optional `asset["tcgcsv_subtype"]`.
  - Both: no id/group → `skipped`; group fetch empty or price unresolved → `no_match`; success → `ok` with `price`, `url = PRICES_URL.format(group_id)`.
  - `PRICES_URL = "https://tcgcsv.com/tcgplayer/3/{group_id}/prices"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/poke_api/test_tcgcsv_source.py
from scanner.comps.model import SOLD_DERIVED
from scanner.poke_api import tcgcsv_source


_ROWS = [{"productId": 610516, "subTypeName": "Normal", "marketPrice": 1528.09}]


def _fp_ok(_group_id):
    return _ROWS


def _fp_empty(_group_id):
    return []


def test_fetch_ok_builds_tcgcsv_quote():
    src = tcgcsv_source.TcgCsvSource(fetch_prices=_fp_ok)
    product = {"ppt_id": "610516", "tcgcsv_group_id": 23821}
    q = src.fetch("umbreon_box", product, 1_700_000_000)
    assert q.source == "tcgcsv"
    assert q.kind == SOLD_DERIVED
    assert q.status == "ok"
    assert q.price == 1528.09
    assert q.url == "https://tcgcsv.com/tcgplayer/3/23821/prices"


def test_fetch_no_id_is_skipped_zero_network():
    called = {"n": 0}

    def _fp_spy(_g):
        called["n"] += 1
        return _ROWS

    src = tcgcsv_source.TcgCsvSource(fetch_prices=_fp_spy)
    q = src.fetch("x", {"tcgcsv_group_id": 23821}, 1_700_000_000)  # no ppt_id
    assert q.status == "skipped"
    assert q.price is None
    assert called["n"] == 0  # never fetched without an id


def test_fetch_no_group_is_skipped():
    src = tcgcsv_source.TcgCsvSource(fetch_prices=_fp_ok)
    q = src.fetch("x", {"ppt_id": "610516"}, 1_700_000_000)  # no group
    assert q.status == "skipped"
    assert q.price is None


def test_fetch_unresolved_price_is_no_match():
    src = tcgcsv_source.TcgCsvSource(fetch_prices=_fp_empty)
    product = {"ppt_id": "610516", "tcgcsv_group_id": 23821}
    q = src.fetch("x", product, 1_700_000_000)
    assert q.status == "no_match"
    assert q.price is None


def test_fetch_non_numeric_id_is_skipped_never_crashes():
    src = tcgcsv_source.TcgCsvSource(fetch_prices=_fp_ok)
    product = {"ppt_id": "abc", "tcgcsv_group_id": 23821}
    q = src.fetch("x", product, 1_700_000_000)
    assert q.status == "skipped"


def test_raw_reference_quote_ok():
    asset = {"tcgplayer_id": "610516", "tcgcsv_group_id": 23821}
    q = tcgcsv_source.raw_reference_quote(asset, 1_700_000_000, fetch_prices=_fp_ok)
    assert q.source == "tcgcsv"
    assert q.status == "ok"
    assert q.price == 1528.09
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/poke_api/test_tcgcsv_source.py -q`
Expected: FAIL with `ModuleNotFoundError: scanner.poke_api.tcgcsv_source`

- [ ] **Step 3: Implement the adapter**

```python
# scanner/poke_api/tcgcsv_source.py
"""TCGCSV reference adapter — turns the free TCGplayer-market mirror into a CompSourceQuote.

TCGCSV is a REFERENCE source (TCGplayer lineage == PPT), NOT independent of PPT. This
adapter fills the dead SEALED ``tcg`` slot in ``CompEngine`` (its number lifts confidence
via the existing tcg+pc agreement path) and supplies a raw-asset REFERENCE quote that is
recorded external-footing but never slotted into the raw independent resolver (spec §9).
0 PPT credits by construction (never constructs a PPT client). Resolves by EXACT
tcgplayer_id + tcgcsv_group_id + optional exact subTypeName; any miss is an honest status,
never a guess. A source bug never raises into a caller (honest degrade)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from ..comps.model import SOLD_DERIVED, CompSourceQuote
from . import tcgcsv as tcgcsv_mod

PRICES_URL = "https://tcgcsv.com/tcgplayer/3/{group_id}/prices"


def _quote(status: str, price: float | None, url: str, checked_at: int,
           detail: str) -> CompSourceQuote:
    fetched_at = datetime.fromtimestamp(int(checked_at)).isoformat(timespec="seconds")
    return CompSourceQuote("tcgcsv", SOLD_DERIVED, status, price, url, fetched_at,
                           detail=detail)


def _resolve(product_id_raw: Any, group_id_raw: Any, subtype: Any, checked_at: int,
             fetch_prices: Callable[[int], list[dict]]) -> CompSourceQuote:
    """Shared exact-identity resolve for both sealed products and raw assets."""
    product_id_s = str(product_id_raw or "").strip()
    group_id_s = str(group_id_raw or "").strip()
    if not product_id_s or not group_id_s:
        return _quote("skipped", None, "", checked_at,
                      "no tcgplayer_id / tcgcsv_group_id mapped")
    try:
        product_id = int(product_id_s)
        group_id = int(group_id_s)
    except ValueError:
        return _quote("skipped", None, "", checked_at,
                      "non-numeric tcgplayer_id / tcgcsv_group_id")
    url = PRICES_URL.format(group_id=group_id)
    rows = fetch_prices(group_id)  # honest degrade: tcgcsv.fetch_prices returns [] on failure
    subtype_s = str(subtype).strip() if subtype not in (None, "") else None
    price = tcgcsv_mod.pick_market_price(product_id, subtype_s, rows)
    if price is None:
        return _quote("no_match", None, url, checked_at,
                      "no clean TCGCSV market price (missing/ambiguous/null)")
    return _quote("ok", price, url, checked_at, "TCGCSV TCGplayer market (reference)")


class TcgCsvSource:
    """Sealed CompEngine ``tcg`` slot (mirrors ``comps.tcgplayer.TcgPlayerSource``)."""

    def __init__(self, cfg: Any = None, *, fetch_prices: Callable[[int], list[dict]] | None = None) -> None:
        self._fetch_prices = fetch_prices or tcgcsv_mod.fetch_prices

    def fetch(self, product_key: str, product: dict, checked_at: int) -> CompSourceQuote:
        return _resolve(product.get("ppt_id"), product.get("tcgcsv_group_id"),
                        product.get("tcgcsv_subtype"), checked_at, self._fetch_prices)


def raw_reference_quote(asset: dict, checked_at: int, *,
                        fetch_prices: Callable[[int], list[dict]] | None = None) -> CompSourceQuote:
    """Free raw-asset TCGplayer-market REFERENCE (0 credits). Recorded external-footing;
    never fills the raw independent ``tcg`` slot (spec §9.3)."""
    fp = fetch_prices or tcgcsv_mod.fetch_prices
    return _resolve(asset.get("tcgplayer_id"), asset.get("tcgcsv_group_id"),
                    asset.get("tcgcsv_subtype"), checked_at, fp)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/poke_api/test_tcgcsv_source.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (all green; +6)

- [ ] **Step 6: Commit**

```bash
git add scanner/poke_api/tcgcsv_source.py tests/poke_api/test_tcgcsv_source.py
git commit -m "feat(poke): TCGCSV reference adapter (source=tcgcsv, exact id+group, honest degrade, 0 credits)"
```

---

### Task 2: `tcgcsv_group_id` catalog field — retire set-name matching in the gate

Adds the exact `tcgcsv_group_id` field to the pipeline: `build_pairs` (the gate) resolves the group by the exact field instead of set-name matching, and `propose_mappings` (ingest) surfaces the `tcgcsv_group_id` alongside the `tcgplayer_id` so the operator can map both at once. `resolve_group_id` (set-name) stays **only** for the ingest `--group <name>` operator-typed path.

**Files:**
- Modify: `scanner/poke_api/tcgcsv_check.py` (`build_pairs`)
- Modify: `scanner/poke_api/tcgcsv_ingest.py` (`propose_mappings`)
- Test: `tests/poke_api/test_tcgcsv_check.py`, `tests/poke_api/test_tcgcsv_ingest.py`

**Interfaces:**
- `build_pairs(assets, observations, groups, fetch_prices=None)` — unchanged signature; internally resolves the group as `int(asset["tcgcsv_group_id"])` (exact), and honest-skips `{"asset_key", "reason": "no tcgcsv_group_id mapped"}` when absent/non-numeric. No longer calls `resolve_group_id` for asset→group.
- `propose_mappings(products, assets, *, group_id=None)` — each `"exact"` proposal dict additionally carries `"tcgcsv_group_id": group_id`.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/poke_api/test_tcgcsv_check.py
from scanner.poke_api import tcgcsv_check
from scanner.poke_api import history as history_mod


def _obs_ppt(asset, price, date="2026-07-07"):
    # An observation carries a precomputed "item_key" STRING (item_key_for_asset returns a
    # str, not a dict) — matches how every existing test in the suite builds observations.
    return {"item_key": history_mod.item_key_for_asset(asset), "kind": history_mod.MARKET_COMP,
            "source": "ppt_cards", "comp": price, "capture_date": date}


def test_build_pairs_uses_exact_group_id_field(monkeypatch):
    asset = {"asset_class": "raw", "name": "Umbreon ex 161", "set": "Prismatic Evolutions",
             "card_number": "161", "tcgplayer_id": "610516", "tcgcsv_group_id": 23821}
    assets = {"umbreon_ex_161_raw_nm": asset}
    obs = [_obs_ppt(asset, 1528.09)]

    seen = {}

    def _fp(group_id):
        seen["group_id"] = group_id
        return [{"productId": 610516, "subTypeName": "Normal", "marketPrice": 1528.09}]

    # groups list is now irrelevant to asset->group resolution; pass empty to prove it.
    pairs, skipped = tcgcsv_check.build_pairs(assets, obs, [], fetch_prices=_fp)
    assert seen["group_id"] == 23821       # resolved from the field, not name-matching
    assert len(pairs) == 1
    assert pairs[0]["tcgplayer_id"] == "610516"


def test_build_pairs_skips_when_no_group_id_field():
    asset = {"asset_class": "raw", "name": "Umbreon ex 161", "set": "Prismatic Evolutions",
             "tcgplayer_id": "610516"}  # no tcgcsv_group_id
    assets = {"umbreon_ex_161_raw_nm": asset}
    obs = [_obs_ppt(asset, 1528.09)]
    pairs, skipped = tcgcsv_check.build_pairs(assets, obs, [], fetch_prices=lambda g: [])
    assert pairs == []
    assert any("tcgcsv_group_id" in s["reason"] for s in skipped)
```

```python
# add to tests/poke_api/test_tcgcsv_ingest.py
from scanner.poke_api import tcgcsv_ingest


def test_proposal_carries_group_id():
    products = [{"productId": 111, "name": "Umbreon ex",
                 "extendedData": [{"name": "Number", "value": "161/131"}]}]
    assets = [{"asset_key": "umbreon_ex_161", "name": "Umbreon ex", "card_number": "161/131"}]
    out = tcgcsv_ingest.propose_mappings(products, assets, group_id=23821)
    assert out[0]["match"] == "exact"
    assert out[0]["tcgcsv_group_id"] == 23821
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/poke_api/test_tcgcsv_check.py tests/poke_api/test_tcgcsv_ingest.py -q`
Expected: FAIL (build_pairs still name-matches / TypeError on `group_id=` kwarg).

- [ ] **Step 3: Edit `build_pairs` to resolve by the exact field**

In `scanner/poke_api/tcgcsv_check.py` `build_pairs`, **replace** the group-resolution block (current lines 119–123, the `group_id = resolve_group_id(asset.get("set", ""), groups)` stanza) with:

```python
        raw_group_id = str(asset.get("tcgcsv_group_id") or "").strip()
        if not raw_group_id:
            skipped.append({"asset_key": asset_key,
                            "reason": "no tcgcsv_group_id mapped (exact-id only; set-name "
                                      "matching retired)"})
            continue
        try:
            group_id = int(raw_group_id)
        except ValueError:
            skipped.append({"asset_key": asset_key, "reason": "non-numeric tcgcsv_group_id"})
            continue
```

The `groups` parameter is now unused by `build_pairs`; leave it in the signature (the CLI still passes it, and the ingest path uses `resolve_group_id`) — add a one-line comment `# groups no longer used for asset->group (exact tcgcsv_group_id); kept for signature stability`.

- [ ] **Step 4: Edit `propose_mappings` to carry the group id**

In `scanner/poke_api/tcgcsv_ingest.py`, change the signature to `def propose_mappings(products, assets, *, group_id=None):` and add `"tcgcsv_group_id": group_id` to the **exact** proposal dict (leave the `"none"` branch unchanged).

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/poke_api/test_tcgcsv_check.py tests/poke_api/test_tcgcsv_ingest.py -q`
Expected: PASS

- [ ] **Step 6: Update the ingest CLI call site + full suite**

In `scanner/poke_api/edge_cli.py` `_cmd_tcgcsv_ingest` (around line 891), pass the resolved `group_id` into `propose_mappings(..., group_id=group_id)` so proposals include it. Read the exact call at execution and thread the kwarg.

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (all green)

- [ ] **Step 7: Commit**

```bash
git add scanner/poke_api/tcgcsv_check.py scanner/poke_api/tcgcsv_ingest.py scanner/poke_api/edge_cli.py tests/poke_api/test_tcgcsv_check.py tests/poke_api/test_tcgcsv_ingest.py
git commit -m "feat(poke): exact tcgcsv_group_id field retires set-name matching in the gate; ingest proposes it"
```

---

### Task 3: Sealed CompEngine wiring (`high` on tcgcsv + pricecharting)

Fill the dead sealed `tcg` slot with `TcgCsvSource` when `poke.tcgcsv` is on — `resolve()` is untouched, so its existing `tcg + pc agree → high` precedence applies. Extend `_exact_source_url` to attribute a `tcgcsv` quote.

**Files:**
- Modify: `scanner/comps/engine.py` (`from_config`)
- Modify: `scanner/comps/model.py` (`_exact_source_url`, `:146-155`)
- Test: `tests/test_comps_engine.py` + `tests/test_comps_model.py` (flat `tests/` layout — verified; `tests/test_comps_model.py` already has a `resolve()` helper at `:20`)

**Interfaces:**
- Consumes: `scanner.poke_api.tcgcsv.tcgcsv_enabled(cfg)`, `scanner.poke_api.tcgcsv_source.TcgCsvSource`.
- Produces: no new public API; `CompEngine.from_config(cfg)` returns an engine whose `.tcg` is a `TcgCsvSource` iff `tcgcsv_enabled(cfg)` else `TcgPlayerSource`.

- [ ] **Step 1: Write the failing test — `_exact_source_url` accepts tcgcsv**

```python
# add to tests/test_comps_model.py  (uses CompSourceQuote, NormalizedComp, _exact_source_url, SOLD_DERIVED)
from scanner.comps import model as m


def test_exact_source_url_accepts_tcgcsv():
    q = m.CompSourceQuote("tcgcsv", m.SOLD_DERIVED, "ok", 1528.09,
                          "https://tcgcsv.com/tcgplayer/3/23821/prices", "2026-07-07T00:00:00")
    n = m.NormalizedComp(item_key="k", comp=1528.09, comp_basis="b", confidence="high",
                         confidence_reason="r", sources=(q,), ebay_floor=None,
                         ebay_active_count=None, spread_pct=None, captured_at="2026-07-07")
    assert m._exact_source_url(n) == "https://tcgcsv.com/tcgplayer/3/23821/prices"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_model.py -q -k exact_source_url_accepts_tcgcsv`
Expected: FAIL (returns `""` — tcgcsv not matched).

- [ ] **Step 3: Edit `_exact_source_url`**

In `scanner/comps/model.py`, in `_exact_source_url` (`:146-155`), after the `tcgplayer` branch add a `tcgcsv` branch (its URL is the group prices endpoint, honest attribution of where we read the number):

```python
        if quote.source in ("tcgplayer", "tcgcsv") and quote.url:
            return quote.url                       # product page (tcgplayer) / prices endpoint (tcgcsv)
```

(Replace the existing single-source `tcgplayer` line with the tuple form above; leave the `pricecharting` branch unchanged.)

- [ ] **Step 4: Write the failing test — sealed selects tcgcsv by flag + reaches high**

```python
# add to tests/test_comps_engine.py
from scanner import config as cfg_mod
from scanner.comps.engine import CompEngine
from scanner.comps.tcgplayer import TcgPlayerSource
from scanner.poke_api.tcgcsv_source import TcgCsvSource


def _cfg(tcgcsv_on):
    # a real Config (from_mapping supplies every fee/ebay/comps default) so from_config's
    # pc/ebay source construction never trips on a missing field. Same builder the divergence
    # + comps tests use. `locations` is the only required key.
    return cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"},
                                 "poke": {"tcgcsv": tcgcsv_on}})


def test_from_config_uses_tcgcsv_when_enabled():
    assert isinstance(CompEngine.from_config(_cfg(True)).tcg, TcgCsvSource)


def test_from_config_uses_dead_tcgplayer_when_disabled():
    assert isinstance(CompEngine.from_config(_cfg(False)).tcg, TcgPlayerSource)
```

- [ ] **Step 5: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_engine.py -q -k from_config_uses`
Expected: FAIL (both return `TcgPlayerSource`).

- [ ] **Step 6: Edit `CompEngine.from_config`**

In `scanner/comps/engine.py`, replace `from_config` (`:48-50`) — import **lazily inside the method** (comps is a lower-level package than poke_api; a top-level `comps → poke_api` import risks a cycle, so keep it local and cycle-proof):

```python
    @classmethod
    def from_config(cls, cfg: Any) -> "CompEngine":
        # Sealed tcg slot: the free TCGCSV mirror when poke.tcgcsv is on (spec §9.2 — its
        # number lifts confidence via the unchanged tcg+pc agreement path); else the dead
        # TcgPlayerSource. TCGCSV stays NON-independent (edge/divergence classification).
        # Lazy import: comps must not import poke_api at module load (cycle-proofing).
        from ..poke_api import tcgcsv as _tcgcsv
        from ..poke_api.tcgcsv_source import TcgCsvSource
        tcg = TcgCsvSource(cfg) if _tcgcsv.tcgcsv_enabled(cfg) else None
        return cls(cfg, tcg_source=tcg)
```

(Leave `__init__`'s `self.tcg = tcg_source or TcgPlayerSource(cfg)` as-is — a `None` still falls back to the dead source when the flag is off.) Verify `python -c "import scanner.comps.engine"` succeeds after the edit.

- [ ] **Step 7: Run the tests + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_engine.py tests/test_comps_model.py -q` then `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (all green). Note: a live sealed comp reaching `high` on `tcgcsv + pricecharting` agreement is covered by `resolve()`'s existing two-source test; the confidence math is unchanged, so no new resolve() test is required.

- [ ] **Step 8: Commit**

```bash
git add scanner/comps/engine.py scanner/comps/model.py tests/test_comps_engine.py tests/test_comps_model.py
git commit -m "feat(poke): sealed CompEngine uses TCGCSV tcg slot under poke.tcgcsv (high on tcgcsv+pc); attribute tcgcsv url"
```

---

### Task 4: Independence classification + the two required guards

Register `tcgcsv` as external-footing and enforce that it is **never** independent: never `cross_source_validated`, and never selected as the independent/"ours" side of the divergence matrix — while `ppt_cards` stays the canonical "theirs" reference.

**Files:**
- Modify: `scanner/poke_api/edge.py` (`_EXTERNAL_SLUGS`, `:55`)
- Modify: `scanner/poke_api/divergence.py` (`_EXTERNAL_SLUGS` `:36`, add `_PPT_SLUGS`, `_latest_market_comp` `:107-116`)
- Test: `tests/test_poke_divergence.py`, `tests/test_poke_edge.py` (flat `tests/` layout — verified; `test_poke_divergence.py` already imports `dv`, `history`, `router`, `cfg_mod` and defines `_NoProvider`/`_FailingClient` — reuse them)

**Interfaces:**
- `divergence._EXTERNAL_SLUGS = frozenset({"ppt_cards", "tcgcsv"})` — the non-independent-of-PPT set (excluded from the "ours"/independent side).
- `divergence._PPT_SLUGS = frozenset({"ppt_cards"})` — the canonical audited PPT number (the "theirs" side).
- `divergence._INDEPENDENT_OF_PPT` — unchanged `frozenset({"pricecharting"})`.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_poke_divergence.py — reuses the file's existing imports
# (dv, history, router, cfg_mod) and helpers (_NoProvider, _FailingClient).
_RAW = {"asset_class": "raw", "name": "Umbreon ex 161", "set": "Prismatic Evolutions",
        "card_number": "161", "condition": "NM"}
_IK_RAW = history.item_key_for_asset(_RAW)


def _mc(source, price, date, conf="low"):
    # observation shape used throughout the suite: an explicit "item_key" STRING field.
    return {"item_key": _IK_RAW, "kind": "market_comp", "comp": price,
            "capture_date": date, "source": source, "comp_confidence": conf}


def _deps_raw(obs):
    cfg = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    return router.PokeApiDeps(products={}, assets={"umbreon_raw": _RAW},
                             read_observations=lambda: list(obs), comp_provider=_NoProvider(),
                             today="2026-07-07", cfg=cfg, card_client=_FailingClient())


def test_tcgcsv_agreeing_with_ppt_is_never_cross_source_validated():
    # tcgcsv agreeing to the cent with ppt_cards must NOT be cross-source-validated
    # (contrast: the existing pricecharting+ppt test yields cross=True). NOTE: cross keys on
    # _INDEPENDENT_OF_PPT membership, so this holds by construction — the SUBSTANTIVE
    # exclusion guard is the matrix test below; the extra `ours_source` assert makes this
    # one also fail if tcgcsv is ever wrongly picked as the local/"ours" side.
    obs = [_mc("tcgcsv", 1528.09, "2026-07-07"), _mc("ppt_cards", 1528.09, "2026-07-07")]
    row = dv.audit_local(_deps_raw(obs), asset_keys=["umbreon_raw"])["rows"][0]
    assert row["cross_source_validated"] is False
    assert row["ours_source"] != "tcgcsv"          # tcgcsv is never the local/independent side


def test_recorded_tcgcsv_is_never_the_independent_ours_side_of_the_matrix():
    # a MORE-RECENT tcgcsv comp must not shadow the independent pricecharting comp as "ours".
    obs = [_mc("pricecharting", 1500.00, "2026-07-05"),
           _mc("tcgcsv", 1528.09, "2026-07-07"),
           _mc("ppt_cards", 1528.09, "2026-07-07")]
    row = dv.audit_matrix(_deps_raw(obs), asset_keys=["umbreon_raw"])["rows"][0]
    assert row["ours_source"] == "pricecharting"           # tcgcsv excluded from the independent side
```

```python
# add to tests/test_poke_edge.py
from scanner.poke_api import edge as edge_mod


def test_tcgcsv_slug_is_external_footing_not_local():
    assert "tcgcsv" in edge_mod._EXTERNAL_SLUGS
    assert "tcgcsv" not in edge_mod._LOCAL_SLUGS
    # a tcgcsv + ppt_cards comp is external_only, never local_plus_external_audit
    comp = {"estimate": 1528.09,
            "sources": [{"source": "tcgcsv"}, {"source": "ppt_cards"}]}
    assert "external_only" in edge_mod.source_posture(comp)
    assert "local_plus_external_audit" not in edge_mod.source_posture(comp)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_divergence.py tests/test_poke_edge.py -q -k tcgcsv`
Expected: FAIL (tcgcsv currently unclassified: treated as local/independent).

- [ ] **Step 3: Edit `edge.py`**

In `scanner/poke_api/edge.py:55`, add `tcgcsv` to the external set (leave `_LOCAL_SLUGS` alone — add a one-line comment that legacy `tcgplayer` remains in `_LOCAL_SLUGS`, same lineage but inert since that source is dead-blocked):

```python
_EXTERNAL_SLUGS = frozenset({"ppt_cards", "tcgcsv"})
# NOTE: legacy "tcgplayer" stays in _LOCAL_SLUGS below — same lineage as tcgcsv but inert
# (that source is always-blocked/dead). tcgcsv is the live external-footing reference.
```

- [ ] **Step 4: Edit `divergence.py`**

In `scanner/poke_api/divergence.py`:

(a) Replace the slug sets (`:36-40`):

```python
_EXTERNAL_SLUGS = frozenset({"ppt_cards", "tcgcsv"})   # non-independent-of-PPT; never the "ours" side
_PPT_SLUGS = frozenset({"ppt_cards"})                  # the canonical audited PPT number (the "theirs" side)
# Sources genuinely INDEPENDENT of the PPT market number for cross-source validation.
# TCGplayer/TCGCSV are excluded: they mirror the PPT number (Phase F finding), so agreement
# with PPT is NOT independent corroboration.
_INDEPENDENT_OF_PPT = frozenset({"pricecharting"})
```

(b) Update `_latest_market_comp` (`:107-116`) so `external=True` selects **only** `_PPT_SLUGS` (theirs) and `external=False` skips the whole `_EXTERNAL_SLUGS` (ours = neither ppt nor tcgcsv):

```python
def _latest_market_comp(observations, item_key, *, external: bool):
    best = None
    for o in history_mod.filter_observations(observations, item_key=item_key,
                                             kind=history_mod.MARKET_COMP):
        src = history_mod.source_of(o)
        if external:
            if src not in _PPT_SLUGS:      # "theirs" is strictly the PPT number
                continue
        elif src in _EXTERNAL_SLUGS:       # "ours" excludes ppt_cards AND tcgcsv (non-independent)
            continue
        if best is None or str(o.get("capture_date") or "") >= str(best.get("capture_date") or ""):
            best = o
    return best
```

`_latest_independent_comp` (`:200-211`) already excludes `_EXTERNAL_SLUGS` — now widened to include tcgcsv — so the matrix "ours" side auto-excludes tcgcsv with no further change. `audit_local`'s `cross` guard (`:175`) already keys on `_INDEPENDENT_OF_PPT`, so tcgcsv → `cross=False`.

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_divergence.py tests/test_poke_edge.py -q`
Expected: PASS

- [ ] **Step 6: Full suite (guard against divergence regressions)**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (all green). If any existing divergence test asserted a tcgcsv-agnostic "theirs" selection, reconcile: `ppt_cards` remains the sole "theirs" — behavior for the existing `{ppt_cards}`-only ledgers is unchanged.

- [ ] **Step 7: Commit**

```bash
git add scanner/poke_api/edge.py scanner/poke_api/divergence.py tests/test_poke_divergence.py tests/test_poke_edge.py
git commit -m "feat(poke): classify tcgcsv external/non-independent; never cross-validated, never the independent side (2 guards)"
```

---

### Task 5: Raw-asset reference — never-displace serving rule + recording CLI

Two parts: (A) the asset serving read never lets a free `tcgcsv` reference displace an independent/paid comp as the DISPLAYED headline (operator decision 2026-07-07 — spec §9.3); (B) a `tcgcsv-ref` CLI that records the free TCGplayer-market reference for a mapped raw asset as an external-footing `market_comp` at `low` confidence. The reference never lifts live confidence (external + single-source → gated out of `live_min_confidence`), Task 4's guards keep it out of cross-validation, and Part A keeps it from overwriting a PriceCharting/ppt_cards number as the served comp.

**Files:**
- Modify: `scanner/poke_api/lab.py` (`resolve_asset_comp_row`, `:60-68`) — never-displace serving rule
- Modify: `scanner/poke_api/edge_cli.py` (new `tcgcsv-ref` subcommand + dispatch, alongside `record-asset-comp` at `:526`)
- Test: `tests/test_poke_asset_api.py` (serving read-back) + `tests/test_poke_asset_comp_record.py` (the record-asset-comp test file — same recording precedent + a ledger read-back helper), or the tcgcsv CLI test file where Plan-1's `tcgcsv-check` refuse test lives — match whichever the executor finds.

**Interfaces:**
- Serving (Part A): `resolve_asset_comp_row(observations, asset_key, asset)` prefers the latest **non-`tcgcsv`** `market_comp`; only when every comp for the item is `tcgcsv` does it serve the tcgcsv reference. No signature change; behavior is identical for any ledger with no tcgcsv comp (no regression).
- Recording (Part B): consumes `tcgcsv_source.raw_reference_quote(asset, checked_at)` (Task 1); `tcgcsv.tcgcsv_enabled(cfg)`; the **existing** writer `sources.record_asset_comp(ledger_path, asset, *, comp, confidence, source, ...)` (`sources.py:273`, which `record-asset-comp` already uses) / `sources.build_asset_comp_observation` (`sources.py:238`) — do NOT hand-roll the observation. On `status=="ok"`, records one `market_comp` (`comp=<price>, confidence="low", source="tcgcsv", source_url=<prices endpoint>`); refuses (0 network) when `poke.tcgcsv` is false or the asset lacks `tcgplayer_id`/`tcgcsv_group_id`; non-ok status records nothing and prints the honest reason.

- [ ] **Step 1: Write the failing test — never-displace serving rule**

```python
# add to tests/test_poke_asset_api.py (or wherever resolve_asset_comp_row is unit-tested)
from scanner.poke_api import lab as lab_mod, history as history_mod

_RAW5 = {"asset_class": "raw", "name": "Umbreon ex 161", "set": "Prismatic Evolutions",
         "card_number": "161", "condition": "NM"}
_IK5 = history_mod.item_key_for_asset(_RAW5)


def _mc5(source, price, date):
    return {"item_key": _IK5, "kind": "market_comp", "comp": price, "capture_date": date,
            "source": source, "comp_confidence": "low"}


def test_tcgcsv_reference_never_displaces_independent_comp_as_headline():
    # newer tcgcsv reference must NOT become the served comp over an older pricecharting comp
    obs = [_mc5("pricecharting", 1500.0, "2026-07-05"), _mc5("tcgcsv", 1528.09, "2026-07-07")]
    row = lab_mod.resolve_asset_comp_row(obs, "umbreon_raw", _RAW5)
    assert row is not None
    assert "1,500" in str(row["estimate"]) or row.get("sourceUrl", "").find("pricecharting") >= 0


def test_tcgcsv_reference_served_when_it_is_the_only_comp():
    obs = [_mc5("tcgcsv", 1528.09, "2026-07-07")]
    row = lab_mod.resolve_asset_comp_row(obs, "umbreon_raw", _RAW5)
    assert row is not None                      # the sole number IS served (free reference value)
```

- [ ] **Step 2: Run to verify it fails, then implement the never-displace rule**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_asset_api.py -q -k never_displaces` (Expected: FAIL — latest-wins currently serves the tcgcsv comp).

In `scanner/poke_api/lab.py`, edit `resolve_asset_comp_row` (`:60-68`) to prefer a non-tcgcsv comp:

```python
def resolve_asset_comp_row(observations, asset_key, asset):
    """Read-first asset comp resolution (offline). A free tcgcsv REFERENCE never displaces
    an independent/paid comp as the served headline (spec §9.3): serve the latest non-tcgcsv
    market_comp when one exists, else fall back to the latest tcgcsv (reference is the sole
    number). Never constructs a network source."""
    ikey = history_mod.item_key_for_asset(asset)
    non_ref = [o for o in history_mod.filter_observations(
        observations, item_key=ikey, kind=history_mod.MARKET_COMP)
        if history_mod.source_of(o) != "tcgcsv"]
    latest = (history_mod.latest(non_ref, ikey) if non_ref
              else history_mod.latest(observations, ikey))
    return _ledger_comp_row(latest, asset_key, asset) if latest is not None else None
```

Re-run: PASS. (For a ledger with no tcgcsv comp, `non_ref` == all comps → identical to today; no regression.)

- [ ] **Step 3: Write the failing test — CLI refuses when gate off; records at low when on**

```python
# add to the tcgcsv CLI test file
def test_tcgcsv_ref_refuses_when_gate_off(capsys, monkeypatch):
    from scanner.poke_api import edge_cli, tcgcsv_source
    # deps/cfg with poke.tcgcsv=False; assert nonzero rc and no fetch attempted
    def _boom(*a, **k):
        raise AssertionError("must not fetch when gate off")
    monkeypatch.setattr(tcgcsv_source, "raw_reference_quote", _boom)
    # ...build args (asset key) + deps with tcgcsv=False; call the dispatch; assert rc != 0
    ...


def test_tcgcsv_ref_records_low_confidence_tcgcsv_observation():
    # deps with tcgcsv=True + one mapped raw asset; patch raw_reference_quote -> ok quote;
    # call the command; read back the ledger; assert the appended row has
    # source=="tcgcsv" and comp_confidence=="low" and the price, 0 credits.
    ...
```

*(This task follows the Plan-1 CLI-wiring convention: the pure logic it calls — `raw_reference_quote` (Task 1), the ledger writer, `item_key_for_asset` — is already coded/tested; the exact argparser + dispatch + ledger-writer call must be read from the current `edge_cli.py` at execution and extended faithfully, since it is operator-facing CLI. The two tests above are the required, unambiguous target.)*

- [ ] **Step 4: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -q -k tcgcsv_ref`
Expected: FAIL (no `tcgcsv-ref` command).

- [ ] **Step 5: Wire the `tcgcsv-ref` subcommand**

Read the current `edge_cli.py` argparser block (`:212-225`, where `tcgcsv-check`/`tcgcsv-ingest` are added) and the dispatch (`:928-931`), and the existing `record-asset-comp` recording path to reuse its ledger writer. Add `tcgcsv-ref --asset <asset_key>` that: (a) refuses unless `tcgcsv.tcgcsv_enabled(deps.cfg)` (mirror `_cmd_tcgcsv_check`, `:787-789`); (b) looks up the asset in `deps.assets`, honest-errors if unmapped; (c) calls `tcgcsv_source.raw_reference_quote(asset, _today_ts(deps.today))`; (d) on `status=="ok"` appends a `market_comp` observation (`source="tcgcsv"`, `comp_confidence="low"`, the quote's price + url, identity via `history.item_key_for_asset(asset)`, `capture_date=deps.today`); on any non-ok status prints the honest reason and records nothing; (e) prints the recorded reference. Add the dispatch line `if args.cmd == "tcgcsv-ref": return _cmd_tcgcsv_ref(args, deps)`.

- [ ] **Step 6: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -q -k tcgcsv_ref`
Expected: PASS

- [ ] **Step 7: Full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (all green)

- [ ] **Step 8: Commit**

```bash
git add scanner/poke_api/lab.py scanner/poke_api/edge_cli.py tests/test_poke_asset_api.py tests/test_poke_asset_comp_record.py
git commit -m "feat(poke): tcgcsv reference — never-displace serving rule + tcgcsv-ref recording CLI (low, 0 credits)"
```

---

### Task 6: T1 gate-pass mapping workstream (operator-gated, money-class)

Attempt to turn the still-false T1 gate green at n≥5 by mapping more raw singles and recording fresh `ppt_cards` comps — **honestly**. This task is a guarded operator procedure, not TDD code: it edits `assets.yaml` (operator review) and spends PPT credits (operator go-ahead). If the gate FAILS at n≥5, that is a documented, first-class outcome — nothing is tuned to force a pass, and `poke.tcgcsv` stays false (T2 ships dormant).

**Files:**
- Modify: `data/poke/assets.yaml` (operator-reviewed mappings; never auto-written)
- Create (generated): `docs/poke/tcgcsv-sample-check-<date>.md` (the committed result doc)

**Preconditions (STOP/money-class):**
- `poke.tcgcsv: true` set **locally** (config.yaml stays false in the repo).
- Operator go-ahead for the PPT spend (est. **~4–5 credits**, `limit=1`, free tier 100/day).

- [ ] **Step 1: Discover candidate mappings (0 credits).** For each target raw single (prefer **NM** raws: the F.1 `charizard_ex_199_151_raw_nm`, `pikachu_ex_238_ss_raw_nm`, plus ~1–2 new NM raws in a TCGCSV-present set; **avoid** the `sylveon_ex_156_raw_lp` LP card so no condition-agnostic market number is recorded against an LP asset), run:

```
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli tcgcsv-ingest --group "<set name or numeric groupId>"
```

Review `data/poke/tcgcsv-proposals-<group>.json`. Accept **only** `"match": "exact"` proposals.

- [ ] **Step 2: Operator writes the mappings.** For each accepted proposal, add `tcgplayer_id: "<productId>"` **and** `tcgcsv_group_id: <groupId>` to that asset in `data/poke/assets.yaml`. Also backfill `tcgcsv_group_id` for the already-mapped `umbreon_ex_161_raw_nm` (its group). **Never** auto-write; the operator confirms each row.

- [ ] **Step 3: Record fresh `ppt_cards` raw comps (money-class).** Surface the estimated spend (~1 credit/raw asset, `limit=1` pinned — `market.py`), get operator go-ahead, then for each newly-mapped raw asset record its `ppt_cards` market comp via the existing paid PPT path (the asset `refresh=true` resolve that persists through the `record_asset_comp` writer, or a manual `record-asset-comp --comp <captured> --source ppt_cards` if the number was already captured). Confirm the exact command against the current `edge_cli.py`/router at execution. Target: ≥5 raw assets each holding both a `tcgplayer_id` + `tcgcsv_group_id` mapping AND a fresh `ppt_cards` comp.

- [ ] **Step 4: Run the gate (0 credits).**

```
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli tcgcsv-check
```

This reads the held `ppt_cards` comps and diffs them against a live TCGCSV fetch (0 PPT credits), writing `docs/poke/tcgcsv-sample-check-<date>.md`.

- [ ] **Step 5: Record the honest verdict.**
  - **PASS (n≥5, every pair ≤2%):** commit the result doc; the operator may keep `poke.tcgcsv: true` locally (T2 is now earned/live). Note the PASS in `.superpowers/sdd/progress.md`.
  - **FAIL (n<5 or any pair >2%):** commit the result doc as-is (the fail is the finding); set `poke.tcgcsv: false` locally (T2 ships dormant, identical to gated-off). Do **not** adjust tolerances, cherry-pick pairs, or otherwise tune toward a pass.

- [ ] **Step 6: Commit the result doc + mappings**

```bash
git add data/poke/assets.yaml docs/poke/tcgcsv-sample-check-*.md
git commit -m "chore(poke): T1 gate sample at n>=5 — <PASS|FAIL>; map raw tcgplayer_id + tcgcsv_group_id"
```

---

## Self-Review

**Spec coverage (this plan = spec T2 + spec §9 + the §9.1 gate-pass workstream):**
- T2 reference adapter (`fetch → CompSourceQuote`, exact id, honest degrade, 0 credits) → Task 1 ✓
- §9.2 sealed `high` (fill dead tcg slot, `resolve()` unchanged, attribute tcgcsv url) → Task 3 ✓
- §9.3 raw/graded reference-only (never fills the independent slot; recorded external-footing low; and — operator decision 2026-07-07 — never displaces an independent/paid comp as the served headline) → Tasks 1 (`raw_reference_quote`) + 5 (never-displace serving rule + recording CLI) ✓
- §9.4 independence (tcgcsv → `_EXTERNAL_SLUGS` both files, never `_INDEPENDENT_OF_PPT`, excluded both audit sides) + the **two required tests** → Task 4 ✓
- §9.5 `tcgcsv_group_id` field retires set-name matching in the gate; ingest proposes it → Task 2 ✓
- §9.6 soft gate coupling via `poke.tcgcsv` (config.yaml stays false; fetch + confidence both gated) → Tasks 1/3 (adapter+from_config both gate on `tcgcsv_enabled`) ✓
- §9.1 build T2 now + attempt to pass T1 (honest, money-class, ships dormant on fail) → Task 6 ✓
- Graded: unaffected (TCGCSV has no graded number) — no task, correctly ✓.

**Placeholder scan:** Tasks 1–4 carry full test + implementation code. Tasks 5 (CLI wiring) and 6 (operator/money-class procedure) intentionally give exact anchors + required tests + guardrails instead of reproducing the money-class CLI argparser and the operator's manual `assets.yaml`/PPT steps — mirroring Plan 1's documented convention (the pure logic they call is fully coded/tested in Tasks 1–4). No `TBD`/`TODO`/"add error handling" placeholders.

**Type consistency:** `CompSourceQuote(source, kind, status, price, url, fetched_at, ...)` used identically in Task 1 and Task 3's test. `TcgCsvSource.fetch(product_key, product, checked_at)` matches the `CompEngine._safe_quote` call contract (`comps.tcgplayer.TcgPlayerSource.fetch`). `raw_reference_quote(asset, checked_at, *, fetch_prices=None)` consistent across Tasks 1 and 5. `build_pairs(assets, observations, groups, fetch_prices=None)` signature unchanged (Task 2). `propose_mappings(products, assets, *, group_id=None)` consistent between Task 2's edit, test, and the edge_cli call site. Divergence sets (`_EXTERNAL_SLUGS`/`_PPT_SLUGS`/`_INDEPENDENT_OF_PPT`) named consistently across Task 4's edits and tests. `tcgcsv.tcgcsv_enabled(cfg)` (Plan-1, verified present) is the single gate reader.

**Deferred to Plan 3 (deliberately):** T4 honest fee model + T5 sealed credit accounting — independent subsystems; their surfaces are already mapped. Not a gap — the operator-approved split.
