"""Shared HTTP client wrapper used by every retailer adapter.

Folds three concerns into one place so each adapter doesn't reinvent them:

1. Retry + exponential backoff on transient failures (5xx, connection
   errors, timeouts). 4xx is *not* retried — that's a config bug, not
   transient.
2. Per-retailer health tracking: too many consecutive failures and the
   retailer is auto-disabled for `cooldown_seconds`, so a broken
   adapter doesn't burn the whole poll budget. Reset on first success.
3. Cost-guard: a hard ceiling on requests/hour per retailer. Once hit,
   subsequent calls raise BudgetExceeded until the rolling window
   slides. Protects against runaway loops accidentally pounding a site.

These are the things every "I built a scraper" project misses on the
first pass and then duct-tapes in retailer-by-retailer."""
from __future__ import annotations

import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import requests

from .log import get_logger

log = get_logger(__name__)

_DEFAULT_BACKOFF = (1.0, 2.0, 5.0)  # seconds; len = max retries
_DEFAULT_HEALTH_FAIL_THRESHOLD = 5
_DEFAULT_HEALTH_COOLDOWN_SECONDS = 15 * 60
_DEFAULT_RATE_PER_HOUR = 2000


class BudgetExceeded(RuntimeError):
    """Raised when a retailer's per-hour request ceiling has been hit."""


class RetailerDisabled(RuntimeError):
    """Raised when a retailer is currently auto-disabled by the health tracker."""


@dataclass
class _Health:
    fails: int = 0
    disabled_until: float = 0.0
    request_times: deque[float] = field(default_factory=deque)
    # (timestamp, response_ms) tuples for the last hour; powers anomaly_factor
    response_samples: deque = field(default_factory=deque)


