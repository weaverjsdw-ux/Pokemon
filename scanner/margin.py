"""Pure fee-adjusted margin math for the deal-intelligence verdict.

Resale comps are context for MSRP-protection decisions, not a scalping target.
No network or disk I/O — every input is passed in, every output is a value.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeeModel:
    ebay_fvf_pct: float = 0.1325
    ebay_fixed_fee: float = 0.40
    local_haircut_pct: float = 0.15


@dataclass(frozen=True)
class MarginResult:
    channel: str
    net_proceeds: float
    dollar_margin: float
    roi_pct: float
    breakeven_price: float


def cost_basis(observed_price: float, tax_rate: float) -> float:
    """Landed cost = observed retail price grossed up by sales tax."""
    return round(observed_price * (1.0 + tax_rate), 2)


def _roi(dollar_margin: float, cost_incl_tax: float) -> float:
    if cost_incl_tax <= 0:
        return 0.0
    return dollar_margin / cost_incl_tax * 100.0


def net_margin(
    cost_incl_tax: float,
    comp: float,
    channel: str,
    est_shipping: float,
    fees: FeeModel,
) -> MarginResult:
    """Net proceeds and margin for selling at `comp` on `channel`.

    eBay: fee = comp*fvf + fixed; seller-paid shipping is a cost.
    local: no platform fee/shipping; comp is haircut to a derived local price.
    """
    if channel == "ebay":
        fee = comp * fees.ebay_fvf_pct + fees.ebay_fixed_fee
        net = comp - fee - est_shipping
        denom = 1.0 - fees.ebay_fvf_pct
        breakeven = (
            (cost_incl_tax + fees.ebay_fixed_fee + est_shipping) / denom
            if denom > 0
            else float("inf")
        )
    elif channel == "local":
        net = comp * (1.0 - fees.local_haircut_pct)
        denom = 1.0 - fees.local_haircut_pct
        breakeven = cost_incl_tax / denom if denom > 0 else float("inf")
    else:
        raise ValueError(f"Unknown sell channel: {channel!r}")

    margin = net - cost_incl_tax
    return MarginResult(
        channel=channel,
        net_proceeds=round(net, 2),
        dollar_margin=round(margin, 2),
        roi_pct=_roi(margin, cost_incl_tax),
        breakeven_price=round(breakeven, 2),
    )
