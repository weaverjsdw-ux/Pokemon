"""Slickdeals merchant-page resolver (Slice 6B).

A Slickdeals discovery candidate points at a *thread* page
(``slickdeals.net/f/<id>-<slug>``), not a buyable merchant page. This module
resolves that thread to a **safe, real merchant/buy URL** so the existing page
verifier (:func:`scanner.discovery.verify.verify_page`) can check live stock and
price. It never decides buyability — it only produces (or honestly fails to
produce) a URL.

Doctrine (all load-bearing):

* **One polite GET of the thread**, plus at most ``MAX_HOPS`` GETs to follow an
  internal Slickdeals redirect endpoint to its merchant landing URL. All fetches
  go through ``retailers/http.py`` (retry/backoff, query-string redaction).
  **No carts, no logins, no bot-wall evasion** — HTTP 403/429 is reported
  ``blocked``, never worked around.
* **Safe URLs only.** The resolved merchant URL must be ``http``/``https`` with a
  real host and must not still be on a slickdeals host (an unresolved internal /
  tracking-only redirect shell). Anything else is refused — no guessing.
* **Degrade, never guess.** A thread with no recognizable "See Deal" outbound
  structure is ``drift`` (the markup changed — re-probe), not a fabricated URL.

The failure vocabulary here is resolver-local (``blocked``/``unavailable``/
``drift``/``unresolved``); the verifier maps it onto its own terminal states so
this module never imports :mod:`scanner.discovery.verify` (no cycle).

**The featured "See Deal" selectors are live-confirmed** against a real thread
capture (thread 19650840, 2026-07-04); the legacy synthetic markers are kept
alongside. That featured CTA resolves to an internal ``/click`` redirect endpoint
whose merchant landing is followed live but is not exercised offline, so that hop
stays mocked in tests. Because resolution degrades rather than guesses, a stale
selector — or a ``/click`` endpoint that stops redirecting — under-alerts (safe)
instead of mis-alerting.
"""
from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import unquote, urljoin, urlparse

from ..retailers import http as retailer_http

MAX_HOPS = 5
EVIDENCE_MAX_CHARS = 300
# The only clickable-URL schemes; one allowlist for every gate in this module so
# the safety policy cannot drift between the follow loop and the final check.
_HTTP_SCHEMES = ("http", "https")
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# A "See Deal" outbound anchor is recognized by any of these markers (matched as
# a lowercased substring of the anchor's opening tag). Conservative on purpose:
# an unmarked anchor is never treated as the buy link, so a discussion thread
# with only nav/comment links -- or a page of *related*-deal cards -- resolves to
# drift rather than a guess.
#
# Two marker families, both load-bearing:
#   * legacy synthetic/representative -- documented patterns modelled by the
#     hand-authored fixtures; kept so those still resolve.
#   * live-confirmed -- the current Vue-rendered "Get Deal at <store>" CTA on a
#     real thread page (captured from thread 19650840 on 2026-07-04). Both live
#     markers sit on the featured deal's outclick <a>. Related-deal cards
#     (dealCardGrid__*) and in-post outclick links (data-cta="outclick" only, no
#     see-deal marker) carry NEITHER, so they are deliberately not selected.
# The featured CTA's href is an internal slickdeals /click redirect endpoint, so
# resolution still degrades (never guesses) if that endpoint stops redirecting.
_SEE_DEAL_MARKERS = ("data-role=\"seedealbutton\"", "seedeallink",
                     "dealbutton", "dealbtn",
                     "dealdetailsoutclickbutton", "data-qa-ddp-seedeal-button")
_ANCHOR_RE = re.compile(r"<a\b[^>]*>", re.I)
_HREF_RE = re.compile(r'\bhref="([^"]+)"', re.I)
_U2_RE = re.compile(r"[?&]u2=([^&]+)")


