"""Logging module — just confirms shape, not specific output."""
from __future__ import annotations

import logging

import scanner.log as log_mod


def test_configure_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(log_mod, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(log_mod, "LOG_FILE", tmp_path / "logs" / "scanner.log")
    monkeypatch.setattr(log_mod, "_configured", False)
    log_mod.configure("INFO")
    before = len(logging.getLogger("scanner").handlers)
    log_mod.configure("INFO")
    after = len(logging.getLogger("scanner").handlers)
    assert before == after


def test_get_logger_namespaces(monkeypatch):
    monkeypatch.setattr(log_mod, "_configured", False)
    a = log_mod.get_logger("scanner.foo")
    b = log_mod.get_logger("bar")
    assert a.name == "scanner.foo"
    assert b.name == "scanner.bar"


def test_log_level_env_override(monkeypatch, tmp_path):
    monkeypatch.setattr(log_mod, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(log_mod, "LOG_FILE", tmp_path / "logs" / "scanner.log")
    monkeypatch.setattr(log_mod, "_configured", False)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    # Reset handlers from prior tests
    logging.getLogger("scanner").handlers.clear()
    log_mod.configure("INFO")
    assert logging.getLogger("scanner").level == logging.DEBUG
