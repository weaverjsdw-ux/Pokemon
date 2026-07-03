import json

import pytest

from scanner.discovery.ledger import (
    append_observation, entry_id, existing_ids, item_key,
)


def _obs(**kw):
    base = dict(kind="deal", item="Prismatic ETB", set="Prismatic Evolutions",
                variant="", grade="", condition="", price=39.99, currency="USD",
                source_url="https://example.com/x", capture_date="2026-06-27",
                captured="verified", sweep_id="2026-06-27-now", event="now", note="")
    base.update(kw)
    return base


def test_item_key_is_normalized_identity():
    k = item_key(_obs())
    # set|item|variant|grade|condition, lowercased
    assert k == "prismatic evolutions|prismatic etb|||"
    assert k.islower() and k.count("|") == 4


def test_entry_id_is_stable_and_kind_sensitive():
    a = entry_id("deal", "k", "u", "2026-06-27")
    b = entry_id("deal", "k", "u", "2026-06-27")
    c = entry_id("market_comp", "k", "u", "2026-06-27")
    assert a == b and a != c


def test_append_is_idempotent(tmp_path):
    p = tmp_path / "ledger.jsonl"
    assert append_observation(p, _obs()) is True
    assert append_observation(p, _obs()) is False          # duplicate -> no-op
    lines = p.read_text().strip().splitlines()
    assert len(lines) == 1


def test_deal_and_market_comp_are_separate_lines(tmp_path):
    p = tmp_path / "ledger.jsonl"
    append_observation(p, _obs(kind="deal"))
    append_observation(p, _obs(kind="market_comp", price=60.0))
    assert len(p.read_text().strip().splitlines()) == 2


def test_correction_appends_not_mutates(tmp_path):
    p = tmp_path / "ledger.jsonl"
    append_observation(p, _obs(price=39.99))
    append_observation(p, _obs(price=42.99, capture_date="2026-06-28",
                               note="corrects 2026-06-27 entry"))
    lines = p.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["price"] == 39.99  # original is untouched


def test_bad_kind_rejected(tmp_path):
    with pytest.raises(ValueError):
        append_observation(tmp_path / "l.jsonl", _obs(kind="banana"))


def test_existing_ids_empty_for_missing_file(tmp_path):
    assert existing_ids(tmp_path / "nope.jsonl") == set()


def test_listing_kind_appends_idempotently(tmp_path):
    path = tmp_path / "history.jsonl"
    obs = {"kind": "listing", "set": "Prismatic Evolutions", "item": "ETB",
           "variant": "", "grade": "", "condition": "",
           "source_url": "https://slickdeals.net/f/1-etb", "capture_date": "2026-07-03",
           "price": 39.99, "source": "slickdeals", "listing_id": "1"}
    assert append_observation(path, obs) is True
    assert append_observation(path, dict(obs)) is False
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
