# Phase F — Independent Singles/Slabs Sold-Source Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a genuinely non-PPT, sold-derived comp for raw/graded assets (PriceCharting via plain requests, TCGplayer via rendered) persisted into the same asset ledger, so `divergence-audit --local` becomes a true independent cross-source validation.

**Architecture:** New `scanner/poke_api/independent_sources.py` holds a shared PriceCharting detail-page parser plus three `fetch(asset, checked_at) -> CompSourceQuote` adapters that slot into the existing `resolve_raw_comp`/`resolve_graded_comp` `pc_source`/`tcg_source` parameters (currently wired to `None`). The in-house confidence ladder (`comps.model.resolve`) still produces the number; the graded PriceCharting branch is locked to `low`. A new operator-run CLI path `record-asset-comp --refresh-independent` persists the number at 0 PPT credits; the local divergence audit surfaces `ours_source` and flags cross-source agreement. PPT stays audit-only.

**Tech Stack:** Python 3.12, `requests` (plain), `pytest` (network-mocked), optional `playwright` (conditional, non-blocking).

**Spec:** `docs/superpowers/specs/2026-07-05-phase-f-independent-sold-source-validation-design.md`

## Global Constraints

- **Price accuracy is STOP-class:** no source → no number; exact-id only (never fuzzy); every persisted price carries source URL + capture date + basis; an active ask is context, never a comp.
- **0 PPT credits on the independent path:** the PriceCharting/TCGplayer adapters never call PPT. Only the pre-existing `--refresh` (PPT) and external divergence mode spend credits, and they are unchanged.
- **Assets stay WATCH:** no verified entries, no live-eligibility, no candidate creation. `opportunities.py` and the E verified-entry route are untouched.
- **Per-mapped-asset, not bulk.** No broad card/set/DB import.
- **PriceCharting exact-slug adapter (raw+graded) is the required completion gate;** TCGplayer/Playwright is conditional + non-blocking (Tasks 8–9 only after the gate is green).
- **Graded PriceCharting confidence is LOCKED at `low`** regardless of cell; an eBay ask never lifts it. Cross-source validation is the divergence-audit signal, not the confidence field.
- **Suite stays network-free:** all HTTP/render is injected and mocked; a browser is never launched by the default suite. Run the full suite with `.venv/Scripts/python.exe -m pytest -q`.
- **Slug identity:** persisted independent comps use `source` slug `pricecharting` / `tcgplayer` (both outside `divergence._EXTERNAL_SLUGS = {"ppt_cards"}`).
- **Commit style:** `feat(poke):` / `test(poke):` / `docs(poke):` / `data(poke):`. End commit messages with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Verified fetchability (probe 2026-07-05):** PriceCharting detail page `https://www.pricecharting.com/game/pokemon-prismatic-evolutions/umbreon-ex-161` is plain-requests-parseable. Cell→grade map: `used_price`=Ungraded, `complete_price`=Grade 7, `new_price`=Grade 8, `graded_price`=Grade 9, `box_only_price`=Grade 9.5, `manual_only_price`=PSA 10. Each cell is `<td id="{cell}"...><span class="price js-price">$X,XXX.XX</span>`.

---

## File structure

**Create:**
- `scanner/poke_api/independent_sources.py` — parser + `PriceChartingRawSource` + `PriceChartingGradedSource` + `TcgPlayerRenderedSource` + `playwright_render` + builders. One responsibility: turn an exact-mapped asset into an independent `CompSourceQuote`.
- `tests/fixtures/comps/pricecharting_umbreon_ex_161.html` — trimmed real `#price_data` table fixture.
- `tests/test_poke_independent_sources.py` — parser + adapter + confidence-lock tests.
- `docs/poke/pricecharting-detail-probe-2026-07-05.md` — probe evidence doc.
- `docs/poke/phase-f-independent-source-result-2026-07-06.md` — result doc (Task 6; captures the gitignored ledger writes + audit outcome).

**Modify:**
- `scanner/poke_api/sources.py` — lock `resolve_graded_comp` PC branch to `low`; add `resolve_independent_asset_row`.
- `scanner/poke_api/edge_cli.py` — `--refresh-independent` + `_record_independent`; independent slug never falls back to `ppt_cards`.
- `scanner/poke_api/divergence.py` — `_local_ours` returns `source`; `audit_local` rows carry `ours_source` + `cross_source_validated`.
- `scanner/config.py` — `PokeCfg.independent_sources: bool = False` + parse.
- `data/poke/assets.yaml` — add `pricecharting_slug` to the four Umbreon assets.
- `tests/test_poke_asset_sources.py` — flip the ask-corroborated-medium graded test to `low`.
- `docs/poke/private-price-api.md`, `docs/poke/sources.md`, `docs/poke/edge-layer-runbook.md` — Track F docs.

---

## REQUIRED GATE (Tasks 1–7) — PriceCharting, complete before any TCGplayer work

### Task 1: PriceCharting detail-page parser + fixture

**Files:**
- Create: `tests/fixtures/comps/pricecharting_umbreon_ex_161.html`
- Create: `scanner/poke_api/independent_sources.py`
- Test: `tests/test_poke_independent_sources.py`

**Interfaces:**
- Produces: `pricecharting_card_prices_from_html(body: str) -> dict` returning `{"cells": {cell_id: float}, "blocked": bool}`; module constants `PC_RAW_CELL="used_price"`, `PC_PSA10_CELL="manual_only_price"`, `PC_GRADE_CELLS={"9.5":"box_only_price","9":"graded_price","8":"new_price","7":"complete_price"}`.

- [ ] **Step 1: Create the fixture** (real structure + real probe values)

Create `tests/fixtures/comps/pricecharting_umbreon_ex_161.html`:

```html
<table id="price_data" class="info_box">
  <thead>
    <tr>
      <th>Ungraded</th><th>Grade 7</th><th>Grade 8</th>
      <th>Grade 9</th><th>Grade 9.5</th><th>PSA 10</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td id="used_price"><span class="price js-price">$1,425.00</span></td>
      <td id="complete_price"><span class="price js-price">$1,270.00</span></td>
      <td id="new_price"><span class="price js-price">$1,286.91</span></td>
      <td id="graded_price" class="tablet-portrait-hidden"><span class="price js-price">$1,554.05</span></td>
      <td id="box_only_price" class="tablet-portrait-hidden"><span class="price js-price">$3,112.50</span></td>
      <td id="manual_only_price" class="tablet-portrait-hidden"><span class="price js-price">$7,013.08</span></td>
    </tr>
  </tbody>
</table>
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_poke_independent_sources.py`:

```python
"""Phase F — independent (non-PPT) PriceCharting/TCGplayer source adapters."""
from pathlib import Path

from scanner.poke_api import independent_sources as indep

FIXTURE = Path(__file__).parent / "fixtures" / "comps" / "pricecharting_umbreon_ex_161.html"


def _fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parser_extracts_every_grade_cell():
    parsed = indep.pricecharting_card_prices_from_html(_fixture())
    assert parsed["blocked"] is False
    cells = parsed["cells"]
    assert cells["used_price"] == 1425.00
    assert cells["complete_price"] == 1270.00
    assert cells["new_price"] == 1286.91
    assert cells["graded_price"] == 1554.05
    assert cells["box_only_price"] == 3112.50
    assert cells["manual_only_price"] == 7013.08


def test_parser_challenge_page_is_blocked():
    parsed = indep.pricecharting_card_prices_from_html("<html>Just a moment...</html>")
    assert parsed["blocked"] is True
    assert parsed["cells"] == {}


def test_parser_malformed_html_is_empty_not_crash():
    parsed = indep.pricecharting_card_prices_from_html("<table><td>no ids here</td></table>")
    assert parsed["blocked"] is False
    assert parsed["cells"] == {}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_independent_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.poke_api.independent_sources'`.

