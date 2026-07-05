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
    def __init__(self, payload, status=200, json_boom=None):
        self._payload = payload
        self.status_code = status
        self.headers = {}
        self._json_boom = json_boom

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._json_boom is not None:
            raise self._json_boom          # e.g. a malformed 200 body -> ValueError
        return self._payload


class _CapturingSession:
    def __init__(self, payload=None, status=200, boom=None, json_boom=None):
        self.payload = payload if payload is not None else {"data": {}}
        self.status = status
        self.boom = boom
        self.json_boom = json_boom
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        if self.boom is not None:
            raise self.boom
        return _FakeResp(self.payload, self.status, json_boom=self.json_boom)


class _BoomPptClient:
    """A card client whose lookups raise — proves a client bug degrades to honest
    no-comp and never crashes the asset comp route (containment)."""
    def raw_quote(self, asset, checked_at):
        raise RuntimeError("client boom")

    def graded_smart(self, asset, checked_at):
        raise RuntimeError("client boom")


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


def test_raw_ask_only_is_never_a_comp():
    """Policy (D.5): a raw ask-only listing set is CONTEXT, not a comp. With no
    sold-derived source, the estimate must be None and confidence ``none`` — never a
    low-confidence number invented from asks. (Previously this returned 80.0/low.)"""
    row = sources.resolve_raw_comp(RAW, checked_at=CHECKED,
                                   ebay_source=_FixedSource(_ask(80.0, count=6)))
    comp, conf = comp_from_row(row)
    assert comp is None            # ask-only alone can never become the raw estimate
    assert conf == "none"
    assert row["confidence"] == "none"


def test_raw_ask_only_still_surfaces_the_ask_as_context():
    """The ask isn't discarded — it stays in ``sources[]`` as context/provenance so a
    caller can see the active-ask signal, it just isn't promoted to an estimate."""
    row = sources.resolve_raw_comp(RAW, checked_at=CHECKED,
                                   ebay_source=_FixedSource(_ask(80.0, count=6)))
    asks = [s for s in row.get("sources", []) if s.get("kind") == ACTIVE_ASK]
    assert asks and asks[0]["price"] == 80.0     # context preserved, not silently dropped


def test_raw_one_sold_derived_is_low():
    """A single sold-derived raw source (no corroboration) is a real — if weak —
    comp: low confidence, never suppressed like an ask-only set."""
    row = sources.resolve_raw_comp(
        RAW, checked_at=CHECKED,
        tcg_source=_FixedSource(_sold("tcgplayer", 100.0)))
    comp, conf = comp_from_row(row)
    assert comp == 100.0
    assert conf == "low"


def test_raw_disagreeing_sold_derived_is_not_fake_high():
    """Two sold-derived sources that disagree beyond tolerance must NOT mint high
    confidence — they degrade to medium (source_spread), never a fake agreement."""
    row = sources.resolve_raw_comp(
        RAW, checked_at=CHECKED,
        ppt_client=_FixedPptClient(raw=_sold("ppt_cards", 100.0)),
        tcg_source=_FixedSource(_sold("tcgplayer", 220.0)))
    comp, conf = comp_from_row(row)
    assert conf == "medium"        # disagreement is honest, not high
    assert comp == 100.0           # still min() of the two, never invented


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


# ---- graded PriceCharting fallback (no smart price -> PC graded page) ---------

def test_graded_pricecharting_fallback_uncorroborated_is_low():
    """With no smart price, a PriceCharting graded page is the fallback single
    sold-derived source -> low (uncorroborated)."""
    row = sources.resolve_graded_comp(
        GRADED, checked_at=CHECKED,
        pc_source=_FixedSource(_sold("pricecharting", 240.0)))
    comp, conf = comp_from_row(row)
    assert comp == 240.0
    assert conf == "low"


def test_graded_pricecharting_fallback_ask_corroborated_is_medium():
    """A PriceCharting graded price corroborated by a nearby eBay ask -> medium (the
    ask lifts confidence but is never itself the comp)."""
    row = sources.resolve_graded_comp(
        GRADED, checked_at=CHECKED,
        pc_source=_FixedSource(_sold("pricecharting", 240.0)),
        ebay_source=_FixedSource(_ask(250.0)))
    comp, conf = comp_from_row(row)
    assert comp == 240.0           # the PC sold-derived price, never the ask
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


# ---- provider-neutral public identity (D.5) ----------------------------------

def test_external_card_client_is_the_public_name():
    """The production client's public identity is provider-neutral: the configured
    external card price source, not a specific vendor's brand."""
    class _Cfg:
        market_preferred = True
        market_api_key = "abc"
    client = sources.card_client_from_config(_Cfg())
    assert isinstance(client, sources.ExternalCardPriceClient)


def test_ppt_card_client_is_retained_compat_alias():
    """Legacy name still resolves (deprecated compat) so existing imports keep working."""
    assert sources.PptCardClient is sources.ExternalCardPriceClient


# ---- #4 malformed provider payloads degrade honestly (never crash) -----------

def test_raw_malformed_200_json_degrades_honestly():
    """A 200 with an unparseable body makes ``resp.json()`` raise ValueError; the
    client must degrade to a no-price quote, not propagate the decode error."""
    session = _CapturingSession(json_boom=ValueError("No JSON object could be decoded"))
    client = sources.PptCardClient(api_key="k", session=session)
    q = client.raw_quote(RAW, CHECKED)
    assert q.status != "ok" and q.price is None


