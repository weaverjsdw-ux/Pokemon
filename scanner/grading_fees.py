"""Sourced, dated PSA grading cost schedule (STOP-class provenance).

PSA paused its discount "value" grading tiers on **2026-06-02**, so the realistic
floor for a raw->graded submission is now the Regular tier all-in cost (grading fee +
return shipping) -- NOT a stale ~$25 value-tier assumption still floating around older
configs/comps. Every snapshot in ``GRADING_SCHEDULE`` carries an ``effective_date`` +
``source_url``, and a requested tier absent at a given date (the paused "value" tier,
or any unknown tier) falls back to the CHEAPEST tier actually available at that date --
this module never fabricates a paused/nonexistent tier's price.

PIN-FIRST (STOP-class, money-class): this seed's ~$80 Regular-tier figure is an
``operator_assumption`` -- badged in ``source_url`` -- until the LIVE PSA pricing page
is pinned and cited with a capture date. Fail-safe direction: for grading-EV a HIGHER
grading cost is the conservative error (it makes the EV LESS likely to greenlight
grading a raw), so this seed is pinned at-or-above the known real floor, never below
it. Flip the badge from ``operator_assumption`` to a cited source once the live PSA
page is pinned. No network, no clock -- ``as_of`` is supplied by the caller.
"""
from __future__ import annotations

# operator_assumption: estimated return shipping + insurance to get the slab back from
# PSA; not yet pinned to a cited carrier rate. Included because "all-in" grading cost
# for EV purposes must be landed cost, not just the grading-tier sticker price.
RETURN_SHIPPING_ASSUMED = 15.0

# operator_assumption: the PSA Regular-tier grading sticker price (pre return
# shipping), seeded as a conservative (higher-is-safer) floor -- see PIN-FIRST note
# above. Shared by BOTH the ``tiers`` value and the provenance ``source_url`` prose
# below so a future PIN-FIRST update to the real number can never desync the two.
PSA_REGULAR_FEE_ASSUMED = 80.0

# operator_assumption badge text, threaded into every un-pinned snapshot's source_url so
# any consumer (grading_ev provenance, CLI output, tests) can see at a glance that this
# number is not yet a cited live-page figure.
_OPERATOR_ASSUMPTION_BADGE = "operator_assumption"

GRADING_SCHEDULE: list[dict] = [
    {
        "effective_date": "2026-06-02",  # PSA value-tier pause date (operator-known)
        "source_url": (
            f"{_OPERATOR_ASSUMPTION_BADGE}: PSA discount 'value' grading tiers paused "
            "2026-06-02 (value tier ~$25 no longer offered); Regular tier all-in seeded "
            f"at ${PSA_REGULAR_FEE_ASSUMED:.2f} grading + ${RETURN_SHIPPING_ASSUMED:.2f} "
            "return shipping/insurance as a conservative (higher-is-safer) floor -- "
            "PENDING pin of the live PSA pricing page + capture date, see PIN-FIRST "
            "note in scanner/grading_fees.py"
        ),
        "tiers": {
            # No "value" key here: the tier is paused, not just expensive -- absence is
            # the honest representation. grading_fee_for() falls back to the cheapest
            # tier actually present (today, "regular") rather than inventing one.
            "regular": PSA_REGULAR_FEE_ASSUMED + RETURN_SHIPPING_ASSUMED,
        },
    },
]


def _snapshot_for(as_of: str | None) -> dict:
    """The latest schedule snapshot with ``effective_date <= as_of`` (ISO ``YYYY-MM-DD``
    strings compare lexicographically). ``as_of=None`` means "today" for a
    forward-seeded schedule -- use the latest known snapshot. A date older than every
    snapshot falls back to the earliest one (the schedule has no data before it)."""
    dated = [s for s in GRADING_SCHEDULE if as_of is None or s["effective_date"] <= as_of]
    pool = dated or GRADING_SCHEDULE
    return max(pool, key=lambda s: s["effective_date"])


def grading_fee_for(as_of: str | None = None, tier: str = "regular") -> tuple[float, str, str]:
    """``(all_in_fee, effective_date, source_url)`` for ``tier`` as of ``as_of``.

    ``as_of`` is an ISO ``YYYY-MM-DD`` string (or ``None`` for the latest snapshot).
    When the requested tier does not exist in that snapshot -- the paused PSA "value"
    tier, or any unrecognized tier name -- this falls back to the CHEAPEST tier that
    actually exists in the snapshot and appends a note to ``source_url``; it never
    invents a price for a paused/nonexistent tier."""
    snap = _snapshot_for(as_of)
    tiers = snap["tiers"]
    key = str(tier or "regular").strip().lower()
    if key in tiers:
        return tiers[key], snap["effective_date"], snap["source_url"]
    cheapest_key = min(tiers, key=lambda k: tiers[k])
    note = (f" [requested tier '{key}' unavailable as of {snap['effective_date']} "
            f"(paused/nonexistent) -- fell back to cheapest available tier "
            f"'{cheapest_key}', never fabricated]")
    return tiers[cheapest_key], snap["effective_date"], snap["source_url"] + note
