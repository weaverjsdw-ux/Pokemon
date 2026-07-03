"""Slice 6A - parser drift canaries.

Every fixture-backed parser must fail LOUD, never silent, when the upstream
markup/schema drifts. "Loud" means one of:

  * adapters / verifier -> a ``confidence.PARSER_SUSPECT`` (or SOURCE_BLOCKED /
    PAGE_UNAVAILABLE) state, never ``WORKING`` with an empty result set that
    reads as "nothing on sale today";
  * comp parsers -> a ``no_matches`` status with NO number, never a fabricated
    price (STOP-class: a wrong comp is worse than no comp).

Each parser gets two canaries:
  1. a STRUCTURAL assertion that the committed fixture still contains the tokens
     the selectors depend on (so swapping in a drifted fixture fails here), and
  2. a GUTTED-fixture assertion that the drift is reported honestly.

Coverage already living elsewhere (referenced, not duplicated):
  * slickdeals empty-page / garbage -> PARSER_SUSPECT: test_disc_slickdeals.py
  * ebay_browse missing itemSummaries key / non-dict -> PARSER_SUSPECT:
    test_disc_ebay_browse.py
  * verify_page garbage / ambiguous carousel / zero-rows -> PARSER_SUSPECT:
    test_poke_verify.py
  * golden belt mutation (missing section / dangling anchor / evidence tamper):
    test_poke_golden.py
This module adds the canaries those files do NOT cover: the slickdeals
inner-selector drift that used to go silently empty, the PriceCharting comp
parser structural drift, and the TCGplayer STUB premise.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scanner import confidence, resale
from scanner.comps.tcgplayer import TcgPlayerSource
from scanner.discovery.adapters.slickdeals import Slickdeals, parse_search_html

DISC_FIX = Path("tests/fixtures/discovery")
COMPS_FIX = Path("tests/fixtures/comps")
POPULATED = (DISC_FIX / "slickdeals_search_populated.html").read_text(encoding="utf-8")

CATALOG = {
    "prismatic_etb": {"name": "Prismatic Evolutions Elite Trainer Box",
                      "set": "Prismatic Evolutions", "type": "ETB", "msrp": "$49.99"},
}
SET_WATCH = ["Mega Evolution"]
CFG = SimpleNamespace()


def _slickdeals(text):
    adapter = Slickdeals()
    cands = adapter.discover(CFG, CATALOG, SET_WATCH,
                             http_get=lambda url, **kw: SimpleNamespace(status_code=200, text=text))
    return adapter, cands


# ----------------------------------------------------------- slickdeals drift

def test_slickdeals_fixture_still_carries_the_selectors_it_parses():
    """Structural canary: if a future fixture refresh drops these tokens the
    parser's selectors are stale and this fails before any behavior test."""
    assert 'class="dealCardListView' in POPULATED
    assert "dealCardListView__title" in POPULATED
    assert "dealCardListView__finalPrice" in POPULATED
    # baseline: the real fixture parses to its known live cards
    cands, stats = parse_search_html(POPULATED, CATALOG, SET_WATCH, "2026-07-03T00:00:00")
    assert len(cands) == 2 and stats.cards_found == 8
    assert stats.non_expired == 2 and stats.titled == 2


def test_slickdeals_gutted_title_selector_is_parser_suspect_not_silent_empty():
    """THE drift gap this slice closes: cards are still present (container class
    intact) but the title selector drifted, so every card fails extraction. The
    old behavior was WORKING with zero candidates - a silent empty success that
    reads as 'no Pokemon deals right now'. It must be PARSER_SUSPECT instead."""
    gutted = POPULATED.replace("dealCardListView__title", "dealCardListView__headline")
    adapter, cands = _slickdeals(gutted)
    assert cands == []
    assert adapter.state == confidence.PARSER_SUSPECT
    assert adapter.state_detail                       # reason recorded, never silent


_EXPIRED_ONLY = (
    '<div class="dealCardListView dealCardListView--expired" data-threadid="111"></div>'
    '<div class="dealCardListView dealCardListView--expired" data-threadid="222"></div>'
)