def test_graded_malformed_200_json_returns_none():
    session = _CapturingSession(json_boom=ValueError("bad json"))
    client = sources.PptCardClient(api_key="k", session=session)
    assert client.graded_smart(GRADED, CHECKED) is None


def test_raw_missing_data_degrades():
    session = _CapturingSession(payload={"ok": True})       # no "data" key
    client = sources.PptCardClient(api_key="k", session=session)
    q = client.raw_quote(RAW, CHECKED)
    assert q.status != "ok" and q.price is None


def test_raw_data_wrong_type_degrades():
    session = _CapturingSession(payload={"data": 5})         # data is a scalar
    client = sources.PptCardClient(api_key="k", session=session)
    q = client.raw_quote(RAW, CHECKED)
    assert q.status != "ok" and q.price is None


def test_raw_prices_wrong_type_degrades():
    """``data.prices`` as a list (not an object) must not AttributeError on ``.get``."""
    session = _CapturingSession(payload={"data": {"prices": [1, 2, 3],
                                                  "tcgPlayerUrl": "u"}})
    client = sources.PptCardClient(api_key="k", session=session)
    q = client.raw_quote(RAW, CHECKED)
    assert q.status != "ok" and q.price is None


def test_raw_missing_prices_degrades():
    session = _CapturingSession(payload={"data": {"tcgPlayerUrl": "u"}})
    client = sources.PptCardClient(api_key="k", session=session)
    q = client.raw_quote(RAW, CHECKED)
    assert q.status != "ok" and q.price is None


def test_graded_sales_by_grade_wrong_type_returns_none():
    """``data.ebay.salesByGrade`` as a list must not AttributeError on ``.get``."""
    session = _CapturingSession(payload={"data": {"tcgPlayerUrl": "u",
                                                  "ebay": {"salesByGrade": [1, 2]}}})
    client = sources.PptCardClient(api_key="k", session=session)
    assert client.graded_smart(GRADED, CHECKED) is None


def test_graded_missing_sales_by_grade_returns_none():
    session = _CapturingSession(payload={"data": {"tcgPlayerUrl": "u", "ebay": {}}})
    client = sources.PptCardClient(api_key="k", session=session)
    assert client.graded_smart(GRADED, CHECKED) is None


def test_graded_missing_smart_price_returns_none():
    session = _CapturingSession(payload={"data": {"ebay": {"salesByGrade": {"psa10": {}}}}})
    client = sources.PptCardClient(api_key="k", session=session)
    assert client.graded_smart(GRADED, CHECKED) is None


def test_graded_bad_confidence_string_normalizes_to_medium():
    payload = {"data": {"tcgPlayerUrl": "u", "ebay": {"salesByGrade": {
        "psa10": {"smartMarketPrice": {"price": 250.0, "confidence": "wobbly"}}}}}}
    session = _CapturingSession(payload=payload)
    client = sources.PptCardClient(api_key="k", session=session)
    smart = client.graded_smart(GRADED, CHECKED)
    assert smart.price == 250.0 and smart.confidence == "medium"


# ---- #7 a client exception never crashes the asset comp resolve (containment) --

def test_raw_refresh_survives_client_exception():
    row = sources.resolve_raw_comp(RAW, checked_at=CHECKED, ppt_client=_BoomPptClient())
    comp, conf = comp_from_row(row)
    assert comp is None and conf == "none"       # honest no-comp, not a crash


def test_graded_refresh_survives_client_exception():
    row = sources.resolve_graded_comp(GRADED, checked_at=CHECKED, ppt_client=_BoomPptClient())
    comp, conf = comp_from_row(row)
    assert comp is None and conf == "none"


def test_raw_refresh_with_malformed_payload_is_honest_none():
    """End-to-end: a real client fed a malformed payload resolves to honest none
    through resolve_raw_comp (no crash on the refresh path)."""
    session = _CapturingSession(payload={"data": {"prices": ["oops"]}})
    client = sources.PptCardClient(api_key="k", session=session)
    row = sources.resolve_raw_comp(RAW, checked_at=CHECKED, ppt_client=client)
    comp, conf = comp_from_row(row)
    assert comp is None and conf == "none"


# ---- #8 billable-surface credit bound (deterministic, stateless) -------------

def test_credit_bound_no_client_is_zero():
    acct = sources.expected_asset_credits(RAW, card_client=None)
    assert acct.total == 0 and acct.source == "local"


def test_credit_bound_unmapped_id_is_zero():
    unmapped = {"asset_class": "raw", "name": "x", "set": "y", "condition": "NM"}  # no tcgplayer_id
    acct = sources.expected_asset_credits(unmapped, card_client=object())
    assert acct.total == 0 and acct.source == "local"


def test_credit_bound_raw_mapped_is_one():
    acct = sources.expected_asset_credits(RAW, card_client=object())
    assert acct.total == 1 and acct.estimated is True and acct.source == "external"


def test_credit_bound_graded_mapped_is_two():
    """Graded uses includeEbay=true → basic 1 + eBay +1 = 2 credits (ppt-v2-notes)."""
    acct = sources.expected_asset_credits(GRADED, card_client=object())
    assert acct.total == 2 and acct.estimated is True and acct.source == "external"


def test_credit_bound_graded_without_grade_key_is_zero():
    """A graded asset with no grade_key issues no /cards call → 0 credits."""
    no_grade = {"asset_class": "graded", "name": "x", "set": "y", "grader": "PSA",
                "grade": "10", "tcgplayer_id": "999001"}   # grade_key intentionally absent
    acct = sources.expected_asset_credits(no_grade, card_client=object())
    assert acct.total == 0 and acct.source == "local"
