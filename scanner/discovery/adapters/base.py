"""Discovery source interface (spec section 9.3).

Adapters emit normalized CandidateDeals and NEVER raise out of discover():
degradations are recorded as a confidence.py state on the adapter (the
pipeline reports them into health under disc:<slug>). One taxonomy, no
parallel vocabulary.
"""
from __future__ import annotations

from typing import Any

from ... import confidence
from ..candidates import CandidateDeal


class DiscoverySource:
    slug: str = ""
    min_interval_seconds: int = 900
    requires: str = ""        # "" | "ebay_keyset" | "playwright"

    def __init__(self, **opts: Any) -> None:
        self.opts = opts
        self.state = confidence.READY
        self.state_detail = ""

    def _set_state(self, state: str, detail: str = "") -> None:
        self.state = state
        self.state_detail = detail

    def discover(self, cfg: Any, catalog: dict, set_watch: list[str],
                 **kwargs: Any) -> list[CandidateDeal]:
        """Return normalized candidates; record degradation via _set_state."""
        return []


class StubSource(DiscoverySource):
    """Declared not-implemented source: honest placeholder, never fakes rows."""

    reason: str = "not implemented"

    def discover(self, cfg: Any, catalog: dict, set_watch: list[str],
                 **kwargs: Any) -> list[CandidateDeal]:
        self._set_state(confidence.NOT_IMPLEMENTED, self.reason)
        return []