- [ ] **Step 4: Write the module (parser only)**

Create `scanner/poke_api/independent_sources.py`:

```python
"""Independent (non-PPT) sold-source adapters for raw/graded assets (Phase F).

PriceCharting (plain requests, the required completion gate) + TCGplayer (rendered,
conditional + non-blocking). Each adapter exposes ``fetch(asset, checked_at) ->
CompSourceQuote`` — the interface ``sources.resolve_raw_comp`` / ``resolve_graded_comp``
already accept in their ``pc_source`` / ``tcg_source`` slots.

STOP-class, baked in structurally: exact ``pricecharting_slug`` / ``tcgplayer_id`` only
(never fuzzy); a challenge page is ``blocked`` (never evaded); no source ->
``no_match``/``skipped`` (never a guessed number). These sources NEVER call PPT — every
fetch is 0 PPT credits.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import requests

from ..comps.model import SOLD_DERIVED, CompSourceQuote

PC_GAME_URL = "https://www.pricecharting.com/game/{slug}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36")
_CHALLENGE_MARKERS = ("Just a moment", "cf-browser-verification", "Checking your browser")

# Verified 2026-07-05 vs pricecharting.com/game/pokemon-prismatic-evolutions/umbreon-ex-161.
PC_RAW_CELL = "used_price"              # Ungraded column (raw loose/NM proxy)
PC_PSA10_CELL = "manual_only_price"    # the PSA-exact column
PC_GRADE_CELLS = {                      # grade number -> grader-agnostic PriceCharting cell
    "9.5": "box_only_price",
    "9": "graded_price",
    "8": "new_price",
    "7": "complete_price",
}


def _iso(checked_at: int) -> str:
    return datetime.fromtimestamp(int(checked_at)).isoformat(timespec="seconds")


def _price_cell(body: str, cell_id: str) -> float | None:
    """The $ value inside ``<td id="{cell_id}">...<span class="...js-price">$X</span>``.
    Returns None if the cell/price is absent or unparseable (never raises)."""
    m = re.search(
        r'id="' + re.escape(cell_id) + r'"[^>]*>\s*'
        r'<span[^>]*class="[^"]*js-price[^"]*"[^>]*>\s*\$?([\d,]+\.?\d*)',
        body, flags=re.I | re.S)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def pricecharting_card_prices_from_html(body: str) -> dict:
    """Parse a PriceCharting card DETAIL page price table.

    Returns ``{"cells": {cell_id: price}, "blocked": bool}``. A challenge/interstitial
    page -> ``blocked: True`` with no cells. Malformed/empty HTML -> empty cells,
    ``blocked: False`` (honest no-source, never a crash)."""
    body = body or ""
    if any(marker in body for marker in _CHALLENGE_MARKERS):
        return {"cells": {}, "blocked": True}
    cells: dict[str, float] = {}
    for cid in (PC_RAW_CELL, PC_PSA10_CELL, *PC_GRADE_CELLS.values()):
        price = _price_cell(body, cid)
        if price is not None and price > 0:
            cells[cid] = price
    return {"cells": cells, "blocked": False}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_independent_sources.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add scanner/poke_api/independent_sources.py tests/test_poke_independent_sources.py tests/fixtures/comps/pricecharting_umbreon_ex_161.html
git commit -m "feat(poke): PriceCharting card detail-page price parser (Phase F Task 1)"
```

---

### Task 2: PriceCharting raw + graded adapters (confidence locked low)

**Files:**
- Modify: `scanner/poke_api/independent_sources.py`
- Test: `tests/test_poke_independent_sources.py`

**Interfaces:**
- Consumes: `pricecharting_card_prices_from_html`, `PC_RAW_CELL`, `PC_PSA10_CELL`, `PC_GRADE_CELLS`.
- Produces: `PriceChartingRawSource(session=None).fetch(asset, checked_at) -> CompSourceQuote`; `PriceChartingGradedSource(session=None).fetch(asset, checked_at) -> CompSourceQuote`; `_grade_cell_for(grade_key: str) -> tuple[str | None, str]`. Both adapters emit slug `pricecharting`, `kind=SOLD_DERIVED`; status one of `ok/skipped/blocked/no_match/error`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_poke_independent_sources.py`:

```python
RAW_ASSET = {"asset_key": "umbreon_raw_nm", "asset_class": "raw", "name": "Umbreon ex 161",
             "set": "Prismatic Evolutions", "condition": "NM",
             "pricecharting_slug": "pokemon-prismatic-evolutions/umbreon-ex-161"}
PSA10 = {"asset_key": "umbreon_psa10", "asset_class": "graded", "name": "Umbreon ex 161",
         "set": "Prismatic Evolutions", "grade_key": "psa10",
         "pricecharting_slug": "pokemon-prismatic-evolutions/umbreon-ex-161"}
PSA9 = {**PSA10, "asset_key": "umbreon_psa9", "grade_key": "psa9"}


class _FakeSession:
    """Returns a canned response for .get(); no network."""
    def __init__(self, text, status=200, exc=None):
        self._text, self._status, self._exc = text, status, exc

    def get(self, url, **kw):
        if self._exc is not None:
            raise self._exc
        return _FakeResp(self._text, self._status)


class _FakeResp:
    def __init__(self, text, status):
        self.text, self.status_code = text, status


def test_raw_adapter_uses_ungraded_cell():
    src = indep.PriceChartingRawSource(session=_FakeSession(_fixture()))
    q = src.fetch(RAW_ASSET, 1_700_000_000)
    assert q.source == "pricecharting" and q.status == "ok"
    assert q.price == 1425.00
    assert "pokemon-prismatic-evolutions/umbreon-ex-161" in q.url


def test_raw_adapter_no_slug_is_skipped():
    q = indep.PriceChartingRawSource(session=_FakeSession(_fixture())).fetch(
        {"asset_class": "raw", "name": "x", "set": "y"}, 1_700_000_000)
    assert q.status == "skipped" and q.price is None


def test_graded_psa10_uses_manual_only_price_exact():
    q = indep.PriceChartingGradedSource(session=_FakeSession(_fixture())).fetch(PSA10, 1_700_000_000)
    assert q.status == "ok" and q.price == 7013.08
    assert "PSA-exact" in q.detail


def test_graded_psa9_uses_grade9_column_grader_agnostic():
    q = indep.PriceChartingGradedSource(session=_FakeSession(_fixture())).fetch(PSA9, 1_700_000_000)
    assert q.status == "ok" and q.price == 1554.05
    assert "grader-agnostic" in q.detail


def test_graded_cgc10_has_no_exact_cell_no_match():
    q = indep.PriceChartingGradedSource(session=_FakeSession(_fixture())).fetch(
        {**PSA10, "grade_key": "cgc10"}, 1_700_000_000)
    assert q.status == "no_match" and q.price is None


