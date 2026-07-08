"""CompEngine: cache TTL, staleness ladder (spec 4.4), ledger appends, legacy round-trip."""
import json
from pathlib import Path

from scanner.comps import model
from scanner.comps.engine import CompEngine
from scanner.comps.tcgplayer import TcgPlayerSource
from scanner.poke_api.tcgcsv_source import TcgCsvSource
from scanner.state import State
from scanner import config as cfg_mod
from scanner import market as market_mod
from scanner.discovery import sweep as sweep_mod

PRODUCT = {"name": "Destined Rivals Elite Trainer Box", "set": "Destined Rivals",
           "type": "ETB", "msrp": "$49.99",
           "resale_query": "Pokemon TCG Destined Rivals Elite Trainer Box sealed",
           "ppt_id": "624676"}


class Cfg:
    class comps:
        engine = "inhouse"
        agreement_tolerance_pct = 20.0
        ebay_floor_sanity_pct = 50.0
        cache_ttl_seconds = 21600
        politeness_seconds = 0.0
    class poke:
        staleness_days = 30


class RecordingSource:
    def __init__(self, result):
        self.result, self.calls = result, 0
    def fetch(self, key, product, checked_at):
        self.calls += 1
        return self.result


def ok_quote(source, price, url):
    return model.CompSourceQuote(source, model.SOLD_DERIVED, "ok", price, url,
                                 "2026-07-03T10:00:00")


def failed_quote(source):
    return model.CompSourceQuote(source, model.SOLD_DERIVED, "error", None,
                                 "https://example.com", "2026-07-03T10:00:00", detail="down")


def make_engine(tmp_path, tcg, pc, ebay=None, clock=lambda: 1_000_000.0):
    return CompEngine(
        Cfg(), state=State(db_path=tmp_path / "state.db"),
        tcg_source=RecordingSource(tcg), pc_source=RecordingSource(pc),
        ebay_source=RecordingSource(ebay or model.EbayAsk(
            model.CompSourceQuote("ebay_api", model.ACTIVE_ASK, "not_configured", None,
                                  "https://ebay.com", "2026-07-03T10:00:00"))),
        ledger_path=tmp_path / "history.jsonl", clock=clock, sleep=lambda s: None)


def test_estimate_round_trips_through_existing_pipeline(tmp_path):
    engine = make_engine(
        tmp_path,
        ok_quote("tcgplayer", 180.65, "https://www.tcgplayer.com/product/624676"),
        ok_quote("pricecharting", 190.0,
                 "https://www.pricecharting.com/game/pokemon-destined-rivals/elite-trainer-box"))
    row = engine.estimate("destined_rivals_etb", PRODUCT, 1_000_000)
    assert market_mod.comp_from_row(row) == (180.65, "high")
    assert row["creditsConsumed"] == 0            # never spends PPT credits
    price_conf, source_url, method, detail = sweep_mod._provenance(row, "high")
    assert price_conf == "verified"
    assert source_url == "https://www.tcgplayer.com/product/624676"


def test_cache_hit_within_ttl_skips_sources(tmp_path):
    tcg = ok_quote("tcgplayer", 100.0, "https://www.tcgplayer.com/product/1")
    pc = ok_quote("pricecharting", 105.0, "https://www.pricecharting.com/game/a/b")
    engine = make_engine(tmp_path, tcg, pc)
    engine.estimate("k", PRODUCT, 1_000_000)
    assert engine.tcg.calls == 1
    row2 = engine.estimate("k", PRODUCT, 1_000_000 + 60)
    assert engine.tcg.calls == 1                  # served from cache
    assert row2["status"] == "ok" and row2.get("cacheHit") is True


def test_ttl_expiry_refetches(tmp_path):
    tcg = ok_quote("tcgplayer", 100.0, "https://www.tcgplayer.com/product/1")
    pc = ok_quote("pricecharting", 105.0, "https://www.pricecharting.com/game/a/b")
    engine = make_engine(tmp_path, tcg, pc)
    engine.estimate("k", PRODUCT, 1_000_000)
    engine.estimate("k", PRODUCT, 1_000_000 + 21601)
    assert engine.tcg.calls == 2


def test_refetch_failure_serves_cached_degraded_one_tier(tmp_path):
    engine = make_engine(
        tmp_path,
        ok_quote("tcgplayer", 100.0, "https://www.tcgplayer.com/product/1"),
        ok_quote("pricecharting", 105.0, "https://www.pricecharting.com/game/a/b"))
    engine.estimate("k", PRODUCT, 1_000_000)                     # cached as high
    engine.tcg.result = failed_quote("tcgplayer")
    engine.pc.result = failed_quote("pricecharting")
    row = engine.estimate("k", PRODUCT, 1_000_000 + 30000)       # ttl < age < 24h
    assert row["status"] == "ok" and row["confidence"] == "medium"   # high -> medium
    assert "cached" in row["detail"]


def test_cache_older_than_24h_is_stale_low(tmp_path):
    engine = make_engine(
        tmp_path,
        ok_quote("tcgplayer", 100.0, "https://www.tcgplayer.com/product/1"),
        ok_quote("pricecharting", 105.0, "https://www.pricecharting.com/game/a/b"))
    engine.estimate("k", PRODUCT, 1_000_000)
    engine.tcg.result = failed_quote("tcgplayer")
    engine.pc.result = failed_quote("pricecharting")
    row = engine.estimate("k", PRODUCT, 1_000_000 + 90000)       # > 24h
    assert row["status"] == "ok" and row["confidence"] == "low"
    assert row.get("stale") is True


def test_cache_older_than_30d_is_honest_no_match(tmp_path):
    engine = make_engine(
        tmp_path,
        ok_quote("tcgplayer", 100.0, "https://www.tcgplayer.com/product/1"),
        ok_quote("pricecharting", 105.0, "https://www.pricecharting.com/game/a/b"))
    engine.estimate("k", PRODUCT, 1_000_000)
    engine.tcg.result = failed_quote("tcgplayer")
    engine.pc.result = failed_quote("pricecharting")
    row = engine.estimate("k", PRODUCT, 1_000_000 + 31 * 86400)
    assert row["status"] == "no_matches"
    assert market_mod.comp_from_row(row) == (None, "none")       # no invented number


def test_ledger_one_observation_per_ok_source_per_day(tmp_path):
    engine = make_engine(
        tmp_path,
        ok_quote("tcgplayer", 100.0, "https://www.tcgplayer.com/product/1"),
        ok_quote("pricecharting", 105.0, "https://www.pricecharting.com/game/a/b"))
    engine.estimate("k", PRODUCT, 1_000_000)
    lines = [json.loads(l) for l in
             (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2                       # one per ok source
    assert {l["source"] for l in lines} == {"tcgplayer", "pricecharting"}
    assert all(l["kind"] == "market_comp" for l in lines)
    # idempotent within the day: cache-busted second call adds nothing
    engine.estimate("k", PRODUCT, 1_000_000 + 21601)
    lines2 = (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines2) == 2


def _cfg(tcgcsv_on):
    # a real Config (from_mapping supplies every fee/ebay/comps default) so from_config's
    # pc/ebay source construction never trips on a missing field. Same builder the divergence
    # + comps tests use. `locations` is the only required key.
    return cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"},
                                 "poke": {"tcgcsv": tcgcsv_on}})


def test_from_config_uses_tcgcsv_when_enabled():
    assert isinstance(CompEngine.from_config(_cfg(True)).tcg, TcgCsvSource)


def test_from_config_uses_dead_tcgplayer_when_disabled():
    assert isinstance(CompEngine.from_config(_cfg(False)).tcg, TcgPlayerSource)
