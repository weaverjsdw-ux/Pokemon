"""Slice 6B: Slickdeals merchant-page resolver.

Resolve a Slickdeals thread URL to a safe, real merchant/buy URL so the existing
page verifier can check it. Network-mocked only. Doctrine: accept only http(s);
reject unsafe/empty/tracking-only/unresolved-internal links; follow redirect
chains hop-capped with per-hop scheme safety; never guess a destination.

The thread fixtures are SYNTHETIC/REPRESENTATIVE (operator-probe-pending) — see
the header comment in each fixture file. The resolver degrades rather than
guesses, so a stale selector under-alerts instead of mis-alerting.
"""
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
import requests

from scanner.discovery import resolve

FIXTURES = Path("tests/fixtures/discovery")
CHECKED_AT = "2026-07-03T10:00:00+00:00"

THREAD_U2 = "https://slickdeals.net/f/19710354-pokemon-tcg-mega-evolution"
THREAD_REDIRECT = "https://slickdeals.net/f/19710355-prismatic-etb"
THREAD_DIRECT = "https://slickdeals.net/f/19710356-surging-sparks"
THREAD_NOCTA = "https://slickdeals.net/f/19710357-discussion"

WALMART = ("https://www.walmart.com/ip/"
           "Pokemon-TCG-Mega-Evolution-Ascended-Heroes-Mega-EX-Box/123456789")
TARGET = "https://www.target.com/p/pokemon-tcg-surging-sparks-booster-bundle/-/A-98765432"
RD_ENDPOINT = "https://slickdeals.net/rd/12345/?tid=19710355&lno=1&tres=1"

# --- Live capture (thread 19650840, 2026-07-04). See fixture header + test_live_* below.
THREAD_LIVE = ("https://slickdeals.net/f/19650840-"
               "pok-mon-tcg-mega-lucario-ex-league-battle-deck-27-95")
# MOCKED merchant landing for the internal /click redirect. The approved live
# capture was a SINGLE thread GET only; the /click -> merchant hop was NOT
# fetched live, so this 302 target is a stand-in that exercises the resolver's
# existing follow-chain. B0GRCDKMSW is the real Amazon ASIN from the thread.
AMAZON_LIVE = "https://www.amazon.com/dp/B0GRCDKMSW"
# Related-deal cards embedded in the same live thread page (OTHER threads).
RELATED_THREAD_IDS = ("19719783", "19714542", "19719687")


def _live_get(calls):
    """Fake http_get for the live fixture: serves the thread, treats any
    slickdeals ``/click`` as a 302 to the merchant, records every fetched URL,
    and refuses any other GET (so a wrongly-selected anchor surfaces loudly)."""
    def _get(url, **kwargs):
        calls.append(url)
        if url == THREAD_LIVE:
            return _html_resp(_fixture("slickdeals_thread_live_19650840.html"))
        parsed = urlparse(url)
        if parsed.netloc.endswith("slickdeals.net") and parsed.path == "/click":
            return _redirect_resp(AMAZON_LIVE)
        raise AssertionError(f"unexpected GET: {url}")
    return _get


def _fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _html_resp(text, status=200, url=""):
    return SimpleNamespace(status_code=status, text=text, headers={}, url=url)


def _redirect_resp(location, status=302, url=""):
    return SimpleNamespace(status_code=status, text="", headers={"Location": location},
                           url=url)


def _get_map(mapping):
    """A fake http_get dispatching by exact URL; raises on an unexpected fetch."""
    def _get(url, **kwargs):
        if url not in mapping:
            raise AssertionError(f"unexpected GET: {url}")
        resp = mapping[url]
        if isinstance(resp, Exception):
            raise resp
        return resp
    return _get


# --------------------------------------------------------------- safe_merchant_url

@pytest.mark.parametrize("url,ok", [
    ("https://www.walmart.com/ip/x", True),
    ("http://target.com/p/x", True),
    ("https://www.bestbuy.com/site/x/6543.p", True),
    ("", False),
    ("   ", False),
    ("javascript:alert(1)", False),
    ("data:text/html,<b>x</b>", False),
    ("mailto:deals@slickdeals.net", False),
    ("ftp://host.example/x", False),
    ("/f/19710354-relative-only", False),          # relative, no scheme
    ("https://", False),                            # no host
    ("https://localhost/x", False),                 # bare host, no dot
    ("https://slickdeals.net/rd/12345", False),     # unresolved internal
    ("https://www.slickdeals.net/x", False),        # internal subdomain
    ("https://d2.slickdeals.net/rd/1", False),      # cdn redirect host
])
def test_safe_merchant_url(url, ok):
    assert resolve.safe_merchant_url(url) is ok