def test_adapter_challenge_page_is_blocked():
    src = indep.PriceChartingRawSource(session=_FakeSession("Just a moment..."))
    assert src.fetch(RAW_ASSET, 1_700_000_000).status == "blocked"


def test_adapter_http_403_is_blocked():
    src = indep.PriceChartingRawSource(session=_FakeSession("", status=403))
    assert src.fetch(RAW_ASSET, 1_700_000_000).status == "blocked"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_independent_sources.py -k "adapter or graded" -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'PriceChartingRawSource'`.

- [ ] **Step 3: Implement the adapters**

Append to `scanner/poke_api/independent_sources.py`:

```python
class _PriceChartingBase:
    """Shared plain-requests fetch of a PriceCharting detail page (0 PPT credits)."""

    def __init__(self, session: Any = None) -> None:
        self.session = session or requests.Session()

    def _fetch_cells(self, slug: Any, checked_at: int):
        """(cells, url, status, detail). status: skipped|blocked|error|ok."""
        slug = str(slug or "").strip().strip("/")
        if not slug:
            return {}, "", "skipped", "no pricecharting_slug mapped"
        url = PC_GAME_URL.format(slug=slug)
        try:
            resp = self.session.get(
                url, headers={"User-Agent": UA, "Accept": "text/html"}, timeout=20)
        except requests.RequestException as exc:
            return {}, url, "error", str(exc)[:200]
        if getattr(resp, "status_code", 200) in (403, 429):
            return {}, url, "blocked", f"HTTP {resp.status_code}"
        parsed = pricecharting_card_prices_from_html(resp.text)
        if parsed["blocked"]:
            return {}, url, "blocked", "challenge/interstitial page (recorded blocked, not evaded)"
        return parsed["cells"], url, "ok", ""


class PriceChartingRawSource(_PriceChartingBase):
    """Raw single Ungraded (``used_price``) comp, exact-slug only. Sold-derived,
    slug ``pricecharting``. Ungraded is a loose/NM proxy — condition not distinguished."""

    def fetch(self, asset: dict, checked_at: int) -> CompSourceQuote:
        fetched = _iso(checked_at)
        cells, url, status, detail = self._fetch_cells(asset.get("pricecharting_slug"), checked_at)
        if status != "ok":
            return CompSourceQuote("pricecharting", SOLD_DERIVED, status, None, url, fetched, detail=detail)
        price = cells.get(PC_RAW_CELL)
        if price is None:
            return CompSourceQuote("pricecharting", SOLD_DERIVED, "no_match", None, url, fetched,
                                   detail="no Ungraded (used_price) cell on the PriceCharting page")
        return CompSourceQuote("pricecharting", SOLD_DERIVED, "ok", price, url, fetched,
                               detail="PriceCharting Ungraded market summary (condition not distinguished)")


def _grade_cell_for(grade_key: Any) -> tuple[str | None, str]:
    """(cell_id, basis note) for a normalized grade_key, or (None, reason). Exact-only:
    ``psa10`` -> the PSA-exact column; grades 7/8/9/9.5 -> the grader-agnostic column;
    anything else (``cgc10``, ``bgs10``, ``*6``…) -> (None, reason) => honest no_match."""
    gk = str(grade_key or "").strip().lower()
    m = re.match(r"^([a-z]+)([\d.]+)$", gk)
    if not m:
        return None, f"unparseable grade_key {grade_key!r}"
    grader, num = m.group(1), m.group(2)
    if num == "10":
        if grader == "psa":
            return PC_PSA10_CELL, "PriceCharting PSA 10 column (PSA-exact)"
        return None, f"no exact PriceCharting cell for {gk} (only PSA 10 has a graded column)"
    cell = PC_GRADE_CELLS.get(num)
    if cell is None:
        return None, f"no PriceCharting cell for grade {num!r}"
    return cell, f"PriceCharting Grade {num} column (grader-agnostic proxy)"


class PriceChartingGradedSource(_PriceChartingBase):
    """Graded comp from the exact grade cell, slug ``pricecharting``. The PSA-exact vs
    grader-agnostic distinction rides in the quote ``detail`` (basis note); confidence is
    locked to ``low`` downstream in ``sources.resolve_graded_comp``."""

    def fetch(self, asset: dict, checked_at: int) -> CompSourceQuote:
        fetched = _iso(checked_at)
        cell_id, note = _grade_cell_for(asset.get("grade_key"))
        if cell_id is None:
            return CompSourceQuote("pricecharting", SOLD_DERIVED, "no_match", None, "", fetched, detail=note)
        cells, url, status, detail = self._fetch_cells(asset.get("pricecharting_slug"), checked_at)
        if status != "ok":
            return CompSourceQuote("pricecharting", SOLD_DERIVED, status, None, url, fetched, detail=detail)
        price = cells.get(cell_id)
        if price is None:
            return CompSourceQuote("pricecharting", SOLD_DERIVED, "no_match", None, url, fetched,
                                   detail=f"no {cell_id} cell on the PriceCharting page")
        return CompSourceQuote("pricecharting", SOLD_DERIVED, "ok", price, url, fetched,
                               detail=note, raw_excerpt=note)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_independent_sources.py -v`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add scanner/poke_api/independent_sources.py tests/test_poke_independent_sources.py
git commit -m "feat(poke): PriceCharting raw+graded independent adapters, exact-slug (Phase F Task 2)"
```

---

### Task 3: Lock graded confidence + wire the independent resolver

**Files:**
- Modify: `scanner/poke_api/sources.py:394-436` (`resolve_graded_comp`) and add `resolve_independent_asset_row`
- Modify: `tests/test_poke_asset_sources.py` (flip the ask-corroborated graded test)
- Test: `tests/test_poke_independent_sources.py`

**Interfaces:**
- Consumes: `PriceChartingRawSource`, `PriceChartingGradedSource`, `TcgPlayerRenderedSource` (via a `sources` dict), `resolve_raw_comp`, `resolve_graded_comp`, `catalog_mod.RAW`.
- Produces: `sources.resolve_independent_asset_row(asset, *, sources, checked_at, tolerance_pct=20.0, floor_sanity_pct=50.0) -> dict` (legacy comp row); `sources` is a dict with keys `pc_raw`/`pc_graded`/`tcg`.

- [ ] **Step 1: Write the failing test (confidence lock via the resolver)**

Append to `tests/test_poke_independent_sources.py`:

