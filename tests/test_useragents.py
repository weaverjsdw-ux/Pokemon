"""User-agent pool + From header."""
from __future__ import annotations

import importlib

from scanner import useragents


def test_ua_is_a_real_browser_string():
    assert "Mozilla/5.0" in useragents.UA
    assert useragents.UA in useragents._POOL


def test_common_headers_includes_ua():
    h = useragents.common_headers()
    assert h["User-Agent"] == useragents.UA
    assert "From" not in h


def test_common_headers_includes_from_when_operator_set():
    h = useragents.common_headers("ops@example.com")
    assert h["From"] == "ops@example.com"


def test_common_headers_strips_blank_operator():
    h = useragents.common_headers("   ")
    assert "From" not in h


def test_seed_makes_pick_deterministic(monkeypatch):
    monkeypatch.setenv("SCANNER_UA_SEED", "alpha")
    importlib.reload(useragents)
    a = useragents.UA
    monkeypatch.setenv("SCANNER_UA_SEED", "alpha")
    importlib.reload(useragents)
    b = useragents.UA
    assert a == b


def test_env_override(monkeypatch):
    monkeypatch.setenv("SCANNER_UA", "my-custom-ua/1.0")
    importlib.reload(useragents)
    assert useragents.UA == "my-custom-ua/1.0"
