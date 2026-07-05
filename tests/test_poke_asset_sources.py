"""Track D1 — raw/graded source adapters + the dormant PPT /cards client.

No live network: the PPT client is exercised with a fake session that captures
params. Proves honest none when unmapped/unconfigured (#4), degrade-not-crash on
401/429 (#7), limit=1 on both card calls (#8), and that ask-only data can never
mint high confidence and a graded ask can never become the comp (#2, #9)."""
from __future__ import annotations

import requests

from scanner.comps.model import ACTIVE_ASK, SOLD_DERIVED, CompSourceQuote, EbayAsk
from scanner.poke_api import sources
from scanner.market import comp_from_row


CHECKED = 1_751_673_600   # 2026-07-05T00:00:00 (UTC-ish; exact tz irrelevant to tests)

RAW = {"asset_key": "umbreon_raw_nm", "asset_class": "raw", "name": "Umbreon ex",
       "set": "Prismatic Evolutions", "card_number": "161", "condition": "NM",
       "tcgplayer_id": "999001"}
GRADED = {"asset_key": "umbreon_psa10", "asset_class": "graded", "name": "Umbreon ex",
          "set": "Prismatic Evolutions", "card_number": "161", "grader": "PSA",
          "grade": "10", "grade_key": "psa10", "tcgplayer_id": "999001"}


# ---- fakes -------------------------------------------------------------------

def _sold(source, price, url="https://tcg/x", status="ok"):
    return CompSourceQuote(source, SOLD_DERIVED, status, price, url, "2026-07-05T00:00:00")


def _ask(price, count=5, status="ok"):
    q = CompSourceQuote("ebay_api", ACTIVE_ASK, status, price, "https://ebay/x",
                        "2026-07-05T00:00:00")
    return EbayAsk(q, floor=price, count=count)


class _FixedSource:
    """A raw source adapter that returns a preset quote from .fetch()."""
    def __init__(self, quote):
        self._quote = quote

    def fetch(self, asset, checked_at):
        return self._quote


class _FixedPptClient:
    def __init__(self, raw=None, smart=None):
        self._raw = raw
        self._smart = smart

    def raw_quote(self, asset, checked_at):
        return self._raw

    def graded_smart(self, asset, checked_at):
        return self._smart


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _CapturingSession:
    def __init__(self, payload=None, status=200, boom=None):
        self.payload = payload if payload is not None else {"data": {}}
        self.status = status
        self.boom = boom
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        if self.boom is not None:
            raise self.boom
        return _FakeResp(self.payload, self.status)


# ---- #4 honest none when unmapped/unconfigured -------------------------------

def test_unmapped_raw_is_honest_none():
    row = sources.resolve_raw_comp({"asset_class": "raw", "name": "x", "set": "y",
                                    "condition": "NM"}, checked_at=CHECKED)
    comp, conf = comp_from_row(row)
    assert comp is None
    assert conf == "none"
    assert row["confidence"] == "none"


def test_unmapped_graded_is_honest_none():
    row = sources.resolve_graded_comp({"asset_class": "graded", "name": "x", "set": "y",
                                       "grader": "PSA", "grade": "10", "grade_key": "psa10"},
                                      checked_at=CHECKED)
    comp, conf = comp_from_row(row)
    assert comp is None
    assert conf == "none"


# ---- #2 / #9 graded ask never becomes the comp -------------------------------

def test_graded_ask_only_is_never_a_comp():
    row = sources.resolve_graded_comp(GRADED, checked_at=CHECKED,
                                      ebay_source=_FixedSource(_ask(300.0)))
    comp, conf = comp_from_row(row)
    assert comp is None            # a graded ask alone is context, never the estimate
    assert conf == "none"


# ---- raw confidence ladder (reused from comps.model) -------------------------

def test_raw_two_agreeing_sold_derived_is_high():
    row = sources.resolve_raw_comp(
        RAW, checked_at=CHECKED,
        ppt_client=_FixedPptClient(raw=_sold("ppt_cards", 100.0)),
        tcg_source=_FixedSource(_sold("tcgplayer", 104.0)))
    comp, conf = comp_from_row(row)
    assert conf == "high"
    assert comp == 100.0           # min of the two agreeing sold-derived sources


