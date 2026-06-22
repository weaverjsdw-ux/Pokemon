"""Pure BUY/THIN/SKIP tier logic. Demote-never-hide.

Margin sets the tier (gated on net dollars AND % ROI by default); hype affects
only ranking elsewhere; confidence can cap a BUY down but never invents one.
"""
from __future__ import annotations

from dataclasses import dataclass

from .margin import MarginResult

CONFIDENCE_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


@dataclass(frozen=True)
class VerdictThresholds:
    skip_floor_net: float = 5.0
    buy_floor_net: float = 15.0
    roi_gate_enabled: bool = True
    skip_floor_roi: float = 10.0
    buy_floor_roi: float = 20.0
    min_buy_confidence: str = "medium"


@dataclass(frozen=True)
class Verdict:
    tier: str
    headline: str
    net: float
    roi_pct: float
    channel: str
    confidence: str


def thresholds_from_config(cfg) -> VerdictThresholds:
    return VerdictThresholds(
        skip_floor_net=cfg.skip_floor_net,
        buy_floor_net=cfg.buy_floor_net,
        roi_gate_enabled=cfg.roi_gate_enabled,
        skip_floor_roi=cfg.skip_floor_roi,
        buy_floor_roi=cfg.buy_floor_roi,
        min_buy_confidence=cfg.min_buy_confidence,
    )


def _margin_tier(margin: MarginResult, t: VerdictThresholds) -> str:
    roi_ok_buy = (not t.roi_gate_enabled) or margin.roi_pct >= t.buy_floor_roi
    roi_bad_skip = t.roi_gate_enabled and margin.roi_pct < t.skip_floor_roi
    if margin.dollar_margin >= t.buy_floor_net and roi_ok_buy:
        return "BUY"
    if margin.dollar_margin < t.skip_floor_net or roi_bad_skip:
        return "SKIP"
    return "THIN"


def buy_verdict(
    margin: MarginResult,
    comp_confidence: str,
    thresholds: VerdictThresholds,
    derived_only: bool = False,
) -> Verdict:
    tier = _margin_tier(margin, thresholds)
    confidence = (comp_confidence or "none").lower()

    capped_reason = ""
    if tier == "BUY":
        below_min = CONFIDENCE_ORDER.get(confidence, 0) < CONFIDENCE_ORDER.get(
            thresholds.min_buy_confidence, 2
        )
        if derived_only:
            tier = "THIN"
            capped_reason = " (derived local comp)"
        elif below_min:
            tier = "THIN"
            capped_reason = f" ({confidence}-confidence comp)"

    headline = (
        f"{tier} · {_signed(margin.dollar_margin)} net, "
        f"{margin.roi_pct:g}% ROI{capped_reason}"
    )
    return Verdict(
        tier=tier,
        headline=headline,
        net=margin.dollar_margin,
        roi_pct=margin.roi_pct,
        channel=margin.channel,
        confidence=confidence,
    )


def _signed(amount: float) -> str:
    sign = "+" if amount >= 0 else "-"
    return f"{sign}${abs(amount):.2f}"