```python
from scanner.poke_api import sources as sources_mod


def _srcs(session):
    return {"pc_raw": indep.PriceChartingRawSource(session=session),
            "pc_graded": indep.PriceChartingGradedSource(session=session),
            "tcg": indep.TcgPlayerRenderedSource(render=None)}  # rendering dormant


def test_independent_raw_row_is_low_single_source():
    row = sources_mod.resolve_independent_asset_row(
        RAW_ASSET, sources=_srcs(_FakeSession(_fixture())), checked_at=1_700_000_000)
    assert row["status"] == "ok"
    assert float(row["estimate"]) == 1425.00
    assert row["confidence"] == "low"       # single independent sold source
    ok_sources = [s for s in row.get("sources", []) if s.get("status") == "ok"]
    assert any(s["source"] == "pricecharting" for s in ok_sources)  # PC produced the number
    assert all(s["source"] != "ppt_cards" for s in row.get("sources", []))


def test_independent_graded_row_is_locked_low_even_psa_exact():
    row = sources_mod.resolve_independent_asset_row(
        PSA10, sources=_srcs(_FakeSession(_fixture())), checked_at=1_700_000_000)
    assert row["status"] == "ok"
    assert float(row["estimate"]) == 7013.08
    assert row["confidence"] == "low"       # LOCKED low even on the PSA-exact cell
    assert "PSA-exact" in (row.get("confidenceReason") or row.get("detail") or "")


def test_independent_graded_uses_pricecharting_slug_not_ppt():
    row = sources_mod.resolve_independent_asset_row(
        PSA9, sources=_srcs(_FakeSession(_fixture())), checked_at=1_700_000_000)
    slugs = [s.get("source") for s in row.get("sources", [])]
    assert "pricecharting" in slugs
    assert "ppt_cards" not in slugs
```

(The `_row_source_slug` line degrades to `True` if that helper is absent — it is illustrative, not required.)

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_independent_sources.py -k independent -v`
Expected: FAIL — `AttributeError: ... 'resolve_independent_asset_row'` (and `TcgPlayerRenderedSource` not yet defined — that is Task 8; add a minimal stub now, see Step 3b).

- [ ] **Step 3a: Lock the graded PC branch to `low`**

In `scanner/poke_api/sources.py`, `resolve_graded_comp`, replace the PriceCharting branch and drop the now-unused ask corroboration. Replace:

```python
    pc = _safe_fetch(pc_source, asset, checked_at, "pricecharting") if pc_source is not None else None
    ebay = None
    if ebay_source is not None:
        try:
            ebay = ebay_source.fetch(asset, checked_at)
        except Exception:  # noqa: BLE001
            ebay = None

    if pc is not None and pc.status == "ok" and pc.price and pc.price > 0:
        corroborated = _ask_ok(ebay) and _within(pc.price, ebay.quote.price, 20.0)
        conf = "medium" if corroborated else "low"
        detail = ("single sold-derived graded source"
                  + (", ask corroborated" if corroborated else ", uncorroborated"))
        return _legacy_row(asset_key, asset, status="ok", estimate=pc.price,
                           confidence=conf, basis="pricecharting graded page",
                           source="pricecharting", url=pc.url, checked_at=checked_at,
                           detail=detail)
```

with:

```python
    pc = _safe_fetch(pc_source, asset, checked_at, "pricecharting") if pc_source is not None else None

    if pc is not None and pc.status == "ok" and pc.price and pc.price > 0:
        # Phase F: graded PriceCharting confidence is LOCKED at low. A single independent
        # sold-derived source is low regardless of cell (PSA-exact included); an eBay ask
        # is context and can never lift it. Cross-source validation is supplied by the
        # divergence audit agreeing, not by this field. The PSA-exact vs grader-agnostic
        # distinction rides in the basis note (pc.raw_excerpt / pc.detail).
        note = pc.raw_excerpt or pc.detail or "single sold-derived graded source"
        return _legacy_row(asset_key, asset, status="ok", estimate=pc.price,
                           confidence="low", basis="pricecharting graded page",
                           source="pricecharting", url=pc.url, checked_at=checked_at,
                           detail=note)
```

Then delete the now-unused helpers `_ask_ok` and `_within` (defined just above `resolve_graded_comp`) and remove the unused `ebay_source` handling body — keep the `ebay_source=None` parameter for signature compatibility but do not fetch it.

- [ ] **Step 3b: Add a minimal `TcgPlayerRenderedSource` stub** (fully built in Task 8; needed now so `_srcs` imports)

Append to `scanner/poke_api/independent_sources.py`:

```python
class TcgPlayerRenderedSource:
    """Rendered TCGplayer market price (Playwright). CONDITIONAL + NON-BLOCKING: with no
    injected ``render`` callable (the default) every fetch is a ``blocked`` shell — never
    raises, never on the Phase F completion path. Full render wired in Task 9."""

    PRODUCT_URL = "https://www.tcgplayer.com/product/{tcg_id}"

    def __init__(self, render: Any = None) -> None:
        self._render = render

    def fetch(self, asset: dict, checked_at: int) -> CompSourceQuote:
        fetched = _iso(checked_at)
        tcg_id = str(asset.get("tcgplayer_id") or "").strip()
        if not tcg_id:
            return CompSourceQuote("tcgplayer", SOLD_DERIVED, "skipped", None, "", fetched,
                                   detail="no tcgplayer_id mapped")
        url = self.PRODUCT_URL.format(tcg_id=tcg_id)
        if self._render is None:
            return CompSourceQuote("tcgplayer", SOLD_DERIVED, "blocked", None, url, fetched,
                                   detail="rendering not enabled (Playwright dormant / not installed)")
        return CompSourceQuote("tcgplayer", SOLD_DERIVED, "blocked", None, url, fetched,
                               detail="render path wired in Task 9")
```

- [ ] **Step 3c: Add `resolve_independent_asset_row`**

Append to `scanner/poke_api/sources.py` (near `resolve_asset_source_row`):

```python
def resolve_independent_asset_row(asset: dict, *, sources: dict, checked_at: int,
                                  tolerance_pct: float = 20.0,
                                  floor_sanity_pct: float = 50.0) -> dict:
    """Resolve a raw/graded asset comp from the INDEPENDENT (non-PPT) adapters only —
    ``ppt_client`` is never passed, so this path spends 0 PPT credits. ``sources`` is the
    dict from ``independent_sources.build_independent_sources`` (``pc_raw`` / ``pc_graded``
    / ``tcg``). Raw goes through the in-house ladder (a single independent sold source is
    ``low``, two agreeing are ``high``); graded is PriceCharting-only, locked ``low``."""
    if str(asset.get("asset_class")) == catalog_mod.RAW:
        return resolve_raw_comp(asset, checked_at=checked_at, ppt_client=None,
                                pc_source=(sources or {}).get("pc_raw"),
                                tcg_source=(sources or {}).get("tcg"),
                                tolerance_pct=tolerance_pct, floor_sanity_pct=floor_sanity_pct)
    return resolve_graded_comp(asset, checked_at=checked_at, ppt_client=None,
                               pc_source=(sources or {}).get("pc_graded"))
```

- [ ] **Step 3d: Flip the existing graded test**

In `tests/test_poke_asset_sources.py`, `test_graded_pricecharting_fallback_ask_corroborated_is_medium` — rename to `test_graded_pricecharting_ask_no_longer_lifts_confidence` and change the assertion:

```python
def test_graded_pricecharting_ask_no_longer_lifts_confidence():
    """Phase F: graded PriceCharting confidence is LOCKED at low — an eBay ask is context
    and can no longer lift it to medium (cross-source validation is the audit's job)."""
    row = sources.resolve_graded_comp(
        GRADED, checked_at=CHECKED,
        pc_source=_FixedSource(_sold("pricecharting", 240.0)),
        ebay_source=_FixedSource(_ask("ebay", 245.0)))
    conf = row["confidence"]
    assert conf == "low"
```

(If `_ask` / the ebay fixture helper is unused elsewhere after this, leave it — it is shared test scaffolding.)

- [ ] **Step 4: Run the affected tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_independent_sources.py tests/test_poke_asset_sources.py -v`
Expected: PASS (independent resolver rows are `low`; the flipped graded test is `low`).

