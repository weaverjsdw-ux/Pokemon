"""Phase C activation — verified candidate model + entry gate + append-only ledger.

The entry gate is STOP-class: a candidate may only carry an ``entry_price`` when
there is explicit observed price + stock evidence (mirrors
``verify.alert_allowed``). A parser_suspect / unverifiable / no-evidence candidate
is still a valid *evidence* record, never a buy row. Pure: no network, no clock.
"""
from __future__ import annotations

from types import SimpleNamespace

from scanner.poke_api import candidates as cand


# ---------------------------------------------------------------- entry gate

def test_entry_gate_passes_with_full_evidence():
    ok, reason = cand.entry_evidence_ok(
        stock_status="verified_buyable", buy_url="https://shop/x", entry_price=49.99,
        stock_evidence="operator verified page price + stock", stock_checked_at="2026-07-05")
    assert ok is True and reason == ""


def test_entry_gate_fails_named_conditions():
    ok, reason = cand.entry_evidence_ok(
        stock_status="unverifiable", buy_url="", entry_price=None,
        stock_evidence="", stock_checked_at="")
    assert ok is False
    for needle in ("stock", "price", "buy_url", "evidence", "checked"):
        assert needle in reason.lower()


def test_entry_gate_rejects_zero_price():
    ok, reason = cand.entry_evidence_ok(
        stock_status="in_stock", buy_url="u", entry_price=0.0,
        stock_evidence="e", stock_checked_at="t")
    assert ok is False and "price" in reason.lower()


# ---------------------------------------------------------------- make_candidate

def test_manual_candidate_with_evidence_is_entry_verified():
    """Required test 1 — verified evidence => a VerifiedCandidate that carries an entry."""
    c = cand.make_candidate(
        source="manual_verified", product_key="prismatic_evolutions_etb",
        entry_price="$49.99", buy_url="https://shop.example/pe-etb",
        stock_status="verified_buyable", stock_evidence="operator verified page price + stock",
        stock_checked_at="2026-07-05", observed_at="2026-07-05", retailer="Example",
        confidence="high")
    assert c.entry_verified is True
    assert c.entry_price == 49.99
    assert c.product_key == "prismatic_evolutions_etb"
    assert c.candidate_id  # stable id present
    assert c.reason == ""


def test_manual_candidate_missing_evidence_is_non_entry():
    """Required test 2 — missing evidence => marked non-entry, entry_price stripped."""
    c = cand.make_candidate(
        source="manual_verified", product_key="pe_etb", entry_price="$49.99",
        buy_url="", stock_status="unverifiable", stock_evidence="", stock_checked_at="",
        observed_at="2026-07-05")
    assert c.entry_verified is False
    assert c.entry_price is None            # STOP-class: no evidence => no price
    assert "buy_url" in c.reason.lower()


def test_parser_suspect_candidate_stays_evidence_row():
    c = cand.make_candidate(
        source="manifest_replay", product_key="pe_etb", entry_price=49.99,
        buy_url="https://x", stock_status="parser_suspect",
        stock_evidence="no schema.org availability signal parsed",
        stock_checked_at="2026-07-05", observed_at="2026-07-05")
    assert c.entry_verified is False
    assert c.entry_price is None


def test_candidate_id_is_stable_and_evidence_sensitive():
    kw = dict(source="manual_verified", product_key="pe_etb", listing_id="L1",
              buy_url="https://x", stock_status="verified_buyable",
              stock_evidence="e", stock_checked_at="2026-07-05", observed_at="2026-07-05")
    a = cand.make_candidate(entry_price=49.99, **kw)
    b = cand.make_candidate(entry_price=49.99, **kw)
    c = cand.make_candidate(entry_price=39.99, **kw)   # corrected price => new identity
    assert a.candidate_id == b.candidate_id
    assert a.candidate_id != c.candidate_id


# ---------------------------------------------------------------- ledger

def test_append_and_read_roundtrip(tmp_path):
    path = tmp_path / "verified_candidates.jsonl"
    assert cand.read_rows(path) == []
    c = cand.make_candidate(
        source="manual_verified", product_key="pe_etb", entry_price=49.99,
        buy_url="https://x", stock_status="verified_buyable", stock_evidence="e",
        stock_checked_at="2026-07-05", observed_at="2026-07-05")
    assert cand.append_candidate(path, c) is True
    rows = cand.read_rows(path)
    assert len(rows) == 1
    assert rows[0]["candidate_id"] == c.candidate_id
    assert rows[0]["kind"] == "candidate"
    assert rows[0]["entry_price"] == 49.99


