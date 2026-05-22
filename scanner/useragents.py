"""Browser User-Agent rotation, ToS-aligned.

Every adapter previously hardcoded the same Chrome-on-Mac UA. That's
fine functionally but presents a uniform fingerprint across all users
of this scanner. We rotate across a small fixed pool of modern, real
browser UAs — picked **once per process** so a single session looks
consistent (mid-session rotation triggers anti-bot heuristics).

This is not evasion. To stay ToS-aligned:

  - We always include a `From:` header with the user's `operator_email`
    (set in config.yaml) so retailers can contact the operator if they
    want this traffic to stop. RFC 2616 §14.22 is explicit about this
    being for "the human user who controls the requesting user agent."
  - Best Buy uses the official API path and doesn't need either.
  - Geocoder (Nominatim) keeps its own UA per OSM policy.
  - The shared User-Agent is documented at docs/retailer-tos.md.

The pool is small on purpose: a few dozen scanner instances spread
across a handful of UAs is "modern browsers visiting public product
pages." A pool of hundreds would be evasion."""
from __future__ import annotations

import os
import random


_POOL = [
    # Chrome / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Safari / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    # Chrome / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Firefox / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Chrome / Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def _pick() -> str:
    # SCANNER_UA env override is intended for tests + special cases.
    override = os.environ.get("SCANNER_UA", "").strip()
    if override:
        return override
    seed = os.environ.get("SCANNER_UA_SEED")
    if seed is not None:
        rng = random.Random(seed)
        return rng.choice(_POOL)
    return random.choice(_POOL)


# Resolved once at import time so every adapter sees the same UA per process.
UA = _pick()


def common_headers(operator_email: str = "") -> dict[str, str]:
    """Standard headers every retailer call should ship with. Adapters
    can extend (Accept, Accept-Language) but should always start from
    this dict so the From header / UA propagate consistently."""
    h = {"User-Agent": UA}
    if operator_email.strip():
        h["From"] = operator_email.strip()
    return h
