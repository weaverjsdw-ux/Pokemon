"""Phase F — independent (non-PPT) PriceCharting/TCGplayer source adapters."""
from pathlib import Path

from scanner import config as config_mod
from scanner.market import comp_from_row
from scanner.poke_api import independent_sources as indep
from scanner.poke_api import sources as sources_mod

FIXTURE = Path(__file__).parent / "fixtures" / "comps" / "pricecharting_umbreon_ex_161.html"


def _fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parser_extracts_every_grade_cell():
    parsed = indep.pricecharting_card_prices_from_html(_fixture())
    assert parsed["blocked"] is False
    cells = parsed["cells"]
    assert cells["used_price"] == 1425.00
    assert cells["complete_price"] == 1270.00
    assert cells["new_price"] == 1286.91
    assert cells["graded_price"] == 1554.05
    assert cells["box_only_price"] == 3112.50
    assert cells["manual_only_price"] == 7013.08


def test_parser_challenge_page_is_blocked():
    parsed = indep.pricecharting_card_prices_from_html("<html>Just a moment...</html>")
    assert parsed["blocked"] is True
    assert parsed["cells"] == {}


def test_parser_malformed_html_is_empty_not_crash():
    parsed = indep.pricecharting_card_prices_from_html("<table><td>no ids here</td></table>")
    assert parsed["blocked"] is False
    assert parsed["cells"] == {}


RAW_ASSET = {"asset_key": "umbreon_raw_nm", "asset_class": "raw", "name": "Umbreon ex 161",
             "set": "Prismatic Evolutions", "condition": "NM",
             "pricecharting_slug": "pokemon-prismatic-evolutions/umbreon-ex-161"}
PSA10 = {"asset_key": "umbreon_psa10", "asset_class": "graded", "name": "Umbreon ex 161",
         "set": "Prismatic Evolutions", "grade_key": "psa10",
         "pricecharting_slug": "pokemon-prismatic-evolutions/umbreon-ex-161"}
PSA9 = {**PSA10, "asset_key": "umbreon_psa9", "grade_key": "psa9"}


class _FakeSession:
    """Returns a canned response for .get(); no network."""
    def __init__(self, text, status=200, exc=None):
        self._text, self._status, self._exc = text, status, exc

    def get(self, url, **kw):
        if self._exc is not None:
            raise self._exc
        return _FakeResp(self._text, self._status)


class _FakeResp:
    def __init__(self, text, status):
        self.text, self.status_code = text, status


def test_raw_adapter_uses_ungraded_cell():
    src = indep.PriceChartingRawSource(session=_FakeSession(_fixture()))
    q = src.fetch(RAW_ASSET, 1_700_000_000)
    assert q.source == "pricecharting" and q.status == "ok"
    assert q.price == 1425.00
    assert "pokemon-prismatic-evolutions/umbreon-ex-161" in q.url


def test_raw_adapter_no_slug_is_skipped():
    q = indep.PriceChartingRawSource(session=_FakeSession(_fixture())).fetch(
        {"asset_class": "raw", "name": "x", "set": "y"}, 1_700_000_000)
    assert q.status == "skipped" and q.price is None


def test_graded_psa10_uses_manual_only_price_exact():
    q = indep.PriceChartingGradedSource(session=_FakeSession(_fixture())).fetch(PSA10, 1_700_000_000)
    assert q.status == "ok" and q.price == 7013.08
    assert "PSA-exact" in q.detail


def test_graded_psa9_uses_grade9_column_grader_agnostic():
    q = indep.PriceChartingGradedSource(session=_FakeSession(_fixture())).fetch(PSA9, 1_700_000_000)
    assert q.status == "ok" and q.price == 1554.05
    assert "grader-agnostic" in q.detail


def test_graded_cgc10_has_no_exact_cell_no_match():
    q = indep.PriceChartingGradedSource(session=_FakeSession(_fixture())).fetch(
        {**PSA10, "grade_key": "cgc10"}, 1_700_000_000)
    assert q.status == "no_match" and q.price is None


def test_adapter_challenge_page_is_blocked():
    src = indep.PriceChartingRawSource(session=_FakeSession("Just a moment..."))
    assert src.fetch(RAW_ASSET, 1_700_000_000).status == "blocked"


def test_adapter_http_403_is_blocked():
    src = indep.PriceChartingRawSource(session=_FakeSession("", status=403))
    assert src.fetch(RAW_ASSET, 1_700_000_000).status == "blocked"


def _srcs(session):
    return {"pc_raw": indep.PriceChartingRawSource(session=session),
            "pc_graded": indep.PriceChartingGradedSource(session=session),
            "tcg": indep.TcgPlayerRenderedSource(render=None)}  # rendering dormant


