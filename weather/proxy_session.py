"""A requests.Session wrapper that rotates through a pool of proxies.

The session sends each request through the "current" proxy. When a request
fails for a transient reason -- a connection/timeout error, a 429 rate-limit
response, or a 5xx server error -- the session advances to the next proxy and
retries. Proxies that just produced a failure are put on a short cooldown so
the rotation skips them until they have had a chance to recover.

This keeps a CLI within a public API's per-IP rate limits without hammering a
single exit address. It is *not* a tool for defeating authentication or
hiding abusive traffic: be a good API citizen, honour robots/ToS, and keep
your aggregate request rate reasonable.

Proxy file format (JSON). Either a bare list of URLs::

    ["http://user:pass@host1:8080", "http://host2:8080"]

or an object with a "proxies" key, whose entries may be URL strings or
per-scheme maps::

    {
      "proxies": [
        "http://host1:8080",
        {"http": "http://host2:8080", "https": "http://host2:8080"}
      ]
    }

A bare URL is applied to both http and https schemes.
"""
from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger("weather.proxy")

# Status codes worth retrying on a different proxy. 429 = rate limited;
# 5xx = upstream/proxy trouble that another exit may not share.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class AllProxiesFailedError(RuntimeError):
    """Raised when every available proxy has been tried without success."""


@dataclass
class Proxy:
    """A single proxy entry plus its rotation bookkeeping."""

    # Mapping passed straight to requests' ``proxies=`` argument, e.g.
    # {"http": "http://host:8080", "https": "http://host:8080"}.
    mapping: dict[str, str]
    label: str
    # Wall-clock time before which this proxy should be skipped.
    cooldown_until: float = 0.0
    failures: int = 0

    def available(self, now: float) -> bool:
        return now >= self.cooldown_until


def _normalise_entry(entry: Any) -> dict[str, str]:
    """Turn one proxy-file entry into a requests proxy mapping."""
    if isinstance(entry, str):
        url = entry.strip()
        if not url:
            raise ValueError("empty proxy URL in proxy file")
        return {"http": url, "https": url}
    if isinstance(entry, dict):
        mapping = {
            scheme: str(url).strip()
            for scheme, url in entry.items()
            if str(url).strip()
        }
        if not mapping:
            raise ValueError(f"proxy entry has no usable URLs: {entry!r}")
        return mapping
    raise ValueError(f"unsupported proxy entry type: {type(entry).__name__}")


