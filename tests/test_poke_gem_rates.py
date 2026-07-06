"""Phase G — gem-rate math + append-only evidence ledger.

STOP-class: a gem rate is either ``sourced`` (from a dated PriceCharting population
blob) or an explicit ``operator_assumption`` — NEVER invented. Grader-specific: PSA
and CGC are never combined. Canonical formula: ``PSA10 / total PSA population``. The
ledger is append-only + idempotent by a sha256 entry_id (mirrors paper_ledger)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scanner.poke_api import gem_rates as gr

# Umbreon ex #161 PSA population, verbatim from the live 2026-07-06 probe (roadmap §3.3).
UMBREON_PSA = [1, 2, 4, 15, 43, 161, 428, 2654, 9195, 5487]


# ---------------------------------------------------------------- pinned index map + formula

def test_index_map_pins_last_element_as_grade_10_via_published_totals():
    """The 10-element array is grades 1..10 (no half/Authentic offset). Confirmed —
    not assumed — by cross-checking the array against Umbreon's INDEPENDENTLY published
    PSA total (17,990) and PSA-10 (5,487): if last==grade10 and sum==total, the map holds."""
    assert gr.POP_GRADE_LADDER == (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
    assert len(UMBREON_PSA) == len(gr.POP_GRADE_LADDER)
    assert sum(UMBREON_PSA) == 17990          # matches roadmap's published PSA total
    assert UMBREON_PSA[-1] == 5487            # matches roadmap's published PSA-10


def test_gem_rate_formula_is_psa10_over_total():
    r = gr.gem_rate_from_counts(UMBREON_PSA, grader="PSA")
    assert r["status"] == "ok"
    assert r["sample_size"] == 17990
    assert r["gem_rate"] == pytest.approx(5487 / 17990, abs=1e-4)   # ~0.305
    assert r["gem_rate_formula"] == gr.gem_rate_formula("PSA") == "PSA10 / total PSA population"
    assert r["counts_by_grade"]["10"] == 5487
    assert r["counts_by_grade"]["1"] == 1


def test_gem_rate_is_grader_specific_cgc_not_combined():
    cgc = [0, 0, 0, 1, 0, 2, 16, 122, 259, 366]   # Umbreon CGC series
    r = gr.gem_rate_from_counts(cgc, grader="CGC")
    assert r["status"] == "ok"
    assert r["sample_size"] == 766                 # CGC total only, NOT PSA+CGC
    assert r["gem_rate"] == pytest.approx(366 / 766, abs=1e-4)
    # The formula label names the row's OWN grader — never a PSA figure on a CGC row.
    assert r["gem_rate_formula"] == gr.gem_rate_formula("CGC") == "CGC10 / total CGC population"


def test_gem_rate_formula_builder_is_grader_specific():
    assert gr.gem_rate_formula("psa") == "PSA10 / total PSA population"
    assert gr.gem_rate_formula("CGC") == "CGC10 / total CGC population"
    assert gr.gem_rate_formula("bgs") == "BGS10 / total BGS population"


# ---------------------------------------------------------------- sample-size floor

def test_below_sample_floor_is_insufficient_not_a_guess():
    small = [0, 0, 0, 0, 0, 0, 1, 2, 40, 30]       # total 73 < 300
    r = gr.gem_rate_from_counts(small, grader="PSA")
    assert r["status"] == "insufficient_sample"
    assert r["sample_size"] == 73


def test_at_floor_is_ok():
    counts = [0, 0, 0, 0, 0, 0, 0, 0, 200, 100]    # total 300 == floor
    assert gr.gem_rate_from_counts(counts, grader="PSA")["status"] == "ok"


def test_custom_floor_respected():
    counts = [0, 0, 0, 0, 0, 0, 0, 0, 200, 100]    # total 300
    assert gr.gem_rate_from_counts(counts, grader="PSA", sample_floor=500)["status"] \
        == "insufficient_sample"


# ---------------------------------------------------------------- malformed / never-crash

def test_short_array_is_invalid():
    assert gr.gem_rate_from_counts([1, 2, 3], grader="PSA")["status"] == "invalid"


def test_nonnumeric_counts_invalid():
    bad = [1, 2, 4, 15, 43, 161, 428, 2654, 9195, "oops"]
    assert gr.gem_rate_from_counts(bad, grader="PSA")["status"] == "invalid"


def test_zero_population_invalid_not_zero_rate():
    assert gr.gem_rate_from_counts([0] * 10, grader="PSA")["status"] == "invalid"


def test_negative_count_invalid():
    bad = [1, 2, 4, 15, 43, 161, 428, 2654, 9195, -5]
    assert gr.gem_rate_from_counts(bad, grader="PSA")["status"] == "invalid"


# ---------------------------------------------------------------- entry_id identity

def test_entry_id_stable_over_the_declared_identity():
    kw = dict(asset_key="umbreon_ex_161_raw_nm", grader="PSA",
              source_url="https://www.pricecharting.com/game/x/umbreon-ex-161",
              capture_date="2026-07-06", formula=gr.gem_rate_formula("PSA"), label="sourced")
    assert gr.gem_rate_entry_id(**kw) == gr.gem_rate_entry_id(**kw)


def test_entry_id_changes_with_capture_date_and_label():
    base = dict(asset_key="a", grader="PSA", source_url="u",
                capture_date="2026-07-06", formula=gr.gem_rate_formula("PSA"), label="sourced")
    other_day = {**base, "capture_date": "2026-07-07"}
    other_label = {**base, "label": "operator_assumption"}
    assert gr.gem_rate_entry_id(**base) != gr.gem_rate_entry_id(**other_day)
    assert gr.gem_rate_entry_id(**base) != gr.gem_rate_entry_id(**other_label)


# ---------------------------------------------------------------- append-only + idempotent ledger

def _ledger(tmp_path) -> Path:
    return tmp_path / "gem_rates.jsonl"


def test_record_sourced_writes_stamped_row(tmp_path):
    path = _ledger(tmp_path)
    wrote = gr.record_sourced(
        path, asset_key="umbreon_ex_161_raw_nm", grader="PSA", counts=UMBREON_PSA,
        source_url="https://www.pricecharting.com/game/x/umbreon-ex-161",
        capture_date="2026-07-06", basis="PriceCharting PSA population census (monthly)")
    assert wrote is True
    rows = gr.read_rows(path)
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "gem_rate"
    assert row["label"] == "sourced"
    assert row["source"] == "pricecharting_pop"
    assert row["grader"] == "PSA"
    assert row["gem_rate"] == pytest.approx(5487 / 17990, abs=1e-4)
    assert row["sample_size"] == 17990
    assert row["gem_rate_formula"] == gr.gem_rate_formula("PSA")
    assert row["sample_floor"] == 300                    # the floor recorded against
    assert row["counts_by_grade"]["10"] == 5487
    assert row["source_url"].endswith("umbreon-ex-161")
    assert row["capture_date"] == "2026-07-06"
    assert row["entry_id"]


def test_record_sourced_persists_custom_sample_floor(tmp_path):
    """A custom --sample-floor is persisted on the row so read-time provenance judges
    sufficiency against the floor USED AT RECORD TIME, not the default."""
    path = _ledger(tmp_path)
    counts = [0, 0, 0, 0, 0, 0, 0, 50, 150, 50]          # total 250 (>= 200, < 300)
    gr.record_sourced(path, asset_key="a", grader="PSA", counts=counts,
                      source_url="u", capture_date="2026-07-06", sample_floor=200)
    row = gr.read_rows(path)[0]
    assert row["sample_floor"] == 200
    assert row["sample_size"] == 250


def test_record_sourced_is_idempotent(tmp_path):
    path = _ledger(tmp_path)
    kw = dict(asset_key="a", grader="PSA", counts=UMBREON_PSA,
              source_url="u", capture_date="2026-07-06")
    assert gr.record_sourced(path, **kw) is True
    assert gr.record_sourced(path, **kw) is False        # same identity -> no-op
    assert len(gr.read_rows(path)) == 1


def test_record_sourced_below_floor_refuses_to_write(tmp_path):
    path = _ledger(tmp_path)
    with pytest.raises(ValueError):
        gr.record_sourced(path, asset_key="a", grader="PSA",
                          counts=[0, 0, 0, 0, 0, 0, 1, 2, 40, 30],  # total 73
                          source_url="u", capture_date="2026-07-06")
    assert gr.read_rows(path) == []                       # nothing written


def test_record_assumption_labels_operator_assumption(tmp_path):
    path = _ledger(tmp_path)
    wrote = gr.record_assumption(
        path, asset_key="a", grader="PSA", gem_rate=0.30,
        basis="operator assumption: 30% base rate for modern SIR", capture_date="2026-07-06")
    assert wrote is True
    row = gr.read_rows(path)[0]
    assert row["label"] == "operator_assumption"
    assert row["source"] == "operator_assumption"
    assert row["gem_rate"] == 0.30
    assert row["sample_size"] is None                    # no population behind an assumption
    assert row["basis"].startswith("operator assumption")


def test_record_assumption_rejects_out_of_range_rate(tmp_path):
    path = _ledger(tmp_path)
    for bad in (0.0, 1.5, -0.1):
        with pytest.raises(ValueError):
            gr.record_assumption(path, asset_key="a", grader="PSA", gem_rate=bad,
                                 basis="x", capture_date="2026-07-06")


def test_latest_for_returns_last_write_per_asset_grader(tmp_path):
    path = _ledger(tmp_path)
    gr.record_assumption(path, asset_key="a", grader="PSA", gem_rate=0.25,
                         basis="first", capture_date="2026-07-05")
    gr.record_assumption(path, asset_key="a", grader="PSA", gem_rate=0.30,
                         basis="second", capture_date="2026-07-06")
    latest = gr.latest_for(gr.read_rows(path), "a", "PSA")
    assert latest["gem_rate"] == 0.30                    # last-write-wins (both retained in file)
    assert len(gr.read_rows(path)) == 2                  # append-only: nothing overwritten


def test_latest_for_none_when_absent(tmp_path):
    assert gr.latest_for([], "missing", "PSA") is None


def test_read_rows_missing_file_is_empty(tmp_path):
    assert gr.read_rows(tmp_path / "nope.jsonl") == []


def test_read_rows_skips_malformed_lines(tmp_path):
    path = _ledger(tmp_path)
    path.write_text('{"kind":"gem_rate"}\nnot json\n\n{"entry_id":"x"}\n', encoding="utf-8")
    rows = gr.read_rows(path)
    assert len(rows) == 2                                # blank + malformed skipped
