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
