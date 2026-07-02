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


class _FakeResponse:
    def __init__(self, payload, headers=None):
        self._payload = payload
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload, headers=None):
        self._payload = payload
        self._headers = headers
        self.last = None

    def get(self, url, params=None, headers=None, timeout=None):
        self.last = {"url": url, "params": params, "headers": headers}
        return _FakeResponse(self._payload, self._headers)


def test_v2_sealed_by_id_parses_unopened_price_as_medium():
    # querying by tcgPlayerId returns a single product object
    payload = {
        "data": {"tcgPlayerId": "593355", "name": "Prismatic Evolutions Elite Trainer Box",
                 "setName": "SV: Prismatic Evolutions", "unopenedPrice": 199.14},
        "metadata": {"total": 1, "count": 1},
    }
    session = _FakeSession(payload)
    client = PokemonPriceTrackerClient(api_key="k", session=session)
    row = client.estimate(
        "prismatic_evolutions_etb",
        {"msrp": "$49.99", "ppt_id": "593355", "resale_query": "Prismatic Evolutions ETB sealed"},
        0,
    )
    assert row["status"] == "ok"
    comp, conf = comp_from_row(row)
    assert comp == pytest.approx(199.14)
    assert conf == "medium"  # TCGplayer market price = single-source market summary
    # exact id lookup against the v2 sealed endpoint (no risky name search)
    assert session.last["url"].endswith("/api/v2/sealed-products")
    assert session.last["params"]["tcgPlayerId"] == "593355"
    assert "search" not in session.last["params"]
    assert session.last["params"]["limit"] == 1  # bills 1 credit, not the default 50
    assert session.last["headers"]["Authorization"] == "Bearer k"


def test_v2_no_ppt_id_skips_api_and_returns_no_match():
    session = _FakeSession({"data": [], "metadata": {}})
    client = PokemonPriceTrackerClient(api_key="k", session=session)
    row = client.estimate("x", {"resale_query": "Prismatic Evolutions ETB sealed"}, 0)
    assert row["status"] == "no_matches"
    assert comp_from_row(row) == (None, "none")
    assert session.last is None  # never hit the API (0 credits) without an id


def test_v2_id_with_empty_data_returns_no_matches():
    client = PokemonPriceTrackerClient(api_key="k", session=_FakeSession({"data": None, "metadata": {"total": 0}}))
    row = client.estimate("x", {"ppt_id": "999"}, 0)
    assert row["status"] == "no_matches"
    assert comp_from_row(row) == (None, "none")


def test_v2_ok_row_carries_source_url_and_credit_telemetry():
    payload = {
        "data": {"tcgPlayerId": "593355", "name": "Prismatic Evolutions Elite Trainer Box",
                 "tcgPlayerUrl": "https://www.tcgplayer.com/product/593355",
                 "unopenedPrice": 199.14},
        "metadata": {"apiCallsConsumed": {"total": 1}},
    }
    session = _FakeSession(payload, headers={"X-API-Calls-Consumed": "1",
                                             "X-RateLimit-Daily-Remaining": "87"})
    client = PokemonPriceTrackerClient(api_key="k", session=session)
    row = client.estimate("prismatic_evolutions_etb", {"msrp": "$49.99", "ppt_id": "593355"}, 0)
    assert row["status"] == "ok"
    assert row["sourceUrl"] == "https://www.tcgplayer.com/product/593355"
    assert row["url"] == "https://www.tcgplayer.com/product/593355"
    assert row["creditsConsumed"] == 1
    assert row["dailyRemaining"] == 87


def test_v2_credits_fall_back_to_metadata_then_one():
    # no headers at all -> metadata total; no metadata either -> default 1 (a call happened)
    payload = {"data": {"tcgPlayerId": "1", "unopenedPrice": 10.0},
               "metadata": {"apiCallsConsumed": {"total": 3}}}
    client = PokemonPriceTrackerClient(api_key="k", session=_FakeSession(payload))
    row = client.estimate("x", {"ppt_id": "1"}, 0)
    assert row["creditsConsumed"] == 3
    assert row["dailyRemaining"] is None

    bare = {"data": {"tcgPlayerId": "1", "unopenedPrice": 10.0}}
    row = PokemonPriceTrackerClient(api_key="k", session=_FakeSession(bare)).estimate(
        "x", {"ppt_id": "1"}, 0)
    assert row["creditsConsumed"] == 1


def test_v2_no_match_after_http_still_bills_credit():
    session = _FakeSession({"data": None, "metadata": {}},
                           headers={"X-API-Calls-Consumed": "1",
                                    "X-RateLimit-Daily-Remaining": "42"})
    row = PokemonPriceTrackerClient(api_key="k", session=session).estimate(
        "x", {"ppt_id": "999"}, 0)
    assert row["status"] == "no_matches"
    assert row["creditsConsumed"] == 1
    assert row["dailyRemaining"] == 42


def test_fallback_row_carries_primary_telemetry():
    primary = _StubClient(row={"status": "no_matches", "creditsConsumed": 1,
                               "dailyRemaining": 42})
    fallback = _StubClient(row=_ok_row("$50.00"))
    client = MarketFallbackClient(primary, fallback)
    row = client.estimate("k", {"msrp": "$49.99"}, 0)
    assert row["status"] == "ok"
    assert row["creditsConsumed"] == 1
    assert row["dailyRemaining"] == 42


def test_fallback_row_untouched_when_primary_never_called_http():
    primary = _StubClient(row={"status": "no_matches"})  # e.g. no ppt_id, 0 credits
    fallback = _StubClient(row=_ok_row("$50.00"))
    row = MarketFallbackClient(primary, fallback).estimate("k", {"msrp": "$49.99"}, 0)
    assert "creditsConsumed" not in row