@dataclass(frozen=True)
class MerchantResolution:
    ok: bool
    original_url: str            # the slickdeals thread URL fed in
    resolved_url: str            # the merchant/buy URL; "" unless ok
    method: str                  # "u2_param" | "direct_href" | "redirect_chain" | ""
    checked_at: str              # ISO datetime of the resolution attempt
    evidence: str                # what was matched (original + resolved), <= 300 chars
    degraded_reason: str = ""    # honest cause when not ok
    failure_kind: str = ""       # "" when ok; else blocked|unavailable|drift|unresolved


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clip(text: str) -> str:
    return " ".join(str(text).split())[:EVIDENCE_MAX_CHARS]


def _redact(exc: Exception) -> str:
    return retailer_http._redact_query_strings(str(exc) or exc.__class__.__name__)


def _host(netloc: str) -> str:
    """Bare hostname from a urlparse netloc: userinfo + port stripped, lowercased.
    One implementation so every host check in this module normalizes identically."""
    return (netloc or "").lower().split("@")[-1].split(":")[0]


def _is_slickdeals(netloc: str) -> bool:
    host = _host(netloc)
    return host == "slickdeals.net" or host.endswith(".slickdeals.net")


def safe_merchant_url(url: str) -> bool:
    """True only for an http(s) URL with a real off-slickdeals host.

    Rejects empty/relative/unsafe-scheme URLs, hostless URLs, bare hosts with no
    dot (e.g. ``localhost``), and any URL still on a slickdeals host (an
    unresolved internal or tracking-only redirect shell).
    """
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    if parsed.scheme.lower() not in _HTTP_SCHEMES:
        return False
    host = _host(parsed.netloc)
    if not host or "." not in host:
        return False
    return not _is_slickdeals(parsed.netloc)


def _location(resp: Any) -> str | None:
    headers = getattr(resp, "headers", {}) or {}
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    return getter("Location") or getter("location")


def follow_to_merchant(
    url: str,
    *,
    http_get: Callable[..., Any] | None = None,
    max_hops: int = MAX_HOPS,
) -> tuple[str | None, str, str]:
    """Follow an internal Slickdeals redirect endpoint to its merchant landing.

    Returns ``(final_url | None, failure_kind, reason)``. Stops (without a fetch)
    as soon as the current URL points OFF slickdeals — that off-host URL is the
    merchant destination and is returned for the caller to re-validate. Each hop
    is scheme-checked before it is fetched; the hop count is capped so a redirect
    loop terminates instead of hanging. HTTP 403/429 is ``blocked`` (no evasion).
    """
    get = http_get or retailer_http.get
    current = url
    for _ in range(max_hops):
        scheme = urlparse(current).scheme.lower()
        if scheme not in _HTTP_SCHEMES:
            return None, "unresolved", f"redirect to unsupported scheme {scheme or 'none'!r}"
        if not _is_slickdeals(urlparse(current).netloc):
            return current, "", ""            # off-slickdeals: this is the merchant URL
        try:
            resp = get(current, headers={"User-Agent": _UA}, timeout=20,
                       allow_redirects=False, retailer="disc:slickdeals")
        except Exception as exc:              # transport failure, not a crash
            return None, "unavailable", f"redirect transport failure: {_redact(exc)}"
        status = getattr(resp, "status_code", 200)
        if status in (403, 429):
            return None, "blocked", f"HTTP {status} while following the redirect"
        if not (300 <= status < 400):
            return None, "unresolved", (
                f"redirect endpoint returned HTTP {status}, no merchant URL")
        location = _location(resp)
        if not location:
            return None, "unresolved", f"HTTP {status} redirect with no Location header"
        current = urljoin(current, location)
    # Arrival check for a merchant reached by exactly the max_hops-th redirect:
    # the loop advances `current` on its last iteration, so without this a chain
    # that lands off-slickdeals on the final permitted hop would be miscounted as
    # "exceeded" (off-by-one). Only http(s) off-slickdeals lands are accepted.
    if (urlparse(current).scheme.lower() in _HTTP_SCHEMES
            and not _is_slickdeals(urlparse(current).netloc)):
        return current, "", ""
    return None, "unresolved", f"redirect chain exceeded {max_hops} hops"


