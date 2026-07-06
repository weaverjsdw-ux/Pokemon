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
