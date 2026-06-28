from scanner import config as cfg_mod
from scanner.discovery.schema import DealRow
from scanner.discovery.score import (
    assign_badges, compute_pct_off, dedup, fake_markdown_flags,
    flipper_is_buy, lens_tags, split_min_discount,
)

CFG = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})


def _row(**kw):
    base = dict(item="ETB", asset_class="sealed", category="sealed-etb",
                deal_price=39.99, market_comp=60.0, retailer="Target",
                source_url="u", captured_at="2026-06-27",
                price_confidence="verified", comp_confidence="high")
    base.update(kw)
    return DealRow(**base)


def test_pct_off_basis_is_market_comp():
    assert compute_pct_off(39.99, 60.0) == 33  # round((60-39.99)/60*100)
    assert compute_pct_off(39.99, None) is None


def test_inflated_original_when_claimed_exceeds_comp_30pct():
    flags = fake_markdown_flags(40, market_comp=60, claimed_was=90, has_legit_explanation=False)
    assert "INFLATED_ORIGINAL" in flags  # claimed 90 > comp 60 by 50% (>30)


def test_suspiciously_low_without_explanation():
    flags = fake_markdown_flags(30, market_comp=60, claimed_was=None, has_legit_explanation=False)
    assert "SUSPICIOUSLY_LOW" in flags  # 30 < 70% of 60 (=42), no explanation


def test_suspiciously_low_suppressed_with_explanation():
    flags = fake_markdown_flags(30, market_comp=60, claimed_was=None, has_legit_explanation=True)
    assert "SUSPICIOUSLY_LOW" not in flags


def test_misleading_pct_when_price_within_normal_range():
    # big claimed discount but sale price ~ comp -> misleading
    flags = fake_markdown_flags(58, market_comp=60, claimed_was=120, has_legit_explanation=False)
    assert "MISLEADING_PCT" in flags


def test_flipper_buy_matches_backbone():
    # deal 40, comp 100 -> healthy net margin -> BUY
    assert flipper_is_buy(40.0, 100.0, CFG) is True
    # deal 58, comp 60 -> thin -> not BUY
    assert flipper_is_buy(58.0, 60.0, CFG) is False


def test_steal_requires_verified_and_threshold():
    steal = assign_badges(_row(deal_price=39.99, market_comp=60.0, pct_off=33), CFG)
    assert "STEAL" in steal                       # verified, 33% >= steal_pct 30
    thin = assign_badges(_row(deal_price=57.0, market_comp=60.0, pct_off=5), CFG)
    assert "STEAL" not in thin


def test_est_row_gets_est_badge_never_steal():
    badges = assign_badges(_row(price_confidence="est", comp_confidence="low",
                                derivation_method="comp_inference",
                                deal_price=39.99, market_comp=60.0, pct_off=33), CFG)
    assert "EST" in badges and "STEAL" not in badges


def test_flp_tag_is_deterministic_and_backbone_aligned():
    tags = lens_tags(_row(deal_price=40.0, market_comp=100.0, pct_off=60), CFG)
    assert "FLP" in tags
    tags2 = lens_tags(_row(deal_price=58.0, market_comp=60.0, pct_off=3), CFG)
    assert "FLP" not in tags2


def test_flp_omitted_on_est_comp():
    # price-accuracy rule: never tag a lens off an EST comp, even if margin clears
    tags = lens_tags(_row(price_confidence="est", comp_confidence="low",
                          derivation_method="comp_inference",
                          deal_price=40.0, market_comp=100.0, pct_off=60), CFG)
    assert "FLP" not in tags


def test_dedup_keeps_lowest_price_per_identity():
    a = _row(deal_price=45.0, set="Prismatic", variant="", retailer="A")
    b = _row(deal_price=39.99, set="Prismatic", variant="", retailer="B")
    out = dedup([a, b])
    assert len(out) == 1 and out[0].deal_price == 39.99


def test_split_min_discount_drops_thin_rows():
    deal = _row(deal_price=39.99, market_comp=60.0, pct_off=33)
    thin = _row(deal_price=59.0, market_comp=60.0, pct_off=2)
    deals, below = split_min_discount([deal, thin], CFG)
    assert deal in deals and thin in below
