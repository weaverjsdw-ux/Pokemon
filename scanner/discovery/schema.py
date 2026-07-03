"""Per-deal row schema + the pre-render STOP gate. Pure, no I/O.

Price accuracy beats coverage. The gate halts a sweep rather than ship a row
that overstates confidence or fabricates a basis.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields

ASSET_CLASSES = {"sealed", "raw", "graded"}
PRICE_CONFIDENCE = {"verified", "est"}
STOCK_STATUSES = {"unknown", "in_stock", "limited", "out_of_stock", "unverifiable"}
POSITIVE_STOCK = {"in_stock", "limited"}


class StopGateError(Exception):
    """Raised when any row violates the price-accuracy STOP gate."""


@dataclass
class DealRow:
    item: str
    asset_class: str            # sealed | raw | graded
    category: str               # display section key, e.g. "sealed-etb"
    deal_price: float
    market_comp: float | None
    retailer: str
    source_url: str
    captured_at: str            # ISO date
    price_confidence: str       # verified | est
    comp_confidence: str        # high | medium | low | none
    pct_off: float | None = None
    derivation_method: str = "" # required when price_confidence == "est"
    confidence_detail: str = ""
    capture_method: str = ""
    stale: bool = False
    badges: list[str] = field(default_factory=list)     # STEAL | WARN | EST
    warn_reason: str = ""
    lens_tags: list[str] = field(default_factory=list)  # COL | PLY | INV | FLP
    stock_status: str = "unknown"
    stock_evidence: str = ""
    buy_url: str = ""           # click-to-buy link (distinct from source_url = comp attribution)
    stock_checked_at: str = ""  # ISO datetime of the live stock check
    stock_method: str = ""      # verification method slug, e.g. "retailer_adapter:walmart"
    comp_basis: str = ""        # comp derivation basis (STEAL requires sold-derived)
    reprint_risk: bool = False
    finite: bool = False
    grade: str = ""             # graded only, e.g. "PSA 10"
    grader: str = ""            # PSA | CGC | BGS
    cert_number: str = ""
    condition: str = ""         # raw only, e.g. NM | LP
    authenticity_risk: bool = False
    scanner_verdict: str = ""   # attached when item matches a catalog SKU
    note: str = ""
    set: str = ""               # for dedup/ledger identity
    variant: str = ""           # for dedup/ledger identity


def validate_row(row: DealRow) -> list[str]:
    v: list[str] = []
    tag = row.item or "<unnamed>"
    if not isinstance(row.deal_price, (int, float)) or row.deal_price <= 0:
        v.append(f"{tag}: deal_price must be a positive number")
    if row.asset_class not in ASSET_CLASSES:
        v.append(f"{tag}: asset_class must be one of {sorted(ASSET_CLASSES)}")
    if row.price_confidence not in PRICE_CONFIDENCE:
        v.append(f"{tag}: price_confidence must be 'verified' or 'est'")
    if row.price_confidence == "verified":
        if not row.source_url:
            v.append(f"{tag}: verified row needs source_url")
        if not row.captured_at:
            v.append(f"{tag}: verified row needs captured_at")
        if "EST" in row.badges:
            v.append(f"{tag}: verified row must not carry EST badge")
    if row.price_confidence == "est":
        if not row.derivation_method:
            v.append(f"{tag}: est row needs derivation_method")
        if "EST" not in row.badges:
            v.append(f"{tag}: est row must carry EST badge")
    if row.market_comp is not None and row.pct_off is not None and row.market_comp > 0:
        expected = round((row.market_comp - row.deal_price) / row.market_comp * 100)
        if abs(expected - row.pct_off) > 1:
            v.append(f"{tag}: pct_off must be computed from market_comp (got {row.pct_off}, expected ~{expected})")
    if row.stock_status not in STOCK_STATUSES:
        v.append(f"{tag}: stock_status must be one of {sorted(STOCK_STATUSES)}")
    if row.stock_status in POSITIVE_STOCK:
        # A positive stock claim without evidence is a gate violation, same
        # class as a fabricated price: it must halt the render, not ship.
        if not row.stock_evidence:
            v.append(f"{tag}: positive stock_status needs stock_evidence")
        if not row.buy_url:
            v.append(f"{tag}: positive stock_status needs buy_url")
        if not row.stock_checked_at:
            v.append(f"{tag}: positive stock_status needs stock_checked_at")
    if row.asset_class == "graded" and (not row.grade or not row.grader):
        v.append(f"{tag}: graded row needs grade + grader")
    if row.asset_class == "raw" and not row.condition:
        v.append(f"{tag}: raw row needs condition")
    if row.authenticity_risk and "STEAL" in row.badges:
        v.append(f"{tag}: authenticity_risk row must not be a confirmed STEAL")
    return v


def assert_sweep(rows: list[DealRow]) -> None:
    violations = [msg for row in rows for msg in validate_row(row)]
    if violations:
        raise StopGateError("STOP GATE failed:\n" + "\n".join(violations))


_FIELD_NAMES = {f.name for f in fields(DealRow)}


def row_from_dict(d: dict) -> DealRow:
    """Build a DealRow from a sweep-JSON dict, ignoring unknown keys."""
    return DealRow(**{k: v for k, v in d.items() if k in _FIELD_NAMES})
