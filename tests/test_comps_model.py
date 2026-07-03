"""Confidence resolution matrix - spec 4.3, exhaustive per tier + edges."""
from scanner.comps import model


def q(source, price, kind=model.SOLD_DERIVED, status="ok", url="", sample_size=None):
    return model.CompSourceQuote(
        source=source, kind=kind, status=status, price=price,
        url=url or f"https://example.com/{source}", fetched_at="2026-07-03T10:00:00",
        sample_size=sample_size,
    )


def ask(median, floor, count):
    return model.EbayAsk(
        quote=q("ebay_api", median, kind=model.ACTIVE_ASK, sample_size=count),
        floor=floor, count=count,
    )


def resolve(msrp=50.0, tcg=None, pc=None, ebay=None, tol=20.0, floor_pct=50.0):
    return model.resolve("set|item|||", msrp, tcg, pc, ebay, "2026-07-03",
                         tolerance_pct=tol, floor_sanity_pct=floor_pct)


def test_high_both_agree_floor_sane():
    n = resolve(tcg=q("tcgplayer", 100.0), pc=q("pricecharting", 110.0), ebay=ask(105.0, 95.0, 12))
    assert n.confidence == "high"
    assert n.comp == 100.0          # min() of the agreeing pair - conservative
    assert n.spread_pct is not None and 9.9 < n.spread_pct < 10.1
    assert n.ebay_floor == 95.0 and n.ebay_active_count == 12


def test_high_both_agree_no_ebay():
    n = resolve(tcg=q("tcgplayer", 100.0), pc=q("pricecharting", 110.0))
    assert n.confidence == "high" and n.comp == 100.0
    assert n.ebay_floor is None and n.ebay_active_count is None


def test_medium_floor_insane():
    n = resolve(tcg=q("tcgplayer", 100.0), pc=q("pricecharting", 110.0), ebay=ask(60.0, 40.0, 8))
    assert n.confidence == "medium"
    assert "floor_below_comp" in n.confidence_reason


def test_medium_source_spread():
    n = resolve(tcg=q("tcgplayer", 100.0), pc=q("pricecharting", 150.0))
    assert n.confidence == "medium" and n.comp == 100.0
    assert "source_spread" in n.confidence_reason


def test_premium_caps_agreeing_pair_to_low():
    n = resolve(msrp=20.0, tcg=q("tcgplayer", 100.0), pc=q("pricecharting", 105.0))
    assert n.confidence == "low" and "high_premium" in n.confidence_reason
    assert n.comp == 100.0          # capped, not suppressed (Phase-0 closure)


def test_medium_single_sold_corroborated_by_ask():
    n = resolve(tcg=q("tcgplayer", 100.0), ebay=ask(108.0, 90.0, 5))
    assert n.confidence == "medium" and n.comp == 100.0
    assert "active_ask" not in n.comp_basis   # comp is sold-derived; STEAL stays eligible


def test_medium_pc_side_corroboration():
    n = resolve(pc=q("pricecharting", 100.0), ebay=ask(95.0, 80.0, 4))
    assert n.confidence == "medium" and n.comp == 100.0


def test_low_single_sold_uncorroborated():
    n = resolve(pc=q("pricecharting", 100.0))
    assert n.confidence == "low" and n.comp == 100.0


def test_low_single_sold_ask_diverges():
    n = resolve(tcg=q("tcgplayer", 100.0), ebay=ask(200.0, 150.0, 9))
    assert n.confidence == "low"


def test_low_ask_only_with_sample():
    n = resolve(ebay=ask(80.0, 70.0, 6))
    assert n.confidence == "low" and n.comp == 80.0
    assert "active_ask" in n.comp_basis      # ask-derived comp is marked - blocks STEAL later


def test_unknown_ask_only_thin_sample():
    n = resolve(ebay=ask(80.0, 70.0, 2))
    assert n.confidence == "unknown" and n.comp is None


def test_unknown_nothing_ok():
    n = resolve(tcg=q("tcgplayer", None, status="blocked"), pc=q("pricecharting", None, status="no_match"))
    assert n.confidence == "unknown" and n.comp is None
    assert n.comp_basis == "none"
    assert len(n.sources) == 2               # failures are still recorded as evidence


def test_premium_caps_single_source():
    n = resolve(msrp=20.0, pc=q("pricecharting", 90.0))
    assert n.confidence == "low" and "high_premium" in n.confidence_reason


from scanner import market as market_mod


def test_legacy_row_ok_high_verified_eligible():
    tcg = q("tcgplayer", 180.65, url="https://www.tcgplayer.com/product/624676")
    pc = q("pricecharting", 190.0, url="https://www.pricecharting.com/game/pokemon-destined-rivals/elite-trainer-box")
    n = resolve(msrp=49.99, tcg=tcg, pc=pc)
    row = model.to_legacy_row(n, "destined_rivals_etb", {"name": "Destined Rivals ETB", "msrp": "$49.99"}, 1780500000)
    assert row["status"] == "ok"
    assert row["estimate"] == "$180.65"           # money STRING - comp_from_row parses it
    assert market_mod.comp_from_row(row) == (180.65, "high")
    assert row["sourceUrl"] == "https://www.tcgplayer.com/product/624676"  # exact page -> verified-eligible
    assert row["basis"] == n.comp_basis
    assert row["checkedAt"] == 1780500000


def test_legacy_row_low_has_no_sourceurl():
    n = resolve(pc=q("pricecharting", 100.0, url="https://www.pricecharting.com/game/x/y"))
    row = model.to_legacy_row(n, "k", {"name": "X", "msrp": "$50"}, 1)
    assert row["confidence"] == "low"
    assert "sourceUrl" not in row                 # low never earns the verified path


def test_legacy_row_medium_pc_exact_url_promotes():
    pc = q("pricecharting", 100.0, url="https://www.pricecharting.com/game/pokemon-x/etb")
    n = resolve(pc=pc, ebay=ask(102.0, 90.0, 5))
    row = model.to_legacy_row(n, "k", {"name": "X", "msrp": "$50"}, 1)
    assert row["confidence"] == "medium"
    assert row["sourceUrl"] == pc.url             # PC product page counts as exact


def test_legacy_row_unknown_is_no_match_with_no_number():
    n = resolve()
    row = model.to_legacy_row(n, "k", {"name": "X"}, 1)
    assert row["status"] == "no_matches"
    assert row["estimate"] == "" and row["confidence"] == "none"
    assert market_mod.comp_from_row(row) == (None, "none")


def test_legacy_row_carries_annotate_quote_keys():
    n = resolve(tcg=q("tcgplayer", 100.0), pc=q("pricecharting", 105.0))
    row = model.to_legacy_row(n, "k", {"name": "X", "msrp": "$50"}, 1)
    for key in ("productKey", "status", "source", "basis", "query", "estimate", "low",
                "high", "sampleSize", "checkedAt", "url", "detail", "confidence",
                "confidenceLabel", "confidenceReason", "premiumRatio", "flags",
                "needsVerification", "asterisk", "compBasis", "ebayFloor",
                "ebayActiveCount", "sources"):
        assert key in row, key
