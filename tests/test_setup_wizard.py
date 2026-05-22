"""Setup wizard end-to-end: feed scripted answers, parse the result."""
from __future__ import annotations

import yaml

from scanner import setup_wizard


def _run(tmp_path, answers):
    target = tmp_path / "config.yaml"
    rc = setup_wizard.run(target_path=target, stdin=iter(answers))
    return rc, target


def test_writes_valid_yaml_with_required_fields(tmp_path):
    rc, target = _run(
        tmp_path,
        [
            "123 Home St",         # home
            "456 Work Ave",        # work
            "5",                   # radius
            "America/Chicago",     # timezone
            "",                    # discord
            "",                    # ntfy
            "n",                   # bestbuy enable
            "y",                   # quiet hours
        ],
    )
    assert rc == 0
    cfg = yaml.safe_load(target.read_text())
    assert cfg["locations"]["home"] == "123 Home St"
    assert cfg["locations"]["work"] == "456 Work Ave"
    assert cfg["route_radius_miles"] == 5
    assert cfg["timezone"] == "America/Chicago"
    assert cfg["quiet_hours"]["start"] == "23:00"
    assert cfg["retailers"]["bestbuy"]["enabled"] is False


def test_re_asks_until_address_provided(tmp_path):
    rc, target = _run(
        tmp_path,
        [
            "",                    # home (blank -> reprompt)
            "100 Real St",         # home (real)
            "",                    # work (blank -> reprompt)
            "200 Office Ln",       # work (real)
            "",                    # radius (default)
            "",                    # timezone (default)
            "",                    # discord
            "",                    # ntfy
            "",                    # bestbuy (default n)
            "",                    # quiet (default y)
        ],
    )
    assert rc == 0
    cfg = yaml.safe_load(target.read_text())
    assert cfg["locations"]["home"] == "100 Real St"
    assert cfg["locations"]["work"] == "200 Office Ln"


def test_refuses_to_overwrite_existing_config(tmp_path):
    target = tmp_path / "config.yaml"
    target.write_text("# existing\n")
    rc = setup_wizard.run(
        target_path=target,
        stdin=iter(["n"]),  # do not overwrite
    )
    assert rc == 1
    assert target.read_text() == "# existing\n"


def test_quiet_hours_off_writes_empty_window(tmp_path):
    rc, target = _run(
        tmp_path,
        [
            "1 H", "2 W", "4",
            "UTC", "", "",
            "n",
            "n",  # quiet hours off
        ],
    )
    assert rc == 0
    cfg = yaml.safe_load(target.read_text())
    assert cfg["quiet_hours"]["start"] == ""
    assert cfg["quiet_hours"]["end"] == ""


def test_invalid_timezone_reprompts(tmp_path):
    rc, target = _run(
        tmp_path,
        [
            "1 H", "2 W", "4",
            "Mars/Olympus",        # invalid
            "America/New_York",    # valid retry
            "", "",
            "n",
            "n",
        ],
    )
    assert rc == 0
    cfg = yaml.safe_load(target.read_text())
    assert cfg["timezone"] == "America/New_York"
