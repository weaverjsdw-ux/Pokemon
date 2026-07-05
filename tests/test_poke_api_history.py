"""Ledger-backed price-history reader/index + momentum (Track B). Pure, no network."""
from __future__ import annotations

import json

from scanner.poke_api import history


def _mc(item_key, comp, capture_date, *, source_url="", source=None, confidence="medium"):
    """A market_comp ledger record (dict), matching the real ledger shape."""
    rec = {
        "entry_id": f"{item_key}|{source_url}|{capture_date}|{comp}",
        "item_key": item_key,
        "kind": "market_comp",
        "set": item_key.split("|")[0],
        "item": item_key.split("|")[1],
        "variant": "", "grade": "", "condition": "",
        "source_url": source_url,
        "capture_date": capture_date,
        "comp": comp,
        "comp_confidence": confidence,
    }
    if source is not None:
        rec["source"] = source
    return rec


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


IKEY = "prismatic evolutions|prismatic evolutions elite trainer box|||"


# --- read_ledger --------------------------------------------------------------

def test_read_ledger_missing_file_is_empty(tmp_path):
    result = history.read_ledger(tmp_path / "does_not_exist.jsonl")
    assert result.observations == []
    assert result.total_lines == 0
    assert result.valid == 0
    assert result.malformed == 0


def test_read_ledger_skips_and_counts_malformed_lines(tmp_path):
    p = tmp_path / "ledger.jsonl"
    good1 = json.dumps(_mc(IKEY, 40.0, "2026-07-01"))
    good2 = json.dumps(_mc(IKEY, 41.0, "2026-07-02"))
    p.write_text(
        good1 + "\n"
        + "{not valid json\n"          # malformed
        + "\n"                          # blank line ignored (not counted)
        + "42\n"                        # valid json but not an object
        + good2 + "\n",
        encoding="utf-8",
    )
    result = history.read_ledger(p)
    assert result.valid == 2
    assert result.malformed == 2       # the bad line + the non-object
    assert result.total_lines == 4     # blank line not counted
    assert [o["comp"] for o in result.observations] == [40.0, 41.0]


# --- source_of ----------------------------------------------------------------

def test_source_of_prefers_explicit_source_field():
    obs = _mc(IKEY, 40.0, "2026-07-01",
              source_url="https://www.tcgplayer.com/product/1", source="tcgplayer")
    assert history.source_of(obs) == "tcgplayer"


def test_source_of_derives_from_url_when_no_source_field():
    obs = _mc(IKEY, 40.0, "2026-07-01",
              source_url="https://www.pricecharting.com/game/x/etb")
    assert history.source_of(obs) == "pricecharting"


# --- item_key_for_product (real-data regression) ------------------------------

def test_item_key_for_product_matches_real_ledger_key():
    # The real catalog stores the 151 set as "151" (not "Scarlet & Violet 151"),
    # so the derived key must match the observed ledger key exactly.
    product = {"set": "151", "name": "Scarlet & Violet 151 Elite Trainer Box"}
    assert (history.item_key_for_product(product, "scarlet_violet_151_etb")
            == "151|scarlet & violet 151 elite trainer box|||")


def test_item_key_for_product_falls_back_to_key_when_no_name():
    assert history.item_key_for_product({"set": "PE"}, "pe_etb") == "pe|pe_etb|||"


# --- latest -------------------------------------------------------------------

def test_latest_selected_by_capture_date(tmp_path):
    p = tmp_path / "ledger.jsonl"
    _write(p, [
        _mc(IKEY, 40.0, "2026-07-01"),
        _mc(IKEY, 44.0, "2026-07-03"),
        _mc(IKEY, 42.0, "2026-07-02"),
    ])
    obs = history.read_ledger(p).observations
    latest = history.latest(obs, IKEY)
    assert latest["comp"] == 44.0
    assert latest["capture_date"] == "2026-07-03"


def test_latest_none_for_unknown_item(tmp_path):
    p = tmp_path / "ledger.jsonl"
    _write(p, [_mc(IKEY, 40.0, "2026-07-01")])
    obs = history.read_ledger(p).observations
    assert history.latest(obs, "no|such|item|||") is None


# --- history grouped by source ------------------------------------------------

def test_history_grouped_by_source(tmp_path):
    p = tmp_path / "ledger.jsonl"
    _write(p, [
        _mc(IKEY, 40.0, "2026-07-01", source="tcgplayer"),
        _mc(IKEY, 41.0, "2026-07-02", source="pricecharting"),
        _mc(IKEY, 42.0, "2026-07-03", source="tcgplayer"),
    ])
    obs = history.read_ledger(p).observations
    grouped = history.history_grouped(obs, IKEY)
    assert set(grouped) == {"tcgplayer", "pricecharting"}
    assert [o["comp"] for o in grouped["tcgplayer"]] == [40.0, 42.0]
    assert [o["comp"] for o in grouped["pricecharting"]] == [41.0]


# --- momentum -----------------------------------------------------------------

def test_momentum_no_history_when_empty(tmp_path):
    p = tmp_path / "ledger.jsonl"
    _write(p, [_mc("other|item|||", 40.0, "2026-07-01")])
    obs = history.read_ledger(p).observations
    m = history.momentum(obs, IKEY)
    assert m["status"] == "no_history"
    assert m["latest"] is None
    assert m["delta_abs"] is None


def test_momentum_single_observation_surfaces_latest_without_delta(tmp_path):
    p = tmp_path / "ledger.jsonl"
    _write(p, [_mc(IKEY, 40.0, "2026-07-01")])
    obs = history.read_ledger(p).observations
    m = history.momentum(obs, IKEY)
    assert m["status"] == "single_observation"
    assert m["latest"] == 40.0
    assert m["previous"] is None
    assert m["delta_abs"] is None


def test_momentum_computes_delta_for_two_dates(tmp_path):
    p = tmp_path / "ledger.jsonl"
    _write(p, [
        _mc(IKEY, 40.0, "2026-07-01"),
        _mc(IKEY, 50.0, "2026-07-03"),
    ])
    obs = history.read_ledger(p).observations
    m = history.momentum(obs, IKEY)
    assert m["status"] == "ok"
    assert m["latest"] == 50.0
    assert m["previous"] == 40.0
    assert m["delta_abs"] == 10.0
    assert m["delta_pct"] == 25.0
    assert m["first_seen"] == "2026-07-01"
    assert m["last_seen"] == "2026-07-03"
    assert m["observations"] == 2


def test_momentum_same_day_multisource_does_not_fake_delta(tmp_path):
    # Engine writes one market_comp per source; two sources on the SAME date must
    # collapse to one canonical value/date, never look like day-over-day movement.
    p = tmp_path / "ledger.jsonl"
    _write(p, [
        _mc(IKEY, 40.0, "2026-07-03", source="tcgplayer"),
        _mc(IKEY, 45.0, "2026-07-03", source="pricecharting"),
    ])
    obs = history.read_ledger(p).observations
    m = history.momentum(obs, IKEY)
    assert m["status"] == "single_observation"   # only ONE distinct date
    assert m["previous"] is None
    assert m["delta_abs"] is None


def test_momentum_staleness_from_today(tmp_path):
    p = tmp_path / "ledger.jsonl"
    _write(p, [
        _mc(IKEY, 40.0, "2026-06-01"),
        _mc(IKEY, 42.0, "2026-06-02"),
    ])
    obs = history.read_ledger(p).observations
    m = history.momentum(obs, IKEY, today="2026-07-04", stale_days=30)
    assert m["stale_days"] == 32
    assert m["stale"] is True