- [ ] **Step 5: Commit**

```bash
git add scanner/poke_api/sources.py scanner/poke_api/independent_sources.py tests/test_poke_independent_sources.py tests/test_poke_asset_sources.py
git commit -m "feat(poke): lock graded PC confidence low + independent asset resolver (Phase F Task 3)"
```

---

### Task 4: Config gate `poke.independent_sources`

**Files:**
- Modify: `scanner/config.py:31-40` (`PokeCfg`) and `:243-251` (parse)
- Modify: `scanner/poke_api/independent_sources.py` (add `independent_sources_enabled` + `build_independent_sources`)
- Test: `tests/test_poke_independent_sources.py`

**Interfaces:**
- Produces: `PokeCfg.independent_sources: bool = False`; `independent_sources.independent_sources_enabled(cfg) -> bool`; `independent_sources.build_independent_sources(*, render=None, enable_render=False) -> dict`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_poke_independent_sources.py`:

```python
from scanner import config as config_mod


def test_independent_sources_gate_defaults_off():
    cfg = config_mod.Config()
    assert indep.independent_sources_enabled(cfg) is False


def test_independent_sources_gate_reads_poke_flag():
    cfg = config_mod.Config()
    cfg.poke.independent_sources = True
    assert indep.independent_sources_enabled(cfg) is True


def test_build_independent_sources_has_pc_and_dormant_tcg():
    srcs = indep.build_independent_sources()
    assert isinstance(srcs["pc_raw"], indep.PriceChartingRawSource)
    assert isinstance(srcs["pc_graded"], indep.PriceChartingGradedSource)
    # TCGplayer render dormant by default -> a blocked quote, never a crash
    q = srcs["tcg"].fetch({"tcgplayer_id": "610516"}, 1_700_000_000)
    assert q.status == "blocked"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_independent_sources.py -k "gate or build_independent" -v`
Expected: FAIL — `AttributeError: 'PokeCfg' object has no attribute 'independent_sources'`.

- [ ] **Step 3: Add the config field + parse**

In `scanner/config.py`, add to `PokeCfg` (after `daily_credit_cap`):

```python
    independent_sources: bool = False  # Phase F: allow CLI live PriceCharting/TCGplayer fetch (0 PPT credits)
```

And in the `PokeCfg(...)` construction (after `daily_credit_cap=...`):

```python
            independent_sources=bool(poke_raw.get("independent_sources", False)),
```

- [ ] **Step 4: Add the builders**

Append to `scanner/poke_api/independent_sources.py`:

```python
def independent_sources_enabled(cfg: Any) -> bool:
    """The ``poke.independent_sources`` master gate (default False). Purely a
    'live network is allowed on the CLI refresh path' switch — no key required."""
    return bool(getattr(getattr(cfg, "poke", None), "independent_sources", False))


