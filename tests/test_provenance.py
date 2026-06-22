"""ID provenance sidecar read/write/merge (no network)."""
from __future__ import annotations

from scanner import provenance


def test_record_and_get_roundtrip(tmp_path):
    path = tmp_path / "id_provenance.json"
    provenance.record("foo", "target_tcin", source_url="https://t/A-1", path=path)

    entry = provenance.get("foo", "target_tcin", path=path)
    assert entry["sourceUrl"] == "https://t/A-1"


def test_record_merges_without_clobbering(tmp_path):
    path = tmp_path / "id_provenance.json"
    provenance.record("foo", "target_tcin", source_url="https://t/A-1", path=path)
    provenance.record(
        "foo", "target_tcin", status="CONFIRMED", verified_at=123, detail="ok", path=path
    )

    entry = provenance.get("foo", "target_tcin", path=path)
    assert entry["sourceUrl"] == "https://t/A-1"  # preserved
    assert entry["status"] == "CONFIRMED"
    assert entry["verifiedAt"] == 123


def test_load_tolerates_missing_and_corrupt(tmp_path):
    missing = tmp_path / "nope.json"
    assert provenance.load(missing) == {}

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert provenance.load(corrupt) == {}


def test_is_suspect():
    assert provenance.is_suspect({"status": "NOT_FOUND"}) is True
    assert provenance.is_suspect({"status": "SUSPECT_FORMAT"}) is True
    assert provenance.is_suspect({"status": "CONFIRMED"}) is False
    assert provenance.is_suspect(None) is False
