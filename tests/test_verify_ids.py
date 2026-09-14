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


def test_offline_accepts_verified_10_digit_target_tcin():
    # Target's first-party listing for this product publishes this 10-digit TCIN.
    v = verify_ids.verify_one("target", "p", "1011206804", {}, online=False)
    assert v["status"] == provenance.UNCHECKED


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
    # An 11-digit Target TCIN that nevertheless resolves -> eyeball it.
    get = lambda url, **kw: FakeResp(200, {"data": {"product": {"tcin": "10112068045"}}})
    v = verify_ids.verify_one("target", "p", "10112068045", {}, online=True, get=get)
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


def test_verify_catalog_offline_accepts_verified_10_digit_tcin(tmp_path):
    path = tmp_path / "prov.json"
    cfg = _cfg({"prism": {"name": "Prism", "target_tcin": "1011206804"}})

    results = verify_ids.verify_catalog(cfg, online=False, path=path)

    assert results[0]["status"] == provenance.UNCHECKED


# --- Defect A: an unreachable source is not a malformed ID -------------------
# Regression guard. Before this, a failing format check plus a BLOCKED/ERROR/
# NO_KEY network verdict returned SUSPECT_FORMAT carrying only the format
# reason, discarding what the network actually said - reporting "your data is
# wrong" when the truth was "we cannot reach the source".

def test_blocked_source_is_not_reported_as_malformed_id():
    get = lambda url, **kw: FakeResp(403)
    v = verify_ids.verify_one("target", "p", "1011206804", {}, online=True, get=get)
    assert v["status"] == provenance.BLOCKED


def test_blocked_verdict_still_carries_the_format_concern():
    get = lambda url, **kw: FakeResp(403)
    v = verify_ids.verify_one("target", "p", "10112068045", {}, online=True, get=get)
    assert "403" in v["detail"]
    assert "7-10 digits" in v["detail"]


def test_no_key_is_not_reported_as_malformed_id():
    get = lambda url, **kw: FakeResp(200, {"sku": "x"})
    v = verify_ids.verify_one(
        "bestbuy", "p", "123456789012", {}, online=True, get=get, api_key=""
    )
    assert v["status"] == provenance.NO_KEY


def test_good_format_blocked_is_unchanged():
    get = lambda url, **kw: FakeResp(403)
    v = verify_ids.verify_one("target", "p", "93954446", {}, online=True, get=get)
    assert v["status"] == provenance.BLOCKED
    assert "format unverified" not in v["detail"]


# --- The sweep classifier: ONE named event, not N flakes ---------------------

def _r(slug, status, detail="", value="1", product="p"):
    return {"productKey": product, "slug": slug, "field": f"{slug}_id",
            "value": value, "status": status, "detail": detail}


def test_no_sweep_when_everything_answers():
    results = [_r("target", provenance.CONFIRMED), _r("walmart", provenance.CONFIRMED)]
    assert verify_ids.classify_block_sweep(results) is None


def test_partial_block_is_an_ordinary_bad_run_not_a_sweep():
    results = [
        _r("target", provenance.BLOCKED, "HTTP 403: blocked"),
        _r("target", provenance.CONFIRMED),
    ]
    assert verify_ids.classify_block_sweep(results) is None


def test_sweep_requires_an_explicit_403():
    results = [_r("target", provenance.BLOCKED, "HTTP 500: retailer endpoint unavailable")]
    assert verify_ids.classify_block_sweep(results) is None


def test_source_shaped_when_another_retailer_still_answers():
    results = [
        _r("target", provenance.BLOCKED, "HTTP 403: blocked"),
        _r("target", provenance.BLOCKED, "HTTP 403: blocked"),
        _r("walmart", provenance.CONFIRMED),
    ]
    event = verify_ids.classify_block_sweep(results)
    assert event["classification"] == "source_shaped"
    assert event["blocked_sources"] == ["target"]
    assert "walmart" in event["healthy_evidence"]


def test_not_found_counts_as_the_source_answering():
    # A 404 proves reachability just as well as a 200 does.
    results = [
        _r("target", provenance.BLOCKED, "HTTP 403: blocked"),
        _r("walmart", provenance.NOT_FOUND, "HTTP 404: no such product"),
    ]
    assert verify_ids.classify_block_sweep(results)["classification"] == "source_shaped"


def test_environment_shaped_when_nothing_answers_anywhere():
    results = [
        _r("target", provenance.BLOCKED, "HTTP 403: blocked"),
        _r("walmart", provenance.BLOCKED, "HTTP 403: blocked"),
    ]
    event = verify_ids.classify_block_sweep(results)
    assert event["classification"] == "environment_shaped"
    assert event["healthy_evidence"] == []


def test_no_key_is_neutral_and_never_makes_a_source_look_healthy():
    results = [
        _r("target", provenance.BLOCKED, "HTTP 403: blocked"),
        _r("bestbuy", provenance.NO_KEY, "Best Buy API key required"),
    ]
    event = verify_ids.classify_block_sweep(results)
    # NO_KEY means bestbuy was never attempted, so target is the only source
    # this run actually reached for - not enough to indict the environment.
    assert event["classification"] == "scope_limited"
    assert "bestbuy" not in event["healthy_evidence"]
    assert event["blocked_sources"] == ["target"]


def test_classifier_names_sources_but_never_leaks_id_values():
    secret = "9999999999"
    results = [
        _r("target", provenance.BLOCKED, "HTTP 403: blocked", value=secret),
        _r("walmart", provenance.CONFIRMED, value=secret),
    ]
    event = verify_ids.classify_block_sweep(results)
    assert secret not in event["warning"]
    assert secret not in repr(event["blocked_sources"])


def test_sweep_warning_names_a_concrete_operator_action():
    results = [
        _r("target", provenance.BLOCKED, "HTTP 403: blocked"),
        _r("walmart", provenance.CONFIRMED),
    ]
    warning = verify_ids.classify_block_sweep(results)["warning"]
    assert "target" in warning
    assert "do NOT" in warning


def test_single_source_run_cannot_claim_the_environment_is_at_fault():
    # `--retailer target` attempts exactly one source. "Nothing answered" is
    # then an artifact of the scope, not evidence about connectivity.
    results = [
        _r("target", provenance.BLOCKED, "HTTP 403: blocked"),
        _r("target", provenance.BLOCKED, "HTTP 403: blocked"),
    ]
    event = verify_ids.classify_block_sweep(results)
    assert event["classification"] == "scope_limited"
    assert "re-run" in event["warning"].lower()


def test_two_sources_attempted_and_both_dead_is_environment_shaped():
    results = [
        _r("target", provenance.BLOCKED, "HTTP 403: blocked"),
        _r("walmart", provenance.BLOCKED, "HTTP 403: blocked"),
    ]
    assert verify_ids.classify_block_sweep(results)["classification"] == "environment_shaped"