# --------------------------------------------------------------- resolve success

def test_resolve_u2_param_decodes_merchant_url():
    r = resolve.resolve_slickdeals_merchant(
        THREAD_U2, http_get=_get_map({THREAD_U2: _html_resp(_fixture("slickdeals_thread_u2.html"))}),
        checked_at=CHECKED_AT)
    assert r.ok is True
    assert r.resolved_url == WALMART
    assert r.method == "u2_param"
    assert r.original_url == THREAD_U2
    assert r.checked_at == CHECKED_AT
    assert r.failure_kind == "" and r.degraded_reason == ""
    assert THREAD_U2 in r.evidence and WALMART in r.evidence   # both URLs preserved


def test_resolve_direct_merchant_href():
    r = resolve.resolve_slickdeals_merchant(
        THREAD_DIRECT,
        http_get=_get_map({THREAD_DIRECT: _html_resp(_fixture("slickdeals_thread_direct.html"))}),
        checked_at=CHECKED_AT)
    assert r.ok is True
    assert r.resolved_url == TARGET
    assert r.method == "direct_href"


def test_resolve_direct_href_with_incidental_u2_is_not_hijacked():
    # A REAL merchant href that happens to carry a ?u2= param must resolve to the
    # merchant URL, not the junk u2 value. The u2 outbound param is a slickdeals
    # convention; it is only honored on a slickdeals host.
    html = ('<a class="dealButton" data-role="seeDealButton" '
            'href="https://shop.example.com/product?u2=banner&amp;id=42">See Deal</a>')
    r = resolve.resolve_slickdeals_merchant(
        THREAD_DIRECT, http_get=_get_map({THREAD_DIRECT: _html_resp(html)}),
        checked_at=CHECKED_AT)
    assert r.ok is True
    assert r.method == "direct_href"
    assert r.resolved_url == "https://shop.example.com/product?u2=banner&id=42"


def test_resolve_follows_redirect_chain_to_merchant():
    # thread -> /rd/ endpoint -> 302 -> merchant (off-slickdeals). The resolver
    # follows the redirect and returns the merchant URL WITHOUT re-fetching it.
    mapping = {
        THREAD_REDIRECT: _html_resp(_fixture("slickdeals_thread_redirect.html")),
        RD_ENDPOINT: _redirect_resp(TARGET),
    }
    r = resolve.resolve_slickdeals_merchant(
        THREAD_REDIRECT, http_get=_get_map(mapping), checked_at=CHECKED_AT)
    assert r.ok is True
    assert r.resolved_url == TARGET
    assert r.method == "redirect_chain"


def test_resolve_follows_multi_hop_redirect_chain():
    hop2 = "https://slickdeals.net/rd/12345/hop2"
    mapping = {
        THREAD_REDIRECT: _html_resp(_fixture("slickdeals_thread_redirect.html")),
        RD_ENDPOINT: _redirect_resp(hop2),
        hop2: _redirect_resp(TARGET),
    }
    r = resolve.resolve_slickdeals_merchant(
        THREAD_REDIRECT, http_get=_get_map(mapping), checked_at=CHECKED_AT)
    assert r.ok is True and r.resolved_url == TARGET


# ------------------------------------------------- live thread markup (Slice 6B)
# Real captured markup from a current Slickdeals thread (see fixture header). The
# featured "Get Deal at <store>" CTA is a Vue-rendered outclick button whose href
# is an internal /click redirect; the resolver must recognize it AND ignore the
# related-deal cards / in-post links / nav that share the page.

