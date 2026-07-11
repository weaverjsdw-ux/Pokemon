"""Raw -> graded grading EV (Session E Slice D).

Pure, STOP-class expected-value math for the "buy a raw single, grade it, sell the
slab" hypothesis. Reuses the exact alert-path fee model (``margin.net_margin`` on
eBay) — no new money math. It **blocks on any missing required input** (raw entry,
raw comp, graded comp for the target grade, grading fee, resale fees, gem rate) and
**never invents** a gem rate, a comp, or a fee: absent → ``status: blocked`` with a
named blocker and ``None`` dollars.

The gem rate is inherently an operator assumption (not verified-data confidence), so a
grading-EV opportunity is capped at PAPER-grade conviction (``actionable``); the edge
layer never promotes it to LIVE. Every number in the output carries a cited
assumption line. No network, no clock.
"""
from __future__ import annotations

from typing import Any

from .. import grading_fees as grading_fees_mod
from .. import margin as margin_mod
from .gem_rates import POP_PROXY_CAVEAT

# The standard sensitivity band a grading decision is read against (never a point
# estimate). The actual sourced/assumed rate is added alongside these.
SENSITIVITY_RATES = (0.20, 0.30, 0.40, 0.50)

# Sentinel distinguishing "caller omitted grading_fee" (derive from the sourced,
# dated schedule) from "caller explicitly passed None" (a genuine missing-input
# block, exercised by test_missing_grading_fee_blocks). A plain ``None`` default
# cannot make this distinction, so a private sentinel object stands in for "not
# supplied" instead.
_FEE_NOT_GIVEN = object()


