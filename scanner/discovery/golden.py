"""Golden checks for a rendered /poke dashboard. Shared by the sweep CLI and tests.

Returns HARD-FAIL messages (empty = pass). The caller halts rather than ship
a dashboard that is structurally broken or suspiciously thin (acquisition
failure), or that contains a deal row without provenance.
"""
from __future__ import annotations

import re

from .render import element_ids, nav_anchors, section_html

# Stock markers that must NEVER appear in the Buyable now section: a row there
# must carry verified positive stock evidence (in_stock/limited), not unknown,
# out-of-stock, or unverifiable. Belt over the STOP-gate suspenders.
_NON_BUYABLE_STOCK_MARKERS = ("stock-unknown", "stock-out_of_stock", "stock-unverifiable")


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
    buyable = section_html(html, "buyable-now")
    for marker in _NON_BUYABLE_STOCK_MARKERS:
        if marker in buyable:
            fails.append("Buyable now section contains a row without positive stock evidence "
                         f"({marker})")
            break
    return fails
