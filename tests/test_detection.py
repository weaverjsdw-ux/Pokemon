"""Block detection: captcha, Cloudflare, generic challenge pages."""
from __future__ import annotations

from scanner.detection import detect_block, looks_like_html_error


def test_clean_response_not_blocked():
    d = detect_block("target", '{"data": {"product": {}}}')
    assert d.blocked is False


def test_cloudflare_marker_detected():
    body = "<html><body>Just a moment...</body></html>"
    d = detect_block("target", body)
    assert d.blocked is True
    assert "Just a moment" in d.reason


def test_amazon_captcha_detected():
    body = "<form><img class='captcha-image'>"
    d = detect_block("amazon", body)
    assert d.blocked is True


def test_walmart_perimeterx_detected():
    body = '<script>window._pxhd = "x"</script>'
    d = detect_block("walmart", body)
    assert d.blocked is True


def test_429_status_always_blocks():
    d = detect_block("target", "", status_code=429)
    assert d.blocked is True
    assert "429" in d.reason


def test_403_status_blocks():
    d = detect_block("target", "<html>OK</html>", status_code=403)
    assert d.blocked is True


def test_cloudflare_503_challenge():
    d = detect_block("target", "<html>Browser challenge in progress</html>", status_code=503)
    assert d.blocked is True


def test_unknown_retailer_falls_through_to_generic():
    body = "Access Denied"
    d = detect_block("some-new-retailer", body)
    assert d.blocked is True


def test_html_error_heuristic():
    assert looks_like_html_error("<!DOCTYPE html><html>") is True
    assert looks_like_html_error('{"json": true}') is False
    assert looks_like_html_error("") is False


def test_empty_body_with_200_not_blocked():
    """An empty 200 may be legitimately empty (no matches); don't block on it."""
    d = detect_block("target", "")
    assert d.blocked is False
