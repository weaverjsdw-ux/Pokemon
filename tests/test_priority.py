"""Priority tiers + quiet hours."""
from __future__ import annotations

from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import pytest

from scanner import priority as pri


def _qh(start, end, tz="UTC"):
    return pri.parse_quiet_hours({"start": start, "end": end}, tz)


def test_default_tier_is_nice_to_have():
    assert pri.product_tier({}) == pri.NICE_TO_HAVE


def test_unknown_tier_falls_back_to_default():
    assert pri.product_tier({"priority": "bogus"}) == pri.NICE_TO_HAVE


def test_must_have_recognized():
    assert pri.product_tier({"priority": "must_have"}) == pri.MUST_HAVE


def test_mute_short_circuits():
    qh = _qh("", "")
    assert pri.should_alert({"mute": True, "priority": "must_have"}, qh) is False


def test_no_quiet_hours_always_alerts():
    qh = _qh("", "")
    assert pri.should_alert({}, qh) is True


def test_quiet_hours_suppresses_nice_to_have():
    qh = _qh("23:00", "07:00")
    now = datetime(2026, 5, 21, 2, 0, tzinfo=ZoneInfo("UTC"))
    assert pri.should_alert({"priority": "nice_to_have"}, qh, now) is False


def test_quiet_hours_lets_must_have_through():
    qh = _qh("23:00", "07:00")
    now = datetime(2026, 5, 21, 2, 0, tzinfo=ZoneInfo("UTC"))
    assert pri.should_alert({"priority": "must_have"}, qh, now) is True


def test_quiet_hours_outside_window_allows():
    qh = _qh("23:00", "07:00")
    now = datetime(2026, 5, 21, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert pri.should_alert({"priority": "fyi"}, qh, now) is True


def test_quiet_hours_same_day_window():
    qh = _qh("12:00", "14:00")
    inside = datetime(2026, 5, 21, 13, 0, tzinfo=ZoneInfo("UTC"))
    outside = datetime(2026, 5, 21, 15, 0, tzinfo=ZoneInfo("UTC"))
    assert qh.active_at(inside) is True
    assert qh.active_at(outside) is False


def test_quiet_hours_invalid_format_raises():
    with pytest.raises(SystemExit, match="quiet_hours"):
        pri.parse_quiet_hours({"start": "midnight", "end": "07:00"}, "UTC")


def test_quiet_hours_tz_aware():
    qh = pri.parse_quiet_hours(
        {"start": "23:00", "end": "07:00"}, "America/Chicago"
    )
    # 06:00 UTC = 00:00 or 01:00 in America/Chicago depending on DST.
    # Either way it's inside the 23:00 - 07:00 quiet window.
    now = datetime(2026, 5, 21, 6, 0, tzinfo=ZoneInfo("UTC"))
    assert qh.active_at(now) is True
