"""Retry/backoff behavior of the shared HTTP helper. No real network or sleeps."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
import requests

from scanner import health
from scanner.retailers import http


class FakeResp:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


def _sequence(monkeypatch, responses):
    """Patch requests.get to return/raise the given items in order."""
    calls = {"n": 0}

    def fake_get(url, **kwargs):
        item = responses[calls["n"]]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr("scanner.retailers.http.requests.get", fake_get)
    return calls


def test_retries_on_429_then_succeeds(monkeypatch):
    calls = _sequence(monkeypatch, [FakeResp(429), FakeResp(429), FakeResp(200)])
    slept = []
    resp = http.get("http://x", backoff=0.01, sleep=slept.append)
    assert resp.status_code == 200
    assert calls["n"] == 3
    assert len(slept) == 2


def test_retries_on_transient_5xx(monkeypatch):
    calls = _sequence(monkeypatch, [FakeResp(503), FakeResp(200)])
    slept = []
    resp = http.get("http://x", backoff=0.01, sleep=slept.append)
    assert resp.status_code == 200
    assert calls["n"] == 2
    assert len(slept) == 1


def test_post_retries_on_transient_5xx(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, **kwargs):
        calls["n"] += 1
        return FakeResp(503) if calls["n"] == 1 else FakeResp(200)

    monkeypatch.setattr("scanner.retailers.http.requests.post", fake_post)
    slept = []
    resp = http.post("http://x", json={"a": 1}, backoff=0.01, sleep=slept.append)
    assert resp.status_code == 200
    assert calls["n"] == 2
    assert len(slept) == 1


def test_does_not_retry_on_404(monkeypatch):
    calls = _sequence(monkeypatch, [FakeResp(404)])
    slept = []
    resp = http.get("http://x", backoff=0.01, sleep=slept.append)
    assert resp.status_code == 404
    assert calls["n"] == 1
    assert slept == []


def test_honors_retry_after_header(monkeypatch):
    _sequence(monkeypatch, [FakeResp(429, {"Retry-After": "2"}), FakeResp(200)])
    slept = []
    # backoff is huge so a non-header sleep would be obvious.
    http.get("http://x", backoff=99, sleep=slept.append)
    assert slept == [2.0]


def test_honors_retry_after_http_date(monkeypatch):
    retry_at = datetime.now(timezone.utc) + timedelta(seconds=60)
    header = format_datetime(retry_at, usegmt=True)
    _sequence(monkeypatch, [FakeResp(429, {"Retry-After": header}), FakeResp(200)])
    slept = []
    http.get("http://x", backoff=99, sleep=slept.append)
    assert 0 < slept[0] <= 60.5


def test_gives_up_after_max_retries_and_returns_last(monkeypatch):
    calls = _sequence(monkeypatch, [FakeResp(429)] * 5)
    slept = []
    resp = http.get("http://x", max_retries=2, backoff=0.01, sleep=slept.append)
    assert resp.status_code == 429
    assert calls["n"] == 3  # initial attempt + 2 retries
    assert len(slept) == 2


def test_retries_transport_error_then_raises(monkeypatch):
    health.reset()
    calls = _sequence(
        monkeypatch,
        [requests.ConnectionError("boom"), requests.ConnectionError("boom")],
    )
    slept = []
    with pytest.raises(requests.RequestException):
        http.get("http://x", retailer="target", max_retries=1, backoff=0.01, sleep=slept.append)
    assert calls["n"] == 2
    assert len(slept) == 1
    assert health.get("target")["last_status"] == "ERROR"
    health.reset()


def test_missing_status_code_treated_as_success(monkeypatch):
    class NoStatus:
        pass

    _sequence(monkeypatch, [NoStatus()])
    resp = http.get("http://x")
    assert isinstance(resp, NoStatus)


def test_retailer_kwarg_is_not_forwarded_and_notes_status(monkeypatch):
    health.reset()
    captured = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return FakeResp(403)

    monkeypatch.setattr("scanner.retailers.http.requests.get", fake_get)

    resp = http.get("http://x", retailer="target", timeout=5)

    assert resp.status_code == 403
    assert captured == {"timeout": 5}
    assert health.get("target")["last_http_status"] == 403
    health.reset()
