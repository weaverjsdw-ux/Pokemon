"""Golden checks for a rendered /poke dashboard. Shared by the sweep CLI and tests.

Returns HARD-FAIL messages (empty = pass). The caller halts rather than ship
a dashboard that is structurally broken or suspiciously thin (acquisition
failure), or that contains a deal row without provenance.
"""
from __future__ import annotations

import re

from .render import element_ids, nav_anchors, section_html

# A row in the Buyable now section must carry verified POSITIVE stock
# (in_stock/limited) AND non-empty evidence. Belt over the STOP-gate suspenders.
# Matches only the stock cell's class attribute (never the escaped free-text
# evidence, which could legitimately contain a 'stock-...' token).
_STOCK_CLASS_RE = re.compile(r'class="[^"]*\bstock-(\w+)"')
_POSITIVE_STOCK_TITLE_RE = re.compile(
    r'class="stock stock-(?:in_stock|limited)" title="([^"]*)"')
_POSITIVE_STATUSES = ("in_stock", "limited")


def _buyable_now_fails(html: str) -> list[str]:
    section = section_html(html, "buyable-now")
    fails: list[str] = []
    for m in _STOCK_CLASS_RE.finditer(section):
        if m.group(1) not in _POSITIVE_STATUSES:
            fails.append("Buyable now section contains a non-positive stock row "
                         f"(stock-{m.group(1)})")
            return fails
    for m in _POSITIVE_STOCK_TITLE_RE.finditer(section):
        if not m.group(1).strip():
            fails.append("Buyable now section contains a row without stock evidence")
            return fails
    return fails


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
    fails.extend(_buyable_now_fails(html))
    return fails
