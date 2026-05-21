"""Drop-window parsing + active-window selection."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scanner import drop_windows as dw


UTC = ZoneInfo("UTC")


def test_empty_parse():
    assert dw.parse(None) == []
    assert dw.parse([]) == []


def test_parse_one_window():
    [w] = dw.parse([
        {"retailers": ["target"], "days": ["tue"], "start": "06:00", "end": "10:00",
         "poll_interval_seconds": 60}
    ])
    assert w.retailers == ["target"]
    assert w.days == {1}
    assert w.poll_interval_seconds == 60


def test_parse_all_days():
    [w] = dw.parse([
        {"retailers": ["x"], "days": "all", "start": "00:00", "end": "00:01",
         "poll_interval_seconds": 30}
    ])
    assert w.days == set(range(7))


def test_unknown_day_raises():
    with pytest.raises(SystemExit, match="unknown day"):
        dw.parse([{"retailers": ["x"], "days": ["typo"],
                   "start": "00:00", "end": "00:01", "poll_interval_seconds": 30}])


def test_missing_retailers_raises():
    with pytest.raises(SystemExit, match="retailers required"):
        dw.parse([{"retailers": [], "days": ["mon"],
                   "start": "00:00", "end": "01:00", "poll_interval_seconds": 30}])


def test_zero_interval_raises():
    with pytest.raises(SystemExit, match="poll_interval_seconds"):
        dw.parse([{"retailers": ["x"], "days": ["mon"],
                   "start": "00:00", "end": "01:00", "poll_interval_seconds": 0}])


def test_active_within_window():
    [w] = dw.parse([
        {"retailers": ["target"], "days": ["tue"], "start": "06:00", "end": "10:00",
         "poll_interval_seconds": 60}
    ])
    # Tuesday 2026-05-19 at 08:00 UTC
    assert w.active_at(datetime(2026, 5, 19, 8, 0, tzinfo=UTC)) is True


def test_inactive_outside_window():
    [w] = dw.parse([
        {"retailers": ["target"], "days": ["tue"], "start": "06:00", "end": "10:00",
         "poll_interval_seconds": 60}
    ])
    assert w.active_at(datetime(2026, 5, 19, 12, 0, tzinfo=UTC)) is False
    assert w.active_at(datetime(2026, 5, 20, 8, 0, tzinfo=UTC)) is False  # Wed


def test_midnight_wrap_active():
    [w] = dw.parse([
        {"retailers": ["x"], "days": ["mon"], "start": "23:00", "end": "01:00",
         "poll_interval_seconds": 30}
    ])
    # Monday 23:30
    assert w.active_at(datetime(2026, 5, 18, 23, 30, tzinfo=UTC)) is True


def test_effective_interval_no_match_returns_default():
    windows = dw.parse([
        {"retailers": ["target"], "days": ["tue"], "start": "06:00", "end": "10:00",
         "poll_interval_seconds": 60}
    ])
    interval, tags = dw.effective_interval(
        windows, ["target"], default_seconds=180,
        now=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
    )
    assert interval == 180
    assert tags == []


def test_effective_interval_picks_smallest():
    windows = dw.parse([
        {"retailers": ["target"], "days": ["tue"], "start": "06:00", "end": "10:00",
         "poll_interval_seconds": 120},
        {"retailers": ["pokemoncenter"], "days": ["tue"], "start": "06:00", "end": "10:00",
         "poll_interval_seconds": 30},
    ])
    interval, tags = dw.effective_interval(
        windows, ["target", "pokemoncenter"], default_seconds=180,
        now=datetime(2026, 5, 19, 8, 0, tzinfo=UTC),
    )
    assert interval == 30
    assert "pokemoncenter" in tags


def test_effective_interval_skips_windows_for_disabled_retailers():
    windows = dw.parse([
        {"retailers": ["bestbuy"], "days": ["tue"], "start": "06:00", "end": "10:00",
         "poll_interval_seconds": 30}
    ])
    interval, tags = dw.effective_interval(
        windows, ["target"], default_seconds=180,
        now=datetime(2026, 5, 19, 8, 0, tzinfo=UTC),
    )
    assert interval == 180
    assert tags == []
