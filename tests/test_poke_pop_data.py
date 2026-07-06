"""Phase G — PriceCharting VGPC.pop_data parser + 0-credit pop fetch adapter.

The population blob is embedded in the SAME already-fetched detail-page HTML as the
price cells (no Playwright, no login, no paid API). The parser is STOP-class robust:
missing / malformed / challenge / grader-absent all return an honest no-pop (or block),
never a crash and never a guessed number."""
from __future__ import annotations

from pathlib import Path

from scanner.poke_api import gem_rates as gr
from scanner.poke_api import independent_sources as indep

POP_FIXTURE = Path(__file__).parent / "fixtures" / "comps" / "pricecharting_pop_umbreon_ex_161.html"


def _pop_html() -> str:
    return POP_FIXTURE.read_text(encoding="utf-8")


# ---------------------------------------------------------------- valid blob

def test_parser_extracts_valid_pop_data():
    parsed = indep.pricecharting_pop_from_html(_pop_html())
    assert parsed["present"] is True
    assert parsed["blocked"] is False
    assert parsed["pop"]["psa"] == [1, 2, 4, 15, 43, 161, 428, 2654, 9195, 5487]
    assert parsed["pop"]["cgc"] == [0, 0, 0, 1, 0, 2, 16, 122, 259, 366]
    assert set(parsed["graders"]) == {"psa", "cgc"}


def test_parsed_pop_feeds_grader_specific_gem_rate():
    """End-to-end: the parsed PSA array yields the ~30.5% Umbreon gem rate; CGC is a
    SEPARATE series (never combined)."""
    parsed = indep.pricecharting_pop_from_html(_pop_html())
    psa = gr.gem_rate_from_counts(parsed["pop"]["psa"], grader="PSA")
    assert psa["status"] == "ok"
    assert psa["sample_size"] == 17990
    assert round(psa["gem_rate"], 3) == 0.305
    cgc = gr.gem_rate_from_counts(parsed["pop"]["cgc"], grader="CGC")
    assert cgc["sample_size"] == 766           # CGC only, disjoint from PSA


# ---------------------------------------------------------------- honest degrades

def test_parser_missing_blob_is_honest_no_pop():
    parsed = indep.pricecharting_pop_from_html("<html><body>no pop here</body></html>")
    assert parsed["present"] is False
    assert parsed["pop"] == {}
    assert parsed["blocked"] is False


def test_parser_malformed_blob_is_no_pop_not_crash():
    body = '<script>VGPC.pop_data = {"psa":[1,2,3,,]};</script>'   # invalid JSON
    parsed = indep.pricecharting_pop_from_html(body)
    assert parsed["present"] is True          # the blob marker was there ...
    assert parsed["pop"] == {}                 # ... but it did not parse -> honest no-pop


def test_parser_challenge_page_is_blocked():
    parsed = indep.pricecharting_pop_from_html("<html>Just a moment...</html>")
    assert parsed["blocked"] is True
    assert parsed["pop"] == {}


def test_parser_grader_absent_returns_other_graders_only():
    body = '<script>VGPC.pop_data = {"psa":[1,2,4,15,43,161,428,2654,9195,5487]};</script>'
    parsed = indep.pricecharting_pop_from_html(body)
    assert "psa" in parsed["pop"]
    assert "cgc" not in parsed["pop"]          # grader simply absent, not a guessed zero


def test_parser_nonnumeric_array_excluded():
    body = '<script>VGPC.pop_data = {"psa":["a","b"],"cgc":[0,0,0,1,0,2,16,122,259,366]};</script>'
    parsed = indep.pricecharting_pop_from_html(body)
    assert "psa" not in parsed["pop"]          # nonnumeric array is not counts
    assert parsed["pop"]["cgc"] == [0, 0, 0, 1, 0, 2, 16, 122, 259, 366]


def test_parser_non_object_blob_is_no_pop():
    parsed = indep.pricecharting_pop_from_html('<script>VGPC.pop_data = [1,2,3];</script>')
    assert parsed["pop"] == {}


# ---------------------------------------------------------------- 0-credit fetch adapter

class _FakeSession:
    def __init__(self, text, status=200, exc=None):
        self._text, self._status, self._exc = text, status, exc

    def get(self, url, **kw):
        if self._exc is not None:
            raise self._exc
        return _FakeResp(self._text, self._status)


class _FakeResp:
    def __init__(self, text, status):
        self.text, self.status_code = text, status


UMBREON = {"asset_key": "umbreon_ex_161_raw_nm", "asset_class": "raw",
           "name": "Umbreon ex 161", "set": "Prismatic Evolutions", "card_number": "161",
           "pricecharting_slug": "pokemon-prismatic-evolutions/umbreon-ex-161"}


def test_pop_source_fetch_ok():
    src = indep.PriceChartingPopSource(session=_FakeSession(_pop_html()))
    res = src.fetch_pop(UMBREON, 1_700_000_000)
    assert res["status"] == "ok"
    assert res["pop"]["psa"][-1] == 5487
    assert "umbreon-ex-161" in res["url"]
    assert res["number"] == "161"              # page card number (wrong-slug guard input)


def test_pop_source_no_slug_skips_no_network():
    src = indep.PriceChartingPopSource(session=_FakeSession(_pop_html()))
    res = src.fetch_pop({"asset_key": "x"}, 1_700_000_000)
    assert res["status"] == "skipped"
    assert res["pop"] == {}


def test_pop_source_http_block():
    src = indep.PriceChartingPopSource(session=_FakeSession("", status=403))
    res = src.fetch_pop(UMBREON, 1_700_000_000)
    assert res["status"] == "blocked"


def test_pop_source_no_pop_on_page():
    src = indep.PriceChartingPopSource(session=_FakeSession("<html>prices but no pop</html>"))
    res = src.fetch_pop(UMBREON, 1_700_000_000)
    assert res["status"] == "no_pop"
    assert res["pop"] == {}


def test_pop_source_never_constructs_ppt_client():
    """The pop path is 0 PPT credits by construction — the adapter takes only a plain
    requests session, never a PPT client, and touches only the PriceCharting detail page."""
    import inspect
    sig = inspect.signature(indep.PriceChartingPopSource.__init__)
    assert "ppt_client" not in sig.parameters
    assert "card_client" not in sig.parameters
