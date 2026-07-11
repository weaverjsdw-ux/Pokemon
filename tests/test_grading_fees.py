"""Sourced, dated PSA grading cost schedule (STOP-class provenance).

PSA paused its discount "value" grading tiers 2026-06-02, so the realistic floor for
a raw->graded submission is the Regular tier all-in cost (grading fee + return
shipping) -- NOT a stale ~$25 value-tier assumption. PIN-FIRST: the seeded figure is
an ``operator_assumption`` until the live PSA pricing page is pinned + cited, so these
tests assert a FLOOR (``>= 80``), never an exact memory-locked number. Fail-safe
direction: for grading-EV a higher grading cost is the conservative error."""
from __future__ import annotations

from scanner import grading_fees


def test_regular_tier_reflects_paused_value_tiers_post_2026_06():
    fee, eff, url = grading_fees.grading_fee_for("2026-07-01", "regular")
    assert fee >= 80.0            # value tiers paused -> real floor, not ~$25
    assert eff <= "2026-07-01" and url


def test_value_tier_unavailable_after_pause_falls_back_never_fabricates():
    fee, eff, url = grading_fees.grading_fee_for("2026-07-01", "value")
    assert fee >= 80.0            # no $25 value tier exists post-pause; never invents one


def test_schedule_snapshot_is_badged_operator_assumption_until_pinned():
    # PIN-FIRST: the seeded figure must not read as a cited live-page number until the
    # live PSA pricing page is actually pinned + cited with a capture date.
    fee, eff, url = grading_fees.grading_fee_for("2026-07-01", "regular")
    assert "operator_assumption" in url.lower()


def test_unknown_tier_falls_back_to_cheapest_available_with_a_note():
    fee, eff, url = grading_fees.grading_fee_for("2026-07-01", "made_up_tier_xyz")
    assert fee >= 80.0
    assert "made_up_tier_xyz" in url.lower() or "fell back" in url.lower() or "fallback" in url.lower()


def test_as_of_none_uses_latest_snapshot():
    fee, eff, url = grading_fees.grading_fee_for(None, "regular")
    assert fee >= 80.0 and eff and url
