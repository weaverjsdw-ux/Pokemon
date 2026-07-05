"""Opportunity model + deterministic, rules-first scoring (Phase C).

Turns the owned comp response + momentum summary + an optional verified deal
candidate into a deterministic ``Opportunity`` record: which money hypothesis a
sealed product tests, the evidence for/against, and whether the program would
paper-buy / watch / reject / mark it live-packet-eligible.

Pure: no network, no clock (``as_of`` is passed in), no writes. Money math is NOT
re-invented here — ``expected_net``/``expected_roi_pct``/``verdict_tier`` are
computed by the exact same functions the alert path uses (``margin`` +
``verdict``), fed the way ``scanner.main.verdict_for_alert`` feeds them, so the
numbers match. Price accuracy is STOP-class: no verified entry price or no comp
=> the dollar fields are ``None``, never a fabricated or MSRP-as-if-a-price value.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .. import margin as margin_mod
from .. import resale
from .. import verdict as verdict_mod

TBD = "TBD_OPERATOR_POLICY"

# Trade taxonomy (sealed-only in Phase C). key -> the money hypothesis it tests.
TRADE_TYPES: dict[str, str] = {
    "sealed_catalog_gap": "product lacks enough comp/history data; improve before acting",
    "sealed_stale_comp": "comp exists but is stale; not safe for action, refresh first",
    "sealed_retail_arbitrage": "verified retail price is materially below current market comp",
    "sealed_momentum_watch": "appreciating/strengthening, but no buyable entry confirmed yet",
    "sealed_no_edge": "no current actionable edge",
}
# Only these trade types may EVER reach LIVE_PACKET_ELIGIBLE (evidence-spine anchor).
LIVE_ELIGIBLE: set[str] = {"sealed_retail_arbitrage"}

# Scoring weights (module-level so they are easy to audit/tune; no ML).
W_DISCOUNT = 30.0
W_NET = 25.0
W_ROI = 15.0
W_MOMENTUM_UP = 10.0
W_MOMENTUM_SINGLE = 3.0
W_MOMENTUM_DOWN = -8.0
W_CONF = {"high": 15.0, "medium": 9.0, "low": 3.0, "none": 0.0}
W_SRC = {"agree": 5.0, "partial": 3.0, "single": 1.0, "none": 0.0}
P_STALE = -15.0
P_NO_HISTORY = -10.0
P_RISK_EACH = -4.0
P_RISK_CAP = -12.0
RISK_SCORED = {"high_premium_over_msrp", "single_source_comp", "declining_momentum"}


@dataclass(frozen=True)
class Opportunity:
    opportunity_id: str
    product_key: str
    name: str
    asset_class: str
    as_of: str
    hypothesis: str
    trade_type: str
    live_eligible: bool
    entry_price: float | None
    market_comp: float | None
    unopenedPrice: float | None
    msrp: float | None
    discount_pct: float | None
    expected_net: float | None
    expected_roi_pct: float | None
    verdict_tier: str
    momentum_delta_pct: float | None
    momentum_status: str
    latest_confidence: str | None
    source_count: int
    source_agreement: str
    stale: bool
    hold_days: int | str
    exit_venue: str
    evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    decision_hint: str = "WATCH"
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------- ids & helpers

def opportunity_id(product_key: str, trade_type: str, as_of: str) -> str:
    raw = f"{product_key}|{trade_type}|{as_of}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _confidence_ge(confidence: str | None, floor: str) -> bool:
    order = verdict_mod.CONFIDENCE_ORDER
    return order.get((confidence or "none").lower(), 0) >= order.get(floor, 2)


def _shipping_for(product: dict, cfg) -> float:
    """Per-product seller-paid shipping override, else the config default.
    Identical to scanner.main._shipping_for so the net math matches."""
    try:
        return float(product.get("est_shipping"))
    except (TypeError, ValueError):
        return cfg.ebay_est_shipping


def _source_agreement(source_count: int, confidence: str) -> str:
    if source_count >= 2 and confidence == "high":
        return "agree"
    if source_count >= 2 and confidence == "medium":
        return "partial"
    if source_count >= 1:
        return "single"
    return "none"


def _primary_source(comp: dict) -> str:
    sources = comp.get("sources") or []
    if sources and isinstance(sources[0], dict) and sources[0].get("source"):
        return str(sources[0]["source"])
    return str(comp.get("compBasis") or "ledger")


# ---------------------------------------------------------------- money math

def compute_margin(entry_price, comp, confidence, product, cfg):
    """(expected_net, expected_roi_pct, verdict_tier) via the exact alert-path
    composition. No verified entry price or no comp => (None, None, 'n/a')."""
    if entry_price is None or comp is None:
        return None, None, "n/a"
    fees = margin_mod.FeeModel(
        ebay_fvf_pct=cfg.ebay_fvf_pct,
        ebay_fixed_fee=cfg.ebay_fixed_fee,
        local_haircut_pct=cfg.local_haircut_pct,
    )
    cost = margin_mod.cost_basis(entry_price, cfg.tax_rate)
    result = margin_mod.net_margin(cost, comp, "ebay", _shipping_for(product, cfg), fees)
    v = verdict_mod.buy_verdict(result, confidence, verdict_mod.thresholds_from_config(cfg))
    return result.dollar_margin, result.roi_pct, v.tier


# ---------------------------------------------------------------- classify

def classify_trade(*, market_comp, momentum_status, stale, entry_price,
                   discount_pct, momentum_delta_pct, cfg) -> str:
    """Deterministic, first-match-wins, facts only. Independent of the eventual
    decision (a failing arbitrage is still that *hypothesis*).

    A verified entry price + a comp is actionable arbitrage even with a thin
    ledger, so the arbitrage check precedes the no-history catalog_gap check; a
    weak comp is still demoted to WATCH downstream by the fee-adjusted verdict."""
    if market_comp is None:
        return "sealed_catalog_gap"
    if stale:
        return "sealed_stale_comp"
    if (entry_price is not None and discount_pct is not None
            and discount_pct >= cfg.poke.min_discount_pct):
        return "sealed_retail_arbitrage"
    if momentum_status == "no_history":
        return "sealed_catalog_gap"
    if momentum_status == "ok" and momentum_delta_pct is not None and momentum_delta_pct > 0:
        return "sealed_momentum_watch"
    return "sealed_no_edge"


# ---------------------------------------------------------------- decide

def _missing_live_requirement(net, roi, confidence, stale, cfg) -> str:
    if stale:
        return "stale comp; not live-eligible"
    if net is None or net < cfg.opportunity.live_min_expected_net:
        return "expected net below live floor"
    if roi is None or roi < cfg.opportunity.live_min_roi_pct:
        return "roi below live floor"
    if not _confidence_ge(confidence, cfg.opportunity.live_min_confidence):
        return "confidence below live floor"
    return "paper buy"


def decide(*, trade_type, verdict_tier, entry_price, market_comp, stale,
           expected_net, expected_roi_pct, latest_confidence, cfg):
    """Total function: every input maps to a decision; never raises.

    LIVE_PACKET_ELIGIBLE only through the verified evidence spine (entry + comp +
    fresh + BUY verdict) AND the stricter live floor AND a live-eligible type."""
    live_eligible = trade_type in LIVE_ELIGIBLE
    live_clear = (
        expected_net is not None and expected_roi_pct is not None
        and expected_net >= cfg.opportunity.live_min_expected_net
        and expected_roi_pct >= cfg.opportunity.live_min_roi_pct
        and _confidence_ge(latest_confidence, cfg.opportunity.live_min_confidence)
    )
    if (live_eligible and entry_price is not None and market_comp is not None
            and not stale and verdict_tier == "BUY" and live_clear):
        return "LIVE_PACKET_ELIGIBLE", "verified buyable + clears live floor"

    if trade_type == "sealed_retail_arbitrage":
        if verdict_tier == "BUY":
            return "PAPER_BUY", _missing_live_requirement(
                expected_net, expected_roi_pct, latest_confidence, stale, cfg)
        if verdict_tier == "SKIP":
            return "REJECT", "fee-adjusted margin below skip floor"
        return "WATCH", "thin margin / capped confidence"

    if trade_type in ("sealed_catalog_gap", "sealed_stale_comp", "sealed_momentum_watch"):
        return "WATCH", TRADE_TYPES[trade_type]
    return "WATCH", "no current actionable edge"


# ---------------------------------------------------------------- risks/evidence

def _risks(*, stale, momentum_status, confidence, source_count, market_comp,
           msrp, momentum_delta_pct, entry_price) -> list[str]:
    risks: list[str] = []
    if stale:
        risks.append("stale_comp")
    if momentum_status in ("no_history", "single_observation"):
        risks.append("thin_history")
    if confidence in ("low", "none"):
        risks.append("low_confidence_comp")
    if source_count <= 1:
        risks.append("single_source_comp")
    if market_comp is not None and msrp not in (None, 0) and (market_comp / msrp - 1) > 0.5:
        risks.append("high_premium_over_msrp")
    if momentum_delta_pct is not None and momentum_delta_pct < 0:
        risks.append("declining_momentum")
    if entry_price is None and market_comp is not None:
        risks.append("no_verified_entry")
    return risks


def _evidence(*, comp, momentum, candidate, entry_price, discount_pct,
              expected_net, expected_roi_pct) -> list[str]:
    """Human-readable evidence. Every numeric line carries source + date
    (STOP-class: no anonymous numbers)."""
    ev: list[str] = []
    est = comp.get("estimate")
    if est is not None:
        ev.append(
            f"market comp ${est:.2f} from {_primary_source(comp)} "
            f"({comp.get('confidence') or 'none'}) as of {comp.get('checkedAt') or 'unknown'}")
    status = momentum.get("status")
    if status == "ok" and momentum.get("delta_pct") is not None:
        ev.append(
            f"momentum ok: {momentum['delta_pct']:+.2f}% "
            f"({momentum.get('first_seen')}->{momentum.get('last_seen')})")
    elif status == "single_observation":
        ev.append(f"momentum single_observation (last_seen {momentum.get('last_seen')})")
    if entry_price is not None:
        who = (candidate or {}).get("retailer") or (candidate or {}).get("source") or "unknown"
        ev.append(f"verified entry ${entry_price:.2f} at {who}")
    if discount_pct is not None:
        ev.append(f"entry {discount_pct:.2f}% below comp")
    if expected_net is not None and expected_roi_pct is not None:
        ev.append(
            f"expected net ${expected_net:.2f} / {expected_roi_pct:.1f}% ROI "
            f"on eBay (after fees+tax)")
    return ev


# ---------------------------------------------------------------- scoring

def score_opportunity(*, discount_pct, expected_net, expected_roi_pct,
                      momentum_status, momentum_delta_pct, confidence,
                      source_agreement, stale, risks, cfg):
    """Deterministic 0..100 score. ``score_breakdown`` holds signed component
    contributions; the (pre-clamp) sum is the raw score."""
    b: dict[str, float] = {}
    b["discount"] = (round(_clamp(discount_pct, 0.0, 50.0) / 50.0 * W_DISCOUNT, 2)
                     if discount_pct is not None else 0.0)
    b["net"] = (round(_clamp(expected_net / (2 * cfg.buy_floor_net), 0.0, 1.0) * W_NET, 2)
                if expected_net is not None and cfg.buy_floor_net > 0 else 0.0)
    b["roi"] = (round(_clamp(expected_roi_pct / (2 * cfg.buy_floor_roi), 0.0, 1.0) * W_ROI, 2)
                if expected_roi_pct is not None and cfg.buy_floor_roi > 0 else 0.0)
    if momentum_status == "ok" and momentum_delta_pct is not None:
        b["momentum"] = (W_MOMENTUM_UP if momentum_delta_pct > 0
                         else W_MOMENTUM_DOWN if momentum_delta_pct < 0 else 0.0)
    elif momentum_status == "single_observation":
        b["momentum"] = W_MOMENTUM_SINGLE
    else:
        b["momentum"] = 0.0
    b["confidence"] = W_CONF.get(confidence or "none", 0.0)
    b["sources"] = W_SRC.get(source_agreement, 0.0)
    b["staleness_penalty"] = P_STALE if stale else 0.0
    b["no_history_penalty"] = P_NO_HISTORY if momentum_status == "no_history" else 0.0
    scored = sum(1 for r in risks if r in RISK_SCORED)
    b["risk_penalty"] = max(P_RISK_EACH * scored, P_RISK_CAP)
    raw = round(sum(b.values()), 1)
    return round(_clamp(raw, 0.0, 100.0), 1), b


# ---------------------------------------------------------------- assemble

def build_opportunity(product_key, product, comp, momentum, candidate, cfg, *, as_of):
    """Assemble one deterministic Opportunity from the owned comp/momentum shapes
    and an optional verified deal candidate."""
    market_comp = comp.get("estimate")
    confidence = str(comp.get("confidence") or "none")
    sources = comp.get("sources") or []
    source_count = len(sources)
    msrp = resale._amount(product.get("msrp"))

    entry_price = resale._amount(candidate.get("verified_price")) if candidate else None
    discount_pct = None
    if entry_price is not None and market_comp is not None and market_comp > 0:
        discount_pct = round((market_comp - entry_price) / market_comp * 100.0, 2)

    momentum_status = str(momentum.get("status") or "no_history")
    momentum_delta_pct = momentum.get("delta_pct")
    stale = bool(comp.get("stale")) or bool(momentum.get("stale"))
    # latest_confidence is the confidence backing the comp number that drives the
    # decision (same one buy_verdict caps on), NOT momentum.latest_confidence.
    latest_confidence = confidence if confidence != "none" else None

    expected_net, expected_roi_pct, verdict_tier = compute_margin(
        entry_price, market_comp, confidence, product, cfg)
    source_agreement = _source_agreement(source_count, confidence)

    trade_type = classify_trade(
        market_comp=market_comp, momentum_status=momentum_status, stale=stale,
        entry_price=entry_price, discount_pct=discount_pct,
        momentum_delta_pct=momentum_delta_pct, cfg=cfg)

    risks = _risks(
        stale=stale, momentum_status=momentum_status, confidence=confidence,
        source_count=source_count, market_comp=market_comp, msrp=msrp,
        momentum_delta_pct=momentum_delta_pct, entry_price=entry_price)
    evidence = _evidence(
        comp=comp, momentum=momentum, candidate=candidate, entry_price=entry_price,
        discount_pct=discount_pct, expected_net=expected_net,
        expected_roi_pct=expected_roi_pct)

    decision, reason = decide(
        trade_type=trade_type, verdict_tier=verdict_tier, entry_price=entry_price,
        market_comp=market_comp, stale=stale, expected_net=expected_net,
        expected_roi_pct=expected_roi_pct, latest_confidence=latest_confidence, cfg=cfg)
    if reason and reason not in evidence:
        evidence = evidence + [f"decision: {decision} — {reason}"]

    score, breakdown = score_opportunity(
        discount_pct=discount_pct, expected_net=expected_net,
        expected_roi_pct=expected_roi_pct, momentum_status=momentum_status,
        momentum_delta_pct=momentum_delta_pct, confidence=confidence,
        source_agreement=source_agreement, stale=stale, risks=risks, cfg=cfg)

    return Opportunity(
        opportunity_id=opportunity_id(product_key, trade_type, as_of),
        product_key=product_key,
        name=product.get("name") or product_key,
        asset_class=str((candidate or {}).get("asset_class") or "sealed"),
        as_of=as_of,
        hypothesis=TRADE_TYPES[trade_type],
        trade_type=trade_type,
        live_eligible=trade_type in LIVE_ELIGIBLE,
        entry_price=entry_price,
        market_comp=market_comp,
        unopenedPrice=market_comp,
        msrp=msrp,
        discount_pct=discount_pct,
        expected_net=expected_net,
        expected_roi_pct=expected_roi_pct,
        verdict_tier=verdict_tier,
        momentum_delta_pct=momentum_delta_pct,
        momentum_status=momentum_status,
        latest_confidence=latest_confidence,
        source_count=source_count,
        source_agreement=source_agreement,
        stale=stale,
        hold_days=cfg.opportunity.max_hold_days.get(trade_type, TBD),
        exit_venue=cfg.opportunity.exit_venue.get(trade_type, TBD),
        evidence=evidence,
        risks=risks,
        decision_hint=decision,
        score=score,
        score_breakdown=breakdown,
    )
