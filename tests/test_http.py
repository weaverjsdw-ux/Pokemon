"""HTTP wrapper — retry/backoff, per-retailer health, cost guard.

No real network; we monkeypatch the underlying requests.Session.
"""
from __future__ import annotations

import time

import pytest
import requests

from scanner import http as http_mod


class _FakeResp:
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.reason = "FAKE"


class _Session:
    """Records calls and returns scripted outcomes (status code or exception)."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else 200
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResp(outcome)


def _make_client(outcomes, **kwargs):
    client = http_mod.HTTPClient(backoff=(0.0, 0.0, 0.0), **kwargs)
    client.session = _Session(outcomes)
    return client


def test_success_first_try():
    client = _make_client([200])
    resp = client.request("foo", "GET", "https://example.test")
    assert resp.status_code == 200
    assert client.session.calls == 1


def test_retries_5xx_then_succeeds():
    client = _make_client([500, 503, 200])
    resp = client.request("foo", "GET", "https://example.test")
    assert resp.status_code == 200
    assert client.session.calls == 3


def test_does_not_retry_4xx():
    client = _make_client([404])
    resp = client.request("foo", "GET", "https://example.test")
    assert resp.status_code == 404
    assert client.session.calls == 1


def test_retries_connection_error_then_raises():
    client = _make_client(
        [requests.ConnectionError(), requests.ConnectionError(),
         requests.ConnectionError(), requests.ConnectionError()],
        fail_threshold=10,
    )
    with pytest.raises(requests.ConnectionError):
        client.request("foo", "GET", "https://example.test")
    # backoff tuple has 3 entries -> max 4 attempts total
    assert client.session.calls == 4


def test_health_auto_disables_after_threshold(monkeypatch):
    client = _make_client(
        [requests.ConnectionError()] * 100,
        fail_threshold=2,
        cooldown_seconds=300,
    )
    # First call exhausts retries (4 attempts) and counts as 1 logical failure.
    with pytest.raises(requests.ConnectionError):
        client.request("foo", "GET", "https://example.test")
    # Second call: 1 more logical failure -> threshold hit, disabled.
    with pytest.raises(requests.ConnectionError):
        client.request("foo", "GET", "https://example.test")
    assert client.is_disabled("foo")
    with pytest.raises(http_mod.RetailerDisabled):
        client.request("foo", "GET", "https://example.test")


def test_health_recovers_on_success():
    client = _make_client(
        [requests.ConnectionError()] * 4 + [200],
        fail_threshold=10,
    )
    with pytest.raises(requests.ConnectionError):
        client.request("foo", "GET", "https://example.test")
    assert client._health["foo"].fails == 1
    resp = client.request("foo", "GET", "https://example.test")
    assert resp.status_code == 200
    assert client._health["foo"].fails == 0


def test_per_retailer_isolation():
    client = _make_client(
        [requests.ConnectionError()] * 4 + [200],
        fail_threshold=10,
    )
    # foo fails; bar should be unaffected
    with pytest.raises(requests.ConnectionError):
        client.request("foo", "GET", "https://example.test")
    resp = client.request("bar", "GET", "https://example.test")
    assert resp.status_code == 200


def test_budget_exceeded():
    client = _make_client([200] * 10, rate_per_hour=3)
    for _ in range(3):
        client.request("foo", "GET", "https://example.test")
    with pytest.raises(http_mod.BudgetExceeded):
        client.request("foo", "GET", "https://example.test")


def test_budget_window_slides(monkeypatch):
    """Old entries outside the 1-hour window drop off."""
    client = _make_client([200] * 10, rate_per_hour=3)
    h = client._health.setdefault("foo", http_mod._Health())
    # Inject 3 calls from > 1h ago
    h.request_times.extend([time.time() - 7200] * 3)
    # Should not raise — those don't count against the rolling window
    client.request("foo", "GET", "https://example.test")


def test_health_snapshot_shape():
    client = _make_client([200])
    client.request("foo", "GET", "https://example.test")
    snap = client.health_snapshot()
    assert "foo" in snap
    assert snap["foo"]["disabled"] is False
    assert snap["foo"]["requests_last_hour"] == 1
