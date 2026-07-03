"""TrackaLacker curator feed — declared stub (wave 2, Playwright-gated).

Phase-0 verdicted TrackaLacker fetchable-playwright (strongest curator).
Stays a stub until the operator approves the Playwright dependency (spec
section 10, open question 2).
"""
from __future__ import annotations

from .base import StubSource


class TrackaLacker(StubSource):
    slug = "trackalacker"
    requires = "playwright"
    reason = ("Phase-0 verdict: JS-required (fetchable-playwright); needs the "
              "wave-2 Playwright decision")