def _pos(value) -> float | None:
    """A strictly-positive float, else None (STOP-class: 0/None/negative is no input)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def breakeven_gem_rate(*, upside_net, downside_net) -> float | None:
    """The gem rate at which fee-adjusted expected net = 0 (the linear EV model
    ``EV(g) = g*upside + (1-g)*downside``). Returns ``None`` when there is no positive
    spread (``upside <= downside``) — raising the gem rate can never reach break-even, so
    a break-even point is undefined rather than fabricated. The value may fall outside
    ``[0,1]`` (already profitable at g=0, or never profitable at g=1) — reported honestly,
    the reader interprets it against the sensitivity band."""
    try:
        up = float(upside_net)
        down = float(downside_net)
    except (TypeError, ValueError):
        return None
    spread = up - down
    if spread <= 0:
        return None
    return round(-down / spread, 4)


def _ev_at(gem: float, *, cost: float, upside: float, downside: float) -> tuple[float, float | None]:
    net = round(gem * upside + (1.0 - gem) * downside, 2)
    roi = round(net / cost * 100.0, 2) if cost > 0 else None
    return net, roi


def _sensitivity_rows(*, cost: float, upside: float, downside: float, actual_gem: float,
                      buy_floor_net: float) -> list[dict]:
    """EV across the standard 20/30/40/50 % band plus the actual sourced/assumed rate, so
    a decision is read against a band, not a point. Same money model (``_ev_at``)."""
    rates = {round(r, 4) for r in SENSITIVITY_RATES}
    rates.add(round(float(actual_gem), 4))
    rows: list[dict] = []
    for g in sorted(rates):
        net, roi = _ev_at(g, cost=cost, upside=upside, downside=downside)
        rows.append({
            "gem_rate": g,
            "expected_net": net,
            "expected_roi_pct": roi,
            "clears_paper_floor": net >= buy_floor_net,
            "is_actual": g == round(float(actual_gem), 4),
        })
    return rows


def grading_ev(*, raw_entry, raw_comp, graded_comp, grading_fee=_FEE_NOT_GIVEN, gem_rate,
               fees: margin_mod.FeeModel, tax_rate: float, est_shipping: float,
               target_grade: str = "", ship_insurance: float = 0.0,
               downside_comp=None, buy_floor_net: float = 15.0,
               gem_rate_basis: str = "", grading_fee_basis: str = "",
               grading_fee_as_of: str | None = None,
               grading_fee_tier: str = "regular") -> dict[str, Any]:
    """(status, expected_net, expected_roi_pct, downside_net, ...) for grading a raw
    single to ``target_grade``. Blocks (dollars ``None``) unless every required input
    is present and valid; ``gem_rate`` must be in ``(0, 1]``.

    ``grading_fee`` is an explicit **operator override** when supplied (e.g.
    ``cfg.poke.grading_cost_all_in``) — including an explicit ``None``, which is a
    genuine missing-input block, never silently backfilled. When the caller omits
    ``grading_fee`` entirely, the fee is derived from the sourced, dated PSA schedule
    (``scanner.grading_fees.grading_fee_for``) for ``grading_fee_as_of``/
    ``grading_fee_tier``, and its ``(effective_date, source_url)`` is recorded in the
    result's ``grading_fee_provenance``."""
    blockers: list[str] = []
    entry = _pos(raw_entry)
    rcomp = _pos(raw_comp)
    gcomp = _pos(graded_comp)

    fee_provenance: dict[str, str] | None = None
    if grading_fee is _FEE_NOT_GIVEN:
        derived_fee, eff_date, source_url = grading_fees_mod.grading_fee_for(
            grading_fee_as_of, grading_fee_tier)
        fee = derived_fee
        fee_provenance = {"effective_date": eff_date, "source_url": source_url}
        grading_fee_basis = grading_fee_basis or (
            f"sourced schedule: PSA {grading_fee_tier} tier ${derived_fee:.2f} all-in "
            f"(effective {eff_date}; {source_url})")
    else:
        try:
            fee = float(grading_fee)
        except (TypeError, ValueError):
            fee = None
    if entry is None:
        blockers.append("no verified raw entry price")
    if rcomp is None:
        blockers.append("no raw comp")
    if gcomp is None:
        blockers.append(f"no graded comp for target grade {target_grade or '(unspecified)'}")
    if fee is None or fee < 0:
        blockers.append("no grading fee assumption (source/date required)")
    gem = None
    if gem_rate is None:
        blockers.append("no gem rate assumption (never invented - supply operator_assumption or a sourced rate)")
    else:
        try:
            gem = float(gem_rate)
        except (TypeError, ValueError):
            gem = None
        if gem is None or not (0.0 < gem <= 1.0):
            blockers.append("gem rate must be a probability in (0, 1]")
            gem = None

    if blockers:
        return {
            "status": "blocked",
            "target_grade": target_grade,
            "expected_net": None, "expected_roi_pct": None,
            "downside_net": None, "upside_net": None, "cost": None,
            "gem_rate": gem_rate, "gem_rate_basis": gem_rate_basis,
            "grading_fee": fee, "grading_fee_basis": grading_fee_basis,
            "grading_fee_provenance": fee_provenance,
            "assumptions": [],
            "breakeven_gem_rate": None,
            "sensitivity": [],
            "blockers": blockers,
            "reason": "grading EV blocked: " + "; ".join(blockers),
        }

    ship_ins = float(ship_insurance or 0.0)
    cost = round(margin_mod.cost_basis(entry, tax_rate) + fee + ship_ins, 2)
    upside = margin_mod.net_margin(cost, gcomp, "ebay", est_shipping, fees).dollar_margin
    down_basis = _pos(downside_comp)
    down_price = down_basis if down_basis is not None else rcomp
    downside = margin_mod.net_margin(cost, down_price, "ebay", est_shipping, fees).dollar_margin
    expected_net = round(gem * upside + (1.0 - gem) * downside, 2)
    expected_roi_pct = round(expected_net / cost * 100.0, 2) if cost > 0 else None

    down_label = (f"lower-grade comp ${down_basis:.2f} supplied"
                  if down_basis is not None
                  else f"downside modeled at raw comp ${rcomp:.2f} (no lower-grade/PSA9 comp supplied)")
    assumptions = [
        f"raw entry ${entry:.2f} + grading fee ${fee:.2f}"
        + (f" + ship/insurance ${ship_ins:.2f}" if ship_ins else "")
        + f" = landed cost ${cost:.2f}",
        f"grading fee basis: {grading_fee_basis or 'poke.grading_cost_all_in (config)'}",
        f"gem rate {gem:.2%} basis: {gem_rate_basis or 'operator_assumption'}",
        f"upside: sell {target_grade or 'target grade'} @ ${gcomp:.2f} on eBay (after fees+tax) -> net ${upside:.2f}",
        f"downside: {down_label}; grading fee sunk -> net ${downside:.2f}",
        f"EV = {gem:.2%} x ${upside:.2f} + {1-gem:.2%} x ${downside:.2f} = ${expected_net:.2f}",
        f"caveat: {POP_PROXY_CAVEAT}",
    ]
    breakeven = breakeven_gem_rate(upside_net=upside, downside_net=downside)
    sensitivity = _sensitivity_rows(cost=cost, upside=upside, downside=downside,
                                    actual_gem=gem, buy_floor_net=buy_floor_net)
    if breakeven is not None:
        assumptions.append(
            f"break-even gem rate {breakeven:.2%} (EV = $0); actual {gem:.2%} is "
            f"{'above' if gem >= breakeven else 'below'} break-even")
    status = "actionable" if expected_net >= buy_floor_net else "watch"
    reason = (f"grading EV ${expected_net:.2f} net / {expected_roi_pct:.1f}% ROI "
              f"({'clears' if status == 'actionable' else 'below'} paper buy floor "
              f"${buy_floor_net:.2f}); gem rate is an operator assumption (never LIVE)")
    return {
        "status": status,
        "target_grade": target_grade,
        "expected_net": expected_net,
        "expected_roi_pct": expected_roi_pct,
        "downside_net": downside,
        "upside_net": upside,
        "cost": cost,
        "gem_rate": gem,
        "gem_rate_basis": gem_rate_basis or "operator_assumption",
        "grading_fee": round(fee, 2),
        "grading_fee_basis": grading_fee_basis or "poke.grading_cost_all_in (config)",
        "grading_fee_provenance": fee_provenance,
        "assumptions": assumptions,
        "breakeven_gem_rate": breakeven,
        "sensitivity": sensitivity,
        "blockers": [],
        "reason": reason,
    }
