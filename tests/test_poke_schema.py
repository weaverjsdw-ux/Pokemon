import json
from pathlib import Path

import pytest

from scanner.discovery.schema import (
    DealRow, StopGateError, assert_sweep, row_from_dict, validate_row,
)


def _sealed(**kw):
    base = dict(
        item="Prismatic Evolutions ETB", asset_class="sealed", category="sealed-etb",
        deal_price=39.99, market_comp=60.0, retailer="Target",
        source_url="https://example.com/x", captured_at="2026-06-27",
        price_confidence="verified", comp_confidence="high", pct_off=33,
        badges=["STEAL"],
    )
    base.update(kw)
    return DealRow(**base)


def test_clean_verified_row_has_no_violations():
    assert validate_row(_sealed()) == []


def test_verified_row_needs_source_and_date():
    assert validate_row(_sealed(source_url="")) != []
    assert validate_row(_sealed(captured_at="")) != []


def test_verified_row_must_not_carry_est_badge():
    assert validate_row(_sealed(badges=["STEAL", "EST"])) != []


def test_est_row_needs_method_and_est_badge():
    bad = _sealed(price_confidence="est", derivation_method="", badges=[])
    assert validate_row(bad) != []
    good = _sealed(price_confidence="est", derivation_method="comp_inference",
                   badges=["EST"], comp_confidence="low")
    assert validate_row(good) == []


def test_nonpositive_price_is_a_violation():
    assert validate_row(_sealed(deal_price=0)) != []


def test_pct_off_must_match_market_comp():
    # comp 60, deal 39.99 -> ~33%; claiming 80 is inconsistent
    assert validate_row(_sealed(pct_off=80)) != []


def test_graded_row_needs_grade_and_grader():
    g = _sealed(asset_class="graded", grade="", grader="")
    assert validate_row(g) != []
    ok = _sealed(asset_class="graded", grade="PSA 10", grader="PSA")
    assert validate_row(ok) == []


def test_raw_row_needs_condition():
    r = _sealed(asset_class="raw", condition="")
    assert validate_row(r) != []


def test_authenticity_risk_cannot_be_a_steal():
    a = _sealed(authenticity_risk=True, badges=["STEAL"])
    assert validate_row(a) != []


def test_assert_sweep_raises_on_any_violation():
    with pytest.raises(StopGateError):
        assert_sweep([_sealed(), _sealed(source_url="")])


def test_row_from_dict_roundtrips_known_fields():
    row = row_from_dict({"item": "X", "asset_class": "sealed", "category": "sealed-etb",
                         "deal_price": 10.0, "market_comp": 20.0, "retailer": "R",
                         "source_url": "u", "captured_at": "2026-06-27",
                         "price_confidence": "verified", "comp_confidence": "high",
                         "pct_off": 50, "badges": ["STEAL"]})
    assert row.item == "X" and row.deal_price == 10.0


def test_sample_sweep_fixture_passes_stop_gate():
    path = Path("data/poke/fixtures/sample-sweep.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = [row_from_dict(d) for d in data["deals"]]
    assert len(rows) >= 10
    assert_sweep(rows)  # must not raise
    assert any(r.price_confidence == "est" for r in rows)
    assert any(r.authenticity_risk for r in rows)
    assert any(r.scanner_verdict for r in rows)