def test_resolve_live_thread_outclick_cta_reaches_merchant():
    # Selector repair proof: the current live CTA (dealDetailsOutclickButton /
    # data-qa-ddp-seedeal-button) is recognized, and its internal /click href is
    # followed off-slickdeals to the merchant.
    calls = []
    r = resolve.resolve_slickdeals_merchant(
        THREAD_LIVE, http_get=_live_get(calls), checked_at=CHECKED_AT)
    assert r.ok is True
    assert r.resolved_url == AMAZON_LIVE
    assert r.method == "redirect_chain"
    assert r.failure_kind == "" and r.degraded_reason == ""
    # Exactly two GETs: the thread, then the single /click endpoint it selected.
    assert len(calls) == 2
    assert calls[0] == THREAD_LIVE
    assert urlparse(calls[1]).path == "/click"


def test_resolve_live_thread_selects_only_featured_deal_ctas():
    # Conservatism proof (negative): on the SAME real page, _see_deal_hrefs picks
    # only the featured deal's outclick anchors (3 buttons + 1 deal image, all the
    # same merchant) and NONE of the related-deal cards, the sticky image link,
    # the in-post outclick link (data-cta only, no see-deal marker), or nav.
    hrefs = resolve._see_deal_hrefs(_fixture("slickdeals_thread_live_19650840.html"))
    assert len(hrefs) == 4
    for h in hrefs:
        assert h.startswith("https://slickdeals.net/click?")   # featured /click only
        assert "u3=" not in h                                  # not the in-post link
        assert "dealCardGrid" not in h and "/forums/" not in h
    assert not any(rid in h for h in hrefs for rid in RELATED_THREAD_IDS)
    # And end-to-end the resolution is the merchant, never a related thread card.
    calls = []
    r = resolve.resolve_slickdeals_merchant(
        THREAD_LIVE, http_get=_live_get(calls), checked_at=CHECKED_AT)
    assert r.resolved_url == AMAZON_LIVE
    for rid in RELATED_THREAD_IDS:
        assert rid not in r.resolved_url
        assert not any(rid in u for u in calls)


# ------------------------------------------------------------- follow_to_merchant

def test_follow_stops_at_first_off_slickdeals_location():
    mapping = {RD_ENDPOINT: _redirect_resp(TARGET)}
    final, kind, reason = resolve.follow_to_merchant(
        RD_ENDPOINT, http_get=_get_map(mapping), max_hops=5)
    assert final == TARGET and kind == "" and reason == ""


def test_follow_returns_merchant_reached_on_the_last_allowed_hop():
    # Boundary: a merchant reached via exactly max_hops redirects must still
    # resolve (the cap is the number of hops allowed, not one fewer).
    r1 = "https://slickdeals.net/rd/1"
    r2 = "https://slickdeals.net/rd/2"
    mapping = {r1: _redirect_resp(r2), r2: _redirect_resp(TARGET)}
    final, kind, reason = resolve.follow_to_merchant(
        r1, http_get=_get_map(mapping), max_hops=2)
    assert final == TARGET and kind == "" and reason == ""


def test_follow_hop_cap_exceeded_is_unresolved():
    # an infinite slickdeals->slickdeals loop must terminate at the cap, not hang
    loop = "https://slickdeals.net/rd/loop"
    mapping = {loop: _redirect_resp(loop)}
    final, kind, reason = resolve.follow_to_merchant(
        loop, http_get=_get_map(mapping), max_hops=3)
    assert final is None and kind == "unresolved" and "hop" in reason.lower()


def test_follow_403_is_blocked_no_evasion():
    mapping = {RD_ENDPOINT: _html_resp("", status=403)}
    final, kind, reason = resolve.follow_to_merchant(
        RD_ENDPOINT, http_get=_get_map(mapping), max_hops=5)
    assert final is None and kind == "blocked" and "403" in reason


def test_follow_transport_failure_is_unavailable():
    mapping = {RD_ENDPOINT: requests.ConnectionError("dns failure")}
    final, kind, reason = resolve.follow_to_merchant(
        RD_ENDPOINT, http_get=_get_map(mapping), max_hops=5)
    assert final is None and kind == "unavailable" and "dns failure" in reason


def test_follow_redirect_to_unsafe_scheme_is_unresolved():
    mapping = {RD_ENDPOINT: _redirect_resp("javascript:alert(1)")}
    final, kind, reason = resolve.follow_to_merchant(
        RD_ENDPOINT, http_get=_get_map(mapping), max_hops=5)
    assert final is None and kind == "unresolved"
    assert "scheme" in reason.lower()


