"""Resale price estimation helpers without live network calls."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from scanner import resale


def _item(title: str, price: str, shipping: str = "0.00") -> dict:
    return {
        "title": title,
        "price": {"value": price, "currency": "USD"},
        "shippingOptions": [
            {"shippingCost": {"value": shipping, "currency": "USD"}},
        ],
    }


def test_quote_from_search_payload_uses_filtered_median_with_shipping():
    product = {
        "name": "Prismatic Evolutions Booster Bundle",
        "msrp": "$26.94",
        "resale_query": "Pokemon TCG Prismatic Evolutions Booster Bundle sealed",
    }
    payload = {
        "itemSummaries": [
            _item("Pokemon TCG Prismatic Evolutions Booster Bundle Sealed", "70.00", "5.00"),
            _item("Pokemon TCG Prismatic Evolutions Booster Bundle Sealed", "80.00"),
            _item("Pokemon TCG Prismatic Evolutions Booster Bundle Sealed", "90.00"),
            _item("Pokemon Center Prismatic Evolutions Booster Bundle Sealed", "140.00"),
            _item("Pokemon TCG Prismatic Evolutions Booster Bundle Empty Box", "10.00"),
        ]
    }

    quote = resale.quote_from_search_payload("booster", product, payload, checked_at=123)

    assert quote["status"] == "ok"
    assert quote["estimate"] == "$80.00"
    assert quote["low"] == "$77.50"
    assert quote["high"] == "$85.00"
    assert quote["sampleSize"] == 3
    assert quote["checkedAt"] == 123
    assert quote["confidence"] == "medium"
    assert quote["premiumRatio"] == 2.97
    assert quote["asterisk"] is False
    assert quote["flags"] == ["asking_price"]


def test_quote_from_search_payload_reports_no_matches():
    product = {
        "name": "Surging Sparks Elite Trainer Box",
        "resale_query": "Pokemon TCG Surging Sparks Elite Trainer Box sealed",
    }

    quote = resale.quote_from_search_payload(
        "surging_sparks_etb",
        product,
        {"itemSummaries": [_item("Surging Sparks sleeves only", "15.00")]},
        checked_at=123,
    )

    assert quote["status"] == "no_matches"
    assert quote["estimate"] == ""
    assert quote["sampleSize"] == 0
    assert quote["confidence"] == "none"


def test_public_search_quotes_from_html_uses_listing_cards():
    product = {
        "name": "Prismatic Evolutions Booster Bundle",
        "resale_query": "Pokemon TCG Prismatic Evolutions Booster Bundle sealed",
    }
    body = """
      <li class="s-item">
        <div class="s-item__title"><span>Pokemon TCG Prismatic Evolutions Booster Bundle Sealed</span></div>
        <span class="s-item__price">$72.00</span>
        <span class="s-item__shipping">+$5.00 shipping</span>
      </li>
      <li class="s-item">
        <div class="s-item__title"><span>Pokemon TCG Prismatic Evolutions Booster Bundle Sealed</span></div>
        <span class="s-item__price">$82.00</span>
        <span class="s-item__shipping">Free shipping</span>
      </li>
      <li class="s-item">
        <div class="s-item__title"><span>Pokemon TCG Prismatic Evolutions Booster Bundle Empty Box</span></div>
        <span class="s-item__price">$9.00</span>
      </li>
    """

    quote = resale.public_search_quotes_from_html("booster", product, body, checked_at=123)

    assert quote["status"] == "ok"
    assert quote["source"] == "eBay public search"
    assert quote["estimate"] == "$79.50"
    assert quote["sampleSize"] == 2
    assert quote["confidence"] == "low"
    assert quote["asterisk"] is True
    assert "public_ebay_search" in quote["flags"]


def test_pricecharting_quote_from_html_uses_first_matching_market_price():
    product = {
        "name": "Prismatic Evolutions Elite Trainer Box",
        "msrp": "$49.99",
        "resale_query": "Pokemon TCG Prismatic Evolutions Elite Trainer Box sealed",
    }
    body = """
      <tr id="product-8256647" data-product="8256647">
        <td class="title">
          <a href="https://www.pricecharting.com/game/pokemon-prismatic-evolutions/elite-trainer-box">Elite Trainer Box</a>
        </td>
        <td class="console phone-landscape-hidden">Pokemon Prismatic Evolutions</td>
        <td class="price numeric used_price"><span class="js-price">$150.00</span></td>
      </tr>
      <tr id="product-999">
        <td class="title"><a href="/game/other">Elite Trainer Box Pokemon Center</a></td>
        <td class="console phone-landscape-hidden">Pokemon Prismatic Evolutions</td>
        <td class="price numeric used_price"><span class="js-price">$250.00</span></td>
      </tr>
    """

    quote = resale.pricecharting_quote_from_html("etb", product, body, checked_at=456)

    assert quote["status"] == "ok"
    assert quote["source"] == "PriceCharting market fallback"
    assert quote["estimate"] == "$150.00"
    assert quote["low"] == "$150.00"
    assert quote["sampleSize"] == 1
    assert quote["confidence"] == "medium"
    assert quote["premiumRatio"] == 3.0
    assert quote["asterisk"] is False
    assert quote["flags"] == ["single_source_summary"]


def test_pricecharting_high_premium_gets_low_confidence_asterisk():
    product = {
        "name": "Scarlet & Violet 151 Elite Trainer Box",
        "msrp": "$49.99",
        "resale_query": "Pokemon TCG Scarlet Violet 151 Elite Trainer Box sealed",
    }
    body = """
      <tr id="product-123" data-product="123">
        <td class="title">
          <a href="/game/pokemon-scarlet-&amp;-violet-151/elite-trainer-box">Elite Trainer Box</a>
        </td>
        <td class="console phone-landscape-hidden">Pokemon Scarlet &amp; Violet 151</td>
        <td class="price numeric used_price"><span class="js-price">$610.00</span></td>
      </tr>
    """

    quote = resale.pricecharting_quote_from_html("sv151_etb", product, body, checked_at=456)

    assert quote["status"] == "ok"
    assert quote["estimate"] == "$610.00"
    assert quote["confidence"] == "low"
    assert quote["premiumRatio"] == 12.2
    assert quote["asterisk"] is True
    assert "high_premium" in quote["flags"]
    assert "single_source_summary" in quote["flags"]


def test_pricecharting_quote_from_html_unescapes_href_entities():
    product = {
        "name": "Prismatic Evolutions Elite Trainer Box",
        "msrp": "$49.99",
        "resale_query": "Pokemon TCG Prismatic Evolutions Elite Trainer Box sealed",
    }
    body = """
      <tr id="product-8256647" data-product="8256647">
        <td class="title">
          <a href="/game/x?utm=a&amp;ref=b">Elite Trainer Box</a>
        </td>
        <td class="console phone-landscape-hidden">Pokemon Prismatic Evolutions</td>
        <td class="price numeric used_price"><span class="js-price">$150.00</span></td>
      </tr>
    """

    quote = resale.pricecharting_quote_from_html("etb", product, body, checked_at=456)

    assert quote["status"] == "ok"
    assert "&" in quote["url"]
    assert "&amp;" not in quote["url"]


def test_pricecharting_rejects_false_magic_marvel_non_tcg_match():
    product = {
        "name": "Magic: The Gathering Marvel Super Heroes Bundle",
        "game": "Magic: The Gathering",
        "set": "Marvel Super Heroes",
        "type": "Bundle",
        "msrp": "$69.99",
        "resale_query": "Magic The Gathering Marvel Super Heroes Bundle sealed",
    }
    body = """
      <tr id="product-123" data-product="123">
        <td class="title">
          <a href="/game/pal-xbox-360/lego-marvel-super-heroes-figure-bundle">LEGO Marvel Super Heroes Figure Bundle</a>
        </td>
        <td class="console phone-landscape-hidden">PAL Xbox 360</td>
        <td class="price numeric used_price"><span class="js-price">$24.32</span></td>
      </tr>
    """

    quote = resale.pricecharting_quote_from_html("mtg_marvel_bundle", product, body, checked_at=456)

    assert quote["status"] == "no_matches"
    assert quote["estimate"] == ""
    assert quote["sampleSize"] == 0


def test_public_fallback_returns_not_released_instead_of_error_after_no_matches():
    class NoMatchClient:
        def estimate(self, product_key, product, checked_at):
            return {"status": "no_matches", "detail": "No source match."}

    product = {
        "name": "Magic: The Gathering Marvel Super Heroes Bundle",
        "game": "Magic: The Gathering",
        "set": "Marvel Super Heroes",
        "type": "Bundle",
        "release_date": "2026-06-26",
        "msrp": "$69.99",
        "resale_query": "Magic The Gathering Marvel Super Heroes Bundle sealed",
    }
    checked_at = int(datetime(2026, 6, 3, 12, 0, 0).timestamp())

    quote = resale.PublicFallbackResaleClient(clients=[NoMatchClient()]).estimate(
        "mtg_marvel_bundle",
        product,
        checked_at,
    )

    assert quote["status"] == "not_released"
    assert quote["estimate"] == ""
    assert "2026-06-26" in quote["detail"]
    assert quote["confidence"] == "none"


def test_resale_cache_snapshot_uses_public_search_without_auth(monkeypatch):
    for name in (
        "EBAY_BROWSE_API_TOKEN",
        "EBAY_OAUTH_TOKEN",
        "EBAY_CLIENT_ID",
        "EBAY_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    cfg = SimpleNamespace(
        resale_price_enabled=True,
        resale_price_interval_seconds=14400,
        ebay_browse_api_token="",
        ebay_client_id="",
        ebay_client_secret="",
        ebay_marketplace_id="EBAY_US",
        products={"booster": {"name": "Booster", "set": "Test", "type": "Booster Bundle"}},
    )

    snapshot = resale.ResalePriceCache(clock=lambda: 100).snapshot(cfg)

    assert snapshot["authSet"] is False
    assert snapshot["source"] == "eBay public search / PriceCharting fallback"
    assert snapshot["intervalSeconds"] == 14400
    assert snapshot["confidenceCounts"] == {"high": 0, "medium": 0, "low": 0, "none": 1}
    assert snapshot["products"]["booster"]["status"] == "pending"
    assert snapshot["products"]["booster"]["confidence"] == "none"
