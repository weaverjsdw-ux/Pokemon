"""Target search discovery — declared stub (wave 2, Playwright-gated).

Probe evidence (docs/poke/target-search-probe-2026-07-03.md): the search page
is a JS shell to plain requests and the plp_search_v2 API answers with a
captcha challenge. No evasion is permitted; this stays a stub until the
operator approves the Playwright dependency. The restock lane's Target
adapter (RedSky product_fulfillment by TCIN) is unaffected.
"""
from __future__ import annotations

from .base import StubSource


class TargetSearch(StubSource):
    slug = "target_search"
    requires = "playwright"
    reason = ("plain-requests probe 2026-07-03: search page is a JS shell and "
              "plp_search_v2 is captcha-walled; needs the wave-2 Playwright "
              "decision (docs/poke/target-search-probe-2026-07-03.md)")