def _see_deal_hrefs(text: str) -> list[str]:
    """Every href on an anchor bearing a See-Deal marker, HTML-unescaped."""
    hrefs: list[str] = []
    for m in _ANCHOR_RE.finditer(text):
        tag = m.group(0)
        if any(marker in tag.lower() for marker in _SEE_DEAL_MARKERS):
            href_m = _HREF_RE.search(tag)
            if href_m:
                hrefs.append(html_lib.unescape(href_m.group(1)))
    return hrefs


def _merchant_from_href(href: str) -> tuple[str | None, str, bool]:
    """(merchant_url | None, method, needs_follow) for one outbound href.

    An absolute off-slickdeals http(s) href IS the merchant URL — used as-is,
    even if it carries an incidental ``u2`` query param of its own (``u2`` is a
    slickdeals redirect convention, not a merchant one). Only on a *slickdeals*
    host is ``u2=`` treated as the encoded outbound destination; a slickdeals
    http(s) href without a ``u2`` is a redirect endpoint to follow. Anything else
    (relative / javascript: / data:) → unusable.
    """
    parsed = urlparse(href)
    if parsed.scheme.lower() not in _HTTP_SCHEMES or not parsed.netloc:
        return None, "", False
    if not _is_slickdeals(parsed.netloc):
        return href, "direct_href", False
    u2 = _U2_RE.search(href)
    if u2:
        return unquote(u2.group(1)), "u2_param", False
    return None, "redirect_chain", True


def resolve_slickdeals_merchant(
    thread_url: str,
    *,
    http_get: Callable[..., Any] | None = None,
    checked_at: str = "",
) -> MerchantResolution:
    """Resolve a Slickdeals thread URL to a safe merchant/buy URL (or an honest
    failure). One GET of the thread, plus redirect follows only when the CTA is
    an internal redirect endpoint."""
    checked_at = checked_at or _now_iso()
    get = http_get or retailer_http.get

    def _fail(kind: str, reason: str) -> MerchantResolution:
        return MerchantResolution(
            ok=False, original_url=thread_url, resolved_url="", method="",
            checked_at=checked_at, evidence=_clip(reason),
            degraded_reason=_clip(reason), failure_kind=kind)

    try:
        resp = get(thread_url, headers={"User-Agent": _UA, "Accept": "text/html"},
                   timeout=20, retailer="disc:slickdeals")
    except Exception as exc:
        return _fail("unavailable", f"thread transport failure: {_redact(exc)}")
    status = getattr(resp, "status_code", 200)
    if status in (403, 429):
        return _fail("blocked", f"HTTP {status}; thread page blocked or rate-limited")
    if status != 200:
        return _fail("unavailable", f"HTTP {status} fetching the thread page")

    hrefs = _see_deal_hrefs(getattr(resp, "text", "") or "")
    if not hrefs:
        return _fail("drift", "no See-Deal outbound link on the thread page; "
                              "markup may have drifted (re-probe before trusting)")

    last_reason = ""
    for href in hrefs:
        merchant, method, needs_follow = _merchant_from_href(href)
        if needs_follow:                      # method is already "redirect_chain"
            merchant, kind, reason = follow_to_merchant(href, http_get=get, max_hops=MAX_HOPS)
            if merchant is None:
                last_reason = reason
                if kind in ("blocked", "unavailable"):
                    return _fail(kind, reason)   # transport problems end the attempt
                continue
        if merchant and safe_merchant_url(merchant):
            return MerchantResolution(
                ok=True, original_url=thread_url, resolved_url=merchant, method=method,
                checked_at=checked_at,
                evidence=_clip(f"resolved {thread_url} -> {merchant} [{method}]"),
                degraded_reason="", failure_kind="")
        if merchant:
            last_reason = f"resolved to an unsafe or internal URL ({_clip(merchant)})"
        elif not last_reason:
            last_reason = f"outbound link not usable as a merchant URL ({_clip(href)})"

    return _fail("unresolved", last_reason or
                 "no safe merchant URL resolved from the thread page")
