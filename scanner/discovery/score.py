"""Deterministic scoring for /poke deals: pct_off, badges, fake-markdown flags,
the four lenses, dedup, and the minimum-discount split.

The Flipper (FLP) lens computes net margin through the existing backbone
(scanner.margin + scanner.verdict) so a dashboard FLP tag equals the scanner's
BUY verdict for the same numbers. No fees are re-hardcoded here.
"""
from __future__ import annotations

from .schema import DealRow
from .. import margin as margin_mod
from .. import verdict as verdict_mod

FAKE_MARKDOWN = {"INFLATED_ORIGINAL", "SUSPICIOUSLY_LOW", "MISLEADING_PCT"}


def compute_pct_off(deal_price: float, market_comp: float | None) -> float | None:
    if not market_comp or market_comp <= 0:
        return None
    return round((market_comp - deal_price) / market_comp * 100)


def fake_markdown_flags(
    deal_price: float,
    market_comp: float | None,
    claimed_was: float | None,
    has_legit_explanation: bool,
) -> list[str]:
    flags: list[str] = []
    if market_comp and market_comp > 0:
        if claimed_was and claimed_was > market_comp * 1.30:
            flags.append("INFLATED_ORIGINAL")
        if deal_price < market_comp * 0.70 and not has_legit_explanation:
            flags.append("SUSPICIOUSLY_LOW")
        # big headline discount but the actual price barely beats market
        if claimed_was and claimed_was > market_comp * 1.20 and deal_price > market_comp * 0.90:
            flags.append("MISLEADING_PCT")
    return flags


def _fees(cfg) -> margin_mod.FeeModel:
    return margin_mod.FeeModel(
        ebay_fvf_pct=cfg.ebay_fvf_pct,
        ebay_fixed_fee=cfg.ebay_fixed_fee,
        local_haircut_pct=cfg.local_haircut_pct,
    )


def flipper_is_buy(deal_price: float, market_comp: float, cfg) -> bool:
    cost = margin_mod.cost_basis(deal_price, cfg.tax_rate)
    result = margin_mod.net_margin(cost, market_comp, "ebay", cfg.ebay_est_shipping, _fees(cfg))
    v = verdict_mod.buy_verdict(result, "high", verdict_mod.thresholds_from_config(cfg))
    return v.tier == "BUY"


def assign_badges(row: DealRow, cfg) -> list[str]:
    badges: list[str] = []
    if row.price_confidence == "est":
        badges.append("EST")
    pct = row.pct_off if row.pct_off is not None else compute_pct_off(row.deal_price, row.market_comp)
    # An ask-basis comp (active listings, not sold data) can never anchor a
    # STEAL, no matter how verified the deal price is (spec 4.3).
    basis = row.comp_basis.lower()
    ask_basis = "active_ask" in basis or "asking" in basis
    steal_ok = (
        row.price_confidence == "verified"
        and not row.authenticity_risk
        and not row.stale
        and not ask_basis
        and pct is not None
        and pct >= cfg.poke.steal_pct
    )
    if steal_ok:
        badges.append("STEAL")
    if row.warn_reason or row.authenticity_risk:
        badges.append("WARN")
    return badges


def lens_tags(row: DealRow, cfg) -> list[str]:
    # A possible-fake/reseal earns NO positive lens recommendation, even if its
    # nominal margin clears — never tell the operator to flip a flagged item.
    if row.authenticity_risk:
        return []
    tags: list[str] = []
    pct = row.pct_off if row.pct_off is not None else compute_pct_off(row.deal_price, row.market_comp)
    verified = row.price_confidence == "verified" and row.comp_confidence in {"high", "medium"}
    # Collector: verified comp + a collectibility marker
    if verified and (row.finite or row.grade or "alt" in row.variant.lower()):
        tags.append("COL")
    # Player: play-value classes clearing the discount floor
    if row.asset_class in {"raw", "sealed"} and row.category in {"sealed-etb", "singles-meta"} \
            and pct is not None and pct >= cfg.poke.min_discount_pct:
        tags.append("PLY")
    # Investor: verified appreciation basis, comp-backed, not deep-reprint-risk
    if verified and not row.reprint_risk and pct is not None and pct >= cfg.poke.min_discount_pct:
        tags.append("INV")
    # Flipper: net margin clears BUY through the backbone — only on a verified comp
    # (price-accuracy rule: never tag a lens off an EST/low-confidence comp).
    if row.price_confidence == "verified" and row.market_comp \
            and flipper_is_buy(row.deal_price, row.market_comp, cfg):
        tags.append("FLP")
    return tags


def _identity(row: DealRow) -> tuple:
    return (row.item.strip().lower(), row.set.strip().lower(),
            row.variant.strip().lower(), row.grade.strip().lower(),
            row.condition.strip().lower())


def dedup(rows: list[DealRow]) -> list[DealRow]:
    best: dict[tuple, DealRow] = {}
    for row in rows:
        key = _identity(row)
        if key not in best or row.deal_price < best[key].deal_price:
            best[key] = row
    return list(best.values())


def split_min_discount(rows: list[DealRow], cfg) -> tuple[list[DealRow], list[DealRow]]:
    deals: list[DealRow] = []
    below: list[DealRow] = []
    for row in rows:
        pct = row.pct_off if row.pct_off is not None else compute_pct_off(row.deal_price, row.market_comp)
        if pct is not None and pct >= cfg.poke.min_discount_pct:
            deals.append(row)
        else:
            below.append(row)
    return deals, below
