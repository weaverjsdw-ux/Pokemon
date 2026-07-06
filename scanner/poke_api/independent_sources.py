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


def pricecharting_page_number_from_html(body: str) -> str | None:
    """The card number (``#NNN``) from the detail page's product-name ``<h1>`` (or the
    ``<title>`` as a fallback), as a digits-only string, or ``None`` when the page
    exposes no confident number (never guesses). Used at the record boundary (F.1) to
    catch a slug that points at the wrong card — a table-only page with no h1/title
    returns ``None`` so the guard is simply skipped, never a false mismatch."""
    body = body or ""
    for pat in (r"<h1[^>]*>(.*?)</h1>", r"<title[^>]*>(.*?)</title>"):
        m = re.search(pat, body, flags=re.I | re.S)
        if m:
            num = re.search(r"#\s*(\d+)", m.group(1))
            if num:
                return num.group(1)
    return None


def pricecharting_card_prices_from_html(body: str) -> dict:
    """Parse a PriceCharting card DETAIL page price table.

    Returns ``{"cells": {cell_id: price}, "number": str|None, "blocked": bool}``. A
    challenge/interstitial page -> ``blocked: True`` with no cells. Malformed/empty HTML
    -> empty cells, ``blocked: False`` (honest no-source, never a crash). ``number`` is
    the page's card number (F.1 wrong-slug guard input) or ``None``."""
    body = body or ""
    if any(marker in body for marker in _CHALLENGE_MARKERS):
        return {"cells": {}, "number": None, "blocked": True}
    cells: dict[str, float] = {}
    for cid in (PC_RAW_CELL, PC_PSA10_CELL, *PC_GRADE_CELLS.values()):
        price = _price_cell(body, cid)
        if price is not None and price > 0:
            cells[cid] = price
    return {"cells": cells, "number": pricecharting_page_number_from_html(body),
            "blocked": False}


# NM-ish raw conditions the single loose "Ungraded" price may stand in for. A non-NM
# raw (LP/MP/HP/DMG…) is NOT auto-recorded off Ungraded — that would over-value it.
_NM_PROXY_CONDITIONS = frozenset({"", "nm", "near mint", "nm-mt", "nmmt", "mint", "m",
                                  "near-mint"})


def raw_condition_recordable(asset: dict) -> tuple[bool, str]:
    """(recordable?, reason) for auto-recording a raw asset's Ungraded comp. PriceCharting
    "Ungraded" is a *single* loose price that does not distinguish raw condition, so only
    an NM-ish proxy may be auto-recorded off it; a non-NM raw returns ``(False, reason)``
    (F.1 makes the Phase-F hand-decision a programmatic guard). Graded assets are
    unaffected — the rule is raw-only."""
    if str(asset.get("asset_class") or "").strip().lower() != "raw":
        return True, ""
    cond = str(asset.get("condition") or "").strip().lower()
    if cond in _NM_PROXY_CONDITIONS:
        return True, ""
    return False, (f"PriceCharting Ungraded is not condition-exact for condition="
                   f"{asset.get('condition')!r}; not auto-recorded (map a condition-"
                   f"specific source or use the audited from-value path)")


def _slug_number_mismatch(asset: dict, page_number: Any) -> tuple[bool, str]:
    """(mismatch?, reason) for the F.1 wrong-slug guard. Only a CONFIDENT mismatch
    counts: the asset carries a ``card_number`` AND the page exposes a number AND they
    differ (digits-only). Any uncertainty (no card_number, or no page number) => no
    mismatch, so a good fetch is never falsely suppressed."""
    want = re.sub(r"\D", "", str(asset.get("card_number") or ""))
    got = re.sub(r"\D", "", str(page_number or ""))
    if want and got and want != got:
        return True, (f"page card #{got} != asset card_number {want} "
                      f"(wrong pricecharting_slug?) — recorded nothing")
    return False, ""


class _PriceChartingBase:
    """Shared plain-requests fetch of a PriceCharting detail page (0 PPT credits)."""

    def __init__(self, session: Any = None) -> None:
        self.session = session or requests.Session()

    def _fetch_cells(self, slug: Any, checked_at: int):
        """(cells, number, url, status, detail). status: skipped|blocked|error|ok.
        ``number`` is the page's card number (F.1 wrong-slug guard) or None."""
        slug = str(slug or "").strip().strip("/")
        if not slug:
            return {}, None, "", "skipped", "no pricecharting_slug mapped"
        url = PC_GAME_URL.format(slug=slug)
        try:
            resp = self.session.get(
                url, headers={"User-Agent": UA, "Accept": "text/html"}, timeout=20)
        except requests.RequestException as exc:
            return {}, None, url, "error", str(exc)[:200]
        if getattr(resp, "status_code", 200) in (403, 429):
            return {}, None, url, "blocked", f"HTTP {resp.status_code}"
        parsed = pricecharting_card_prices_from_html(resp.text)
        if parsed["blocked"]:
            return {}, None, url, "blocked", "challenge/interstitial page (recorded blocked, not evaded)"
        return parsed["cells"], parsed.get("number"), url, "ok", ""


class PriceChartingRawSource(_PriceChartingBase):
    """Raw single Ungraded (``used_price``) comp, exact-slug only. Sold-derived,
    slug ``pricecharting``. Ungraded is a loose/NM proxy — condition not distinguished."""

    def fetch(self, asset: dict, checked_at: int) -> CompSourceQuote:
        fetched = _iso(checked_at)
        cells, number, url, status, detail = self._fetch_cells(asset.get("pricecharting_slug"), checked_at)
        if status != "ok":
            return CompSourceQuote("pricecharting", SOLD_DERIVED, status, None, url, fetched, detail=detail)
        mismatch, reason = _slug_number_mismatch(asset, number)
        if mismatch:
            return CompSourceQuote("pricecharting", SOLD_DERIVED, "no_match", None, url, fetched, detail=reason)
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
        cells, number, url, status, detail = self._fetch_cells(asset.get("pricecharting_slug"), checked_at)
        if status != "ok":
            return CompSourceQuote("pricecharting", SOLD_DERIVED, status, None, url, fetched, detail=detail)
        mismatch, reason = _slug_number_mismatch(asset, number)
        if mismatch:
            return CompSourceQuote("pricecharting", SOLD_DERIVED, "no_match", None, url, fetched, detail=reason)
        price = cells.get(cell_id)
        if price is None:
            return CompSourceQuote("pricecharting", SOLD_DERIVED, "no_match", None, url, fetched,
                                   detail=f"no {cell_id} cell on the PriceCharting page")
        return CompSourceQuote("pricecharting", SOLD_DERIVED, "ok", price, url, fetched,
                               detail=note, raw_excerpt=note)


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