def build_independent_sources(*, render: Any = None, enable_render: bool = False) -> dict:
    """The independent adapter set. PriceCharting is always real (plain requests);
    the TCGplayer render callable is injected only when ``enable_render`` (post the
    operator-approved render probe) — otherwise the TCGplayer adapter is a blocked shell."""
    return {
        "pc_raw": PriceChartingRawSource(),
        "pc_graded": PriceChartingGradedSource(),
        "tcg": TcgPlayerRenderedSource(render=render if enable_render else None),
    }
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_independent_sources.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scanner/config.py scanner/poke_api/independent_sources.py tests/test_poke_independent_sources.py
git commit -m "feat(poke): poke.independent_sources gate + adapter builders (Phase F Task 4)"
```

---

### Task 5: CLI `record-asset-comp --refresh-independent`

**Files:**
- Modify: `scanner/poke_api/edge_cli.py` (argparse + `_cmd_record_asset_comp` + new `_record_independent`)
- Test: `tests/test_poke_edge_cli.py`

**Interfaces:**
- Consumes: `sources_mod.resolve_independent_asset_row`, `independent_sources.independent_sources_enabled`/`build_independent_sources`, `_row_primary_source`, `sources_mod.record_asset_comp`.
- Produces: CLI flag `--refresh-independent` on `record-asset-comp`; behavior — refuse (exit 2) when the gate is off; on success persist with the actual slug (never `ppt_cards`) at 0 PPT credits.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_poke_edge_cli.py` (follow the file's existing deps-building pattern; this sketch names the key assertions):

```python
def test_refresh_independent_persists_pricecharting_slug(tmp_path, monkeypatch):
    from scanner.poke_api import edge_cli, sources as sources_mod, independent_sources as indep
    ledger = tmp_path / "price_history.jsonl"
    asset = {"asset_class": "raw", "name": "Umbreon ex 161", "set": "Prismatic Evolutions",
             "condition": "NM", "pricecharting_slug": "pokemon-prismatic-evolutions/umbreon-ex-161"}
    deps = _deps_with(assets={"umb": asset}, ledger_path=ledger, today="2026-07-06",
                      independent_sources=True)  # cfg.poke.independent_sources = True

    # stub the resolver so the test never hits the network
    monkeypatch.setattr(sources_mod, "resolve_independent_asset_row",
                        lambda a, **k: {"estimate": "1425.00", "confidence": "low",
                                        "sources": [{"source": "pricecharting", "status": "ok",
                                                     "price": 1425.00}],
                                        "sourceUrl": "https://www.pricecharting.com/game/x",
                                        "compBasis": "PriceCharting Ungraded"})
    rc = edge_cli.main(["record-asset-comp", "--asset-key", "umb", "--refresh-independent"], deps=deps)
    assert rc == 0
    rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    assert rows and rows[0]["source"] == "pricecharting"      # never ppt_cards
    assert rows[0]["comp"] == 1425.00 and rows[0]["comp_confidence"] == "low"


def test_refresh_independent_refuses_when_gate_off(tmp_path):
    from scanner.poke_api import edge_cli
    asset = {"asset_class": "raw", "name": "x", "set": "y", "condition": "NM"}
    deps = _deps_with(assets={"umb": asset}, ledger_path=tmp_path / "l.jsonl",
                      today="2026-07-06", independent_sources=False)
    rc = edge_cli.main(["record-asset-comp", "--asset-key", "umb", "--refresh-independent"], deps=deps)
    assert rc == 2   # refused: gate off
```

> If `test_poke_edge_cli.py` has no `_deps_with` helper, add a small local one that builds a `router.build_deps(cfg, ledger_path=..., today=...)` with `cfg.poke.independent_sources` set and `assets` injected (mirror the existing `record-asset-comp` tests in `tests/test_poke_asset_comp_record.py`).

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_edge_cli.py -k refresh_independent -v`
Expected: FAIL — unrecognized argument `--refresh-independent`.

- [ ] **Step 3: Add the argparse flag**

In `scanner/poke_api/edge_cli.py`, in `_build_argparser` under the `record-asset-comp` parser (`prc`), add:

```python
    prc.add_argument("--refresh-independent", action="store_true", dest="refresh_independent",
                     help="0-PPT-credit live fetch from the independent PriceCharting/TCGplayer "
                          "sources; persists with the real source slug (needs poke.independent_sources)")
```

- [ ] **Step 4: Add the dispatch + handler**

In `_cmd_record_asset_comp`, before the `if args.refresh:` block:

```python
    if getattr(args, "refresh_independent", False):
        return _record_independent(args, deps, asset, ledger_path)
```

Add a source-picker that prefers the OK sold source (near `_row_primary_source`). This is
load-bearing: on the raw path the row's `sources[]` lists the *blocked* TCGplayer quote
first, so the naive `_row_primary_source` would persist the wrong slug (`tcgplayer`) instead
of the real comp source (`pricecharting`):

```python
def _row_ok_source(row: dict) -> str:
    """The slug of the FIRST ok sold-derived source in a resolved row (the source that
    actually produced the comp) — not merely the first listed source, which may be a
    blocked/skipped quote. Falls back to the first listed source for single-source rows
    whose entries omit status (e.g. the graded _legacy_row)."""
    for s in row.get("sources") or []:
        if isinstance(s, dict) and s.get("source") and s.get("status") == "ok" and s.get("price"):
            return str(s["source"]).strip().lower()
    return _row_primary_source(row)
```

Add the handler (near `_record_billed`):

```python
def _record_independent(args, deps, asset, ledger_path) -> int:
    """0-PPT-credit live fetch from the independent (PriceCharting/TCGplayer) sources,
    persisted with the ACTUAL source slug (never ppt_cards). Gated on
    poke.independent_sources; a no-source result records nothing (honest)."""
    from . import independent_sources as indep
    if not indep.independent_sources_enabled(deps.cfg):
        print("refused: independent live fetch is off (set poke.independent_sources: true)")
        return 2
    srcs = indep.build_independent_sources()   # PriceCharting real; TCGplayer dormant shell
    try:
        row = sources_mod.resolve_independent_asset_row(
            asset, sources=srcs, checked_at=_today_ts(deps.today))
    except Exception as exc:  # noqa: BLE001 - never persist on a resolver bug
        print(f"independent fetch failed ({str(exc)[:120]}); nothing recorded")
        return 1
    estimate = resale._amount(row.get("estimate"))
    if estimate is None:
        print("independent fetch found no usable sold comp (honest no-source); nothing recorded")
        return 1
    source = _row_ok_source(row)               # the OK sold source, NOT the first (blocked) one;
    if not source or source == "ebay":         # and NO ppt_cards fallback on the independent path
        print(f"refused: independent row has no sold source slug (got {source!r}); nothing recorded")
        return 1
    try:
        wrote = sources_mod.record_asset_comp(
            ledger_path, asset, comp=estimate, confidence=row.get("confidence"),
            source=source, capture_date=deps.today,
            source_url=row.get("sourceUrl") or row.get("url") or "",
            basis=row.get("compBasis") or row.get("basis") or "", asset_key=args.asset_key)
    except ValueError as exc:
        print(f"refused to persist ({exc}); nothing recorded")
        return 1
    print(f"{'recorded' if wrote else 'already recorded'} asset comp {args.asset_key} "
          f"= ${estimate:.2f} [{source}, {row.get('confidence')}] (0 PPT credits)")
    return 0
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_edge_cli.py -k refresh_independent -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add scanner/poke_api/edge_cli.py tests/test_poke_edge_cli.py
git commit -m "feat(poke): record-asset-comp --refresh-independent, 0-credit real-slug persist (Phase F Task 5)"
```

---

### Task 6: Divergence `--local` cross-source surfacing + seed + record + result doc

**Files:**
- Modify: `scanner/poke_api/divergence.py:115-171` (`_local_ours`, `audit_local`) and `edge_cli._print_audit`
- Modify: `data/poke/assets.yaml`
- Create: `docs/poke/phase-f-independent-source-result-2026-07-06.md`
- Test: `tests/test_poke_divergence.py`

**Interfaces:**
- Produces: `audit_local` rows now include `ours_source: str | None` and `cross_source_validated: bool`; `_local_ours` returns a `source` key.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_poke_divergence.py` (match the file's ledger-building pattern):

```python
def test_local_audit_surfaces_cross_source_when_independent_agrees(tmp_path):
    from scanner.poke_api import divergence as dv
    # Two ledger rows for the same asset identity: independent pricecharting + ppt_cards.
    asset = {"asset_class": "raw", "name": "Umbreon ex 161", "set": "Prismatic Evolutions",
             "condition": "NM", "card_number": "161"}
    deps = _deps_with_ledger(tmp_path, asset_key="umb", asset=asset, rows=[
        _comp_row(asset, "umb", comp=1425.00, source="pricecharting", conf="low", date="2026-07-06"),
        _comp_row(asset, "umb", comp=1528.09, source="ppt_cards", conf="low", date="2026-07-06"),
    ])
    res = dv.audit_local(deps, asset_keys=["umb"])
    row = res["rows"][0]
    assert row["ours_source"] == "pricecharting"
    assert row["category"] == "agree"                 # ~7% delta < 20% tolerance
    assert row["cross_source_validated"] is True
    assert res["failed"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_divergence.py -k cross_source -v`
Expected: FAIL — `KeyError: 'ours_source'`.

- [ ] **Step 3: Surface `ours_source` + cross-source flag**

In `scanner/poke_api/divergence.py`, `_local_ours` — add the source to both return dicts:

```python
def _local_ours(obs, item_key, ext_date: str | None) -> dict:
    ours_obs = _latest_market_comp(obs, item_key, external=False)
    if ours_obs is None:
        return {"estimate": None, "confidence": "none", "missing": True, "ask_only": False,
                "stale": False, "source": None}
    o_date = str(ours_obs.get("capture_date") or "")
    return {
        "estimate": history_mod._comp_value(ours_obs),
        "confidence": str(ours_obs.get("comp_confidence") or "none"),
        "missing": False,
        "ask_only": history_mod.source_of(ours_obs) == "ebay",
        "stale": bool(ext_date and o_date and o_date < ext_date),
        "source": history_mod.source_of(ours_obs),
    }
```

In `audit_local`, replace the `rows.append({...})` with:

```python
        clazz = classify_divergence(ours, theirs, tolerance_pct=tol)
        ours_source = ours.get("source")
        cross = bool(ours_source and ours_source not in _EXTERNAL_SLUGS
                     and theirs is not None and clazz["category"] == "agree")
        rows.append({"subject_key": key, "subject_kind": kind,
                     "ours": ours.get("estimate"), "ours_source": ours_source,
                     "theirs": (theirs or {}).get("estimate"),
                     "cross_source_validated": cross, **clazz})
```

In `scanner/poke_api/edge_cli.py`, `_print_audit`, add the source to the per-row line:

```python
        src = f" via {r.get('ours_source')}" if r.get("ours_source") else ""
        xsv = "  [cross-source ✓]" if r.get("cross_source_validated") else ""
        print(f"  [{flag:<8}] {r['subject_key']:<28} {r['category']}{src}"
              f"  ours={_fmt_money(r.get('ours'))} theirs={_fmt_money(r.get('theirs'))}"
              f"  ({r.get('delta_pct')}%){xsv}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_divergence.py -v`
Expected: PASS.

- [ ] **Step 5: Seed the slugs**

In `data/poke/assets.yaml`, add `pricecharting_slug: pokemon-prismatic-evolutions/umbreon-ex-161` to `umbreon_ex_161_raw_nm`, `umbreon_ex_161_raw_lp`, `umbreon_ex_161_psa10`, and `umbreon_ex_161_psa9`. Example for the first:

```yaml
umbreon_ex_161_raw_nm:
  asset_class: raw
  name: "Umbreon ex 161"
  set: "Prismatic Evolutions"
  card_number: "161"
  condition: "NM"
  tcgplayer_id: "610516"   # Umbreon ex - 161/131; verified 2026-07-05
  pricecharting_slug: "pokemon-prismatic-evolutions/umbreon-ex-161"  # Phase F; verified 2026-07-05
```

- [ ] **Step 6: Record the independent comps (operator-run, 0 PPT credits)**

> This is a live PriceCharting fetch. Requires `poke.independent_sources: true` in `config.yaml` and operator go-ahead. It spends **0 PPT credits**. Record `raw_nm`, `psa10`, `psa9` (NOT `raw_lp` — Ungraded doesn't distinguish condition, per the spec's condition caveat).

Run (one per asset):

```bash
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli record-asset-comp --asset-key umbreon_ex_161_raw_nm --refresh-independent
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli record-asset-comp --asset-key umbreon_ex_161_psa10 --refresh-independent
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli record-asset-comp --asset-key umbreon_ex_161_psa9 --refresh-independent
```

Then run the cross-source local audit and capture its JSON:

```bash
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli divergence-audit --local --assets umbreon_ex_161_raw_nm,umbreon_ex_161_psa10,umbreon_ex_161_psa9 --json
```

- [ ] **Step 7: Write the result doc**

Create `docs/poke/phase-f-independent-source-result-2026-07-06.md` recording, in a table, each written ledger row (asset, comp, confidence, source=`pricecharting`, capture_date, source URL, basis) and the `--local` audit outcome per subject (ours, ours_source, theirs, category, delta, cross_source_validated). State plainly that `price_history.jsonl` is gitignored so this doc is the durable evidence, and that graded confidence is `low` by design with cross-source validation supplied by the audit agreement. If the actual recorded values differ from the probe values, record the actual values (STOP-class: never back-fill the probe numbers).

- [ ] **Step 8: Commit**

```bash
git add scanner/poke_api/divergence.py scanner/poke_api/edge_cli.py tests/test_poke_divergence.py data/poke/assets.yaml docs/poke/phase-f-independent-source-result-2026-07-06.md
git commit -m "feat(poke): local audit cross-source surfacing + seed slugs + result doc (Phase F Task 6)"
```

---

### Task 7: Guardrail tests + probe doc + Track F docs (gate closes here)

**Files:**
- Test: `tests/test_poke_independent_sources.py` (guardrails)
- Create: `docs/poke/pricecharting-detail-probe-2026-07-05.md`
- Modify: `docs/poke/private-price-api.md`, `docs/poke/sources.md`, `docs/poke/edge-layer-runbook.md`

- [ ] **Step 1: Write the guardrail tests**

Append to `tests/test_poke_independent_sources.py`:

```python
def test_independent_path_spends_zero_ppt_credits():
    """The independent resolver must never construct/call the PPT card client."""
    import scanner.poke_api.sources as s

    class _ExplodingPPT:
        def raw_quote(self, *a, **k):  # pragma: no cover - must never be called
            raise AssertionError("independent path called the PPT client")
        def graded_smart(self, *a, **k):  # pragma: no cover
            raise AssertionError("independent path called the PPT client")

    # resolve_independent_asset_row never accepts a ppt_client; prove it by resolving
    # with only the independent sources and asserting a pricecharting row.
    row = s.resolve_independent_asset_row(
        RAW_ASSET, sources=_srcs(_FakeSession(_fixture())), checked_at=1_700_000_000)
    assert row["status"] == "ok"
    assert all(src.get("source") != "ppt_cards" for src in row.get("sources", []))


def test_writer_refuses_ask_source():
    """record_asset_comp must refuse an ebay (ask) source — an ask is never a comp."""
    import pytest
    from scanner.poke_api import sources as s
    with pytest.raises(ValueError):
        s.build_asset_comp_observation(RAW_ASSET, comp=100.0, confidence="low",
                                       source="ebay", capture_date="2026-07-06")
```

- [ ] **Step 2: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_independent_sources.py -v`
Expected: PASS.

- [ ] **Step 3: Write the probe doc**

Create `docs/poke/pricecharting-detail-probe-2026-07-05.md` with: method (plain requests, browser UA, 0 PPT credits, read-only), the redirect-to-canonical-slug finding, and the verified cell→grade→value table (from Global Constraints). Note TCGplayer remains SPA-only (needs Playwright).

- [ ] **Step 4: Update the ladder + sources + runbook docs**

- `docs/poke/private-price-api.md`: add a **Track F — Independent singles/slabs sold-source validation** section (PriceCharting exact-slug adapters; graded locked `low`; `record-asset-comp --refresh-independent` at 0 PPT credits; `divergence-audit --local` now cross-source; TCGplayer conditional/non-blocking; PPT stays audit-only).
- `docs/poke/sources.md`: add a verdict row — PriceCharting card **detail** page = **fetchable-plain** (0 PPT credits; evidence 2026-07-05).
- `docs/poke/edge-layer-runbook.md`: document `record-asset-comp --refresh-independent` and reading the cross-source `--local` audit.

- [ ] **Step 5: Run the FULL suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (all pre-existing tests + the new Phase F tests; no network).

- [ ] **Step 6: Commit — REQUIRED GATE COMPLETE**

```bash
git add tests/test_poke_independent_sources.py docs/poke/pricecharting-detail-probe-2026-07-05.md docs/poke/private-price-api.md docs/poke/sources.md docs/poke/edge-layer-runbook.md
git commit -m "test(poke): Phase F guardrails + Track F docs; PriceCharting gate complete (Phase F Task 7)"
```

---

## CONDITIONAL (Tasks 8–9) — TCGplayer rendered; non-blocking; only after the gate is green

### Task 8: TCGplayer rendered adapter — full logic (mocked; no dependency yet)

**Files:**
- Modify: `scanner/poke_api/independent_sources.py` (`TcgPlayerRenderedSource.fetch` full logic + `_tcg_market_price`)
- Test: `tests/test_poke_independent_sources.py`

**Interfaces:**
- Produces: `_tcg_market_price(html: str) -> float | None`; `TcgPlayerRenderedSource(render=<callable(url)->html>)` — `ok` on a parseable rendered page, `blocked` on render failure / challenge / no render callable, `skipped` on no id, `no_match` on no price node.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_poke_independent_sources.py`:

```python
def test_tcg_rendered_ok_with_mock_render():
    html = '<div class="price-guide">Market Price: $1,499.99</div>'
    src = indep.TcgPlayerRenderedSource(render=lambda url: html)
    q = src.fetch({"tcgplayer_id": "610516"}, 1_700_000_000)
    assert q.source == "tcgplayer" and q.status == "ok" and q.price == 1499.99


def test_tcg_render_exception_is_blocked_not_crash():
    def boom(url):
        raise RuntimeError("chromium missing")
    q = indep.TcgPlayerRenderedSource(render=boom).fetch({"tcgplayer_id": "610516"}, 1_700_000_000)
    assert q.status == "blocked"


def test_tcg_challenge_page_is_blocked():
    q = indep.TcgPlayerRenderedSource(render=lambda url: "Just a moment...").fetch(
        {"tcgplayer_id": "610516"}, 1_700_000_000)
    assert q.status == "blocked"


def test_tcg_no_price_node_is_no_match():
    q = indep.TcgPlayerRenderedSource(render=lambda url: "<div>no price here</div>").fetch(
        {"tcgplayer_id": "610516"}, 1_700_000_000)
    assert q.status == "no_match"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_independent_sources.py -k tcg -v`
Expected: FAIL (the Task-3 stub returns `blocked` even for a good mock render).

- [ ] **Step 3: Replace the stub `fetch` with full logic + add `_tcg_market_price`**

In `scanner/poke_api/independent_sources.py`, replace `TcgPlayerRenderedSource.fetch` body and add the parser:

```python
def _tcg_market_price(html: str) -> float | None:
    """Extract 'Market Price: $X' from a rendered TCGplayer product page. The exact
    selector is confirmed by the operator-approved render probe (Task 9); this text
    pattern is the resilient fallback. Returns None if absent (never raises)."""
    m = re.search(r"Market\s*Price:?\s*\$([\d,]+\.?\d*)", html or "", flags=re.I)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None
```

```python
    def fetch(self, asset: dict, checked_at: int) -> CompSourceQuote:
        fetched = _iso(checked_at)
        tcg_id = str(asset.get("tcgplayer_id") or "").strip()
        if not tcg_id:
            return CompSourceQuote("tcgplayer", SOLD_DERIVED, "skipped", None, "", fetched,
                                   detail="no tcgplayer_id mapped")
        url = self.PRODUCT_URL.format(tcg_id=tcg_id)
        if self._render is None:
            return CompSourceQuote("tcgplayer", SOLD_DERIVED, "blocked", None, url, fetched,
                                   detail="rendering not enabled (Playwright dormant / not installed)")
        try:
            html = self._render(url)
        except Exception as exc:  # noqa: BLE001 - a render failure degrades, never crashes
            return CompSourceQuote("tcgplayer", SOLD_DERIVED, "blocked", None, url, fetched,
                                   detail=f"render failed: {str(exc)[:150]}")
        if any(marker in (html or "") for marker in _CHALLENGE_MARKERS):
            return CompSourceQuote("tcgplayer", SOLD_DERIVED, "blocked", None, url, fetched,
                                   detail="challenge/interstitial page (recorded blocked, not evaded)")
        price = _tcg_market_price(html or "")
        if price is None or price <= 0:
            return CompSourceQuote("tcgplayer", SOLD_DERIVED, "no_match", None, url, fetched,
                                   detail="no market price node in the rendered page")
        return CompSourceQuote("tcgplayer", SOLD_DERIVED, "ok", price, url, fetched,
                               detail="TCGplayer rendered market price")
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_independent_sources.py -k tcg -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scanner/poke_api/independent_sources.py tests/test_poke_independent_sources.py
git commit -m "feat(poke): TCGplayer rendered adapter full logic, mocked (Phase F Task 8)"
```

---

### Task 9: Render probe → conditional Playwright install + wire (operator-gated)

**Files:**
- Modify: `scanner/poke_api/independent_sources.py` (add `playwright_render`)
- Modify: `requirements.txt` (only if probe is clean)
- Modify: `docs/poke/phase-f-independent-source-result-2026-07-06.md` (record the outcome)

> **GATE:** This task runs a real headless render of the TCGplayer product page. Do it **only** with explicit operator go-ahead. If the operator declines, or the render is blocked/challenged, STOP after recording the outcome — the `blocked` shell from Task 8 stands and Phase F is already complete (gate closed at Task 7). Never add the dependency without a clean, approved probe.

- [ ] **Step 1: Operator render probe**

With operator approval, run a one-off supervised headless fetch of `https://www.tcgplayer.com/product/610516` (Umbreon ex 161) and confirm a parseable "Market Price: $X" with no challenge wall. Record the outcome (clean / blocked / declined).

- [ ] **Step 2 (clean probe only): Add the guarded render function**

Append to `scanner/poke_api/independent_sources.py`:

```python
def playwright_render(url: str, *, timeout_ms: int = 20000) -> str:
    """Headless-render a page and return its HTML after the market-price node hydrates.
    Guarded import: if Playwright/chromium is unavailable this raises, and the adapter
    turns the failure into a ``blocked`` quote (never crashes). Wired only after the
    operator-approved render probe."""
    from playwright.sync_api import sync_playwright  # optional dependency, imported lazily
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=UA)
            page.goto(url, timeout=timeout_ms)
            page.wait_for_selector("text=Market Price", timeout=timeout_ms)
            return page.content()
        finally:
            browser.close()
```

- [ ] **Step 3 (clean probe only): Add the dependency**

Append `playwright>=1.40` to `requirements.txt`, then:

```bash
.venv/Scripts/pip.exe install "playwright>=1.40"
.venv/Scripts/python.exe -m playwright install chromium
```

- [ ] **Step 4 (clean probe only): Record a live TCGplayer comp**

With `poke.independent_sources: true`, wire the render into the CLI path by building sources with `enable_render=True, render=playwright_render` (extend `_record_independent` to pass these when a `--render` flag is set), then:

```bash
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli record-asset-comp --asset-key umbreon_ex_161_raw_nm --refresh-independent --render
```

Record the resulting `tcgplayer` ledger row in the result doc.

- [ ] **Step 5: Verify suite stays network-free + green**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, no browser launched by the suite (render remains mocked in tests).

- [ ] **Step 6: Record the outcome + commit**

Update `docs/poke/phase-f-independent-source-result-2026-07-06.md` with the render-probe outcome (clean → installed + `tcgplayer` row recorded; or declined/blocked → shell retained). Commit:

```bash
git add requirements.txt scanner/poke_api/independent_sources.py scanner/poke_api/edge_cli.py docs/poke/phase-f-independent-source-result-2026-07-06.md
git commit -m "feat(poke): conditional Playwright render for TCGplayer, operator-gated (Phase F Task 9)"
```

---

## Self-review notes (author)

- **Spec coverage:** F1 → Tasks 1–2; graded lock (rev 3) → Task 3; F3 wiring + config → Tasks 3–4; F3 CLI + slug-fallback fix → Task 5; F4 cross-source → Task 6; F5 seed+record+result-doc (rev 4) → Task 6; F6 tests/docs → Task 7; F2 TCGplayer conditional (rev 2) → Tasks 8–9; completion gate (rev 1) → gate closes at Task 7, TCGplayer off it.
- **0-PPT-credit guarantee:** `resolve_independent_asset_row` never accepts/constructs a PPT client (Task 3), asserted in Task 7. `--refresh-independent` never calls `expected_asset_credits`/PPT (Task 5).
- **Type consistency:** adapters emit `CompSourceQuote(source, kind, status, price, url, fetched_at, ...)`; the graded note travels via `raw_excerpt`/`detail` and is read in `resolve_graded_comp`. `resolve_independent_asset_row` returns the legacy row dict consumed by `record_asset_comp` / `_row_primary_source`.
- **WATCH invariant:** no task touches `opportunities.py`, candidate wiring, or edge decision classes — a comp is added; decisions stay WATCH without a verified entry.