class HTTPClient:
    """Wraps requests.Session with retry, health, and budget.

    One instance per process is fine; per-retailer state is keyed by the
    `retailer` argument to request().
    """

    def __init__(
        self,
        fail_threshold: int = _DEFAULT_HEALTH_FAIL_THRESHOLD,
        cooldown_seconds: int = _DEFAULT_HEALTH_COOLDOWN_SECONDS,
        rate_per_hour: int = _DEFAULT_RATE_PER_HOUR,
        backoff: tuple[float, ...] = _DEFAULT_BACKOFF,
    ) -> None:
        self.fail_threshold = fail_threshold
        self.cooldown_seconds = cooldown_seconds
        self.rate_per_hour = rate_per_hour
        self.backoff = backoff
        self.operator_email = ""    # set from config at startup
        self.session = requests.Session()
        self._health: dict[str, _Health] = {}
        self._lock = threading.Lock()

    # --- public API ---

    def is_disabled(self, retailer: str) -> bool:
        h = self._health.get(retailer)
        return bool(h and h.disabled_until > time.time())

    def health_snapshot(self) -> dict[str, dict[str, Any]]:
        """For heartbeat / dashboard. Read-only view."""
        now = time.time()
        out: dict[str, dict[str, Any]] = {}
        for name, h in self._health.items():
            recent_resp = _trim_response_samples(h.response_samples, now, 3600)
            out[name] = {
                "fails": h.fails,
                "disabled": h.disabled_until > now,
                "disabled_for": max(0, int(h.disabled_until - now)),
                "requests_last_hour": _count_recent(h.request_times, now, 3600),
                "p50_ms": _percentile(recent_resp, 50),
                "p95_ms": _percentile(recent_resp, 95),
            }
        return out

    def anomaly_factor(self, retailer: str) -> float:
        """Return a multiplier in [0.25, 1.0] for the scan interval.

        Below 1.0 means 'poll faster'. Computed from the ratio of recent
        (last 5 min) median response time to longer-term (last 1 hour)
        median. Elevated latency on public site endpoints often correlates
        with imminent drops because retailer load spikes. Cap at 0.25 so
        even a 10x spike doesn't drive the cadence past a reasonable floor."""
        h = self._health.get(retailer)
        if h is None or len(h.response_samples) < 10:
            return 1.0
        now = time.time()
        recent = [ms for ts, ms in h.response_samples if ts >= now - 300]
        hour = [ms for ts, ms in h.response_samples if ts >= now - 3600]
        if len(recent) < 3 or len(hour) < 10:
            return 1.0
        recent_med = _percentile(recent, 50)
        hour_med = _percentile(hour, 50)
        if not hour_med:
            return 1.0
        ratio = recent_med / hour_med
        if ratio < 1.5:
            return 1.0
        # 1.5x -> 0.66; 3x -> 0.33; 10x -> 0.25 (clamped)
        return max(0.25, 1.0 / ratio)

    def request(
        self,
        retailer: str,
        method: str,
        url: str,
        *,
        timeout: float = 15.0,
        retries: int | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        """Issue an HTTP request on behalf of `retailer`.

        - Raises RetailerDisabled if the adapter is in cooldown.
        - Raises BudgetExceeded if the per-hour ceiling is hit.
        - Retries transient failures with backoff; raises the final
          exception if all retries are exhausted.
        - 4xx is returned as-is (it's a config/code bug, not transient).
        """
        with self._lock:
            h = self._health.setdefault(retailer, _Health())

        now = time.time()
        if h.disabled_until > now:
            raise RetailerDisabled(
                f"{retailer} disabled for {int(h.disabled_until - now)}s "
                f"after {h.fails} consecutive failures"
            )
        if _count_recent(h.request_times, now, 3600) >= self.rate_per_hour:
            raise BudgetExceeded(
                f"{retailer} hit {self.rate_per_hour} req/hour ceiling"
            )

        max_attempts = (retries if retries is not None else len(self.backoff)) + 1
        last_exc: Exception | None = None
        # Inject From: header so retailers can ID/contact the operator.
        if self.operator_email and "headers" in kwargs:
            kwargs = dict(kwargs)
            kwargs["headers"] = {**kwargs["headers"]}
            kwargs["headers"].setdefault("From", self.operator_email)
        for attempt in range(max_attempts):
            try:
                started = time.time()
                h.request_times.append(started)
                resp = self.session.request(method, url, timeout=timeout, **kwargs)
                elapsed_ms = (time.time() - started) * 1000.0
                h.response_samples.append((started, elapsed_ms))
                if 500 <= resp.status_code < 600:
                    raise requests.HTTPError(
                        f"{resp.status_code} {resp.reason}", response=resp
                    )
                # 2xx / 3xx / 4xx — return; 4xx is *not* retried.
                self._mark_success(retailer)
                return resp
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                last_exc = exc
                if attempt + 1 >= max_attempts:
                    break
                delay = self.backoff[min(attempt, len(self.backoff) - 1)]
                delay *= random.uniform(0.8, 1.3)  # jitter
                log.warning(
                    "retailer=%s attempt=%d/%d %s — retry in %.1fs",
                    retailer, attempt + 1, max_attempts, exc, delay,
                )
                time.sleep(delay)

        self._mark_failure(retailer)
        assert last_exc is not None
        raise last_exc

    # --- internals ---

    def _mark_success(self, retailer: str) -> None:
        h = self._health.setdefault(retailer, _Health())
        if h.fails:
            log.info("retailer=%s recovered after %d failures", retailer, h.fails)
        h.fails = 0
        h.disabled_until = 0.0

    def _mark_failure(self, retailer: str) -> None:
        h = self._health.setdefault(retailer, _Health())
        h.fails += 1
        if h.fails >= self.fail_threshold and h.disabled_until <= time.time():
            h.disabled_until = time.time() + self.cooldown_seconds
            log.error(
                "retailer=%s auto-disabled for %ds after %d consecutive failures",
                retailer, self.cooldown_seconds, h.fails,
            )


def _count_recent(times: deque[float], now: float, window_seconds: int) -> int:
    """Trim the deque to only entries within `window_seconds` and return count."""
    cutoff = now - window_seconds
    while times and times[0] < cutoff:
        times.popleft()
    return len(times)


def _trim_response_samples(samples: deque, now: float, window_seconds: int) -> list[float]:
    """Drop samples older than the window; return the trimmed ms values."""
    cutoff = now - window_seconds
    while samples and samples[0][0] < cutoff:
        samples.popleft()
    return [ms for _, ms in samples]


def _percentile(values, p: int) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(len(s) * p / 100)))
    return s[k]


# Process-wide default client. Adapters use this; tests can inject their own.
default_client = HTTPClient()
