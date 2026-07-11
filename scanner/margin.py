"""Pure fee-adjusted margin math for the deal-intelligence verdict.

Resale comps are context for MSRP-protection decisions, not a scalping target.
No network or disk I/O — every input is passed in, every output is a value.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date as _date


@dataclass(frozen=True)
class FeeModel:
    ebay_fvf_pct: float = 0.1325
    ebay_fixed_fee: float = 0.40
    local_haircut_pct: float = 0.15
    tcgplayer_commission_pct: float = 0.1075
    tcgplayer_processing_pct: float = 0.025
    tcgplayer_fixed_fee: float = 0.30
    ebay_high_value_threshold: float = 1000.0
    # FAIL-SAFE: equal to the full FVF, i.e. NO discount applies, until the live eBay
    # Trading Cards *category* fee structure is pinned + cited (see PIN-FIRST HARD GATE
    # in docs/superpowers/specs/2026-06-28-resale-engine-program-roadmap.md). An
    # unverified fee must err toward higher fees / lower net, never toward fake profit.
    ebay_high_value_fvf_pct: float = 0.1325
    effective_date: str = ""
    source_url: str = ""


FEE_SCHEDULE: tuple[FeeModel, ...] = (
    FeeModel(effective_date="2026-02-10",
             source_url="https://www.ebay.com/help/selling/fees-credits-invoices/"
                        "selling-fees | https://help.tcgplayer.com/ (TCGplayer 10.75% eff 2026-02-10)"),
)


def fee_model_for(as_of: str | None = None) -> FeeModel:
    """The dated fee snapshot in effect on ``as_of`` (ISO ``YYYY-MM-DD``). ``None`` or a
    MALFORMED date -> the newest snapshot (never a stale era); a valid date before every
    snapshot -> the oldest snapshot. Validated on the ``YYYY-MM-DD`` prefix so a datetime
    string still resolves by its date part."""
    if as_of:
        try:
            _date.fromisoformat(str(as_of)[:10])
        except ValueError:
            as_of = None            # malformed -> newest, never a stale/oldest era
    if not as_of:
        return FEE_SCHEDULE[-1]
    applicable = [m for m in FEE_SCHEDULE if m.effective_date <= as_of]
    return applicable[-1] if applicable else FEE_SCHEDULE[0]


def fee_model_from_cfg(cfg, as_of: str | None = None) -> FeeModel:
    """The dated schedule model for ``as_of``, with the operator's config-scalar
    overrides layered on top (config wins on the 3 fields it carries: eBay FVF/fixed
    fee, local haircut). Starting from ``fee_model_for`` (not a bare 3-scalar
    ``FeeModel(...)``) is what carries the TCGplayer + eBay-high-value + provenance
    fields to every consumer instead of losing them to the config-only fields.
    TCGplayer config overrides layer the same way; ``ebay_high_value_fvf_pct`` is
    NEVER overridden here (stays FAIL-SAFE at the schedule's default -- see
    PIN-FIRST HARD GATE)."""
    return replace(
        fee_model_for(as_of),
        ebay_fvf_pct=cfg.ebay_fvf_pct,
        ebay_fixed_fee=cfg.ebay_fixed_fee,
        local_haircut_pct=cfg.local_haircut_pct,
        tcgplayer_commission_pct=cfg.tcgplayer_commission_pct,
        tcgplayer_processing_pct=cfg.tcgplayer_processing_pct,
        tcgplayer_fixed_fee=cfg.tcgplayer_fixed_fee,
    )


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

    eBay: fee = comp*fvf + fixed; seller-paid shipping is a cost. The FVF rate
        switches to `ebay_high_value_fvf_pct` at `ebay_high_value_threshold`, but
        that rate defaults to the full FVF (fail-safe, no discount) until pinned.
    tcgplayer: fee = comp*(commission_pct + processing_pct) + fixed.
    local: no platform fee/shipping; comp is haircut to a derived local price.
    """
    if channel == "ebay":
        # FAIL-SAFE: ebay_high_value_fvf_pct defaults to the FULL FVF, so this branch is a
        # no-op discount (full rate at any comp) until the live eBay Trading Cards category
        # is pinned + a real discounted rate/threshold is set (see PIN-FIRST HARD GATE).
        fvf_pct = (
            fees.ebay_high_value_fvf_pct
            if comp >= fees.ebay_high_value_threshold
            else fees.ebay_fvf_pct
        )
        fee = comp * fvf_pct + fees.ebay_fixed_fee
        net = comp - fee - est_shipping
        denom = 1.0 - fvf_pct
        breakeven = (
            (cost_incl_tax + fees.ebay_fixed_fee + est_shipping) / denom
            if denom > 0
            else float("inf")
        )
    elif channel == "tcgplayer":
        combined_pct = fees.tcgplayer_commission_pct + fees.tcgplayer_processing_pct
        fee = comp * combined_pct + fees.tcgplayer_fixed_fee
        net = comp - fee - est_shipping
        denom = 1.0 - combined_pct
        breakeven = (
            (cost_incl_tax + fees.tcgplayer_fixed_fee + est_shipping) / denom
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
