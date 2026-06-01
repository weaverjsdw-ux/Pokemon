"""Per-retailer scanner health.

The adapters hit undocumented public endpoints that fail in distinct ways
that used to all look identical (a bare ``None``):

  - genuinely out of stock        -> healthy, just no positive results
  - blocked / rate-limited (403/429) -> degraded source, retry later
  - parser drift (HTTP 200, 0 rows) -> broken source, needs a code fix
  - network/transport error        -> transient, retry

This module records those outcomes per retailer so the CLI and web UI can
show *why* a retailer is quiet instead of leaving the operator guessing.
It is a process-local, thread-safe singleton; every function is
side-effect-only and never raises, so wiring it into the scan loop can't
break a scan.
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

# A retailer is "down" once this many consecutive failures pile up.
DOWN_AFTER_CONSECUTIVE_FAILURES = 3
# Health older than this (no check at all) is reported as stale/unknown.
STALE_AFTER_SECONDS = 30 * 60


@dataclass
class RetailerHealth:
    slug: str
    last_check_ts: int | None = None
    last_success_ts: int | None = None
    last_status: str = ""        # "OK" | "NO_DATA" | "BLOCKED" | "ERROR" | "DISCOVERY_FAILED"
    last_detail: str = ""        # human-readable last note (error text, etc.)
    last_http_status: int | None = None  # last raw HTTP code seen for this retailer
    consecutive_failures: int = 0
    total_checks: int = 0
    total_successes: int = 0
    last_items_found: int = 0

    def state(self, now: int | None = None) -> str:
        """Coarse health bucket for display: healthy/degraded/down/unknown."""
        if self.last_check_ts is None:
            return "unknown"
        if self.consecutive_failures >= DOWN_AFTER_CONSECUTIVE_FAILURES:
            return "down"
        now = now if now is not None else int(time.time())
        if self.last_success_ts is None:
            return "degraded"
        if self.consecutive_failures > 0:
            return "degraded"
        if now - self.last_success_ts > STALE_AFTER_SECONDS:
            return "degraded"
        return "healthy"

    def as_dict(self, now: int | None = None) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state(now)
        return data


class HealthRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_slug: dict[str, RetailerHealth] = {}

    def _get(self, slug: str) -> RetailerHealth:
        h = self._by_slug.get(slug)
        if h is None:
            h = RetailerHealth(slug=slug)
            self._by_slug[slug] = h
        return h

    def record_check(self, slug: str) -> None:
        with self._lock:
            h = self._get(slug)
            h.last_check_ts = int(time.time())
            h.total_checks += 1

    def record_success(self, slug: str, items: int = 0, detail: str = "") -> None:
        with self._lock:
            h = self._get(slug)
            now = int(time.time())
            h.last_check_ts = now
            h.last_success_ts = now
            h.last_status = "OK"
            h.last_detail = detail
            h.last_items_found = items
            h.consecutive_failures = 0
            h.total_successes += 1

    def record_failure(self, slug: str, status: str, detail: str = "") -> None:
        with self._lock:
            h = self._get(slug)
            h.last_check_ts = int(time.time())
            h.last_status = status
            h.last_detail = detail
            h.consecutive_failures += 1

    def note_http_status(self, slug: str, code: int | None) -> None:
        """Supplementary detail from the HTTP layer; does not change up/down
        state on its own (the scan-loop roll-up owns that)."""
        if code is None:
            return
        with self._lock:
            self._get(slug).last_http_status = int(code)

    def snapshot(self) -> list[dict[str, Any]]:
        now = int(time.time())
        with self._lock:
            return [h.as_dict(now) for h in self._by_slug.values()]

    def get(self, slug: str) -> dict[str, Any] | None:
        with self._lock:
            h = self._by_slug.get(slug)
            return h.as_dict() if h else None

    def reset(self) -> None:
        with self._lock:
            self._by_slug.clear()


# Process-wide singleton shared by the CLI loop and the web runner.
REGISTRY = HealthRegistry()


def record_check(slug: str) -> None:
    REGISTRY.record_check(slug)


def record_success(slug: str, items: int = 0, detail: str = "") -> None:
    REGISTRY.record_success(slug, items=items, detail=detail)


def record_failure(slug: str, status: str, detail: str = "") -> None:
    REGISTRY.record_failure(slug, status, detail=detail)


def note_http_status(slug: str, code: int | None) -> None:
    REGISTRY.note_http_status(slug, code)


def snapshot() -> list[dict[str, Any]]:
    return REGISTRY.snapshot()


def get(slug: str) -> dict[str, Any] | None:
    return REGISTRY.get(slug)


def reset() -> None:
    REGISTRY.reset()