def test_duplicate_append_is_idempotent(tmp_path):
    """Required test 3 — re-appending the same candidate is a no-op."""
    path = tmp_path / "verified_candidates.jsonl"
    c = cand.make_candidate(
        source="manual_verified", product_key="pe_etb", entry_price=49.99,
        buy_url="https://x", stock_status="verified_buyable", stock_evidence="e",
        stock_checked_at="2026-07-05", observed_at="2026-07-05")
    assert cand.append_candidate(path, c) is True
    assert cand.append_candidate(path, c) is False    # idempotent
    assert len(cand.read_rows(path)) == 1


def test_old_records_never_overwritten(tmp_path):
    path = tmp_path / "verified_candidates.jsonl"
    c1 = cand.make_candidate(source="manual_verified", product_key="pe_etb",
                             entry_price=49.99, buy_url="https://x",
                             stock_status="verified_buyable", stock_evidence="e",
                             stock_checked_at="2026-07-05", observed_at="2026-07-05")
    c2 = cand.make_candidate(source="manual_verified", product_key="pe_etb",
                             entry_price=44.99, buy_url="https://x",
                             stock_status="verified_buyable", stock_evidence="e2",
                             stock_checked_at="2026-07-06", observed_at="2026-07-06")
    cand.append_candidate(path, c1)
    cand.append_candidate(path, c2)
    rows = cand.read_rows(path)
    assert len(rows) == 2                                   # both preserved
    assert {r["entry_price"] for r in rows} == {49.99, 44.99}


# ---------------------------------------------------------------- candidate_for fold

PRODUCT = {"name": "Prismatic Evolutions ETB", "set": "Prismatic Evolutions", "msrp": 49.99}


def test_candidate_for_returns_only_entry_verified_latest(tmp_path):
    path = tmp_path / "verified_candidates.jsonl"
    # a non-entry evidence row and two entry rows for the same product
    cand.append_candidate(path, cand.make_candidate(
        source="manifest_replay", product_key="pe_etb", stock_status="unverifiable",
        observed_at="2026-07-04"))
    cand.append_candidate(path, cand.make_candidate(
        source="manual_verified", product_key="pe_etb", entry_price=49.99,
        buy_url="https://x", stock_status="verified_buyable", stock_evidence="e",
        stock_checked_at="2026-07-05", observed_at="2026-07-05", retailer="Example"))
    cand.append_candidate(path, cand.make_candidate(
        source="manual_verified", product_key="pe_etb", entry_price=44.99,
        buy_url="https://y", stock_status="verified_buyable", stock_evidence="e2",
        stock_checked_at="2026-07-06", observed_at="2026-07-06", retailer="Example2"))
    provider = cand.candidate_for_provider(cand.read_rows(path))
    got = provider("pe_etb", PRODUCT)
    assert got is not None
    assert got["verified_price"] == 44.99                  # latest entry-verified wins
    assert got["retailer"] == "Example2"
    assert got["matched_product_key"] == "pe_etb"
    # a product with no candidate returns None (dormant)
    assert provider("other_key", PRODUCT) is None


def test_candidate_for_ignores_non_entry_rows(tmp_path):
    path = tmp_path / "verified_candidates.jsonl"
    cand.append_candidate(path, cand.make_candidate(
        source="manifest_replay", product_key="pe_etb", stock_status="parser_suspect",
        stock_evidence="no availability parsed", observed_at="2026-07-05"))
    provider = cand.candidate_for_provider(cand.read_rows(path))
    assert provider("pe_etb", PRODUCT) is None             # evidence-only, not a buy wire


# ---------------------------------------------------------------- C.6 eBay readiness

def test_ebay_source_not_configured_without_keyset():
    cfg = SimpleNamespace(ebay_browse_api_token="", ebay_client_id="", ebay_client_secret="")
    status = cand.ebay_candidate_source(cfg)
    assert status["status"] == "not_configured"
    assert "NEEDS_API_KEY" in status["detail"]
    assert status["candidates"] == []


def test_ebay_source_configured_maps_records_as_evidence():
    cfg = SimpleNamespace(ebay_browse_api_token="tok", ebay_client_id="", ebay_client_secret="")
    item = {"itemId": "v1|123|0", "title": "Prismatic Evolutions ETB",
            "price": {"value": "49.99"}, "itemWebUrl": "https://ebay.com/itm/123",
            "buyingOptions": ["FIXED_PRICE"]}
    status = cand.ebay_candidate_source(cfg, product_key="pe_etb", browse_items=[item])
    assert status["status"] == "configured"
    rec = status["candidates"][0]
    assert rec["source"] == "ebay_browse"
    # advertised price is NOT a verified entry without a live check => evidence-only
    assert rec["entry_verified"] is False
    assert rec["entry_price"] is None
