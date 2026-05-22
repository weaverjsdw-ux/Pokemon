"""Detect when a retailer is shadow-banning or captcha-challenging us.

Every adapter has the same kind of failure mode: the response comes back
200 OK but the body is a captcha page, a Cloudflare interstitial, or an
empty payload that doesn't match the expected schema. The HTTP layer
can't see those — they're "successful" requests as far as TCP goes.

This module gives adapters a single check they can apply to a response
body. When detection fires, the adapter marks a logical failure on the
shared HTTP client (which then drives the existing auto-disable logic).

Patterns are intentionally conservative — false positives here would
disable a working adapter."""
from __future__ import annotations

import re
from dataclasses import dataclass

# Generic markers seen across most "you've been challenged" walls.
_GENERIC_MARKERS = [
    # Cloudflare
    "Just a moment...",
    "cf-browser-verification",
    "cf_chl_opt",
    "/cdn-cgi/challenge-platform/",
    # PerimeterX / DataDome / Akamai
    "px-captcha", "datadome-captcha", "_pxhd", "ak_bmsc",
    # Generic captcha
    "captcha-image",
    "Enter the characters you see",
    "/errors/validateCaptcha",
    # Generic "are you a bot"
    "Request blocked", "Access Denied",
]

# Per-retailer overlay. Adapters can extend if they have higher-fidelity
# markers; falling back to generic catches everyone.
RETAILER_MARKERS: dict[str, list[str]] = {
    "amazon":   ["captcha-image", "errors/validateCaptcha"],
    "walmart":  ["px-captcha", "_pxhd", "Robot or human?"],
    "target":   ["cf-browser-verification", "Just a moment..."],
}


@dataclass
class Detection:
    blocked: bool
    reason: str


def detect_block(retailer: str, body: str, status_code: int = 200) -> Detection:
    """Return Detection(blocked=True, reason=...) when the response looks
    like a challenge / block / shadow-ban, else Detection(False, "")."""
    if status_code == 429:
        return Detection(True, f"http 429 too-many-requests")
    if status_code in (401, 403):
        return Detection(True, f"http {status_code} access denied")
    if not body:
        return Detection(False, "")
    markers = RETAILER_MARKERS.get(retailer, []) + _GENERIC_MARKERS
    for marker in markers:
        if marker in body:
            return Detection(True, f"matched marker: {marker!r}")
    # Cloudflare also serves a 503 with a JS challenge — surface that.
    if status_code == 503 and "challenge" in body.lower():
        return Detection(True, "503 with challenge body")
    return Detection(False, "")


def looks_like_html_error(body: str) -> bool:
    """Lightweight heuristic: a JSON endpoint returning HTML usually means
    the upstream redirected us to an error/login page."""
    if not body:
        return False
    head = body.lstrip()[:200].lower()
    return head.startswith("<!doctype html") or head.startswith("<html")


# Compiled regex variants for the few cases where substring search isn't
# enough. Currently unused but exposed for future adapter authors.
CAPTCHA_RE = re.compile(r"captcha|robot[- ]?check|are you human", re.I)