def test_follow_redirect_with_no_location_is_unresolved():
    mapping = {RD_ENDPOINT: SimpleNamespace(status_code=302, text="", headers={}, url="")}
    final, kind, reason = resolve.follow_to_merchant(
        RD_ENDPOINT, http_get=_get_map(mapping), max_hops=5)
    assert final is None and kind == "unresolved" and "location" in reason.lower()


def test_follow_non_redirect_endpoint_is_unresolved():
    # /rd/ answered 200 (a redirect shell that didn't 3xx) — no merchant URL
    mapping = {RD_ENDPOINT: _html_resp("<html>shell</html>", status=200)}
    final, kind, reason = resolve.follow_to_merchant(
        RD_ENDPOINT, http_get=_get_map(mapping), max_hops=5)
    assert final is None and kind == "unresolved"


# --------------------------------------------------------------- resolve misses

def test_resolve_no_cta_is_drift_parser_suspect():
    r = resolve.resolve_slickdeals_merchant(
        THREAD_NOCTA,
        http_get=_get_map({THREAD_NOCTA: _html_resp(_fixture("slickdeals_thread_nocta.html"))}),
        checked_at=CHECKED_AT)
    assert r.ok is False
    assert r.failure_kind == "drift"
    assert r.resolved_url == ""
    assert "drift" in r.degraded_reason.lower() or "no see-deal" in r.degraded_reason.lower()


def test_resolve_u2_to_unsafe_scheme_is_unresolved_not_a_guess():
    html = ('<a class="dealButton" data-role="seeDealButton" '
            'href="https://slickdeals.net/?u2=javascript%3Aalert(1)">See Deal</a>')
    r = resolve.resolve_slickdeals_merchant(
        THREAD_U2, http_get=_get_map({THREAD_U2: _html_resp(html)}), checked_at=CHECKED_AT)
    assert r.ok is False and r.failure_kind == "unresolved"


def test_resolve_u2_to_internal_slickdeals_is_rejected():
    html = ('<a class="dealButton" data-role="seeDealButton" '
            'href="https://slickdeals.net/?u2=https%3A%2F%2Fslickdeals.net%2Flogin">See Deal</a>')
    r = resolve.resolve_slickdeals_merchant(
        THREAD_U2, http_get=_get_map({THREAD_U2: _html_resp(html)}), checked_at=CHECKED_AT)
    assert r.ok is False and r.failure_kind == "unresolved"
    assert r.resolved_url == ""


def test_resolve_thread_transport_failure_is_unavailable():
    r = resolve.resolve_slickdeals_merchant(
        THREAD_U2, http_get=_get_map({THREAD_U2: requests.ConnectTimeout("timed out")}),
        checked_at=CHECKED_AT)
    assert r.ok is False and r.failure_kind == "unavailable"
    assert "timed out" in r.degraded_reason


def test_resolve_thread_403_is_blocked():
    r = resolve.resolve_slickdeals_merchant(
        THREAD_U2, http_get=_get_map({THREAD_U2: _html_resp("", status=403)}),
        checked_at=CHECKED_AT)
    assert r.ok is False and r.failure_kind == "blocked" and "403" in r.degraded_reason


def test_resolve_thread_non_200_is_unavailable():
    r = resolve.resolve_slickdeals_merchant(
        THREAD_U2, http_get=_get_map({THREAD_U2: _html_resp("", status=404)}),
        checked_at=CHECKED_AT)
    assert r.ok is False and r.failure_kind == "unavailable" and "404" in r.degraded_reason


def test_resolve_redacts_api_keys_in_error_detail():
    exc = requests.ConnectionError(
        "https://slickdeals.net/f/x?apiKey=SECRET123 connection refused")
    r = resolve.resolve_slickdeals_merchant(
        THREAD_U2, http_get=_get_map({THREAD_U2: exc}), checked_at=CHECKED_AT)
    assert "SECRET123" not in r.degraded_reason and "SECRET123" not in r.evidence


def test_resolution_is_immutable_evidence():
    r = resolve.resolve_slickdeals_merchant(
        THREAD_DIRECT,
        http_get=_get_map({THREAD_DIRECT: _html_resp(_fixture("slickdeals_thread_direct.html"))}))
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.ok = False
