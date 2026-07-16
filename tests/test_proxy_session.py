"""Proxy rotation behaviour — no network, no real proxies, no sleeping."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from weather import proxy_session as ps
from weather.proxy_session import (
    AllProxiesFailedError,
    ProxyRotatingSession,
    load_proxies,
)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Make backoff instantaneous so tests stay fast."""
    monkeypatch.setattr(ps.time, "sleep", lambda _s: None)


class FakeResponse:
    def __init__(self, status_code: int, headers: dict | None = None):
        self.status_code = status_code
        self.headers = headers or {}


class ScriptedSession:
    """Stands in for requests.Session, replaying a scripted result per call.

    Each script item is either an int status code, a FakeResponse, or an
    Exception instance to raise. Records the proxy mapping used each call.
    """

    def __init__(self, script):
        self.script = list(script)
        self.proxies_seen: list[dict] = []

    def request(self, method, url, proxies=None, **kwargs):
        self.proxies_seen.append(proxies)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, FakeResponse):
            return item
        return FakeResponse(item)


def _proxies(n: int) -> list[ps.Proxy]:
    return [ps.Proxy(mapping={"https": f"http://p{i}:8080"}, label=f"p{i}") for i in range(n)]


def _session(script, **kw):
    proxies = kw.pop("proxies", None) or _proxies(3)
    # shuffle off so the first proxy used is deterministic (index 0).
    sess = ProxyRotatingSession(
        proxies, shuffle=False, session=ScriptedSession(script), **kw
    )
    return sess


# -- loading ------------------------------------------------------------


def test_load_bare_list(tmp_path: Path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps(["http://a:1", "http://b:2"]))
    proxies = load_proxies(f)
    assert len(proxies) == 2
    assert proxies[0].mapping == {"http": "http://a:1", "https": "http://a:1"}


def test_load_object_with_mixed_entries(tmp_path: Path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"proxies": [
        "http://a:1",
        {"http": "http://b:2", "https": "http://b:2"},
    ]}))
    proxies = load_proxies(f)
    assert len(proxies) == 2
    assert proxies[1].mapping == {"http": "http://b:2", "https": "http://b:2"}


def test_load_redacts_credentials_in_label(tmp_path: Path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps(["http://user:secret@host:8080"]))
    proxies = load_proxies(f)
    assert "secret" not in proxies[0].label
    assert "host:8080" in proxies[0].label


def test_load_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_proxies(tmp_path / "nope.json")


def test_load_bad_json(tmp_path: Path):
    f = tmp_path / "p.json"
    f.write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_proxies(f)


def test_load_empty_pool(tmp_path: Path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps([]))
    with pytest.raises(ValueError, match="no proxies"):
        load_proxies(f)


# -- rotation -----------------------------------------------------------


def test_first_success_uses_one_proxy():
    sess = _session([200])
    resp = sess.get("http://example.com")
    assert resp.status_code == 200
    assert len(sess.session.proxies_seen) == 1


def test_rotates_on_connection_error():
    sess = _session([requests.ConnectionError("boom"), 200])
    resp = sess.get("http://example.com")
    assert resp.status_code == 200
    # Two different proxies should have been used.
    assert sess.session.proxies_seen[0] != sess.session.proxies_seen[1]


def test_rotates_on_rate_limit():
    sess = _session([429, 200])
    resp = sess.get("http://example.com")
    assert resp.status_code == 200
    assert len(sess.session.proxies_seen) == 2


def test_non_retryable_4xx_returned_to_caller():
    sess = _session([404])
    resp = sess.get("http://example.com")
    assert resp.status_code == 404
    assert len(sess.session.proxies_seen) == 1


def test_all_proxies_fail_raises_with_last_status():
    sess = _session([429, 503, 500])
    with pytest.raises(AllProxiesFailedError, match="status 500"):
        sess.get("http://example.com")


def test_all_proxies_fail_on_exception_raises():
    sess = _session([requests.Timeout("t")] * 3)
    with pytest.raises(AllProxiesFailedError, match="last error"):
        sess.get("http://example.com")


def test_failed_proxy_put_on_cooldown():
    sess = _session([429, 200])
    sess.get("http://example.com")
    cooled = [p for p in sess.proxies if p.cooldown_until > 0]
    assert len(cooled) == 1
    assert cooled[0].failures == 1


def test_success_resets_failure_count():
    proxies = _proxies(2)
    proxies[1].failures = 5  # pretend it failed before
    # shuffle off -> first call uses index 1 (after _next_proxy advances 0->1).
    sess = _session([200], proxies=proxies)
    sess.get("http://example.com")
    # whichever proxy served the 200 has its failures reset to 0.
    assert any(p.failures == 0 for p in proxies)


def test_max_attempts_defaults_to_pool_size():
    sess = _session([429] * 5, proxies=_proxies(3))
    with pytest.raises(AllProxiesFailedError):
        sess.get("http://example.com")
    assert len(sess.session.proxies_seen) == 3  # one attempt per proxy


def test_retry_after_header_parsed(monkeypatch):
    captured = []
    sess = _session([FakeResponse(429, {"Retry-After": "7"}), 200])
    monkeypatch.setattr(
        sess, "_sleep_for", lambda attempt, ra: captured.append(ra)
    )
    sess.get("http://example.com")
    assert captured[0] == 7.0
