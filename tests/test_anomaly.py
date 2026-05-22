"""Response-time anomaly detection on the HTTP client."""
from __future__ import annotations

import time
from collections import deque

from scanner import http as http_mod


def _client_with_samples(retailer: str, samples: list[tuple[float, float]]):
    client = http_mod.HTTPClient()
    h = client._health.setdefault(retailer, http_mod._Health())
    h.response_samples = deque(samples)
    return client


def test_no_samples_returns_neutral():
    client = http_mod.HTTPClient()
    assert client.anomaly_factor("target") == 1.0


def test_few_samples_returns_neutral():
    now = time.time()
    samples = [(now, 100.0)] * 5
    client = _client_with_samples("target", samples)
    assert client.anomaly_factor("target") == 1.0


def test_steady_latency_returns_neutral():
    now = time.time()
    samples = [(now - i * 60, 100.0) for i in range(30)]
    client = _client_with_samples("target", samples)
    f = client.anomaly_factor("target")
    assert f == 1.0


def test_recent_spike_pulls_factor_down():
    now = time.time()
    # Last hour: mostly 100ms with the last 5 minutes elevated to 400ms
    old = [(now - 600 - i * 30, 100.0) for i in range(20)]
    recent = [(now - i * 30, 400.0) for i in range(10)]
    client = _client_with_samples("target", old + recent)
    f = client.anomaly_factor("target")
    # 400/100 = 4x spike -> factor ~= 0.25
    assert 0.24 < f < 0.5


def test_factor_is_clamped_above_quarter():
    now = time.time()
    old = [(now - 600 - i * 30, 50.0) for i in range(20)]
    # Wild spike
    recent = [(now - i * 30, 5000.0) for i in range(10)]
    client = _client_with_samples("target", old + recent)
    assert client.anomaly_factor("target") >= 0.25


def test_modest_increase_under_threshold_no_boost():
    now = time.time()
    old = [(now - 600 - i * 30, 100.0) for i in range(20)]
    recent = [(now - i * 30, 130.0) for i in range(10)]   # 1.3x, under 1.5x threshold
    client = _client_with_samples("target", old + recent)
    assert client.anomaly_factor("target") == 1.0


def test_health_snapshot_includes_percentiles():
    now = time.time()
    samples = [(now - i, 100.0 + i) for i in range(20)]
    client = _client_with_samples("target", samples)
    snap = client.health_snapshot()
    assert "p50_ms" in snap["target"]
    assert "p95_ms" in snap["target"]
    assert snap["target"]["p95_ms"] > snap["target"]["p50_ms"]
