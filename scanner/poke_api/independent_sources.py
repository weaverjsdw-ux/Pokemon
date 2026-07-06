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
