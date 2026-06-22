"""ID Doctor verification logic (no real network)."""
from __future__ import annotations

from scanner import provenance, verify_ids
from scanner.config import Config, RetailerCfg


class FakeResp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data if data is not None else {}

    def json(self):
        return self._data


def _cfg(products, retailers=None):
    return Config(
        home_address="h",
        work_address="w",
        route_radius_miles=4,
        routing_engine="osrm",
        google_api_key="",
        retailers=retailers or {"target": RetailerCfg(enabled=True)},
        poll_interval_seconds=180,
        discord_webhook="",
        ntfy_topic="",
        products_filter="all_sealed",
        products=products,
    )


def test_offline_flags_malformed_target_tcin():
    # 10-digit TCIN is unusual (real ones are 7-9 digits).
    v = verify_ids.verify_one("target", "p", "1011206804", {}, online=False)
    assert v["status"] == provenance.SUSPECT_FORMAT


def test_offline_ok_format_is_unchecked():
    v = verify_ids.verify_one("target", "p", "93954446", {}, online=False)
    assert v["status"] == provenance.UNCHECKED


def test_online_confirmed_target():
    get = lambda url, **kw: FakeResp(200, {"data": {"product": {"tcin": "93954446"}}})
    v = verify_ids.verify_one("target", "p", "93954446", {}, online=True, get=get)
    assert v["status"] == provenance.CONFIRMED


def test_online_not_found_on_404():
    get = lambda url, **kw: FakeResp(404)
    v = verify_ids.verify_one("walmart", "p", "15433520586", {}, online=True, get=get)
    assert v["status"] == provenance.NOT_FOUND


def test_online_blocked_on_403():
    get = lambda url, **kw: FakeResp(403)
    v = verify_ids.verify_one("costco", "p", "4000313298", {}, online=True, get=get)
    assert v["status"] == provenance.BLOCKED


def test_bestbuy_without_key_is_no_key():
    get = lambda url, **kw: FakeResp(200, {"sku": "6606082"})
    v = verify_ids.verify_one("bestbuy", "p", "6606082", {}, online=True, get=get, api_key="")
    assert v["status"] == provenance.NO_KEY


def test_bad_format_but_resolves_is_ambiguous():
    # 10-digit Target TCIN that nevertheless resolves -> eyeball it.
    get = lambda url, **kw: FakeResp(200, {"data": {"product": {"tcin": "1011206804"}}})
    v = verify_ids.verify_one("target", "p", "1011206804", {}, online=True, get=get)
    assert v["status"] == provenance.AMBIGUOUS


def test_verify_catalog_writes_provenance(tmp_path):
    path = tmp_path / "prov.json"
    cfg = _cfg({"prism": {"name": "Prism", "target_tcin": "93954446"}})
    get = lambda url, **kw: FakeResp(200, {"data": {"product": {"tcin": "93954446"}}})

    results = verify_ids.verify_catalog(cfg, get=get, path=path)

    assert len(results) == 1
    assert results[0]["status"] == provenance.CONFIRMED
    entry = provenance.get("prism", "target_tcin", path=path)
    assert entry["status"] == provenance.CONFIRMED
    assert entry["verifiedAt"]


def test_verify_catalog_offline_catches_real_malformed_tcin(tmp_path):
    path = tmp_path / "prov.json"
    cfg = _cfg({"prism": {"name": "Prism", "target_tcin": "1011206804"}})

    results = verify_ids.verify_catalog(cfg, online=False, path=path)

    assert results[0]["status"] == provenance.SUSPECT_FORMAT