def test_raw_ask_only_is_low_never_high():
    row = sources.resolve_raw_comp(RAW, checked_at=CHECKED,
                                   ebay_source=_FixedSource(_ask(80.0, count=6)))
    comp, conf = comp_from_row(row)
    assert conf == "low"           # ask-basis only, never high
    assert comp == 80.0


# ---- #3 graded PPT smartMarketPrice pass-through -----------------------------

def test_graded_ppt_smart_price_passthrough_high():
    smart = sources.GradedSmartPrice(price=250.0, confidence="high",
                                     url="https://tcg/x", grade_key="psa10", source="ppt_cards")
    row = sources.resolve_graded_comp(GRADED, checked_at=CHECKED,
                                      ppt_client=_FixedPptClient(smart=smart))
    comp, conf = comp_from_row(row)
    assert comp == 250.0
    assert conf == "high"          # 1:1 pass-through, never downgraded


def test_graded_ppt_smart_price_medium_stays_medium():
    smart = sources.GradedSmartPrice(price=180.0, confidence="medium",
                                     url="https://tcg/x", grade_key="psa10", source="ppt_cards")
    row = sources.resolve_graded_comp(GRADED, checked_at=CHECKED,
                                      ppt_client=_FixedPptClient(smart=smart))
    _comp, conf = comp_from_row(row)
    assert conf == "medium"


# ---- #8 limit=1 on both card calls -------------------------------------------

def test_raw_card_call_uses_limit_1():
    session = _CapturingSession(payload={"data": {"prices": {"market": 100.0},
                                                  "tcgPlayerUrl": "https://tcg/x"}})
    client = sources.PptCardClient(api_key="k", session=session)
    client.raw_quote(RAW, CHECKED)
    assert session.calls[0]["url"].endswith("/cards")
    assert session.calls[0]["params"]["limit"] == 1
    assert session.calls[0]["params"]["tcgPlayerId"] == "999001"


def test_graded_card_call_uses_limit_1_and_include_ebay():
    payload = {"data": {"tcgPlayerUrl": "https://tcg/x", "ebay": {"salesByGrade": {
        "psa10": {"smartMarketPrice": {"price": 250.0, "confidence": "high"}}}}}}
    session = _CapturingSession(payload=payload)
    client = sources.PptCardClient(api_key="k", session=session)
    smart = client.graded_smart(GRADED, CHECKED)
    assert session.calls[0]["url"].endswith("/cards")
    assert session.calls[0]["params"]["limit"] == 1
    assert str(session.calls[0]["params"]["includeEbay"]).lower() == "true"
    assert smart.price == 250.0 and smart.confidence == "high"


# ---- #7 401 / 429 / transport error degrade, never crash ---------------------

def test_raw_client_401_degrades_to_no_price():
    session = _CapturingSession(status=401)
    client = sources.PptCardClient(api_key="bad", session=session)
    q = client.raw_quote(RAW, CHECKED)
    assert q.status != "ok" and q.price is None      # no raise, no fabricated price


def test_graded_client_429_returns_no_smart():
    session = _CapturingSession(status=429)
    client = sources.PptCardClient(api_key="k", session=session)
    assert client.graded_smart(GRADED, CHECKED) is None


def test_raw_client_transport_error_degrades():
    session = _CapturingSession(boom=requests.ConnectionError("down"))
    client = sources.PptCardClient(api_key="k", session=session)
    q = client.raw_quote(RAW, CHECKED)
    assert q.status != "ok" and q.price is None
    # and a failed client resolves to honest none, never a crash
    row = sources.resolve_raw_comp(RAW, checked_at=CHECKED, ppt_client=client)
    comp, conf = comp_from_row(row)
    assert comp is None and conf == "none"


# ---- client gating: dormant unless market.preferred + key --------------------

def test_card_client_dormant_without_key():
    class _Cfg:
        market_preferred = False
        market_api_key = ""
    assert sources.card_client_from_config(_Cfg()) is None


def test_card_client_built_when_preferred_and_keyed():
    class _Cfg:
        market_preferred = True
        market_api_key = "abc"
    client = sources.card_client_from_config(_Cfg())
    assert isinstance(client, sources.PptCardClient)
