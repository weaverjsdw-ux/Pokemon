"""Geocoder fallback chain — no real network."""
from __future__ import annotations

from scanner import geocode as gc


class _FakeResp:
    def __init__(self, status: int, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def test_uses_cache_when_present(monkeypatch, tmp_path):
    cache_path = tmp_path / "cache.json"
    cache_path.write_text('{"123 main": [40.0, -73.0]}')
    monkeypatch.setattr(gc, "CACHE_PATH", cache_path)
    def boom(*a, **kw): raise AssertionError("should not hit network")
    monkeypatch.setattr(gc, "_try_nominatim", boom)
    assert gc.geocode("123 Main") == (40.0, -73.0)


def test_falls_back_through_providers(monkeypatch, tmp_path):
    monkeypatch.setattr(gc, "CACHE_PATH", tmp_path / "cache.json")
    calls = []
    def nom(addr):
        calls.append("nom")
        return None
    def mb(addr):
        calls.append("mb")
        return (10.0, 20.0)
    def google(addr):
        calls.append("google")
        return (99.0, 99.0)
    monkeypatch.setattr(gc, "_PROVIDERS", [("nominatim", nom), ("mapbox", mb), ("google", google)])
    assert gc.geocode("x") == (10.0, 20.0)
    assert calls == ["nom", "mb"]   # google not tried because mapbox won


def test_all_fail_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(gc, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(gc, "_PROVIDERS", [
        ("a", lambda _a: None),
        ("b", lambda _a: None),
    ])
    import pytest
    with pytest.raises(RuntimeError, match="All geocoders failed"):
        gc.geocode("x")


def test_writes_cache_on_success(monkeypatch, tmp_path):
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(gc, "CACHE_PATH", cache_path)
    monkeypatch.setattr(gc, "_PROVIDERS", [("nom", lambda a: (1.0, 2.0))])
    gc.geocode("Test Address")
    import json
    saved = json.loads(cache_path.read_text())
    assert saved == {"test address": [1.0, 2.0]}


def test_mapbox_skipped_without_token(monkeypatch):
    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)
    assert gc._try_mapbox("x") is None


def test_google_skipped_without_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert gc._try_google("x") is None
