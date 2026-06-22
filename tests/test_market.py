import pytest

from scanner import resale
from scanner.market import (
    MarketFallbackClient,
    PokemonPriceTrackerClient,
    comp_from_row,
    market_client_from_config,
)


class _Cfg:
    def __init__(self, **kw):
        self.market_preferred = kw.get("market_preferred", False)
        self.market_api_key = kw.get("market_api_key", "")
        # resale_client_from_config reads these:
        self.ebay_browse_api_token = ""
        self.ebay_client_id = ""
        self.ebay_client_secret = ""
        self.ebay_marketplace_id = "EBAY_US"


class _StubClient:
    def __init__(self, row=None, exc=None):
        self.row = row
        self.exc = exc
        self.calls = 0

    def estimate(self, key, product, checked_at):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.row


def _ok_row(value):
    return resale.annotate_quote(
        {"msrp": "$49.99"},
        {
            "productKey": "k", "status": "ok", "estimate": value,
            "low": value, "high": value, "sampleSize": 12,
            "source": "PokemonPriceTracker", "basis": "sold comp median",
            "checkedAt": 0,
        },
    )


def test_comp_from_row_parses_estimate_and_confidence():
    row = _ok_row("$59.99")
    comp, conf = comp_from_row(row)
    assert comp == pytest.approx(59.99)
    assert conf in {"high", "medium", "low"}


def test_comp_from_row_handles_missing():
    comp, conf = comp_from_row({"status": "pending"})
    assert comp is None
    assert conf == "none"


def test_fallback_used_when_primary_raises():
    import requests
    primary = _StubClient(exc=requests.RequestException("429 quota"))
    fallback = _StubClient(row=_ok_row("$50.00"))
    client = MarketFallbackClient(primary, fallback)
    row = client.estimate("k", {"msrp": "$49.99"}, 0)
    assert row["status"] == "ok"
    assert fallback.calls == 1


def test_fallback_used_when_primary_not_ok():
    primary = _StubClient(row={"status": "no_matches"})
    fallback = _StubClient(row=_ok_row("$50.00"))
    client = MarketFallbackClient(primary, fallback)
    row = client.estimate("k", {"msrp": "$49.99"}, 0)
    assert row["status"] == "ok"
    assert fallback.calls == 1


def test_factory_without_preference_returns_resale_client():
    client = market_client_from_config(_Cfg(market_preferred=False))
    assert not isinstance(client, MarketFallbackClient)


def test_factory_with_preference_wraps_ppt():
    client = market_client_from_config(_Cfg(market_preferred=True, market_api_key="k"))
    assert isinstance(client, MarketFallbackClient)
    assert isinstance(client.primary, PokemonPriceTrackerClient)
