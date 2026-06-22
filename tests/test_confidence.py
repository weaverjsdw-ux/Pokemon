"""Source-Confidence precedence (pure, no I/O)."""
from __future__ import annotations

from scanner import confidence as c


def _state(**over):
    base = dict(
        supported=True,
        enabled=True,
        api_key_required=False,
        api_key_set=False,
        with_id=5,
        total=10,
        health_row=None,
        id_suspect=False,
    )
    base.update(over)
    return c.source_state("target", **base)["state"]


def test_not_implemented_wins():
    assert _state(supported=False, enabled=True) == c.NOT_IMPLEMENTED


def test_disabled():
    assert _state(enabled=False) == c.DISABLED


def test_needs_api_key():
    assert _state(api_key_required=True, api_key_set=False) == c.NEEDS_API_KEY


def test_needs_id():
    assert _state(with_id=0) == c.NEEDS_ID


def test_blocked_from_health_status():
    assert _state(health_row={"last_status": "BLOCKED", "last_check_ts": 1}) == c.BLOCKED


def test_blocked_from_http_403():
    assert _state(health_row={"last_http_status": 403, "last_check_ts": 1}) == c.BLOCKED


def test_parser_suspect_on_no_data():
    assert _state(health_row={"last_status": "NO_DATA", "last_check_ts": 1}) == c.PARSER_SUSPECT


def test_id_suspect():
    assert _state(id_suspect=True, health_row={"last_status": "OK", "state": "healthy", "last_check_ts": 1}) == c.ID_SUSPECT


def test_degraded():
    assert _state(health_row={"state": "degraded", "last_status": "ERROR", "last_check_ts": 1}) == c.DEGRADED


def test_working_when_healthy():
    assert _state(health_row={"state": "healthy", "last_status": "OK", "last_check_ts": 1}) == c.WORKING


def test_ready_when_configured_but_unrun():
    assert _state(health_row=None) == c.READY


def test_needs_id_beats_blocked():
    # precedence: a source with no IDs is NEEDS_ID even if health shows a block
    assert _state(with_id=0, health_row={"last_status": "BLOCKED", "last_check_ts": 1}) == c.NEEDS_ID


def test_target_blocked_action_mentions_key_rotation():
    row = c.source_state(
        "target", supported=True, enabled=True, with_id=5, total=10,
        health_row={"last_status": "BLOCKED", "last_check_ts": 1},
    )
    assert "TARGET_API_KEY" in row["action"]


def test_confidence_report_from_coverage():
    coverage = {
        "retailers": [
            {"slug": "target", "name": "Target", "enabled": True, "supported": True,
             "apiKeyRequired": False, "apiKeySet": False, "onlineOnly": False,
             "withId": 5, "total": 10},
            {"slug": "costco", "name": "Costco", "enabled": True, "supported": True,
             "apiKeyRequired": False, "apiKeySet": False, "onlineOnly": False,
             "withId": 0, "total": 10},
        ]
    }
    rows = c.confidence_report(coverage, [], {"target": True})
    by_slug = {r["slug"]: r for r in rows}
    assert by_slug["costco"]["state"] == c.NEEDS_ID
    assert by_slug["target"]["state"] == c.ID_SUSPECT
    assert by_slug["target"]["name"] == "Target"
