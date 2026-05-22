"""Heartbeat: cadence + payload shape."""
from __future__ import annotations

import time

import pytest

from scanner.heartbeat import Heartbeat


def test_does_not_send_before_interval():
    hb = Heartbeat(interval_seconds=3600)
    sent = []
    hb.record_pass(0)
    hb.maybe_send(lambda t, f: sent.append((t, f)), {}, {})
    assert sent == []


def test_sends_when_interval_elapsed():
    hb = Heartbeat(interval_seconds=0)
    # Force last_sent into the past so the 0-interval check fires deterministically.
    hb.state.last_sent = 0.0
    sent = []
    hb.record_pass(2)
    hb.maybe_send(
        lambda t, f: sent.append((t, dict(f))),
        {"target": {"disabled": False, "requests_last_hour": 12}},
        {"target": ["s1", "s2", "s3"]},
    )
    assert len(sent) == 1
    title, fields = sent[0]
    assert title == "Scanner heartbeat"
    assert "Passes" in fields
    assert fields["Alerts fired"] == "2"
    assert "target: ok" in fields["Retailers"]
    assert "stores=3" in fields["Retailers"]


def test_records_passes_and_alerts():
    hb = Heartbeat()
    hb.record_pass(0)
    hb.record_pass(3)
    hb.record_pass(1)
    assert hb.state.passes == 3
    assert hb.state.alerts == 4


def test_swallows_send_errors():
    hb = Heartbeat(interval_seconds=0)
    hb.state.last_sent = 0.0
    def boom(t, f):
        raise RuntimeError("network down")
    hb.record_pass(0)
    # Must not raise — heartbeat failure shouldn't crash the scan loop.
    hb.maybe_send(boom, {}, {})


def test_shows_disabled_retailer():
    hb = Heartbeat(interval_seconds=0)
    hb.state.last_sent = 0.0
    sent = []
    hb.maybe_send(
        lambda t, f: sent.append(dict(f)),
        {"walmart": {"disabled": True, "requests_last_hour": 0}},
        {"walmart": []},
    )
    assert "walmart: DISABLED" in sent[0]["Retailers"]
