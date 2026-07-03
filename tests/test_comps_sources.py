"""Source normalization tests: every source returns a CompSourceQuote and never raises."""
import requests

from scanner.comps import model
from scanner.comps.pricecharting import PriceChartingSource

PRODUCT = {"name": "Destined Rivals Elite Trainer Box", "set": "Destined Rivals",
           "type": "ETB", "msrp": "$49.99",
           "resale_query": "Pokemon TCG Destined Rivals Elite Trainer Box sealed"}


class FakePcClient:
    def __init__(self, row=None, exc=None):
        self.row, self.exc = row, exc
    def estimate(self, key, product, checked_at):
        if self.exc: raise self.exc
        return self.row


def test_pc_ok_row_maps_to_quote():
    row = {"status": "ok", "estimate": "$190.00",
           "url": "https://www.pricecharting.com/game/pokemon-destined-rivals/elite-trainer-box",
           "detail": "PriceCharting ungraded market summary"}
    quote = PriceChartingSource(cfg=None, client=FakePcClient(row)).fetch("k", PRODUCT, 1780500000)
    assert quote.status == "ok" and quote.price == 190.0
    assert quote.source == "pricecharting" and quote.kind == model.SOLD_DERIVED
    assert quote.url.startswith("https://www.pricecharting.com/game/")
    assert quote.raw_excerpt


def test_pc_no_match():
    row = {"status": "no_matches", "url": "https://www.pricecharting.com/search-products?q=x",
           "detail": "No usable PriceCharting result matched this product."}
    quote = PriceChartingSource(cfg=None, client=FakePcClient(row)).fetch("k", PRODUCT, 1)
    assert quote.status == "no_match" and quote.price is None


def test_pc_http_403_is_blocked():
    quote = PriceChartingSource(cfg=None, client=FakePcClient(
        exc=requests.HTTPError("403 Client Error: Forbidden"))).fetch("k", PRODUCT, 1)
    assert quote.status == "blocked" and quote.price is None


def test_pc_transport_error():
    quote = PriceChartingSource(cfg=None, client=FakePcClient(
        exc=requests.ConnectionError("boom"))).fetch("k", PRODUCT, 1)
    assert quote.status == "error" and quote.price is None


from scanner.comps.ebay import EbayAskSource


class _NoAuthCfg:
    ebay_browse_api_token = ""
    ebay_client_id = ""
    ebay_client_secret = ""
    ebay_marketplace_id = "EBAY_US"


class FakeEbayClient:
    def __init__(self, payload=None, exc=None):
        self.payload, self.exc = payload, exc
    def search_payload(self, product):
        if self.exc: raise self.exc
        return self.payload


def test_ebay_not_configured_degrades_cleanly(monkeypatch):
    # Operator is still waiting on eBay developer-program acceptance: this IS the
    # production path today. Env creds must not leak in.
    for var in ("EBAY_BROWSE_API_TOKEN", "EBAY_OAUTH_TOKEN", "EBAY_CLIENT_ID",
                "EBAY_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    ask = EbayAskSource(cfg=_NoAuthCfg()).fetch("k", PRODUCT, 1)
    assert ask.quote.status == "not_configured"
    assert ask.floor is None and ask.count is None
    assert "ebay-keyset-setup" in ask.quote.detail


def test_ebay_ok_median_floor_count():
    payload = {"itemSummaries": [
        {"title": "Pokemon TCG Destined Rivals Elite Trainer Box sealed",
         "price": {"value": "170.00", "currency": "USD"}},
        {"title": "Pokemon TCG Destined Rivals Elite Trainer Box sealed",
         "price": {"value": "180.00", "currency": "USD"}},
        {"title": "Pokemon TCG Destined Rivals Elite Trainer Box sealed",
         "price": {"value": "200.00", "currency": "USD"}},
    ]}
    ask = EbayAskSource(cfg=None, client=FakeEbayClient(payload)).fetch("k", PRODUCT, 1)
    assert ask.quote.status == "ok" and ask.quote.price == 180.0   # median
    assert ask.floor == 170.0 and ask.count == 3
    assert ask.quote.sample_size == 3 and ask.quote.kind == model.ACTIVE_ASK


def test_ebay_no_matches():
    ask = EbayAskSource(cfg=None, client=FakeEbayClient({"itemSummaries": []})).fetch("k", PRODUCT, 1)
    assert ask.quote.status == "no_match" and ask.floor is None


def test_ebay_transport_error():
    ask = EbayAskSource(cfg=None, client=FakeEbayClient(
        exc=requests.ConnectionError("down"))).fetch("k", PRODUCT, 1)
    assert ask.quote.status == "error"
