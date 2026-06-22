"""Shared product-priority heuristic.

Used by both the scan loop (to flag chase products in alerts) and the web
UI (to sort the stock board). Kept in one place so the two never drift.
"""
from __future__ import annotations

from typing import Any

PRIORITY_KEYWORDS = (
    "prismatic",
    "151",
    "surging sparks",
    "journey together",
    "evolving skies",
    "mega evolution",
    "booster bundle",
    "booster box",
    "play booster",
    "collector booster",
    "jumpstart booster",
    "draft night",
    "gift bundle",
    "bundle",
    "elite trainer box",
    "ultra-premium",
    "premium collection",
    "special collection",
)


def product_priority(product: dict[str, Any]) -> tuple[str, int]:
    """Return (label, score). Higher score sorts first."""
    text = " ".join(
        str(product.get(field, "")) for field in ("name", "game", "set", "type")
    ).lower()
    if any(keyword in text for keyword in PRIORITY_KEYWORDS):
        return "High priority", 100
    return "Standard", 10