def test_slickdeals_all_expired_page_does_not_false_trip_suspect():
    """A page whose cards are all expired is a legitimately empty result, not
    drift: with zero non-expired cards the title canary must NOT fire, so the
    source stays honest (WORKING/empty), not falsely flagged."""
    cands, stats = parse_search_html(_EXPIRED_ONLY, CATALOG, SET_WATCH, "2026-07-03T00:00:00")
    assert stats.cards_found == 2 and stats.non_expired == 0 and stats.titled == 0
    adapter, live = _slickdeals(_EXPIRED_ONLY)
    assert live == []
    assert adapter.state == confidence.WORKING     # empty-by-expiry is not drift


# ----------------------------------------------------- PriceCharting comp drift

# The active (legacy engine) comp parser. A per-product lookup legitimately
# returns "no match" for a product it does not carry, so the truthful drift
# signal here is NOT PARSER_SUSPECT but "no_matches with no fabricated price".
_PC_PRODUCT = {
    "name": "Prismatic Evolutions Elite Trainer Box",
    "msrp": "$49.99",
    "resale_query": "Pokemon TCG Prismatic Evolutions Elite Trainer Box sealed",
}
_PC_GOOD = """
  <tr id="product-8256647" data-product="8256647">
    <td class="title">
      <a href="https://www.pricecharting.com/game/pokemon-prismatic-evolutions/elite-trainer-box">Elite Trainer Box</a>
    </td>
    <td class="console phone-landscape-hidden">Pokemon Prismatic Evolutions</td>
    <td class="price numeric used_price"><span class="js-price">$150.00</span></td>
  </tr>
"""


def test_pricecharting_good_html_parses_a_price():
    quote = resale.pricecharting_quote_from_html("prismatic_etb", _PC_PRODUCT, _PC_GOOD, 456)
    assert quote["status"] == "ok" and quote["estimate"] == "$150.00"


def test_pricecharting_gutted_row_id_yields_no_matches_never_a_fabricated_price():
    """Structural drift: the product row anchor (<tr id="product-...">) changed.
    The parser must return no_matches with an empty estimate, never invent a
    number from whatever digits remain in the markup."""
    gutted = _PC_GOOD.replace('id="product-8256647"', 'id="listing-8256647"')
    quote = resale.pricecharting_quote_from_html("prismatic_etb", _PC_PRODUCT, gutted, 456)
    assert quote["status"] == "no_matches"
    assert quote["estimate"] == "" and not quote.get("low") and not quote.get("high")


def test_pricecharting_gutted_price_selector_yields_no_matches_not_a_guess():
    """The price cell selector (used_price / js-price) drifted. A visible '$150'
    still sits in the row, but without the anchored selector the parser must
    refuse to read it rather than grab a stray number."""
    gutted = _PC_GOOD.replace("js-price", "sale-price").replace("used_price", "list_price")
    quote = resale.pricecharting_quote_from_html("prismatic_etb", _PC_PRODUCT, gutted, 456)
    assert quote["status"] == "no_matches"
    assert quote["estimate"] == ""


# --------------------------------------------------------- TCGplayer STUB premise

def test_tcgplayer_fixtures_are_still_priceless_js_shells():
    """The TCGplayer source is a declared STUB because the product page served a
    JS shell with no parseable price to plain requests (Task-1 probe). This
    canary guards that premise: if a committed fixture ever carries a real price
    token, the shell assumption changed and the STUB should be revisited."""
    fixtures = sorted(COMPS_FIX.glob("tcgplayer_product_*.html"))
    assert fixtures, "TCGplayer probe fixtures must remain committed as evidence"
    for fx in fixtures:
        body = fx.read_text(encoding="utf-8", errors="ignore")
        assert '"marketPrice"' not in body
        assert '"price":' not in body


def test_tcgplayer_source_stays_blocked_on_its_fixtures_never_a_price():
    """Feeding the STUB a 200 response with any fixture body must still yield a
    blocked quote with no price - it never parses a number out of the shell."""
    product = {"name": "Prismatic Evolutions ETB", "set": "Prismatic Evolutions",
               "ppt_id": "593355"}
    for fx in sorted(COMPS_FIX.glob("tcgplayer_product_*.html")):
        body = fx.read_text(encoding="utf-8", errors="ignore")
        session = SimpleNamespace(
            get=lambda url, **kw: SimpleNamespace(status_code=200, text=body))
        quote = TcgPlayerSource(SimpleNamespace(), session=session).fetch(
            "prismatic_etb", product, 456)
        assert quote.status == "blocked"
        assert quote.price is None