def load_proxies(path: str | Path) -> list[Proxy]:
    """Read and validate proxies from a JSON file."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"proxy file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"proxy file {path} is not valid JSON: {exc}") from exc

    if isinstance(raw, dict):
        entries = raw.get("proxies", [])
    elif isinstance(raw, list):
        entries = raw
    else:
        raise ValueError(
            f"proxy file {path} must be a JSON list or an object with a "
            f"'proxies' key, got {type(raw).__name__}"
        )

    if not entries:
        raise ValueError(f"proxy file {path} contains no proxies")

    proxies: list[Proxy] = []
    for entry in entries:
        mapping = _normalise_entry(entry)
        # A readable label without leaking embedded credentials.
        sample = mapping.get("https") or mapping.get("http") or ""
        proxies.append(Proxy(mapping=mapping, label=_redact(sample)))
    return proxies


def _redact(url: str) -> str:
    """Strip any ``user:pass@`` so credentials never reach the logs."""
    if "@" in url:
        scheme, _, rest = url.partition("://")
        host = rest.rsplit("@", 1)[-1]
        return f"{scheme}://{host}" if scheme else host
    return url


@dataclass
class ProxyRotatingSession:
    """HTTP session that cycles proxies on failure or rate limiting.

    Parameters
    ----------
    proxies:
        Pool to rotate through. Load one with :func:`load_proxies`.
    max_attempts:
        Total tries per logical request, across all proxies, before giving
        up. Defaults to one attempt per proxy.
    cooldown_seconds:
        How long a failing proxy is skipped before it may be tried again.
    backoff_base / backoff_cap:
        Exponential backoff (with jitter) applied between attempts, in
        seconds. ``Retry-After`` on a 429 overrides this when present.
    timeout:
        Per-request timeout passed to requests.
    shuffle:
        Randomise the starting proxy so concurrent runs don't stampede the
        same exit first.
    """

    proxies: list[Proxy]
    max_attempts: int = 0
    cooldown_seconds: float = 60.0
    backoff_base: float = 0.5
    backoff_cap: float = 30.0
    timeout: float = 15.0
    shuffle: bool = True
    session: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        if not self.proxies:
            raise ValueError("ProxyRotatingSession requires at least one proxy")
        if self.max_attempts <= 0:
            self.max_attempts = len(self.proxies)
        self._idx = random.randrange(len(self.proxies)) if self.shuffle else 0

    # -- proxy selection -------------------------------------------------

    def _next_proxy(self, now: float) -> Proxy:
        """Advance to the next proxy, preferring ones off cooldown.

        If every proxy is cooling down we still return the soonest-available
        one rather than stalling forever; the caller's backoff sleep gives it
        time to recover.
        """
        n = len(self.proxies)
        for _ in range(n):
            self._idx = (self._idx + 1) % n
            candidate = self.proxies[self._idx]
            if candidate.available(now):
                return candidate
        # All on cooldown: pick the one that frees up soonest.
        soonest = min(self.proxies, key=lambda p: p.cooldown_until)
        self._idx = self.proxies.index(soonest)
        return soonest

    def _penalise(self, proxy: Proxy, now: float) -> None:
        proxy.failures += 1
        proxy.cooldown_until = now + self.cooldown_seconds

    # -- backoff ---------------------------------------------------------

    def _sleep_for(self, attempt: int, retry_after: float | None) -> None:
        if retry_after is not None and retry_after > 0:
            delay = retry_after
        else:
            delay = min(self.backoff_cap, self.backoff_base * (2 ** attempt))
            delay += random.uniform(0, delay * 0.25)  # jitter
        if delay > 0:
            time.sleep(delay)

    @staticmethod
    def _parse_retry_after(resp: requests.Response) -> float | None:
        value = resp.headers.get("Retry-After")
        if not value:
            return None
        try:
            return float(value)  # delta-seconds form
        except ValueError:
            # HTTP-date form: best-effort, fall back to backoff if unparseable.
            try:
                from email.utils import parsedate_to_datetime

                when = parsedate_to_datetime(value)
                return max(0.0, when.timestamp() - time.time())
            except (TypeError, ValueError):
                return None

    # -- request ---------------------------------------------------------

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Issue a request, rotating proxies on failure / rate limit.

        Accepts the same keyword arguments as ``requests.Session.request``.
        Returns the first successful (non-retryable) response. Raises
        :class:`AllProxiesFailedError` if every attempt is exhausted.
        """
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Exception | None = None
        last_resp: requests.Response | None = None

        for attempt in range(self.max_attempts):
            is_last = attempt == self.max_attempts - 1
            now = time.monotonic()
            proxy = self._next_proxy(now)
            try:
                resp = self.session.request(
                    method, url, proxies=proxy.mapping, **kwargs
                )
            except requests.RequestException as exc:
                last_exc = exc
                self._penalise(proxy, now)
                log.warning(
                    "proxy %s failed (%s): %s; rotating",
                    proxy.label, type(exc).__name__, exc,
                )
                if not is_last:  # no point backing off right before we give up
                    self._sleep_for(attempt, None)
                continue

            if resp.status_code in RETRYABLE_STATUS:
                last_resp = resp
                retry_after = self._parse_retry_after(resp)
                self._penalise(proxy, now)
                log.warning(
                    "proxy %s got HTTP %s for %s; rotating%s",
                    proxy.label, resp.status_code, url,
                    f" (Retry-After={retry_after}s)" if retry_after else "",
                )
                if not is_last:
                    self._sleep_for(attempt, retry_after)
                continue

            # Success (any non-retryable status, including 4xx the caller
            # should see and handle, e.g. 404).
            proxy.failures = 0
            return resp

        if last_resp is not None:
            raise AllProxiesFailedError(
                f"all {self.max_attempts} attempts exhausted; last status "
                f"{last_resp.status_code} for {url}"
            )
        raise AllProxiesFailedError(
            f"all {self.max_attempts} attempts exhausted for {url}; "
            f"last error: {last_exc}"
        ) from last_exc

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", url, **kwargs)

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "ProxyRotatingSession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
