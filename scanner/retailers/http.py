"""Shared HTTP helper with polite retry/backoff for flaky public endpoints.

The retailer adapters hit undocumented or rate-limited public endpoints
(RedSky, Walmart product pages, GameStop BOPIS, Pokemon Center Shopify).
A single 429 or transient 5xx shouldn't silently drop a stock check for a
whole poll cycle, so this helper retries those with exponential backoff,
honoring a `Retry-After` header when the server sends one.

GET/POST here are stock-query requests only - they never mutate cart or
purchase state, matching the scanner's no-purchase/no-cart contract.

Adapters call ``http.get(...)`` / ``http.post(...)`` instead of direct
``requests`` calls. The call
goes through the module-level ``requests`` object at call time, so tests
that ``monkeypatch.setattr("scanner.retailers.<mod>.requests.get", ...)``
still intercept it (they mutate the shared ``requests`` module).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
from typing import Any, Callable

import requests

from .. import health

# 429 = rate limited; 5xx = transient server hiccup. 4xx (other than 429)
# are real client errors and not worth retrying.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF = 1.5  # seconds; exponential base


def _redact_query_strings(text: str) -> str:
    return re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?...", text)


def _retry_after_seconds(resp: Any, attempt: int, backoff: float) -> float:
    """Prefer the server's Retry-After (seconds), else exponential backoff."""
    headers = getattr(resp, "headers", None) or {}
    raw = headers.get("Retry-After") if hasattr(headers, "get") else None
    if raw:
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(str(raw))
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                pass
    return backoff * (2 ** attempt)


def _request(
    method: str,
    url: str,
    *,
    retailer: str = "",
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff: float = DEFAULT_BACKOFF,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> requests.Response:
    """Request ``url`` with retry/backoff on rate-limit and transient 5xx.

    Returns the final :class:`requests.Response` (the caller still inspects
    ``status_code`` / calls ``raise_for_status`` as before). If every attempt
    fails at the transport layer, re-raises the last ``requests`` exception.

    ``kwargs`` are forwarded to the selected ``requests`` method.
    """
    last_exc: requests.RequestException | None = None
    resp: requests.Response | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = getattr(requests, method)(url, **kwargs)
        except requests.RequestException as exc:
            last_exc = exc
            if attempt >= max_retries:
                if retailer:
                    health.record_failure(
                        retailer,
                        "ERROR",
                        _redact_query_strings(str(exc) or exc.__class__.__name__),
                    )
                raise
            sleep(backoff * (2 ** attempt))
            continue
        # FakeResponse objects in tests may omit status_code; treat as success.
        status = getattr(resp, "status_code", 200)
        if retailer:
            health.note_http_status(retailer, status)
        if status in RETRY_STATUSES and attempt < max_retries:
            sleep(_retry_after_seconds(resp, attempt, backoff))
            continue
        return resp
    # Loop only exits via return/raise above, but satisfy the type checker.
    if last_exc is not None:
        raise last_exc
    assert resp is not None
    return resp


def get(
    url: str,
    *,
    retailer: str = "",
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff: float = DEFAULT_BACKOFF,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> requests.Response:
    """GET ``url`` with retry/backoff on rate-limit and transient 5xx."""
    return _request(
        "get",
        url,
        retailer=retailer,
        max_retries=max_retries,
        backoff=backoff,
        sleep=sleep,
        **kwargs,
    )


def post(
    url: str,
    *,
    retailer: str = "",
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff: float = DEFAULT_BACKOFF,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> requests.Response:
    """POST ``url`` with retry/backoff on rate-limit and transient 5xx."""
    return _request(
        "post",
        url,
        retailer=retailer,
        max_retries=max_retries,
        backoff=backoff,
        sleep=sleep,
        **kwargs,
    )
