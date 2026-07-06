"""Phase F — independent (non-PPT) PriceCharting/TCGplayer source adapters."""
from pathlib import Path

from scanner.poke_api import independent_sources as indep

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