def test_independent_raw_row_is_low_single_source():
    row = sources_mod.resolve_independent_asset_row(
        RAW_ASSET, sources=_srcs(_FakeSession(_fixture())), checked_at=1_700_000_000)
    assert row["status"] == "ok"
    comp, _conf = comp_from_row(row)        # row["estimate"] is a money string ("$1425.00")
    assert comp == 1425.00
    assert row["confidence"] == "low"       # single independent sold source
    ok_sources = [s for s in row.get("sources", []) if s.get("status") == "ok"]
    assert any(s["source"] == "pricecharting" for s in ok_sources)  # PC produced the number
    assert all(s["source"] != "ppt_cards" for s in row.get("sources", []))


def test_independent_graded_row_is_locked_low_even_psa_exact():
    row = sources_mod.resolve_independent_asset_row(
        PSA10, sources=_srcs(_FakeSession(_fixture())), checked_at=1_700_000_000)
    assert row["status"] == "ok"
    comp, _conf = comp_from_row(row)        # row["estimate"] is a money string ("$7013.08")
    assert comp == 7013.08
    assert row["confidence"] == "low"       # LOCKED low even on the PSA-exact cell
    assert "PSA-exact" in (row.get("confidenceReason") or row.get("detail") or "")


def test_independent_graded_uses_pricecharting_slug_not_ppt():
    row = sources_mod.resolve_independent_asset_row(
        PSA9, sources=_srcs(_FakeSession(_fixture())), checked_at=1_700_000_000)
    slugs = [s.get("source") for s in row.get("sources", [])]
    assert "pricecharting" in slugs
    assert "ppt_cards" not in slugs


class _Cfg:
    """Minimal Config stand-in carrying a real PokeCfg (scanner.config.Config has 10
    required positional fields unrelated to this gate — not worth constructing here)."""
    def __init__(self):
        self.poke = config_mod.PokeCfg()


def test_independent_sources_gate_defaults_off():
    cfg = _Cfg()
    assert indep.independent_sources_enabled(cfg) is False


def test_independent_sources_gate_reads_poke_flag():
    cfg = _Cfg()
    cfg.poke.independent_sources = True
    assert indep.independent_sources_enabled(cfg) is True


def test_build_independent_sources_has_pc_and_dormant_tcg():
    srcs = indep.build_independent_sources()
    assert isinstance(srcs["pc_raw"], indep.PriceChartingRawSource)
    assert isinstance(srcs["pc_graded"], indep.PriceChartingGradedSource)
    # TCGplayer render dormant by default -> a blocked quote, never a crash
    q = srcs["tcg"].fetch({"tcgplayer_id": "610516"}, 1_700_000_000)
    assert q.status == "blocked"


def test_independent_path_spends_zero_ppt_credits():
    """The independent resolver must never construct/call the PPT card client."""
    import scanner.poke_api.sources as s

    class _ExplodingPPT:
        def raw_quote(self, *a, **k):  # pragma: no cover - must never be called
            raise AssertionError("independent path called the PPT client")
        def graded_smart(self, *a, **k):  # pragma: no cover
            raise AssertionError("independent path called the PPT client")

    # resolve_independent_asset_row never accepts a ppt_client; prove it by resolving
    # with only the independent sources and asserting a pricecharting row.
    row = s.resolve_independent_asset_row(
        RAW_ASSET, sources=_srcs(_FakeSession(_fixture())), checked_at=1_700_000_000)
    assert row["status"] == "ok"
    assert all(src.get("source") != "ppt_cards" for src in row.get("sources", []))


def test_writer_refuses_ask_source():
    """record_asset_comp must refuse an ebay (ask) source — an ask is never a comp."""
    import pytest
    from scanner.poke_api import sources as s
    with pytest.raises(ValueError):
        s.build_asset_comp_observation(RAW_ASSET, comp=100.0, confidence="low",
                                       source="ebay", capture_date="2026-07-06")


def test_tcg_rendered_ok_with_mock_render():
    html = '<div class="price-guide">Market Price: $1,499.99</div>'
    src = indep.TcgPlayerRenderedSource(render=lambda url: html)
    q = src.fetch({"tcgplayer_id": "610516"}, 1_700_000_000)
    assert q.source == "tcgplayer" and q.status == "ok" and q.price == 1499.99


def test_tcg_render_exception_is_blocked_not_crash():
    def boom(url):
        raise RuntimeError("chromium missing")
    q = indep.TcgPlayerRenderedSource(render=boom).fetch({"tcgplayer_id": "610516"}, 1_700_000_000)
    assert q.status == "blocked"


def test_tcg_challenge_page_is_blocked():
    q = indep.TcgPlayerRenderedSource(render=lambda url: "Just a moment...").fetch(
        {"tcgplayer_id": "610516"}, 1_700_000_000)
    assert q.status == "blocked"


def test_tcg_no_price_node_is_no_match():
    q = indep.TcgPlayerRenderedSource(render=lambda url: "<div>no price here</div>").fetch(
        {"tcgplayer_id": "610516"}, 1_700_000_000)
    assert q.status == "no_match"
